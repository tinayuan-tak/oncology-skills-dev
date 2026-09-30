"""oncogenic_pathway_alteration.read — library entry for the per-indication oncogenic-pathway-alteration facet.

Reads the MATERIALIZED per-(pathway x indication) alteration-frequency rollup (Sanchez-Vega 2018) and
returns the oncogenic-pathway-alteration-context card's summary_fields for the indication, annotating
which pathway(s) the target belongs to (gene->pathway membership) + that pathway's cohort alteration
frequency. Read grain pre-aggregated → O(1) per-indication slice. Composite indications
(COADREAD/NSCLC) pool member studies sample-weighted, mirroring the DDR/PROGENy readers.

Target-INDEPENDENT cohort context (tier: indication); a target maps in via its pathway membership.
Verdict-INERT: no resolver rung.
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli

METHOD_VERSION = _cli.METHOD_VERSION
DEFAULT_AWS_PROFILE = "cbg"
DERIVED_MANIFEST_ID = "oncogenic-pathway-alteration-per-indication-v1"


def _resolve_derived_uri() -> str:
    """Resolve the derived product's manifest-authoritative S3 URI at call time (not import).

    The resolver seam: the s3_uri lives in the data-catalog manifest (single source of truth),
    never a parallel hand-typed copy that can drift on a re-emit.
    """
    from onc_methods.catalog_query.read import s3_uri_for

    return s3_uri_for(DERIVED_MANIFEST_ID)


# composite indication → member TCGA study codes (mirror the other readers)
_ALIASES = {
    "COADREAD": ["COAD", "READ"],
    "NSCLC": ["LUAD", "LUSC"],
    "CRC": ["COAD", "READ"],
    "GC": ["STAD"],
    "PDAC": ["PAAD"],
    "MELANOMA": ["SKCM"],
}

_GENE_MAP_CACHE = None


from onc_methods.target_id_sidecar import ensure_aws_profile


def _load_product():
    from onc_methods.derived_product import load_materialized_product

    ensure_aws_profile()
    # dev fallback (rebuilds from source) if the materialized product is unreachable
    return load_materialized_product(_resolve_derived_uri(), dev_build=_cli.build_per_indication_table)


def _gene_pathways(target: str):
    global _GENE_MAP_CACHE
    if not target:
        return []
    if _GENE_MAP_CACHE is None:
        try:
            _GENE_MAP_CACHE = _cli.load_gene_pathway_map()
        except Exception as e:  # noqa: BLE001
            # Absence-discipline: a genuinely-missing map is an honest empty ({} → target has no
            # pathway membership); a transient / creds / broken-env error must re-raise, else every
            # target silently reads as "in no pathway" — indistinguishable from a real absence.
            from onc_methods.target_id_sidecar import is_definitively_absent

            if not is_definitively_absent(e):
                raise
            _GENE_MAP_CACHE = {}
    return _GENE_MAP_CACHE.get(target, [])


def read_oncogenic_pathway_alteration(target: Optional[str] = None, indication: Optional[str] = None) -> dict:
    """Return the oncogenic-pathway-alteration-context card summary_fields for the indication.

    `target` used only to annotate the target's own pathway membership + that pathway's cohort
    alteration frequency; never changes the cohort landscape. data_unavailable when unmapped.
    """
    import pandas as pd

    if not indication:
        return {
            "oncogenic_pathway_class": "data_unavailable",
            "_note": "indication required (per-indication cohort facet).",
        }
    df = _load_product()
    codes = _ALIASES.get(indication.upper(), [indication.upper()])
    sub = df[df["indication"].isin(codes)]
    if sub.empty:
        return {
            "oncogenic_pathway_class": "data_unavailable",
            "indication": indication,
            "_note": f"{indication} (codes {codes}) not in the Sanchez-Vega oncogenic-pathway product.",
        }

    # pool composite indications sample-weighted per pathway
    def _pool(g):
        n = g["n_samples"].sum()
        frac = (g["frac_altered"] * g["n_samples"]).sum() / n if n else 0.0
        return pd.Series({"n_samples": int(n), "frac_altered": round(float(frac), 4)})

    pooled = sub.groupby("pathway").apply(_pool, include_groups=False).reset_index()
    pooled["pathway_alteration_class"] = pooled["frac_altered"].map(
        lambda f: (
            "frequently_altered"
            if f >= _cli.HIGH_ALT_FRAC
            else "occasionally_altered"
            if f >= 0.10
            else "rarely_altered"
        )
    )

    frequently = sorted(pooled[pooled.pathway_alteration_class == "frequently_altered"]["pathway"].tolist())
    target_pathways = _gene_pathways(target)
    # the target's pathway alteration frequency in this cohort (if the target maps to a pathway)
    target_pw_rows = pooled[pooled.pathway.isin(target_pathways)][
        ["pathway", "frac_altered", "pathway_alteration_class"]
    ].to_dict("records")

    return {
        "oncogenic_pathway_class": "frequently_altered" if frequently else "profiled",  # PRIMARY
        "indication": indication,
        "frequently_altered_pathways": frequently,
        "n_pathways_profiled": int(len(pooled)),
        "target_pathway_membership": target_pathways,
        "target_pathway_alteration": target_pw_rows,  # the target's pathway's cohort alteration freq
        "per_pathway": pooled.sort_values("frac_altered", ascending=False).to_dict("records"),
        "pooled_from": codes if len(codes) > 1 else None,
        "_method_version": METHOD_VERSION,
        "_source": "Sanchez-Vega 2018 Cell (oncogenic-pathway alteration); verdict-inert cohort context",
    }
