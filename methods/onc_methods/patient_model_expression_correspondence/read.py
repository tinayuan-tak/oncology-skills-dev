"""Q4 recommended_models assembler — target-focused patient↔model expression correspondence.

For a (target, indication): rank DepMap models by how well their TARGET expression represents the
patient tumor TARGET distribution, and classify each into a screen role (positive / negative-control
/ resistance) using the model's Chronos dependency. data_unavailable-safe throughout.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

# indication → DepMap OncotreeLineage. SINGLE SOURCE: import the canonical map from
# depmap_chronos.read rather than forking it here. The prior local fork mapped GC/STAD →
# "Stomach", a lineage that does NOT exist in DepMap 26Q1 Model.csv (the real value is
# "Esophagus/Stomach"), so gastric within-lineage scoping silently matched zero models.
from onc_methods.depmap_chronos.read import INDICATION_TO_DEPMAP_LINEAGE  # noqa: E402

# Chronos dependency cutoffs (DepMap convention): <= -0.5 dependent; >= -0.2 not-dependent.
DEPENDENT_CHRONOS = -0.5
NOT_DEPENDENT_CHRONOS = -0.2
# a model "expresses" the target if its log2(TPM+1) clears the detectable floor (matches stats.py).
DETECTABLE_LOG2TPM = 1.0


def _patient_distribution(target: str, indication: str):
    """Patient tumor TARGET log2(TPM+1) values + the representative band (IQR). Empty → (None...)."""
    from onc_methods.tcga_gtex_expression_distribution import read as _pt

    vals = _pt.read_tumor_samples(target, indication)
    if not vals:
        return [], None, None, None
    import numpy as np

    a = np.asarray(vals, dtype=float)
    return vals, float(np.percentile(a, 25)), float(np.median(a)), float(np.percentile(a, 75))


def _classify_model_role(tpm, chronos) -> str:
    """Screen role for a model, from its target expression + dependency:
    positive_model    — target EXPRESSED and model DEPENDENT (Chronos <= -0.5): the on-target screen model
    resistance_model  — target EXPRESSED but NOT dependent (Chronos >= -0.2): expressed-yet-resistant
    negative_control  — target NOT expressed (below detectable): expected non-responder
    indeterminate     — expressed + intermediate dependency, or missing chronos
    """
    expressed = tpm is not None and tpm >= DETECTABLE_LOG2TPM
    if not expressed:
        return "negative_control"
    if chronos is None:
        return "indeterminate"
    if chronos <= DEPENDENT_CHRONOS:
        return "positive_model"
    if chronos >= NOT_DEPENDENT_CHRONOS:
        return "resistance_model"
    return "indeterminate"


def _representativeness(tpm, p25, p75) -> float:
    """0..1 — how well a model's target TPM sits within the patient tumor IQR. 1.0 inside the IQR;
    decays with distance outside it (scaled by the IQR width, floored so a zero-width IQR is safe)."""
    if tpm is None or p25 is None or p75 is None:
        return 0.0
    if p25 <= tpm <= p75:
        return 1.0
    width = max(p75 - p25, 0.5)
    dist = (p25 - tpm) if tpm < p25 else (tpm - p75)
    import math

    return round(math.exp(-dist / width), 4)


def read_recommended_models(
    target: str, indication: str, release_pin: str = "26q3", top_n: int = 15, plot_data_out: "Optional[Path]" = None
) -> dict:
    """Q4 assembler. Returns the recommended_models table + rollup for a (target, indication).

    Ranking: lineage-matched models first (models of the indication's DepMap lineage are the
    representative panel), then by representativeness (target TPM within the patient IQR), then by
    dependency strength. Each row carries its screen role. data_unavailable-safe."""
    from onc_methods.depmap_expression_dependency import cli as _c4

    vals, p25, med, p75 = _patient_distribution(target, indication)
    target_lineage = INDICATION_TO_DEPMAP_LINEAGE.get(indication.upper().strip())
    base = {
        "target": target,
        "indication": indication,
        "patient_median_log2tpm": med,
        "patient_iqr": ([p25, p75] if p25 is not None else None),
        "n_patient_samples": len(vals),
        "depmap_lineage": target_lineage,
        "release_pin": release_pin,
    }

    if not vals:
        base.update(
            {
                "correspondence_class": "data_unavailable",
                "recommended_models": [],
                "n_models_considered": 0,
                "n_positive_models": 0,
                "_data_note": "no patient tumor TPM for this (target, indication)",
            }
        )
        return base

    # Absence discipline (#832): load_depmap_files_for_card4 converts genuine absence (missing
    # object / target column absent) into its errs channel + empty returns (handled by the
    # `if errs or not tpm_by_model` guard below), so a broad except here would only ever mask a
    # transient / creds / broken-env fault as correspondence_class=data_unavailable. Let those
    # PROPAGATE (an honest _live_read_error at the compose seam) instead.
    chronos_by_model, tpm_by_model, meta, errs = _c4.load_depmap_files_for_card4(
        release_pin=release_pin, target_symbol=target
    )
    if errs or not tpm_by_model:
        base.update(
            {
                "correspondence_class": "data_unavailable",
                "recommended_models": [],
                "n_models_considered": 0,
                "n_positive_models": 0,
                "_data_note": (errs[0].get("_live_read_error") if errs else "no model TPM"),
            }
        )
        return base

    rows = []
    for model_id, tpm in tpm_by_model.items():
        mm = meta.get(model_id, {})
        lineage = str(mm.get("OncotreeLineage") or mm.get("lineage") or "unknown")
        chronos = chronos_by_model.get(model_id)
        lineage_match = bool(target_lineage) and (lineage == target_lineage)
        rows.append(
            {
                "model_id": model_id,
                "cell_line": mm.get("StrippedCellLineName") or mm.get("CellLineName") or model_id,
                "lineage": lineage,
                "lineage_match": lineage_match,
                "target_log2tpm": round(float(tpm), 4),
                "chronos": (round(float(chronos), 4) if chronos is not None else None),
                "screen_role": _classify_model_role(tpm, chronos),
                "representativeness": _representativeness(tpm, p25, p75),
            }
        )

    # rank: lineage-matched first, then representativeness, then dependency strength (more negative first)
    rows.sort(
        key=lambda r: (
            not r["lineage_match"],
            -r["representativeness"],
            r["chronos"] if r["chronos"] is not None else 0.0,
        )
    )
    # Figure Stage 6: persist the FULL per-model rows (the scatter shows ALL models, not just the
    # top-N table) so the figure renders offline. Best-effort, verdict-inert.
    if plot_data_out is not None:
        try:
            import pandas as _pd

            Path(plot_data_out).mkdir(parents=True, exist_ok=True)
            _pd.DataFrame(
                [
                    {
                        "target_log2tpm": r["target_log2tpm"],
                        "chronos": r["chronos"],
                        "screen_role": r["screen_role"],
                        "lineage_match": r["lineage_match"],
                    }
                    for r in rows
                ]
            ).to_parquet(Path(plot_data_out) / "plot_data_recommended_models.parquet", index=False)
        except Exception:  # noqa: BLE001 — persistence best-effort; never break the verdict read
            pass

    n_pos = sum(1 for r in rows if r["screen_role"] == "positive_model")
    n_pos_lineage = sum(1 for r in rows if r["screen_role"] == "positive_model" and r["lineage_match"])
    base.update(
        {
            "recommended_models": rows[:top_n],
            "n_models_considered": len(rows),
            "n_positive_models": n_pos,
            "n_positive_models_in_lineage": n_pos_lineage,
            "n_lineage_models": sum(1 for r in rows if r["lineage_match"]),
            "correspondence_class": _classify_correspondence(n_pos, n_pos_lineage, bool(target_lineage)),
        }
    )
    return base


def _classify_correspondence(n_positive, n_positive_lineage, has_lineage) -> str:
    """Categorical for the card/rules:
    well_modeled_in_lineage — >=1 positive (expressed+dependent) model IN the indication's lineage
    well_modeled_off_lineage — positive models exist but none in the indication's lineage
    poorly_modeled          — no positive models (no expressed+dependent line anywhere)
    data_unavailable        — handled by the caller."""
    if has_lineage and n_positive_lineage >= 1:
        return "well_modeled_in_lineage"
    if n_positive >= 1:
        return "well_modeled_off_lineage"
    return "poorly_modeled"
