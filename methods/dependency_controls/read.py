"""control_position_dependency — the dependency (Gate-C) control-benchmark axis.

Given a target, fetch its pan-panel MEDIAN Chronos AND the median Chronos of each
curated control gene (pan-essential positives + non-essential negatives, from
target-contracts/vocabularies/dependency_controls.yaml), then classify where the
target sits relative to the two control bands — on the SAME Chronos scale, same
DepMap release.

THE INVERSION (vs tumor_presence_controls): positives are pan-essential (an
essentiality CEILING → reading at this depth is a BROAD-TOX liability), negatives are
non-essential (a dependency FLOOR). The therapeutic sweet spot is BETWEEN the bands.
See vocabularies/dependency_controls.yaml header for the full rationale.

NO percentile product: Chronos is already control-normalized, so control genes are
read DIRECTLY from the CRISPR matrix (cheap lru-cached column reads).

data_unavailable-safe: vocab/Chronos read failure → dep_control_position_class of
data_unavailable, never a raise (so this can land before the vocab is merged).
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

METHOD_VERSION = "0.1.0"

DEFAULT_TARGET_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)
CONTROLS_VOCAB_RELPATH = "vocabularies/dependency_controls.yaml"


@lru_cache(maxsize=4)
def _load_controls(contracts_dir: str) -> dict:
    import yaml

    path = Path(contracts_dir) / CONTROLS_VOCAB_RELPATH
    return yaml.safe_load(path.read_text())


def _median_chronos(symbol: str, release_pin: str) -> Optional[float]:
    """Pan-panel median Chronos for a gene, via the cheap column-projection read.
    Returns None if the gene is absent from the panel or the read fails."""
    try:
        from methods.depmap_common.parquet import get_chronos_column

        df = get_chronos_column(symbol, release_pin)
    except Exception:  # noqa: BLE001 — never break the render path on a read failure
        return None
    if df is None:
        return None
    cols = [c for c in df.columns if c != "ModelID"]
    if not cols:
        return None
    try:
        import pandas as pd  # noqa: F401

        series = df[cols[0]].dropna()
        if len(series) == 0:
            return None
        return float(series.median())
    except Exception:  # noqa: BLE001
        return None


def _classify_dep_control_position(target_med: Optional[float], pos_meds: dict, neg_meds: dict) -> str:
    """Where does the target's median Chronos sit relative to the control bands?

    Bands are DATA-DRIVEN from the control genes themselves (not hardcoded thresholds):
      pan_essential_ceiling = max (LEAST negative) positive median — the shallow edge of
          the pan-essential band (≈ the common-essential -1 calibration line).
      non_essential_floor   = min (MOST negative) negative median — the deepest a truly
          non-essential gene reaches (≈ 0, small noise).

    Classes (INVERTED vs presence):
      as_essential_as_pan_essential      — target <= pan_essential_ceiling: reads as
          essential as the pan-essential controls → BROAD-TOXICITY liability, not a win.
      between_controls                    — non_essential_floor > target > ceiling: a real,
          SELECTIVE dependency that is not pan-essential (the therapeutic sweet spot).
      non_dependent_near_negatives        — target >= non_essential_floor: no dependency
          (as non-essential as the negative controls).
      data_unavailable                    — target or all controls unrankable.
    """
    if target_med is None:
        return "data_unavailable"
    pos = [m for m in pos_meds.values() if m is not None]
    neg = [m for m in neg_meds.values() if m is not None]
    if not pos and not neg:
        return "data_unavailable"
    # Pan-essential CEILING = the least-negative (shallowest) pan-essential median.
    ceiling = max(pos) if pos else None
    # Non-essential FLOOR = the most-negative non-essential median (deepest a non-essential reaches).
    floor = min(neg) if neg else None

    if ceiling is not None and target_med <= ceiling:
        return "as_essential_as_pan_essential"
    if floor is not None and target_med >= floor:
        return "non_dependent_near_negatives"
    # Below the non-essential floor but above the pan-essential ceiling → selective window.
    return "between_controls"


def control_position_dependency(
    target: str, release_pin: str = "26q1", contracts_dir: str = str(DEFAULT_TARGET_CONTRACTS)
) -> dict:
    """Control-benchmark position for the pan-cancer-crispr-dependency-distribution card.

    Reads the target's + each control gene's pan-panel median Chronos DIRECTLY (no
    percentile product) and classifies the target against the pan-essential ceiling +
    non-essential floor. Returns dep_control_* fields (display-only / verdict-inert).
    """
    try:
        controls = _load_controls(contracts_dir)
    except Exception as e:  # noqa: BLE001 — vocab may not be merged yet; degrade gracefully
        return {
            "dep_control_position_class": "data_unavailable",
            "_dep_control_note": f"controls vocab unavailable: {type(e).__name__}",
            "dep_control_method_version": METHOD_VERSION,
        }

    target_med = _median_chronos(target, release_pin)
    pos_meds = {sym: _median_chronos(sym, release_pin) for sym in (controls.get("positive_controls") or {})}
    neg_meds = {sym: _median_chronos(sym, release_pin) for sym in (controls.get("negative_controls") or {})}

    klass = _classify_dep_control_position(target_med, pos_meds, neg_meds)

    # human-readable position: how the target ranks vs each band (essentiality direction:
    # a target is "more essential than" a control when its Chronos is MORE negative).
    pos_present = [m for m in pos_meds.values() if m is not None]
    neg_present = [m for m in neg_meds.values() if m is not None]
    n_pos = len(pos_present)
    n_neg = len(neg_present)
    n_pos_more_essential = (
        sum(1 for m in pos_present if target_med is not None and target_med <= m) if target_med is not None else 0
    )
    n_neg_more_essential = (
        sum(1 for m in neg_present if target_med is not None and target_med < m) if target_med is not None else 0
    )
    parts = []
    if n_pos:
        parts.append(f"as/more essential than {n_pos_more_essential}/{n_pos} pan-essential control(s)")
    if n_neg:
        parts.append(f"more dependent than {n_neg_more_essential}/{n_neg} non-essential control(s)")
    position = "; ".join(parts) if parts else "no control medians resolved"

    ceiling = max(pos_present) if pos_present else None
    floor = min(neg_present) if neg_present else None
    ctx = (
        f"DepMap {release_pin} pan-panel median Chronos vs curated dependency controls "
        f"(dependency_controls v{controls.get('version')}; "
        f"pan_essential_ceiling={_round(ceiling)}; non_essential_floor={_round(floor)}). "
        f"INVERTED: at/below the ceiling = pan-essential tox liability; between = selective "
        f"dependency window; at/above the floor = non-dependent."
    )

    return {
        "dep_control_position_class": klass,
        "dep_control_position": position,
        "dep_control_target_chronos": _round(target_med),
        "dep_control_positives": {k: _round(v) for k, v in pos_meds.items() if v is not None},
        "dep_control_negatives": {k: _round(v) for k, v in neg_meds.items() if v is not None},
        "dep_control_pan_essential_ceiling": _round(ceiling),
        "dep_control_non_essential_floor": _round(floor),
        "dep_control_position_context": ctx,
        "dep_control_method_version": METHOD_VERSION,
    }


def _round(v, nd=3):
    return round(v, nd) if isinstance(v, (int, float)) else v
