"""progeny_pathway_activity.read — library entry for the per-indication PROGENy pathway-activity facet.

Reads the MATERIALIZED per-(pathway x indication) rollup and returns the pathway-activity-context
card's summary_fields for the requested indication. Read grain is pre-aggregated → an O(1) per-indication
slice (no per-sample scoring at run time). Composite indications (COADREAD/NSCLC) pool their member
TCGA studies' rows sample-weighted, mirroring the DDR reader.

Target-INDEPENDENT (tier: indication): pathway activity is a cohort property; a target maps in only as
"which indication am I in" + (optionally) "which pathway is my target on". Verdict-INERT: no resolver rung.
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli

METHOD_VERSION = _cli.METHOD_VERSION
DEFAULT_AWS_PROFILE = "cbg"
DERIVED_MANIFEST_ID = "progeny-pathway-activity-per-indication-v1"


def _resolve_derived_uri() -> str:
    """Resolve the derived product's manifest-authoritative S3 URI at call time (not import).

    The resolver seam: the s3_uri lives in the data-catalog manifest (single source of truth),
    never a parallel hand-typed copy that can drift on a re-emit.
    """
    from onc_methods.catalog_query.read import s3_uri_for

    return s3_uri_for(DERIVED_MANIFEST_ID)


# activity_z_across_indications thresholds → a compact per-pathway relative class.
_Z_HIGH = 1.0  # >= +1 SD across indications → relatively HIGH activity
_Z_LOW = -1.0  # <= -1 SD → relatively LOW

_ALIASES = _cli.INDICATION_TO_STUDIES  # composite → member studies (reuse the build map)


from onc_methods.target_id_sidecar import ensure_aws_profile


def _load_product():
    from onc_methods.derived_product import load_materialized_product

    ensure_aws_profile()
    # dev fallback (slow): build_per_indication_table() rebuilds from source if the product is unreachable
    return load_materialized_product(_resolve_derived_uri(), dev_build=_cli.build_per_indication_table)


def _member_indications(indication: str):
    """Map a requested indication to the single-study build-indication rows it should read.
    COADREAD → [COAD, READ]; NSCLC → [LUAD, LUSC]; a single indication → itself."""
    studies = _ALIASES.get(indication.upper(), [indication.upper()])
    # reverse: build rows are keyed by the single-study indication code == the study code here
    return studies


def read_progeny_pathway_activity(target: Optional[str] = None, indication: Optional[str] = None) -> dict:
    """Return the pathway-activity-context card's summary_fields for the indication.

    `target` accepted for the dispatcher signature; used only to annotate the target's OWN pathway
    membership (which PROGENy pathway(s) the target is a responsive-gene of), never to change the
    cohort landscape. Returns data_unavailable when the indication is absent.
    """
    import pandas as pd

    if not indication:
        return {
            "pathway_activity_class": "data_unavailable",
            "_note": "indication required (PROGENy activity is a per-indication cohort facet).",
        }
    df = _load_product()
    codes = _member_indications(indication)
    sub = df[df["indication"].isin(codes)]
    if sub.empty:
        return {
            "pathway_activity_class": "data_unavailable",
            "indication": indication,
            "_note": f"{indication} (codes {codes}) not in the PROGENy activity product.",
        }

    # pool member studies sample-weighted per pathway (composite indications)
    def _pool(g):
        n = g["n_samples"].sum()
        wmed = (g["median_activity"] * g["n_samples"]).sum() / n if n else 0.0
        z = (g["activity_z_across_indications"] * g["n_samples"]).sum() / n if n else 0.0
        return pd.Series(
            {"n_samples": int(n), "median_activity": round(float(wmed), 4), "activity_z": round(float(z), 4)}
        )

    pooled = sub.groupby("pathway").apply(_pool, include_groups=False).reset_index()

    def _cls(z):
        return "relatively_high" if z >= _Z_HIGH else "relatively_low" if z <= _Z_LOW else "average"

    pooled["relative_class"] = pooled["activity_z"].map(_cls)

    high = sorted(pooled[pooled.relative_class == "relatively_high"]["pathway"].tolist())
    low = sorted(pooled[pooled.relative_class == "relatively_low"]["pathway"].tolist())

    # target's own pathway membership (which pathways it is a responsive gene of), if mapped
    target_pathways = []
    if target:
        net = _cli._load_model()
        target_pathways = sorted(net[net["target"] == target]["source"].unique().tolist())

    return {
        "pathway_activity_class": "relatively_high"
        if high
        else "profiled",  # PRIMARY (profiled = computed, no standout high)
        "indication": indication,
        "relatively_high_pathways": high,
        "relatively_low_pathways": low,
        "n_pathways_profiled": int(len(pooled)),
        "target_pathway_membership": target_pathways,  # which PROGENy pathways the target reports into
        "per_pathway": pooled.sort_values("activity_z", ascending=False).to_dict("records"),
        "pooled_from": codes if len(codes) > 1 else None,
        "_method_version": METHOD_VERSION,
        "_source": "PROGENy (Schubert 2018, Apache-2.0); verdict-inert cohort pathway-activity context",
    }
