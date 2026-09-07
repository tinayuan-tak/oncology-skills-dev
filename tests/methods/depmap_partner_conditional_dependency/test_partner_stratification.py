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


def test_partner_map_carries_keap1_nfe2l2_lof_entry():
    """Round-1 T2a: KEAP1-loss → NRF2 addiction. KEAP1 is a conditioning variable via the lof_mutation
    arm; NFE2L2 is the curated target (live DepMap 26q1 probe: delta -0.377, q 9.8e-5, rb 0.42, n=27
    KEAP1-LoF → partner_conditional_moderately_dependent)."""
    pm = load_partner_map()
    assert "NFE2L2" in pm, "KEAP1/NFE2L2 partner-conditional entry missing"
    assert any(e["partner"] == "KEAP1" and e["deficiency_type"] == "lof_mutation" for e in pm["NFE2L2"])


def test_partner_map_carries_wnt_hippo_sweep_entries():
    """Conditional-dependency discovery sweep (2026-09-07): APC-loss→CTNNB1 (WNT), NF2-loss→TEAD1/WWTR1
    (Hippo). Live DepMap 26q1 probes: CTNNB1×APC delta -0.881/q 3.2e-37/rb 0.76 (strong); TEAD1×NF2
    delta -0.247/q 2.3e-4/rb 0.34 and WWTR1×NF2 delta -0.251/q 4.4e-4/rb 0.32 (moderate). YAP1×NF2 was
    NOT curated (paralog-buffered, not_partner_stratified)."""
    pm = load_partner_map()
    for tgt, partner in (("CTNNB1", "APC"), ("TEAD1", "NF2"), ("WWTR1", "NF2")):
        assert tgt in pm, f"{tgt}/{partner} partner-conditional entry missing"
        assert any(e["partner"] == partner and e["deficiency_type"] == "lof_mutation" for e in pm[tgt])
    assert "YAP1" not in pm, "YAP1×NF2 is a paralog-buffered honest miss — must NOT be curated"


def test_partner_map_carries_vhl_epas1_lof_entry():
    """Discordance-loop CASE-014: VHL-loss → HIF-2α (EPAS1) addiction (belzutifan-validated ccRCC). VHL is
    a conditioning variable via the lof_mutation arm; EPAS1 is the curated target (live DepMap 26q1 probe:
    delta -0.066, q 2.1e-3, rank-biserial 0.32, n=28 VHL-LoF / 1510 neutral →
    partner_conditional_moderately_dependent). Rescues the pooled non_dependent FN."""
    pm = load_partner_map()
    assert "EPAS1" in pm, "VHL/EPAS1 partner-conditional entry missing"
    assert any(e["partner"] == "VHL" and e["deficiency_type"] == "lof_mutation" for e in pm["EPAS1"])


def test_effect_size_path_recovers_modest_delta_sl():
    """The PRMT5×MTAP / SMARCA2×SMARCA4 shape: a REAL synthetic-lethal contrast whose median-delta is
    modest (misses the -0.2 floor) but whose rank-biserial effect size is moderate (>=0.30) and the
    forward test is significant. The effect-size path must RECOVER it as moderately_dependent — the
    2026-08-24 fix (the -0.2 floor was mis-borrowed from the oncogene mutant-vs-WT regime)."""
    from methods.depmap_partner_conditional_dependency.cli import MODERATE_EFFECT_RB
    # Deterministic, partially-overlapping blocks: deficient shifted MORE dependent (lower Chronos),
    # median delta ~-0.16 (ABOVE the -0.2 floor) but clear stochastic dominance → moderate effect size.
    n_def, n_neu = 184, 485
    deficient = [-0.50 + 0.32 * (k / (n_def - 1)) for k in range(n_def)]   # -0.50 .. -0.18
    neutral = [-0.34 + 0.32 * (k / (n_neu - 1)) for k in range(n_neu)]     # -0.34 .. -0.02
    chronos, dv = _panel(deficient, neutral)
    s = compute_partner_stratification(chronos, dv)
    # Preconditions: we are genuinely testing the effect-size path (delta misses the median floor).
    assert s["delta_chronos_deficient_vs_neutral"] > MODERATE_EFFECT_DELTA, s
    assert s["partner_stratification_effect_size"] >= MODERATE_EFFECT_RB, s
    assert s["partner_stratification_mannwhitney_q"] < 0.05, s
    # ... and it now grades to MODERATE via effect size.
    assert s["partner_stratification_class"] == "partner_conditional_moderately_dependent", s


def test_effect_size_path_does_not_over_admit_low_effect():
    """Guard: a modest-delta contrast with LOW effect size (high overlap) stays not_partner_stratified —
    the effect-size path admits only genuinely-separated SL, not near-floor noise (the PARP1×BRCA1
    boundary: rank-biserial ~0.28 < 0.30 stays out)."""
    from methods.depmap_partner_conditional_dependency.cli import MODERATE_EFFECT_RB
    import random
    rng = random.Random(7)
    # Wide, heavily-overlapping distributions with a small median shift → low rank-biserial.
    deficient = [-0.25 + rng.uniform(-0.6, 0.6) for _ in range(184)]
    neutral = [-0.18 + rng.uniform(-0.6, 0.6) for _ in range(485)]
    chronos, dv = _panel(deficient, neutral)
    s = compute_partner_stratification(chronos, dv)
    assert s["partner_stratification_effect_size"] < MODERATE_EFFECT_RB, s
    assert s["partner_stratification_class"] not in (
        "partner_conditional_strongly_dependent", "partner_conditional_moderately_dependent"), s
