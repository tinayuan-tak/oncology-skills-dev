"""tcga_mc3_signatures.read — library entry for the per-indication mutational-signature context facet.

Reads the MATERIALIZED per-indication rollup (tcga-mc3-mutational-signatures-per-indication-v1) and
returns the mutational-signature-context card's summary_fields for the requested indication. Read
grain is pre-aggregated → an O(1) per-indication lookup (no per-sample refit at run time).

Target-INDEPENDENT (tier: indication): the mutagenic-process profile is a cohort property; a target
maps in only as "which indication am I in". Verdict-INERT: no resolver rung.
"""

from __future__ import annotations

from typing import Optional

from . import cli as _cli
from .signatures import INFORMATIVE_PROCESSES, NON_BASELINE_PROCESSES

METHOD_VERSION = _cli.METHOD_VERSION
DEFAULT_AWS_PROFILE = "cbg"
DERIVED_MANIFEST_ID = "tcga-mc3-mutational-signatures-per-indication-v1"


def _resolve_derived_uri() -> str:
    from onc_methods.catalog_query.read import s3_uri_for

    return s3_uri_for(DERIVED_MANIFEST_ID)


from onc_methods.target_id_sidecar import ensure_aws_profile


def _load_product():
    # No dev-build fallback: an unreachable/empty product raises (RuntimeError), never a silent empty.
    from onc_methods.derived_product import load_materialized_product

    ensure_aws_profile()
    return load_materialized_product(_resolve_derived_uri())


# Framework indication → TCGA study code(s). The product is keyed on TCGA study codes (33 cancers);
# an aliased/composite indication resolves to >1 code and is pooled sample-weighted (mirrors
# pancanatlas_ddr_context). Unaliased indications pass through as their own code (e.g. BRCA, OV).
_INDICATION_ALIASES = {
    "COADREAD": ["COAD", "READ"],
    "CRC": ["COAD", "READ"],
    "NSCLC": ["LUAD", "LUSC"],
    "GC": ["STAD"],
    "GASTRIC": ["STAD"],
    "PDAC": ["PAAD"],
    "MELANOMA": ["SKCM"],
    "GBM": ["GBM"],
    "AML": ["LAML"],
}


def _pool_rows(rows: list, indication: str) -> dict:
    """Combine >1 TCGA-code rows (e.g. COADREAD = COAD+READ) sample-weighted, re-classify on the pool."""
    total_n = int(sum(int(r["n_samples"]) for r in rows))
    out = {"indication": indication, "n_samples": total_n}
    for pr in INFORMATIVE_PROCESSES:
        frac = sum(float(r[f"frac_{pr}_high"]) * int(r["n_samples"]) for r in rows) / total_n if total_n else 0.0
        out[f"frac_{pr}_high"] = round(frac, 4)
        out[f"{pr}_class"] = _cli._classify(total_n, frac)
    nb = {p: out[f"frac_{p}_high"] for p in NON_BASELINE_PROCESSES}
    top = max(nb, key=nb.get) if nb else None
    out["dominant_process"] = top if (top and nb[top] >= _cli.INTERMEDIATE_FRAC) else "no_dominant_process"
    enr = [p for p in NON_BASELINE_PROCESSES if out[f"{p}_class"] == "enriched"]
    out["enriched_processes"] = ",".join(enr) if enr else "none"
    out["pooled_from"] = [r["indication"] for r in rows]
    return out


def read_mutational_signature_context(target: Optional[str] = None, indication: Optional[str] = None) -> dict:
    """Return the mutational-signature-context card's summary_fields for the indication.

    `target` accepted for the dispatcher signature but NOT consumed (cohort-level, target-independent).
    The product is keyed on TCGA study codes (33 cancers); a framework indication is aliased to its
    TCGA code(s) and pooled sample-weighted. Returns data_unavailable when unmapped.
    """
    if not indication:
        return {
            "dominant_process": "data_unavailable",
            "_note": "indication required (signature context is a per-indication cohort facet).",
        }
    df = _load_product()
    codes = _INDICATION_ALIASES.get(indication.upper(), [indication.upper()])
    hit = df[df["indication"].astype(str).str.upper().isin([c.upper() for c in codes])]
    if hit.empty:
        return {
            "dominant_process": "data_unavailable",
            "indication": indication,
            "_note": f"{indication} (codes {codes}) not in the TCGA-MC3 signature product "
            f"(covers {sorted(df['indication'].unique())}).",
        }
    rows = hit.to_dict("records")
    out = _pool_rows(rows, indication) if len(rows) > 1 else {**rows[0], "indication": indication}
    keep = {"indication", "n_samples", "dominant_process", "enriched_processes", "pooled_from"}
    result = {k: out[k] for k in keep if k in out}
    result["n_samples"] = int(result["n_samples"])
    for pr in INFORMATIVE_PROCESSES:
        result[f"{pr}_class"] = out.get(f"{pr}_class")
        result[f"frac_{pr}_high"] = out.get(f"frac_{pr}_high")
    result["_method_version"] = METHOD_VERSION
    result["_source"] = (
        "TCGA MC3 v0.2.8 → SigProfilerAssignment COSMIC v3.3 (pan-cancer, 33 TCGA "
        "studies via TCGA-CDR); verdict-inert cohort context"
    )
    return result
