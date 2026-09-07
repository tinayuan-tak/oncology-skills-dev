"""depmap_fusion_dependency.compute_fusion_stratification — hermetic (synthetic chronos + fusion bool, no S3).

Mirrors depmap_cn_dependency's stratification test shape but for the fusion boolean vector. Pins the
decisive classifications: fusion-positive lines cleanly more dependent → fusion_positive_*_dependent
(the FLI1/ABL1 signal this slice exists to capture, which the mutation + CN paths miss); no separation
→ not_fusion_stratified; too few fusion-positive lines → insufficient_fusion_rate. The one-sided test
guarantees a fusion is NEVER credited with a dependency it lacks (protects the symbol-union v1).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_fusion_dependency.cli import compute_fusion_stratification  # noqa: E402


def _panel(pos_chronos, neg_chronos):
    """Build (chronos_by_model, fusion_by_model) with N fusion-positive + M fusion-negative lines."""
    chronos, fusion = {}, {}
    i = 0
    for c in pos_chronos:
        m = f"ACH-{i:05d}"; chronos[m] = c; fusion[m] = True; i += 1
    for c in neg_chronos:
        m = f"ACH-{i:05d}"; chronos[m] = c; fusion[m] = False; i += 1
    return chronos, fusion


def test_fusion_positive_strongly_dependent():
    """Fusion-positive lines deeply dependent (~-1.0), negative not (~0) → delta <= -0.5 + significant
    → fusion_positive_strongly_dependent (the FLI1/EWSR1-FLI1 Ewing signal, live delta -0.69)."""
    import random
    rng = random.Random(0)
    pos = [-1.0 + rng.uniform(-0.1, 0.1) for _ in range(24)]
    neg = [-0.05 + rng.uniform(-0.1, 0.1) for _ in range(300)]
    chronos, fusion = _panel(pos, neg)
    s = compute_fusion_stratification(chronos, fusion)
    assert s["fusion_stratification_class"] == "fusion_positive_strongly_dependent"
    assert s["delta_chronos_fusion_positive_vs_negative"] <= -0.5
    assert s["n_fusion_positive"] == 24 and s["n_fusion_negative"] == 300


def test_not_fusion_stratified_when_no_separation():
    """Fusion-positive + negative both near 0 → no dependency difference → not_fusion_stratified
    (the method must NOT fabricate a fusion signal, e.g. the ALK/BRAF live result)."""
    import random
    rng = random.Random(1)
    pos = [-0.02 + rng.uniform(-0.08, 0.08) for _ in range(24)]
    neg = [0.0 + rng.uniform(-0.08, 0.08) for _ in range(300)]
    chronos, fusion = _panel(pos, neg)
    s = compute_fusion_stratification(chronos, fusion)
    assert s["fusion_stratification_class"] == "not_fusion_stratified"


def test_moderate_tier():
    """A modest but real separation (delta ~ -0.3) → fusion_positive_moderately_dependent (ABL1 live -0.47)."""
    import random
    rng = random.Random(2)
    pos = [-0.35 + rng.uniform(-0.08, 0.08) for _ in range(30)]
    neg = [-0.02 + rng.uniform(-0.08, 0.08) for _ in range(300)]
    chronos, fusion = _panel(pos, neg)
    s = compute_fusion_stratification(chronos, fusion)
    assert s["fusion_stratification_class"] == "fusion_positive_moderately_dependent"
    assert -0.5 < s["delta_chronos_fusion_positive_vs_negative"] <= -0.2


def test_insufficient_fusion_rate():
    """Fewer than min_positive (5) fusion-positive lines → insufficient_fusion_rate, never a call
    off an underpowered fusion-positive group."""
    import random
    rng = random.Random(3)
    pos = [-1.2, -1.1, -1.3]  # only 3 fusion-positive
    neg = [0.0 + rng.uniform(-0.08, 0.08) for _ in range(300)]
    chronos, fusion = _panel(pos, neg)
    s = compute_fusion_stratification(chronos, fusion)
    assert s["fusion_stratification_class"] == "insufficient_fusion_rate"


def test_fusion_negative_more_dependent_is_never_mislabeled_positive_dependent():
    """Inverse: fusion-NEGATIVE lines strongly MORE dependent than positive. Key guarantee — a fusion is
    NEVER credited with a dependency it lacks — must hold: the FORWARD `fusion_positive_*_dependent`
    classes must NOT fire (this keeps the symbol-union v1 conservative; a bystander-partner fusion only
    dilutes toward the null). With the second-pass reverse test (gap #4) this strong inverse now
    correctly surfaces as `fusion_negative_strongly_dependent` (verdict-inert)."""
    import random
    rng = random.Random(4)
    pos = [-0.02 + rng.uniform(-0.08, 0.08) for _ in range(24)]
    neg = [-0.6 + rng.uniform(-0.1, 0.1) for _ in range(300)]
    chronos, fusion = _panel(pos, neg)
    s = compute_fusion_stratification(chronos, fusion)
    assert s["fusion_stratification_class"] not in ("fusion_positive_strongly_dependent",
                                                    "fusion_positive_moderately_dependent")
    assert s["fusion_stratification_class"] == "fusion_negative_strongly_dependent"
    assert s["fusion_stratification_mannwhitney_q_reverse"] < 0.05
    assert s["delta_chronos_fusion_positive_vs_negative"] > 0   # negative arm more dependent → positive delta


# ── fusion↔alteration confound annotation (verdict-inert; mutation ∪ focal amplification overlap) ──
from methods.depmap_fusion_dependency.read import _fusion_alteration_confound  # noqa: E402


def _fusion_universe(n_pos, n_neg):
    """chronos_by_model + fusion_by_model with n_pos fusion+ / n_neg fusion- ACH ids."""
    chronos, fusion = {}, {}
    for i in range(n_pos):
        m = f"ACH-{i:05d}"; chronos[m] = -0.8; fusion[m] = True
    for j in range(n_neg):
        m = f"ACH-9{j:04d}"; chronos[m] = 0.0; fusion[m] = False
    return chronos, fusion


def _patch_alterations(monkeypatch, mutant_ids=(), amplified_ids=(), mut_fail=False, cn_fail=False):
    def fake_load_mutation_data(release_pin, target_symbol):
        if mut_fail:
            return {}, {}, [{"_live_read_error": "x"}]
        return ({m: True for m in mutant_ids}, {}, [])
    def fake_load_cn_files(release_pin, target_symbol):
        if cn_fail:
            return {}, {}, None, [{"_live_read_error": "x"}]
        return ({m: 3.0 for m in amplified_ids}, {}, "assay", [])
    monkeypatch.setattr("methods.depmap_mutation_dependency.cli.load_mutation_data",
                        fake_load_mutation_data, raising=False)
    monkeypatch.setattr("methods.depmap_cn_distribution.cli.load_cn_files",
                        fake_load_cn_files, raising=False)


def test_confound_flags_majority_altered_fusion_positive(monkeypatch):
    """The KRAS shape: a fusion-positive-dependent call whose fusion+ lines are MAJORITY target-altered
    (mutation ∪ focal amp ≥ 50%) → alteration_confounded (verdict-inert)."""
    chronos, fusion = _fusion_universe(13, 300)
    fpos = sorted(m for m, v in fusion.items() if v)
    _patch_alterations(monkeypatch, mutant_ids=fpos[:6], amplified_ids=fpos[6:8])  # 8/13 = 0.615
    r = _fusion_alteration_confound(fusion, chronos, "KRAS", "fusion_positive_strongly_dependent")
    assert r["fusion_stratification_confound"] == "alteration_confounded"
    assert r["fusion_positive_altered_overlap_fraction"] == 0.6154 and r["n_fusion_positive_altered"] == 8


def test_confound_independent_when_minority_altered(monkeypatch):
    """A REAL fusion driver: fusion+ lines are the driver, NOT target-mutant/amplified → minority overlap
    → alteration_independent (the flag must NOT fire on a genuine fusion dependency)."""
    chronos, fusion = _fusion_universe(20, 300)
    fpos = sorted(m for m, v in fusion.items() if v)
    _patch_alterations(monkeypatch, mutant_ids=fpos[:2], amplified_ids=fpos[2:3])  # 3/20 = 0.15
    r = _fusion_alteration_confound(fusion, chronos, "NTRK1", "fusion_positive_strongly_dependent")
    assert r["fusion_stratification_confound"] == "alteration_independent"
    assert r["fusion_positive_altered_overlap_fraction"] == 0.15


def test_confound_not_applicable_on_non_positive_class(monkeypatch):
    chronos, fusion = _fusion_universe(13, 300)
    _patch_alterations(monkeypatch, mutant_ids=[])
    r = _fusion_alteration_confound(fusion, chronos, "KRAS", "not_fusion_stratified")
    assert r["fusion_stratification_confound"] == "not_applicable"
    assert r["fusion_positive_altered_overlap_fraction"] is None


def test_confound_unassessed_when_both_alteration_lanes_fail(monkeypatch):
    chronos, fusion = _fusion_universe(13, 300)
    _patch_alterations(monkeypatch, mut_fail=True, cn_fail=True)
    r = _fusion_alteration_confound(fusion, chronos, "KRAS", "fusion_positive_moderately_dependent")
    assert r["fusion_stratification_confound"] == "unassessed"


def test_confound_uses_one_lane_when_other_fails(monkeypatch):
    """Fail-soft is per-lane: if CN is unreadable but mutation loads, the overlap still computes from the
    mutation lane (ok=True) rather than degrading to unassessed."""
    chronos, fusion = _fusion_universe(10, 300)
    fpos = sorted(m for m, v in fusion.items() if v)
    _patch_alterations(monkeypatch, mutant_ids=fpos[:6], cn_fail=True)  # 6/10 = 0.6, CN down
    r = _fusion_alteration_confound(fusion, chronos, "KRAS", "fusion_positive_strongly_dependent")
    assert r["fusion_stratification_confound"] == "alteration_confounded"
    assert r["fusion_positive_altered_overlap_fraction"] == 0.6
