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

from methods.catalog_query.read import bucket_key_for

from . import stats as _stats

DEFAULT_AWS_PROFILE = "cbg"
S3_BUCKET = "onc-compbio"

# indication code → landed sc-pseudobulk product key. ONLY the indications whose CELLxGENE Census
# atlases carry a per-cell MALIGNANT annotation AND enough donors for the donor-replicate roll-up are
# materialized (v1: COADREAD + NSCLC + LUSC). Others → data_unavailable (honest capability ceiling,
# never a silent fall-back). PAAD excluded (n=1 donor); STAD excluded (0 malignant-cell annotation in
# the Census gastric atlases). Adding an indication = emit its product (data-catalog) + one line here.
# LUSC has a DEDICATED product (66,617 malignant cells, 4 datasets) — squamous-only denominators,
# distinct from the LUAD+LUSC-mixed NSCLC umbrella. LUAD keeps the umbrella (no LUAD-specific cube).
# 2026-08-11 REVIEW FIX (M3): repoint COADREAD to -v2. The catalog's coadread-v2 SUPERSEDES v1
# (`supersedes: sc-pseudobulk-donor-celltype-coadread-v1`) with a 4.5x-larger cohort — 30 datasets
# / 749 donors / 828,819 cells / 1,663 donor-compartment groups (v1: 21 / 511 / 182,604) — and is
# MATERIALIZED (size_bytes 450455052, md5 1ee88c68…, uploaded to its s3_uri). The reader does not
# follow `supersedes`, so it silently read the stale, biased <25%-cohort subset. NSCLC stays on
# its v1 (no v2 exists). Adding an indication = emit its product + one line here.
# 2026-08-12: PAAD + HNSC wired to 3CA products (data-catalog #334–#340). Census has 0 HNSC malignant
# cells; 3CA fills the gap via inferCNV/CNA-validated malignant call. STAD excluded — no 3CA bucket.
# 2026-08-12: KIRC wired to the 3CA kidney bucket (data-catalog #343–#345). NB the kidney cube is
# MULTI-ENTITY POOLED (ccRCC-dominant but includes papillary/chromophobe/Wilms/normal — no cancer_type
# filter, per the source manifest caveat); it serves a pan-renal presence readout, not a ccRCC-pure
# denominator. Only KIRC is mapped (the strategic ccRCC/NEDD8-UBA3 indication) — KIRP/KICH are NOT
# mapped, because the pooled cube cannot provide entity-specific denominators for them.
# 2026-08-12: OV wired to the 3CA ovarian bucket (data-catalog #347/#349/#350). Like kidney, the
# ovarian cube is MULTI-ENTITY POOLED / pan-gynecologic (ovarian-dominant but includes carcinosarcoma/
# endometrial/GIST/peritoneal — no cancer_type filter, per the source manifest caveat); it serves a
# pan-gynecologic presence readout, NOT an HGSOC-pure denominator. Malignant biology validated (FOLR1/
# MSLN/MUC16/EPCAM/PAX8 high; CD70/CEACAM5 correctly absent).
# 2026-08-13: COADREAD/COAD/READ repointed to the CRC core atlas (Marteau 2025; data-catalog #364/#365)
# from the Census coadread-v2. The decisive upgrade is the EXPLICIT malignant annotation: the CRC atlas
# ships a curated 'Cancer cell' label distinct from normal 'Epithelial cell', so the malignant-anchored
# classifier reads a real malignant call — the Census cube derived compartments via compartment_of()
# inference, which cannot cleanly separate malignant from normal colonic epithelium. CRC = 45 pooled
# studies / 420 tumor-origin donors / 509,919 malignant cells (EPCAM malignant 0.89 / CEACAM5 0.76 /
# PTPRC immune 0.73). Same pattern as the NSCLC→LuCA repoint. Superseded: coadread-v2 (Census, 749 donors
# but inferred malignant compartment) — retained in the catalog, no longer read here.
INDICATION_TO_PRODUCT = {
    "COADREAD": "sc-pseudobulk-tumor-crc-coadread-v1",  # CRC core atlas (Marteau 2025): explicit 'Cancer cell' malignant call
    "COAD": "sc-pseudobulk-tumor-crc-coadread-v1",
    "READ": "sc-pseudobulk-tumor-crc-coadread-v1",
    "NSCLC": "sc-pseudobulk-tumor-luca-nsclc-v1",  # LuCA (Salcher 2022): 193 tumor pts / 21 datasets (upgrade from Census nsclc-v1)
    "LUAD": "sc-pseudobulk-tumor-luca-nsclc-v1",
    "LUSC": "sc-pseudobulk-donor-celltype-lusc-v1",  # dedicated squamous cube (was: nsclc umbrella)
    "PAAD": "sc-pseudobulk-tumor-3ca-pancreas-v1",  # 3CA PDAC — 6 studies / 344K cells (inferCNV malignant)
    "HNSC": "sc-pseudobulk-tumor-3ca-hnsc-v1",  # 3CA HNSCC — Kürten+Puram+Cillo; 0 Census HNSC malignant cells
    "KIRC": "sc-pseudobulk-tumor-3ca-kidney-v1",  # 3CA Kidney — 5 studies / 125 donors / 74 malignant (pan-renal pooled)
    "OV": "sc-pseudobulk-tumor-3ca-ovarian-v1",  # 3CA Ovarian — 11 studies / 115 donors / 106 malignant (pan-gynecologic pooled)
    "STAD": "sc-pseudobulk-tumor-stad-golim-v1",  # Go/Lim gastric atlas (2026, data-catalog #425/#433) — 95 donors / malignant in 88; malignant=Epithelial∩Phenotype==GC (adenocarcinoma proxy, no inferCNV). CLDN18/EPCAM/MUC1/TACSTD2 malignant-enriched (CLDN18 1.23 vs 0.06). Fills the previously-excluded gastric gap (Census 'unknown' tumor label + no 3CA bucket).
    "BRCA": "sc-pseudobulk-tumor-brca-wu-v1",  # Wu/Swarbrick breast atlas (GSE176078; Nat Genet 2021) — 26 primary tumours (11 ER+ / 5 HER2+ / 10 TNBC); malignant='Cancer Epithelial' author annotation (curated), 20/26 donors with malignant cells. ERBB2 malignant 0.28 / TACSTD2 0.76 / EPCAM 0.74. Fills the previously-empty breast tumour scRNA gap. (data-catalog sc-pseudobulk-tumor-brca-wu-v1)
}

# Per-product malignant-annotation PROVENANCE (review G11): HOW the malignant compartment was called,
# and whether it is specific to the QUERIED entity. Derived strictly from the atlas provenance documented
# in INDICATION_TO_PRODUCT above — not guessed. Surfaced so downstream (claim-vector confidence) can read
# a phenotype-proxy / multi-entity-pooled call DOWN relative to a curated / inferCNV / entity-specific one
# (a malignant call on a phenotype heuristic or a pan-entity pool is weaker evidence than a CNA-validated,
# disease-specific one). Verdict-inert.
#   malignant_annotation_method ∈ {curated | infercnv | phenotype_proxy | unspecified}
#     curated         — atlas ships an explicit malignant / 'Cancer cell' label (CRC core, LuCA NSCLC)
#     infercnv        — malignant called by inferCNV / CNA validation (all 3CA products; see block note)
#     phenotype_proxy — malignant = a phenotype heuristic with NO CNA validation (STAD: Epithelial∩GC)
#     unspecified     — the product's method is not documented here (never asserted)
_PRODUCT_ANNOTATION_METHOD = {
    "sc-pseudobulk-tumor-crc-coadread-v1": "curated",
    "sc-pseudobulk-tumor-luca-nsclc-v1": "curated",
    "sc-pseudobulk-tumor-3ca-pancreas-v1": "infercnv",
    "sc-pseudobulk-tumor-3ca-hnsc-v1": "infercnv",
    "sc-pseudobulk-tumor-3ca-kidney-v1": "infercnv",
    "sc-pseudobulk-tumor-3ca-ovarian-v1": "infercnv",
    "sc-pseudobulk-tumor-stad-golim-v1": "phenotype_proxy",
    "sc-pseudobulk-tumor-brca-wu-v1": "curated",  # Wu atlas ships an explicit author 'Cancer Epithelial' malignant label (verbatim), like CRC/LuCA — not inferCNV, not a phenotype heuristic.
    # sc-pseudobulk-donor-celltype-lusc-v1 (LUSC): malignant-call method not documented → unspecified.
}
# Indications whose malignant compartment is POOLED across a broader entity than the query (so the call
# is NOT purified to the queried disease). Documented: 3CA kidney = pan-renal (KIRC), 3CA ovarian =
# pan-gynecologic (OV); LUAD is served by the NSCLC-umbrella LuCA product (LUSC has its own dedicated cube).
_MULTI_ENTITY_POOLED_INDICATIONS = frozenset({"KIRC", "OV", "LUAD"})


def _malignant_annotation_provenance(indication: str) -> dict:
    """Structured malignant-annotation provenance for an indication (review G11). Verdict-inert."""
    ind = str(indication).upper().strip()
    product = INDICATION_TO_PRODUCT.get(ind)
    return {
        "malignant_annotation_method": _PRODUCT_ANNOTATION_METHOD.get(product, "unspecified"),
        "entity_purity": (
            "multi_entity_pooled"
            if ind in _MULTI_ENTITY_POOLED_INDICATIONS
            else ("entity_specific" if product else "unspecified")
        ),
    }


_PARQUET_COLS = [
    "gene_symbol",
    "dataset_id",
    "donor_id",
    "compartment",
    "n_cells",
    "detection_fraction",
    "abundance_log1p_cp10k",
]


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

    s3fs = fs.S3FileSystem(region="us-east-1")  # default cred chain honors AWS_PROFILE=cbg
    # predicate-pushdown on the physical sort key (gene_symbol) — touches few row-groups.
    filters = [("gene_symbol", "==", str(target).upper().strip())]
    try:
        tbl = pq.read_table(f"{S3_BUCKET}/{key}", filesystem=s3fs, filters=filters, columns=_PARQUET_COLS)
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
        return _data_unavailable(
            target,
            indication,
            note=f"No single-cell pseudobulk product landed for indication "
            f"{indication}; sc_rna presence is a named capability gap here.",
        )
    if rows.empty:
        return _data_unavailable(
            target,
            indication,
            note=f"{target} absent from the single-cell pseudobulk product for "
            f"{indication} (not measured in the contributing atlases).",
        )

    comp_summary = _stats.compartment_summary(rows)
    classed = _stats.classify_sc_expression(comp_summary)
    n_donor_groups = rows[["dataset_id", "donor_id"]].drop_duplicates().shape[0]
    out = {
        "sc_expression_class": classed["sc_expression_class"],
        "tce_homogeneity_class": classed["tce_homogeneity_class"],  # Phase 3.2 biologics-homogeneity lens
        "malignant_detection_fraction": classed["malignant_detection_fraction"],
        "malignant_abundance_log1p_cp10k": classed["malignant_abundance_log1p_cp10k"],
        "malignant_compartment_available": classed["malignant_compartment_available"],
        "malignant_n_donors": classed[
            "malignant_n_donors"
        ],  # L1: donors backing the malignant call (reliability floor = MIN_RELIABLE_DONORS)
        "malignant_n_cells": classed[
            "malignant_n_cells"
        ],  # G3: total malignant cells over reliable donors (floor = MIN_MALIGNANT_CELLS_TOTAL)
        "ambient_contamination_risk": classed[
            "ambient_contamination_risk"
        ],  # G8: soup-leakage risk on a malignant-subset call (verdict-inert heuristic)
        "top_microenvironment_compartment": classed["top_microenvironment_compartment"],
        "top_microenvironment_detection_fraction": classed["top_microenvironment_detection_fraction"],
        "n_compartments_measured": classed["n_compartments_measured"],
        "n_donor_groups": int(n_donor_groups),
        "n_datasets": int(rows["dataset_id"].nunique()),
        "compartment_detection": {c: comp_summary[c]["median_detection_fraction"] for c in comp_summary},
        # v1 sc-presence depth (additive; presence ladder above untouched): the FULL per-compartment
        # vector + an explicit CAF/stromal readout (the deck's tumor-vs-CAF dual-target axis).
        "per_compartment": _stats.per_compartment_vector(comp_summary),
        "indication": str(indication).upper().strip(),
        "product_id": INDICATION_TO_PRODUCT.get(str(indication).upper().strip()),
        # G11: malignant-annotation provenance (how the malignant compartment was called + whether it is
        # entity-specific). Verdict-inert; a confidence input for downstream (curated/inferCNV/
        # entity-specific > phenotype_proxy / multi_entity_pooled).
        **_malignant_annotation_provenance(indication),
    }
    out.update(_stats.caf_readout(comp_summary))
    # Stromal-confound attribution (the tumor-selectivity stromal-confound veto instrument): is a bulk
    # selective signal driven by CAF/stroma rather than malignant cells? Provenance-gated so only a
    # trustworthy (curated/inferCNV, entity-specific) cube can fire the verdict-moving veto. Verdict-inert
    # here; wired to the veto via target-contracts + the shared selectivity_veto clamp.
    out["stromal_confound_class"] = _stats.classify_stromal_confound(
        out["sc_expression_class"],
        out["caf_vs_malignant_class"],
        out["top_microenvironment_compartment"],
        out["malignant_annotation_method"],
        out["entity_purity"],
    )
    # Two-axis TCE antigen-escape readout (2026-08-20): within-tumour coverage + INTER-donor consistency,
    # the honest heterogeneity call that supersedes the single-number tce_homogeneity_class (kept above
    # for back-compat). Merge only the NEW keys (malignant_detection_fraction / n_donors already present).
    _het = _stats.malignant_heterogeneity_readout(comp_summary)
    out.update(
        {
            k: _het[k]
            for k in (
                "within_tumor_coverage_class",
                "inter_donor_consistency_class",
                "tce_antigen_escape_class",
                "malignant_detection_donor_iqr",
                "fraction_donors_broadly_detecting",
            )
        }
    )
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
        "malignant_n_donors": 0,
        "malignant_n_cells": 0,
        "ambient_contamination_risk": "data_unavailable",
        "stromal_confound_class": "data_unavailable",
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
        "within_tumor_coverage_class": "data_unavailable",
        "inter_donor_consistency_class": "data_unavailable",
        "tce_antigen_escape_class": "data_unavailable",
        "malignant_detection_donor_iqr": None,
        "fraction_donors_broadly_detecting": None,
        "indication": str(indication).upper().strip(),
        "product_id": INDICATION_TO_PRODUCT.get(str(indication).upper().strip()),
        **_malignant_annotation_provenance(indication),  # G11 (present even on the coverage-gap path)
        "_data_note": note,
    }
