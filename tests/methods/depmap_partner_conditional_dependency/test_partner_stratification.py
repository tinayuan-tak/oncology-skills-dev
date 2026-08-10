"""depmap_partner_conditional_dependency.compute_partner_stratification — hermetic (no S3).

Synthetic chronos + partner-deficiency boolean. Pins the decisive classifications and the two
load-bearing guarantees:
  - the RESCUE-FIRING classes are partner_conditional_{strongly,moderately}_dependent;
  - the MODERATE anchor (WRN×MSI ~ -0.41 live) classifies as moderately (or strongly) dependent —
    NOT lost — which is why the resolver rung must fire at MODERATE, not STRONG;
  - an HONEST-NEGATIVE flat partner (PARP1×HRD ~ -0.03 live) reads not_partner_stratified, never forced;
  - too few partner-deficient lines → insufficient_partner_deficient_rate (no underpowered call);
  - a reverse pattern (neutral more dependent) NEVER mislabels as partner_conditional_*_dependent.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_partner_conditional_dependency.cli import (  # noqa: E402
    compute_partner_stratification, load_partner_map,
    MODERATE_EFFECT_DELTA, STRONG_EFFECT_DELTA,
)


def _panel(deficient_chronos, neutral_chronos):
    """Build (chronos_by_model, partner_deficient_by_model) with N deficient + M neutral lines."""
    chronos, deficient = {}, {}
    i = 0
    for c in deficient_chronos:
        m = f"ACH-{i:05d}"; chronos[m] = c; deficient[m] = True; i += 1
    for c in neutral_chronos:
        m = f"ACH-{i:05d}"; chronos[m] = c; deficient[m] = False; i += 1
    return chronos, deficient


def test_moderate_anchor_wrn_msi_like():
    """The WRN×MSI ANCHOR shape: partner-deficient median ~-0.52, neutral ~-0.11 → delta ~-0.41.
    Must classify as partner_conditional_moderately_dependent (clears MODERATE, below STRONG) — the
    exact live signal (delta -0.41). This is WHY the resolver rung fires at MODERATE."""
    import random
    rng = random.Random(0)
    deficient = [-0.52 + rng.uniform(-0.08, 0.08) for _ in range(91)]   # ~ live n_msi_high
    neutral = [-0.11 + rng.uniform(-0.08, 0.08) for _ in range(1447)]
    chronos, dv = _panel(deficient, neutral)
    s = compute_partner_stratification(chronos, dv)
    assert s["partner_stratification_class"] in (
        "partner_conditional_moderately_dependent", "partner_conditional_strongly_dependent")
    assert s["delta_chronos_deficient_vs_neutral"] <= MODERATE_EFFECT_DELTA
    assert s["n_partner_deficient"] == 91 and s["n_neutral"] == 1447


def test_strongly_dependent():
    """A deep partner-conditional dependency (delta <= -0.5) → strongly_dependent."""
    import random
    rng = random.Random(1)
    deficient = [-1.0 + rng.uniform(-0.1, 0.1) for _ in range(40)]
    neutral = [-0.05 + rng.uniform(-0.1, 0.1) for _ in range(300)]
    chronos, dv = _panel(deficient, neutral)
    s = compute_partner_stratification(chronos, dv)
    assert s["partner_stratification_class"] == "partner_conditional_strongly_dependent"
    assert s["delta_chronos_deficient_vs_neutral"] <= STRONG_EFFECT_DELTA


def test_honest_negative_parp1_hrd_like():
    """The PARP1×HRD HONEST-NEGATIVE shape: deficient ~-0.25, neutral ~-0.22 → delta ~-0.03.
    Must read not_partner_stratified — the framework reports the weak signal faithfully, NOT
    forced into a rescue (mono-KO CRISPR can't see PARPi trapping-based SL)."""
    import random
    rng = random.Random(2)
    deficient = [-0.25 + rng.uniform(-0.15, 0.15) for _ in range(71)]
    neutral = [-0.22 + rng.uniform(-0.15, 0.15) for _ in range(1467)]
    chronos, dv = _panel(deficient, neutral)
    s = compute_partner_stratification(chronos, dv)
    assert s["partner_stratification_class"] not in (
        "partner_conditional_strongly_dependent", "partner_conditional_moderately_dependent")


def test_insufficient_partner_deficient_rate():
    """Fewer than min_deficient (5) partner-deficient lines → insufficient, never an underpowered call."""
    import random
    rng = random.Random(3)
    deficient = [-1.0, -1.1, -0.9]  # only 3
    neutral = [0.0 + rng.uniform(-0.08, 0.08) for _ in range(300)]
    chronos, dv = _panel(deficient, neutral)
    s = compute_partner_stratification(chronos, dv)
    assert s["partner_stratification_class"] == "insufficient_partner_deficient_rate"


def test_reverse_never_mislabeled_partner_dependent():
    """Neutral lines MORE dependent than partner-deficient. The KEY GUARANTEE — a partner is NEVER
    credited with a dependency it lacks: forward partner_conditional_*_dependent must NOT fire."""
    import random
    rng = random.Random(4)
    deficient = [-0.02 + rng.uniform(-0.08, 0.08) for _ in range(40)]
    neutral = [-0.6 + rng.uniform(-0.1, 0.1) for _ in range(300)]
    chronos, dv = _panel(deficient, neutral)
    s = compute_partner_stratification(chronos, dv)
    assert s["partner_stratification_class"] not in (
        "partner_conditional_strongly_dependent", "partner_conditional_moderately_dependent")
    assert s["partner_stratification_class"] == "partner_neutral_strongly_dependent"
    assert s["delta_chronos_deficient_vs_neutral"] > 0


def test_partner_map_loads_anchor():
    """The curated map must load and carry the WRN×MSI anchor with the MSI-signature deficiency type."""
    pm = load_partner_map()
    assert "WRN" in pm
    wrn = pm["WRN"]
    assert any(e["partner"] == "MSI" and e["deficiency_type"] == "msi_signature" for e in wrn)
    # PARP1 (honest-negative) + SMARCA2 (paralog) also present
    assert "PARP1" in pm and "SMARCA2" in pm
    assert any(e["deficiency_type"] == "lof_mutation" for e in pm["PARP1"])
