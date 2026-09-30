"""stemness_index.read — library entry for the per-indication mRNAsi tumor-stemness facet.

Reads the MATERIALIZED per-indication mRNAsi rollup (Malta 2018 signature, reimplemented) and returns
the stemness-context card's summary_fields. Read grain pre-aggregated → O(1) per-indication slice.
Composite indications (COADREAD/NSCLC) pool member studies sample-weighted.

Target-INDEPENDENT cohort context (tier: indication). Verdict-INERT: no resolver rung.
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli

METHOD_VERSION = _cli.METHOD_VERSION
DEFAULT_AWS_PROFILE = "cbg"
DERIVED_MANIFEST_ID = "stemness-mrnasi-per-indication-v1"


def _resolve_derived_uri() -> str:
    """Resolve the derived product's manifest-authoritative S3 URI at call time (not import).

    The resolver seam: the s3_uri lives in the data-catalog manifest (single source of truth),
    never a parallel hand-typed copy that can drift on a re-emit.
    """
    from onc_methods.catalog_query.read import s3_uri_for

    return s3_uri_for(DERIVED_MANIFEST_ID)


_ALIASES = _cli.INDICATION_TO_STUDIES


from onc_methods.target_id_sidecar import ensure_aws_profile


def _load_product():
    from onc_methods.derived_product import load_materialized_product

    ensure_aws_profile()
    # dev fallback (slow: rescores from source) if the materialized product is unreachable
    return load_materialized_product(_resolve_derived_uri(), dev_build=_cli.build_per_indication_table)


def read_stemness_index(target: Optional[str] = None, indication: Optional[str] = None) -> dict:
    """Return the stemness-context card summary_fields for the indication.

    `target` accepted for the dispatcher signature; NOT consumed (cohort-level stemness is
    target-independent). data_unavailable when the indication is absent.
    """
    if not indication:
        return {"stemness_class": "data_unavailable", "_note": "indication required (per-indication cohort facet)."}
    df = _load_product()
    codes = _ALIASES.get(indication.upper(), [indication.upper()])
    sub = df[df["indication"].isin(codes)]
    if sub.empty:
        return {
            "stemness_class": "data_unavailable",
            "indication": indication,
            "_note": f"{indication} (codes {codes}) not in the stemness product.",
        }
    n = int(sub["n_samples"].sum())
    med = float((sub["median_mrnasi"] * sub["n_samples"]).sum() / n) if n else 0.0
    pan_q3 = float(sub["pan_cancer_q3_mrnasi"].iloc[0])
    pan_med = float(sub["pan_cancer_median_mrnasi"].iloc[0])
    cls = "stem_high" if med >= pan_q3 else "stem_low" if med < pan_med else "stem_intermediate"
    return {
        "stemness_class": cls,  # PRIMARY (relative to pan-cancer distribution)
        "indication": indication,
        "median_mrnasi": round(med, 4),
        "pan_cancer_median_mrnasi": round(pan_med, 4),
        "pan_cancer_q3_mrnasi": round(pan_q3, 4),
        "n_samples": n,
        "pooled_from": codes if len(codes) > 1 else None,
        "_method_version": METHOD_VERSION,
        "_source": "Malta 2018 mRNAsi signature, REIMPLEMENTED on recount3 (Spearman+pan-cancer min-max); verdict-inert cohort context",
        "_caveat": "reimplemented per-sample scores (Malta method applied to recount3), NOT the published per-sample table (which is not distributed).",
    }
