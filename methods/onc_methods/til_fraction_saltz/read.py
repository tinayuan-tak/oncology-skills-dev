"""til_fraction_saltz.read — per-indication absolute TIL fraction (Saltz 2018).

read_til_fraction(indication) resolves the OncoTree indication → TCGA study code(s), pushdown-reads the
per-sample product on cancer_type, and reduces to a median til_percentage + til_fraction_class (the
absolute-TIL corroborator of the immune-context CIBERSORT CD8 call). read_target_summary(target,
indication) is the generic-dispatch wrapper (target ignored — indication-tier). 13-study coverage;
any other indication → data_unavailable (fail-closed, never imputed).
"""

from __future__ import annotations

from typing import Optional

from onc_methods._common.s3 import get_s3fs
from onc_methods.catalog_query.read import bucket_key_for
from onc_methods.target_id_sidecar import ensure_aws_profile, is_definitively_absent

METHOD_VERSION = "1.0.0"
DERIVED_MANIFEST_ID = "tcga-til-fraction-saltz-per-sample-v1"
MIN_N = 30  # per-indication admissibility floor (below → data_unavailable, wide-CI guard)

# Reuse the canonical OncoTree→TCGA-study map (+ the NSCLC umbrella supplement), same as immune_context.
try:
    from onc_methods.dge_deseq2.read import INDICATION_TO_TCGA_STUDIES as _DGE_MAP
except Exception:  # noqa: BLE001 — map import is best-effort; empty map → all data_unavailable (honest)
    _DGE_MAP = {}
# UCEC/UVM are in the Saltz 13-study coverage set but absent from the dge_deseq2 map; add them
# (self-mapped) so they resolve rather than returning data_unavailable. (See manifest coverage_studies.)
_UMBRELLA_SUPPLEMENT = {"NSCLC": ["LUAD", "LUSC"], "UCEC": ["UCEC"], "UVM": ["UVM"]}
INDICATION_TO_TCGA_STUDIES = {**_UMBRELLA_SUPPLEMENT, **_DGE_MAP}

# Saltz til_percentage coverage (13 TCGA studies). Absolute-threshold bins on the per-indication median
# til_percentage (coarse; the value is corroboration of the relative CIBERSORT call, not a standalone call).
_HIGH_TIL = 5.0
_INTERMEDIATE_TIL = 2.0


def _get_s3fs():
    return get_s3fs(pre_hook=ensure_aws_profile)


def _classify(median_til: Optional[float], n: int) -> str:
    if n < MIN_N or median_til is None:
        return "data_unavailable"
    if median_til >= _HIGH_TIL:
        return "til_high"
    if median_til >= _INTERMEDIATE_TIL:
        return "til_intermediate"
    return "til_low"


def _read_rows(studies):
    import pyarrow.parquet as pq

    bucket, key = bucket_key_for(DERIVED_MANIFEST_ID)
    try:
        tbl = pq.read_table(f"{bucket}/{key}", filesystem=_get_s3fs(), filters=[("cancer_type", "in", list(studies))])
    except Exception as e:  # noqa: BLE001
        if is_definitively_absent(e):
            return None
        raise
    return tbl.to_pylist()


def _empty(note: str) -> dict:
    return {
        "til_fraction_class": "data_unavailable",
        "_data_note": note,
        "_data_source": DERIVED_MANIFEST_ID,
        "method_version": METHOD_VERSION,
    }


def read_til_fraction(indication: str) -> dict:
    if not indication:
        return _empty("no indication supplied")
    studies = INDICATION_TO_TCGA_STUDIES.get((indication or "").upper().strip())
    if not studies:
        return _empty(f"indication {indication!r} has no TCGA-study mapping")
    rows = _read_rows(studies)
    if rows is None:
        return _empty(f"{DERIVED_MANIFEST_ID} not found (404)")
    tils = [r["til_percentage"] for r in rows if r.get("til_percentage") is not None]
    n = len(tils)
    if n < MIN_N:
        # coverage gap: none of the mapped studies is in the Saltz 13-study set (or too few) → honest gap
        out = _empty(f"only {n} Saltz TIL samples for {indication} (studies {list(studies)}); Saltz covers 13 studies")
        out["n_samples"] = n
        return out
    import statistics

    median_til = statistics.median(tils)
    clusters = [r["number_of_clusters"] for r in rows if r.get("number_of_clusters") is not None]
    cls = _classify(median_til, n)
    return {
        "til_fraction_class": cls,
        "median_til_percentage": round(median_til, 4),
        "median_number_of_clusters": (round(statistics.median(clusters), 2) if clusters else None),
        "n_samples": n,
        "tcga_studies": list(studies),
        "til_context": (
            f"Saltz H&E DL absolute TIL: median til_percentage={median_til:.2f} ({cls}) "
            f"over {n} {'/'.join(studies)} participants — orthogonal corroborator of the "
            f"CIBERSORT relative CD8 call"
        ),
        "_data_source": DERIVED_MANIFEST_ID,
        "method_version": METHOD_VERSION,
    }


def read_target_summary(target: str, indication: Optional[str] = None) -> dict:
    """Generic-dispatch wrapper — target is ignored (indication-tier)."""
    return read_til_fraction(indication)
