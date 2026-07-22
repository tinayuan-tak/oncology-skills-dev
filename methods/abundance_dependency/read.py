"""read_abundance_dependency — target PROTEIN abundance vs its own Chronos dependency (Q7, protein arm).

Join {ModelID: protein_abundance} (Gygi MS) ⋈ {ModelID: Chronos} on shared cell lines, correlate,
classify. data_unavailable-safe. Pure-compute core (classify_abundance_dependency) split out for
unit-testing without S3.
"""
from __future__ import annotations

import os
from typing import Optional

DEFAULT_AWS_PROFILE = "cbg"

# correlation thresholds (protein abundance vs Chronos). A NEGATIVE correlation = higher abundance →
# more dependent (lower Chronos) = abundance predicts dependency. Mirrors the RNA card's sign convention.
STRONG_R = -0.4      # r <= STRONG_R → protein_predicts_dependency
WEAK_R = -0.2        # STRONG_R < r <= WEAK_R → weak link; r > WEAK_R → no link
MIN_PAIRED_MODELS = 20
SIGNIFICANCE_ALPHA = 0.05


def _ensure_aws_profile():
    if "AWS_PROFILE" not in os.environ:
        os.environ["AWS_PROFILE"] = DEFAULT_AWS_PROFILE


def classify_abundance_dependency(pearson_r: Optional[float], pearson_p: Optional[float],
                                  n_paired: int) -> str:
    """Pure classifier — protein-abundance→dependency class from the correlation. No I/O.

      protein_predicts_dependency  — significant, strong NEGATIVE r (high abundance → dependent)
      weak_protein_dependency_link — negative but moderate/insignificant
      no_protein_dependency_link   — non-negative or ~zero correlation
      insufficient_paired_models   — < MIN_PAIRED_MODELS paired lines
    """
    if n_paired < MIN_PAIRED_MODELS:
        return "insufficient_paired_models"
    if pearson_r is None:
        return "data_unavailable"
    if pearson_r <= STRONG_R and (pearson_p is None or pearson_p <= SIGNIFICANCE_ALPHA):
        return "protein_predicts_dependency"
    if pearson_r <= WEAK_R:
        return "weak_protein_dependency_link"
    return "no_protein_dependency_link"


def read_abundance_dependency(target: str, indication: Optional[str] = None,
                              release_pin: str = "26q1") -> dict:
    """Q7 protein arm — correlate target Gygi-MS protein abundance with its Chronos dependency across
    DepMap cell lines. Returns the class + stats + a comparison hook to the RNA arm. data-safe."""
    _ensure_aws_profile()
    sym = target.upper().strip()
    base = {"target": target, "indication": indication or "", "release_pin": release_pin,
            "abundance_layer": "protein_gygi_ms"}

    # 1) protein abundance per model (reuse depmap_protein_abundance loaders)
    try:
        from methods.depmap_protein_abundance import cli as _prot
        accession = _prot.resolve_accession(sym)
        if not accession:
            base.update({"abundance_dependency_class": "data_unavailable",
                         "_data_note": f"{sym} not resolvable to a UniProt accession in the Gygi sidecar"})
            return base
        abundance_by_model, panel_size = _prot.load_abundance_column(accession)
    except Exception as e:  # noqa: BLE001
        base.update({"abundance_dependency_class": "data_unavailable",
                     "_live_read_error": f"protein_load_failed:{type(e).__name__}"})
        return base
    if not abundance_by_model:
        base.update({"abundance_dependency_class": "data_unavailable",
                     "_data_note": f"{sym} undetected in the Gygi MS panel (n_panel={panel_size})"})
        return base

    # 2) Chronos per model (reuse the card4 loader)
    try:
        from methods.depmap_expression_dependency import cli as _dep
        chronos_by_model, _tpm, model_meta, errs = _dep.load_depmap_files_for_card4(
            release_pin=release_pin, target_symbol=sym)
    except Exception as e:  # noqa: BLE001
        chronos_by_model, model_meta, errs = {}, {}, [{"_live_read_error": type(e).__name__}]
    if errs or not chronos_by_model:
        base.update({"abundance_dependency_class": "data_unavailable",
                     "_data_note": (errs[0].get("_live_read_error") if errs else "no Chronos for target")})
        return base

    # 3) join + correlate
    shared = sorted(set(abundance_by_model) & set(chronos_by_model))
    n_paired = len(shared)
    base["n_paired_models"] = n_paired
    base["n_protein_detected_models"] = len(abundance_by_model)
    base["protein_panel_size"] = panel_size
    if n_paired < MIN_PAIRED_MODELS:
        base["abundance_dependency_class"] = classify_abundance_dependency(None, None, n_paired)
        base["_data_note"] = f"only {n_paired} models have BOTH protein + Chronos (need {MIN_PAIRED_MODELS})"
        return base

    import numpy as np
    from scipy import stats
    prot = np.array([abundance_by_model[m] for m in shared], dtype=float)
    chron = np.array([chronos_by_model[m] for m in shared], dtype=float)
    if prot.std() < 1e-9 or chron.std() < 1e-9:
        base.update({"abundance_dependency_class": "data_unavailable",
                     "_data_note": "no variance in protein abundance or Chronos — correlation undefined"})
        return base
    pearson_r, pearson_p = stats.pearsonr(prot, chron)
    spearman_r, spearman_p = stats.spearmanr(prot, chron)

    cls = classify_abundance_dependency(float(pearson_r), float(pearson_p), n_paired)
    base.update({
        "abundance_dependency_class": cls,
        "protein_dependency_pearson_r": round(float(pearson_r), 4),
        "protein_dependency_pearson_p": float(f"{pearson_p:.3g}"),
        "protein_dependency_spearman_r": round(float(spearman_r), 4),
        "n_dependent_models": int((chron <= -0.5).sum()),
        # comparison hook: the RNA arm lives on expression-dependency-correlation; the synthesis layer
        # (Q12 / biomarker facet) compares the two to pick preferred_assay (RNA vs protein).
        "rna_arm_card": "expression-dependency-correlation",
    })
    return base
