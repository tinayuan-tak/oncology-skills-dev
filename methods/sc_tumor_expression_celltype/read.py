"""Per-gene reader over the single-cell donor×compartment pseudobulk products + the presence assembler.

Reads sc-pseudobulk-donor-celltype-{indication}-v1 (one row per dataset_id × donor_id × compartment ×
gene, from a filtered CELLxGENE Census query — see data-catalog scripts/aggregate_sc_pseudobulk.py).
The products are gene-SORTED (sort key + read filter key == gene_symbol), so a per-gene read uses
pyarrow S3FileSystem + predicate-pushdown to touch a few row-groups rather than the full file — the
same gene-keyed-product invariant the bulk tcga_gtex readers rely on.

Dependencies are pyarrow/pandas/numpy/boto3 ONLY — NO scanpy/anndata/cellxgene-census at read time.
The single-cell machinery (Census fetch, per-cell aggregation, numpy-2.x env) lives entirely in the
data-catalog emit step; this method reads the already-pseudobulked parquet.

Credential discipline: boto3 Session(profile_name="cbg") — the default SSO role (Developer-Dev) lacks
GetObject on onc-compbio (see methods/collectri_tf_regulon/read.py); cbg is the read-capable profile.
"""
from __future__ import annotations

from typing import Optional

from . import stats as _stats
from methods.catalog_query.read import bucket_key_for

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"

# indication code → landed sc-pseudobulk product key. ONLY the indications whose CELLxGENE Census
# atlases carry a per-cell MALIGNANT annotation AND enough donors for the donor-replicate roll-up are
# materialized (v1: COADREAD + NSCLC). Others → data_unavailable (honest capability ceiling, never a
# silent fall-back). PAAD excluded (n=1 donor); STAD excluded (0 malignant-cell annotation in the
# Census gastric atlases). Adding an indication = emit its product (data-catalog) + one line here.
INDICATION_TO_PRODUCT = {
    "COADREAD": "sc-pseudobulk-donor-celltype-coadread-v1",
    "COAD": "sc-pseudobulk-donor-celltype-coadread-v1",
    "READ": "sc-pseudobulk-donor-celltype-coadread-v1",
    "NSCLC": "sc-pseudobulk-donor-celltype-nsclc-v1",
    "LUAD": "sc-pseudobulk-donor-celltype-nsclc-v1",
    "LUSC": "sc-pseudobulk-donor-celltype-nsclc-v1",
}

_PARQUET_COLS = ["gene_symbol", "dataset_id", "donor_id", "compartment",
                 "n_cells", "detection_fraction", "abundance_log1p_cp10k"]


def _product_key(indication: str) -> Optional[str]:
    prod = INDICATION_TO_PRODUCT.get(str(indication).upper().strip())
    if not prod:
        return None
    # key resolved from the product manifest (single source of truth).
    return bucket_key_for(prod)[1]


def read_gene_compartment_rows(target: str, indication: str):
    """Per-(dataset, donor, compartment) rows for one gene in one indication's pseudobulk product.

    Returns a pandas DataFrame (possibly empty) with _PARQUET_COLS. Empty (0 rows) when the gene is
    absent from the product, or None when the indication has no landed product — the caller maps
    both to data_unavailable, distinguishing "no product" (None) from "gene not in product" (empty)."""
    key = _product_key(indication)
    if key is None:
        return None
    import pyarrow.fs as fs
    import pyarrow.parquet as pq
    s3fs = fs.S3FileSystem(region="us-east-1")   # default cred chain honors AWS_PROFILE=cbg
    # predicate-pushdown on the physical sort key (gene_symbol) — touches few row-groups.
    filters = [("gene_symbol", "==", str(target).upper().strip())]
    try:
        tbl = pq.read_table(f"{S3_BUCKET}/{key}", filesystem=s3fs,
                            filters=filters, columns=_PARQUET_COLS)
    except FileNotFoundError:
        return None
    return tbl.to_pandas()


def read_sc_expression_presence(target: str, indication: str) -> dict:
    """Assemble the single-cell per-compartment presence summary for a (target, indication).

    Rolls the per-donor pseudobulk up to per-compartment cross-donor medians (donor-is-replicate),
    then classifies into the malignant-anchored `sc_expression_class`. data_unavailable-safe on both
    "no landed product for this indication" and "gene absent from the product"."""
    rows = read_gene_compartment_rows(target, indication)
    if rows is None:
        return _data_unavailable(target, indication,
                                 note=f"No single-cell pseudobulk product landed for indication "
                                      f"{indication}; sc_rna presence is a named capability gap here.")
    if rows.empty:
        return _data_unavailable(target, indication,
                                 note=f"{target} absent from the single-cell pseudobulk product for "
                                      f"{indication} (not measured in the contributing atlases).")

    comp_summary = _stats.compartment_summary(rows)
    classed = _stats.classify_sc_expression(comp_summary)
    n_donor_groups = rows[["dataset_id", "donor_id"]].drop_duplicates().shape[0]
    out = {
        "sc_expression_class": classed["sc_expression_class"],
        "tce_homogeneity_class": classed["tce_homogeneity_class"],   # Phase 3.2 biologics-homogeneity lens
        "malignant_detection_fraction": classed["malignant_detection_fraction"],
        "malignant_abundance_log1p_cp10k": classed["malignant_abundance_log1p_cp10k"],
        "malignant_compartment_available": classed["malignant_compartment_available"],
        "top_microenvironment_compartment": classed["top_microenvironment_compartment"],
        "top_microenvironment_detection_fraction": classed["top_microenvironment_detection_fraction"],
        "n_compartments_measured": classed["n_compartments_measured"],
        "n_donor_groups": int(n_donor_groups),
        "n_datasets": int(rows["dataset_id"].nunique()),
        "compartment_detection": {c: comp_summary[c]["median_detection_fraction"]
                                  for c in comp_summary},
        # v1 sc-presence depth (additive; presence ladder above untouched): the FULL per-compartment
        # vector + an explicit CAF/stromal readout (the deck's tumor-vs-CAF dual-target axis).
        "per_compartment": _stats.per_compartment_vector(comp_summary),
        "indication": str(indication).upper().strip(),
        "product_id": INDICATION_TO_PRODUCT.get(str(indication).upper().strip()),
    }
    out.update(_stats.caf_readout(comp_summary))
    return out


def read_two_antigen_samecell(target: str, partner: str, indication: str) -> dict:
    """Two-antigen SAME-CELL co-expression in the malignant compartment — the deck's dual-target
    cell-type-specificity question (POSTN/PD-L1, CLDN18.2/LRRC15, slide 6): do BOTH antigens sit on
    the SAME tumor cells, or on different cells within the tumor?

    REUSES pair_selectivity_gate.samecell.confirm_pair_samecell (the tested same-cell reader, PR#203)
    — the computation is identical to the bispecific-avidity confirmation; only the FRAMING differs
    (presence/co-localization vs avidity-for-a-bispecific). We do NOT re-read the cube here. Returns
    the same-cell avidity/co-localization call + cross-donor both-fraction/enrichment, presence-framed:
      same_cell_coordinated       — co-expressed on the same malignant cells (true dual-antigen target)
      same_cell_independent       — both present, co-occur ~by chance
      same_cell_mutually_exclusive— rarely the same cell (bulk co-expression was misleading)
      data_unavailable            — cube/pair not landed (honest gap).
    """
    from methods.pair_selectivity_gate.samecell import confirm_pair_samecell
    r = confirm_pair_samecell(target, partner, indication)
    # presence-framed alias on the same underlying call (keep the raw fields for provenance)
    r = dict(r)
    r["two_antigen_colocalization_class"] = r.get("samecell_avidity_call")
    r["target"] = str(target).upper().strip()
    r["partner"] = str(partner).upper().strip()
    r["indication"] = str(indication).upper().strip()
    return r


def _data_unavailable(target: str, indication: str, note: str) -> dict:
    """The honest coverage-gap payload — a primary `sc_expression_class: data_unavailable` (which the
    skills resolver's _summary_is_unavailable honors) plus a human-readable `_data_note`."""
    return {
        "sc_expression_class": "data_unavailable",
        "tce_homogeneity_class": "data_unavailable",
        "malignant_detection_fraction": None,
        "malignant_abundance_log1p_cp10k": None,
        "malignant_compartment_available": False,
        "top_microenvironment_compartment": None,
        "top_microenvironment_detection_fraction": None,
        "n_compartments_measured": 0,
        "n_donor_groups": 0,
        "n_datasets": 0,
        "compartment_detection": {},
        "per_compartment": [],
        "caf_detection_fraction": None,
        "caf_abundance_log1p_cp10k": None,
        "caf_compartment_available": False,
        "caf_vs_malignant_class": "data_unavailable",
        "indication": str(indication).upper().strip(),
        "product_id": INDICATION_TO_PRODUCT.get(str(indication).upper().strip()),
        "_data_note": note,
    }
