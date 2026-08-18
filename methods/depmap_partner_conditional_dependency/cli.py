#!/usr/bin/env python3
"""depmap_partner_conditional_dependency CLI — partner-conditional stratified dependency.

The PARTNER-feature generalization of depmap_cn_dependency (A1a). A1a asks "is the target's
own CN-amplification status stratify its Chronos?"; this asks "does a PARTNER gene's DEFICIENCY
status stratify the target's Chronos?" — the partner_conditional_sl family (WRN×MSI, PARP1×HRD,
SMARCA2×SMARCA4) the pooled dependency scalar structurally misses.

Reuses the PROVEN _mannwhitney_stratification from depmap_mutation_dependency VERBATIM (the kernel
is substrate-agnostic: chronos + {ModelID -> bool}). The only new machinery is the PARTNER-DEFICIENCY
boolean loader, which dispatches on the curated partner_map.yaml deficiency_type:
  - msi_signature : canonical MSI-H boolean from OmicsInferredMolecularSubtypes.csv
  - lof_mutation  : partner damaging-LoF from the DepMap damaging matrix (reuse mutation loader)

Emits partner_stratification_class ∈ {partner_conditional_strongly_dependent,
partner_conditional_moderately_dependent, partner_neutral_strongly_dependent,
not_partner_stratified, insufficient_partner_deficient_rate, no_partner_mapped, data_unavailable}.

Verdict path (target-contracts): the partner_conditional_*_dependent classes fire
partner-conditional-*-dependent rules → dependency.resolver reuses the biomarker_stratified_dependency
rescue (one-directional). RUNG FIRES AT MODERATE (delta <= -0.2): WRN×MSI, a celebrated real SL, is a
-0.41 effect — context-conditional SL effect sizes are structurally smaller than oncogene addiction,
so a STRONG-only rung would rescue nothing real (empirically established 2026-08-09).
"""
from __future__ import annotations

from pathlib import Path

import yaml

METHOD_VERSION = "0.1.0"

# Classification thresholds — mirror depmap_cn_dependency / depmap_mutation_dependency exactly,
# EXCEPT the rung that fires the rescue keys on MODERATE (see module docstring / card).
STRONG_EFFECT_DELTA = -0.5      # partner-deficient median Chronos - neutral <= -0.5 → strongly dependent
MODERATE_EFFECT_DELTA = -0.2    # the RESCUE-FIRING threshold (WRN×MSI = -0.41 clears strong; SL floor is here)
STRATIFICATION_ALPHA = 0.05
MIN_PARTNER_DEFICIENT_CELLS = 5     # mirror min_mutant
MIN_NEUTRAL_CELLS = 30              # mirror min_wildtype

_MAP_PATH = Path(__file__).resolve().parent / "partner_map.yaml"


def load_partner_map(path: Path = _MAP_PATH) -> dict:
    """Load the curated target→[{partner, deficiency_type, note}] map."""
    with open(path) as fh:
        doc = yaml.safe_load(fh)
    return doc.get("partners", {})


def _msi_high_by_model(release_pin: str) -> dict:
    """Canonical MSI-high boolean per ModelID from OmicsInferredMolecularSubtypes.csv.

    Reuses the framework's authoritative MSI call (the SAME source
    subgroup_assigner_directly_tagged consumes) — NOT an MSIScore threshold. Returns
    {ModelID -> bool}; models with a null MSI value are OMITTED (not forced to MSS), so a
    missing call becomes an honest exclusion rather than a fabricated negative.
    """
    # Reuse the shared cache→local→S3 fetcher (existing infra; not modified here).
    from methods.depmap_common.loaders import _fetch_csv, DEPMAP_S3_PREFIX_CRISPR

    key = f"{DEPMAP_S3_PREFIX_CRISPR}/OmicsInferredMolecularSubtypes.csv"
    df = _fetch_csv(key, "OmicsInferredMolecularSubtypes.csv", release_pin)
    if "MSI" not in df.columns or "ModelID" not in df.columns:
        return {}
    out = {}
    for model_id, msi in zip(df["ModelID"], df["MSI"]):
        if msi is None or (isinstance(msi, float) and msi != msi):  # NaN → omit
            continue
        if isinstance(msi, str):
            out[model_id] = msi.strip().upper() in ("MSI-H", "MSI_H", "MSI", "MSIH", "HIGH", "TRUE", "YES")
        else:
            out[model_id] = bool(msi)   # 1/0 or True/False encoding
    return out


def _partner_lof_by_model(release_pin: str, partner_gene: str) -> dict:
    """Partner damaging-LoF boolean per ModelID (reuse the mutation-dependency loader).

    Returns {ModelID -> bool} where True = partner carries a damaging LoF mutation. Only the
    DAMAGING (LoF) arm is used for a partner deficiency (not hotspot/GoF), since partner-conditional
    SL is a LOSS-of-partner-function hypothesis.
    """
    from methods.depmap_mutation_dependency.cli import load_mutation_data

    _hotspot, damaging_by_model, _errs = load_mutation_data(release_pin, partner_gene)
    return {m: bool(v) for m, v in (damaging_by_model or {}).items()}


def build_partner_deficiency_vector(release_pin: str, partner: str, deficiency_type: str) -> dict:
    """Dispatch on deficiency_type → {ModelID -> bool} partner-deficient vector."""
    if deficiency_type == "msi_signature":
        return _msi_high_by_model(release_pin)
    if deficiency_type == "lof_mutation":
        return _partner_lof_by_model(release_pin, partner)
    raise ValueError(f"unknown deficiency_type: {deficiency_type!r} (partner={partner})")


def compute_partner_stratification(chronos_by_model: dict, partner_deficient_by_model: dict,
                                   strong_effect_delta: float = STRONG_EFFECT_DELTA,
                                   moderate_effect_delta: float = MODERATE_EFFECT_DELTA,
                                   stratification_alpha: float = STRATIFICATION_ALPHA,
                                   min_deficient: int = MIN_PARTNER_DEFICIENT_CELLS,
                                   min_neutral: int = MIN_NEUTRAL_CELLS) -> dict:
    """Compute the partner-conditional-dependency summary_fields.

    Runs the SAME Mann-Whitney contrast the mutation/CN paths use (one-sided forward:
    partner-deficient lines MORE dependent; second-pass reverse for the neutral-more-dependent
    class). Returns the card's summary_fields shape + partner_stratification_class.
    """
    from methods.depmap_common.boolean_stratification import mannwhitney_stratification

    res = mannwhitney_stratification(
        chronos_by_model, partner_deficient_by_model,
        min_positive=min_deficient, min_comparator=min_neutral,
    )

    q = res.get("p_value")               # single test → q == p (no multi-tier BH)
    q_reverse = res.get("p_value_reverse")
    delta = res.get("delta_mut_vs_wt")

    def _classify() -> str:
        if res.get("_insufficient_data"):
            return "insufficient_partner_deficient_rate"
        if delta is None:
            return "not_partner_stratified"
        # FORWARD: partner-deficient more dependent (significant + negative delta).
        if q is not None and q < stratification_alpha:
            if delta <= strong_effect_delta:
                return "partner_conditional_strongly_dependent"
            if delta <= moderate_effect_delta:
                return "partner_conditional_moderately_dependent"
        # REVERSE second-pass: neutral lines more dependent (verdict-inert, mirrors A1a).
        if (q_reverse is not None and q_reverse < stratification_alpha
                and delta >= -strong_effect_delta):
            return "partner_neutral_strongly_dependent"
        return "not_partner_stratified"

    cls = _classify()
    n_evaluated = len(set(chronos_by_model) & set(partner_deficient_by_model))

    return {
        "n_cell_lines_evaluated": int(n_evaluated),
        "n_partner_deficient": res["n_mutant"],
        "n_neutral": res["n_wildtype"],
        "median_chronos_partner_deficient": res["median_mutant"],
        "median_chronos_neutral": res["median_wildtype"],
        "delta_chronos_deficient_vs_neutral": delta,
        "partner_stratification_mannwhitney_p": res.get("p_value"),
        "partner_stratification_mannwhitney_q": q,
        "partner_stratification_mannwhitney_q_reverse": q_reverse,
        "partner_stratification_effect_size": res.get("effect_size"),
        "partner_stratification_class": cls,
        "_uncomputable": bool(res.get("_uncomputable")),
    }


try:
    import click

    @click.command()
    @click.option("--target", required=True)
    @click.option("--indication", default=None, help="Accepted for dispatcher signature; not consumed (target-only).")
    @click.option("--release-pin", default="26q1")
    @click.option("--out", type=click.Path(file_okay=False, path_type=Path), default=None)
    def main(target, indication, release_pin, out):
        """Compute partner-conditional stratified dependency for TARGET."""
        from .read import read_partner_conditional_dependency
        import json
        summary = read_partner_conditional_dependency(target, indication, release_pin=release_pin)
        click.echo(json.dumps(summary, indent=2, default=str))
        if out:
            out.mkdir(parents=True, exist_ok=True)
            (out / "partner_conditional_dependency_summary.json").write_text(
                json.dumps(summary, indent=2, default=str)
            )

    if __name__ == "__main__":
        main()
except ImportError:
    pass
