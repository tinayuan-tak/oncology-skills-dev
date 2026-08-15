"""depmap_mutation_drug_response — loaders for the genotype × DRUG-RESPONSE biomarker.

The framework's mutation-stratified-dependency asks "are mutant lines more GENETICALLY
DEPENDENT (CRISPR/Chronos)?". This module supplies the PHARMACOLOGICAL half: "are mutant
lines more SENSITIVE to a DRUG that targets this gene (PRISM Log2AUC)?" — the missing
biomarker→drug-response link (PRISM was previously genotype-blind by design).

Reads the raw per-cell-line PRISM OncRef Log2AUC matrix (ModelID × compound) + the compound
list (SampleID → CompoundName / GeneSymbolOfTargets), selects the compounds that TARGET the
query gene, and builds a per-ModelID drug-response vector. The stratification itself reuses
depmap_mutation_dependency._mannwhitney_stratification verbatim (substrate-agnostic:
chronos_by_model → drug_response_by_model; lower Log2AUC = more sensitive, same direction as
lower Chronos = more dependent).

PRISM Log2AUC scale: (-inf, 0]; active drug typically -0.3..-1.0; near-flat > -0.05.
"""
from __future__ import annotations

import io
import os
from typing import Optional

# Single-source release-pin → PRISM OncRef source prefix (mirrors depmap_prism_precompute v3).
# NOTE the pin is the DepMap pin (default "26q1"): it resolves the DepMap mutation-matrix PARQUET
# product (depmap-{pin}-parquet-v1) in load_mutation_data. It was previously "dmc-26q1", which
# resolves depmap-dmc-26q1-parquet-v1 (UNREGISTERED) → the parquet tier failed → every call fell
# back to the slow full-CSV mutation read. PRISM itself uses its own independent 25q4 release
# regardless of the pin (any unknown pin → the "default" entry below), so the ModelID join is stable.
_PRISM_RELEASES = {
    "26q1": {
        "source_prefix": "data-catalog/sources/depmap-consortium/prism-oncref-dmc-25q4",
        "compound_list": "PRISMOncologyReferenceLumCompoundList.csv",
        "log2auc_matrix": "PRISMOncologyReferenceLumLog2AUCMatrix.csv",
    },
    # PRISM OncRef 25q4 is the current release consumed regardless of the DepMap pin
    # (DepMap and PRISM release on independent cadences; the ModelID join is stable).
    "default": {
        "source_prefix": "data-catalog/sources/depmap-consortium/prism-oncref-dmc-25q4",
        "compound_list": "PRISMOncologyReferenceLumCompoundList.csv",
        "log2auc_matrix": "PRISMOncologyReferenceLumLog2AUCMatrix.csv",
    },
}

_BUCKET = "onc-compbio"
_DEFAULT_AWS_PROFILE = "cbg"


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = _DEFAULT_AWS_PROFILE


def _release_cfg(release_pin: str) -> dict:
    return _PRISM_RELEASES.get(release_pin, _PRISM_RELEASES["default"])


def _read_csv_s3(key: str, **kwargs):
    import boto3
    import pandas as pd
    _ensure_aws_profile()
    s3 = boto3.client("s3")
    obj = s3.get_object(Bucket=_BUCKET, Key=key)
    return pd.read_csv(io.BytesIO(obj["Body"].read()), **kwargs)


def load_on_target_compounds(release_pin: str, target_symbol: str) -> tuple[list, list]:
    """Return (sample_ids, compound_records) for PRISM compounds whose GeneSymbolOfTargets
    includes the target gene. compound_records = [{sample_id, name, target_or_mechanism}].
    An empty list means no on-target compound in the PRISM panel (an honest 'no drug' state)."""
    cfg = _release_cfg(release_pin)
    key = f"{cfg['source_prefix']}/{cfg['compound_list']}"
    try:
        cdf = _read_csv_s3(key)
    except Exception as e:  # noqa: BLE001
        return [], [{"_live_read_error": f"compound_list: {e}"}]

    gene_col = "GeneSymbolOfTargets"
    name_col = "CompoundName"
    id_col = "SampleID"
    moa_col = "TargetOrMechanism"
    if gene_col not in cdf.columns or id_col not in cdf.columns:
        return [], [{"_live_read_error": "compound_list missing expected columns"}]

    tgt = target_symbol.upper()

    def _hits(cell) -> bool:
        # GeneSymbolOfTargets may be a delimited list (e.g. "BRAF, RAF1"); match the WHOLE token.
        if cell is None:
            return False
        toks = [t.strip().upper() for t in str(cell).replace(";", ",").split(",")]
        return tgt in toks

    sel = cdf[cdf[gene_col].apply(_hits)]
    records = []
    seen = set()
    for _, row in sel.iterrows():
        sid = str(row[id_col])
        if sid in seen:
            continue
        seen.add(sid)
        records.append({
            "sample_id": sid,
            "name": str(row.get(name_col, "")),
            "target_or_mechanism": str(row.get(moa_col, "")),
        })
    return [r["sample_id"] for r in records], records


def load_drug_response_by_model(release_pin: str, sample_ids: list,
                                 aggregate: str = "best") -> tuple[dict, list]:
    """Build {ModelID → Log2AUC} over the on-target compounds.

    aggregate:
      'best'   — the MINIMUM (most-sensitive) Log2AUC across on-target compounds per line
                 (the deep-responder biology; a target-selective drug need not be the panel's
                 broadest killer). This is the primary drug-response phenotype.
      'median' — the median across on-target compounds (robustness companion).
    Lines with no measured value across the selected compounds are omitted (not imputed)."""
    if not sample_ids:
        return {}, [{"_live_read_error": "no on-target compounds"}]
    cfg = _release_cfg(release_pin)
    key = f"{cfg['source_prefix']}/{cfg['log2auc_matrix']}"
    try:
        mat = _read_csv_s3(key, index_col=0)
    except Exception as e:  # noqa: BLE001
        return {}, [{"_live_read_error": f"log2auc_matrix: {e}"}]

    present = [c for c in sample_ids if c in mat.columns]
    if not present:
        return {}, [{"_live_read_error": "on-target compounds absent from Log2AUC matrix"}]

    sub = mat[present]
    out = {}
    for model_id, row in sub.iterrows():
        vals = [v for v in row.tolist() if v is not None and not _isnan(v)]
        if not vals:
            continue
        out[str(model_id)] = float(min(vals)) if aggregate == "best" else float(_median(vals))
    return out, []


def _isnan(v) -> bool:
    try:
        return v != v  # NaN != NaN
    except Exception:  # noqa: BLE001
        return False


def _median(vals: list) -> float:
    s = sorted(vals)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def read_mutation_drug_response(target: str, indication: Optional[str] = None,
                                release_pin: str = "26q1", aggregate: str = "best") -> dict:
    """Card entry point: genotype × PRISM drug-response biomarker for target.

    Selects on-target PRISM compounds (GeneSymbolOfTargets == target), builds the per-ModelID
    best-responder Log2AUC vector, joins the mutation matrices, and runs the shared stratification.
    Target-only (indication accepted for back-compat, not consumed — cell-panel drug response is
    indication-independent, like the sibling stratified cards). Returns a dict matching the
    mutation-drug-response card's summary_fields, or a graceful no-compound / data_unavailable dict.
    """
    _ensure_aws_profile()
    from methods.depmap_mutation_drug_response.cli import compute_drug_response_stratification

    sample_ids, compound_records = load_on_target_compounds(release_pin, target)
    load_err = [r for r in compound_records if isinstance(r, dict) and r.get("_live_read_error")]
    if load_err:
        return {"drug_response_stratification_class": "data_unavailable",
                "_live_read_error": load_err[0]["_live_read_error"],
                "n_on_target_compounds": 0, "on_target_compounds": []}
    if not sample_ids:
        return {"drug_response_stratification_class": "no_on_target_compound",
                "n_on_target_compounds": 0, "on_target_compounds": [],
                "_note": "no PRISM compound targets this gene"}

    drug_response_by_model, dr_errs = load_drug_response_by_model(release_pin, sample_ids, aggregate)
    if dr_errs or not drug_response_by_model:
        return {"drug_response_stratification_class": "no_on_target_compound",
                "n_on_target_compounds": len(sample_ids), "on_target_compounds": [],
                "_note": str(dr_errs[:1]) if dr_errs else "no measured on-target drug response"}

    # reuse the dependency method's mutation loader verbatim
    METHODS_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    import sys
    if METHODS_REPO not in sys.path:
        sys.path.insert(0, METHODS_REPO)
    from methods.depmap_mutation_dependency.cli import load_mutation_data
    hotspot, damaging, mut_errs = load_mutation_data(release_pin, target)
    if mut_errs:
        return {"drug_response_stratification_class": "data_unavailable",
                "_live_read_error": mut_errs[0].get("_live_read_error", "mutation_read_failed"),
                "n_on_target_compounds": len(sample_ids), "on_target_compounds": []}

    summary = compute_drug_response_stratification(
        drug_response_by_model, hotspot, damaging, compound_records=compound_records)
    summary["aggregate_metric"] = aggregate
    return summary
