"""pancanatlas_ddr_context.read — library entry for the per-indication DDR/HRD context facet.

Reads the MATERIALIZED per-indication rollup (pancanatlas-ddr-deficiency-per-indication-v1) and
returns the ddr-deficiency-context card's summary_fields for the requested indication. Read grain is
pre-aggregated → an O(1) per-indication lookup (no per-sample groupby at run time). Falls back to a
LIVE build_per_indication_table() only if the derived parquet is unreachable (dev convenience).

Target-INDEPENDENT (tier: indication): the DDR/HRD context is a cohort property; a target maps in
only as "which indication am I in". Verdict-INERT: no resolver rung.
"""
from __future__ import annotations

from typing import Optional

from . import cli as _cli

METHOD_VERSION = _cli.METHOD_VERSION
DEFAULT_AWS_PROFILE = "cbg"

DERIVED_MANIFEST_ID = "pancanatlas-ddr-deficiency-per-indication-v1"


def _resolve_derived_uri() -> str:
    """Resolve the derived product's manifest-authoritative S3 URI at call time (not import).

    The resolver seam: the s3_uri lives in the data-catalog manifest (single source of truth),
    never a parallel hand-typed copy that can drift on a re-emit.
    """
    from methods.catalog_query.read import s3_uri_for
    return s3_uri_for(DERIVED_MANIFEST_ID)

# Map common indication aliases to the TCGA disease codes used in the DDR resource.
_INDICATION_ALIASES = {
    "COADREAD": ["COAD", "READ"], "NSCLC": ["LUAD", "LUSC"],
    "GC": ["STAD"], "PDAC": ["PAAD"], "MELANOMA": ["SKCM"], "CRC": ["COAD", "READ"],
}


from methods.target_id_sidecar import ensure_aws_profile


def _load_product():
    """Load the materialized per-indication product (S3), else live-build fallback."""
    from methods.derived_product import load_materialized_product
    ensure_aws_profile()
    # dev fallback: recompute live from source (slower; ~6s) if the product is unreachable
    return load_materialized_product(_resolve_derived_uri(), dev_build=_cli.build_per_indication_table)


def _combine_rows(rows) -> dict:
    """Combine multiple TCGA-disease rows (e.g. COADREAD = COAD+READ) into one context read.
    frac_hrd_high is a sample-weighted mean; median_hrd_score is a sample-weighted mean of the
    per-cohort medians (an approximation, not the true pooled median). Re-classify on the pooled fraction."""
    total_n = int(sum(r["n_samples"] for r in rows))
    if total_n == 0:
        return {}
    frac = sum(r["frac_hrd_high"] * r["n_samples"] for r in rows) / total_n
    med_hrd = sum(r["median_hrd_score"] * r["n_samples"] for r in rows) / total_n
    return {
        "n_samples": total_n,
        "frac_hrd_high": round(float(frac), 4),
        "median_hrd_score": round(float(med_hrd), 3),
        "ddr_context_class": _cli._classify(total_n, frac),
        "pooled_from": [r["indication"] for r in rows],
    }


def read_ddr_deficiency_context(target: Optional[str] = None,
                                indication: Optional[str] = None) -> dict:
    """Return the ddr-deficiency-context card's summary_fields for the indication.

    `target` accepted for the dispatcher signature but NOT consumed (cohort-level, target-independent).
    Returns data_unavailable when the indication is not in the DDR resource.
    """
    if not indication:
        return {"ddr_context_class": "data_unavailable",
                "_note": "indication required (DDR context is a per-indication cohort facet)."}
    df = _load_product()
    codes = _INDICATION_ALIASES.get(indication.upper(), [indication.upper()])
    rows = [r._asdict() if hasattr(r, "_asdict") else dict(r)
            for r in (df[df["indication"].isin(codes)]).to_dict("records")]
    if not rows:
        return {"ddr_context_class": "data_unavailable", "indication": indication,
                "_note": f"{indication} (codes {codes}) not in the PanCanAtlas DDR resource."}
    if len(rows) == 1:
        out = dict(rows[0])
    else:
        out = _combine_rows(rows)
    out["indication"] = indication
    out["hrd_high_cut"] = _cli.HRD_HIGH_CUT
    out["_method_version"] = METHOD_VERSION
    out["_source"] = "pancanatlas-ddr (Knijnenburg 2018); verdict-inert cohort context"
    return out
