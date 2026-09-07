"""pdxe_drug_response.read — card-side reader for the per-gene PDXE in-vivo drug-response product.

Reads pdxe-drug-response-per-gene-v1 (one row per PDXE 'Treatment target' gene token; see data-catalog
scripts/derive_pdxe_drug_response.py). Returns the per-gene in-vivo drug-response summary the
target-pdx-drug-response card consumes: how many treatments/models named the gene, the median/min
BestAvgResponse (signed % tumour-volume change; LOWER/more-negative = more shrinkage = more active),
the objective-responder fraction (mRECIST CR/PR), and the most-active treatment.

TARGET-GRAIN (gene_symbol ONLY). This rollup aggregates response ACROSS models and does not split by
indication, so `indication` is accepted and IGNORED (the compose-dashboard generic-dispatch contract
calls every reader as fn(target=, indication=)). A per-model genotype-stratified response product is a
downstream v2 (see the derived manifest).

The product is gene-SORTED (sort key == read filter key == gene_symbol), so a per-gene read uses
pyarrow S3FileSystem + predicate-pushdown to touch a few row-groups (the gene-keyed-product invariant).
Dependencies are pyarrow/pandas/boto3 ONLY; pyarrow's default credential chain honours AWS_PROFILE=cbg.

ABSENCE DISCIPLINE: a missing product / an absent gene token resolves data_unavailable (honest coverage
gap, never a fabricated count); transient S3 faults (throttling / timeout / creds) PROPAGATE rather than
masquerade as absence.

VERDICT-INERT: a translational in-vivo-corroboration display facet. It emits a `pdx_drug_response_class`
PRIMARY categorical for provenance/availability accounting, but NO interpretation rule consumes it — it
moves no gate verdict.

CAVEAT — the gene_symbol key is the NATIVE PDXE 'Treatment target' token (curated free text; may be a
protein-FAMILY / pathway / shorthand token, not a clean HGNC symbol). A target whose token is absent
resolves data_unavailable; this reader does not consult the resolver sidecar (a token->HGNC v2).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from methods.catalog_query.read import bucket_key_for

MANIFEST_ID = "pdxe-drug-response-per-gene-v1"
S3_BUCKET = "onc-compbio"
SOURCE = "PDXE-Gao-2015"

_PARQUET_COLS = [
    "gene_symbol",
    "n_treatments",
    "n_models_tested",
    "n_response_records",
    "median_best_avg_response",
    "min_best_avg_response",
    "responder_fraction",
    "most_active_treatment",
    "most_active_treatment_median_best_avg_response",
    "treatment_types",
]


def _round(v, ndigits: int = 4):
    import math

    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(fv) else round(fv, ndigits)


def _int_or_none(v):
    import math

    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _str_or_none(v):
    if v is None:
        return None
    s = str(v)
    return s if s and s.lower() != "nan" else None


@lru_cache(maxsize=256)
def _read_gene_row(target: str):
    """The single per-gene row for `target`. Returns a pandas DataFrame (possibly empty when the token
    is absent), or None when the landed product cannot be found (404). Transient S3 faults propagate."""
    try:
        _, key = bucket_key_for(MANIFEST_ID)
    except FileNotFoundError:
        return None
    import pyarrow.fs as fs
    import pyarrow.parquet as pq

    s3fs = fs.S3FileSystem(region="us-east-1")  # default cred chain honours AWS_PROFILE=cbg
    filters = [("gene_symbol", "==", str(target).upper().strip())]
    try:
        tbl = pq.read_table(f"{S3_BUCKET}/{key}", filesystem=s3fs, filters=filters, columns=_PARQUET_COLS)
    except FileNotFoundError:
        return None
    return tbl.to_pandas()


def _summarize(row) -> dict:
    """Roll the single per-gene product row up to the per-gene PDX in-vivo-response summary."""
    responder_fraction = _round(row["responder_fraction"])
    # descriptive availability/direction class (verdict-inert): were there any objective (mRECIST CR/PR)
    # responders across the PDX population trials naming this target?
    if responder_fraction is None:
        cls = "pdx_response_unavailable"
    elif responder_fraction > 0:
        cls = "pdx_objective_responders"
    else:
        cls = "pdx_no_objective_response"
    return {
        "pdx_drug_response_class": cls,
        "n_treatments": _int_or_none(row["n_treatments"]),
        "n_models_tested": _int_or_none(row["n_models_tested"]),
        "n_response_records": _int_or_none(row["n_response_records"]),
        "median_best_avg_response": _round(row["median_best_avg_response"]),
        "min_best_avg_response": _round(row["min_best_avg_response"]),
        "responder_fraction": responder_fraction,
        "most_active_treatment": _str_or_none(row["most_active_treatment"]),
        "most_active_treatment_median_best_avg_response": _round(row["most_active_treatment_median_best_avg_response"]),
        "treatment_types": _str_or_none(row["treatment_types"]),
        "source": SOURCE,
    }


def _data_unavailable(note: str) -> dict:
    """Honest coverage-gap payload — primary `pdx_drug_response_class: data_unavailable` + a note."""
    return {
        "pdx_drug_response_class": "data_unavailable",
        "n_treatments": None,
        "n_models_tested": None,
        "n_response_records": None,
        "median_best_avg_response": None,
        "min_best_avg_response": None,
        "responder_fraction": None,
        "most_active_treatment": None,
        "most_active_treatment_median_best_avg_response": None,
        "treatment_types": None,
        "source": SOURCE,
        "_data_note": note,
    }


def read_target_summary(target: str, indication: Optional[str] = None) -> dict:
    """Per-gene PDXE IN-VIVO drug-response summary (translational-readiness PDX-corroboration lens).
    VERDICT-INERT display facet. TARGET-GRAIN: `indication` is accepted and IGNORED (the rollup
    aggregates response across models; there is no per-indication split in this product)."""
    if not target:
        return _data_unavailable("no target gene supplied.")
    rows = _read_gene_row(str(target).upper().strip())
    if rows is None:
        return _data_unavailable(f"No landed PDXE drug-response product ({MANIFEST_ID}).")
    if rows.empty:
        return _data_unavailable(
            f"{str(target).upper().strip()} is not a PDXE 'Treatment target' token in {MANIFEST_ID} "
            f"(no treatment in the Gao 2015 PDX trials names this gene as a target)."
        )
    out = _summarize(rows.iloc[0])
    out["_pdxe_target_token"] = str(target).upper().strip()
    out["_product_id"] = MANIFEST_ID
    return out
