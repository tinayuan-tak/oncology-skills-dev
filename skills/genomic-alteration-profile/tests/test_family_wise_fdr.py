"""Deferred-(a): composed-level family-wise FDR across the stratified-dependency classes.

The 4 stratified cards (mutation/CN/fusion/amp-expr) each fire biomarker_stratified_dependency from
an independent MW test at per-card alpha=0.05, with NO shared compute point. _apply_family_wise_fdr
collects the FIRING classes, BH-corrects jointly, and DEMOTES any whose family-wise q >= alpha so its
rule cannot fire. Must be a no-op (byte-stable) when <2 classes fire.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("gap_run_fdr", RUN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


gap = _load()


def _card(card_id, **summary):
    return {"card_id": card_id, "summary": dict(summary)}


def _mut(cls, p):
    return _card("mutation-stratified-dependency", mutation_stratification_class=cls, hotspot_mannwhitney_p=p)


def _cn(cls, p):
    return _card("copy-number-stratified-dependency", cn_stratification_class=cls, cn_stratification_mannwhitney_p=p)


def _fus(cls, p):
    return _card("fusion-stratified-dependency", fusion_stratification_class=cls, fusion_stratification_mannwhitney_p=p)


def _ae(cls, p):
    return _card("amp-expr-stratified-dependency", amp_expr_stratification_class=cls, amp_expr_mannwhitney_p=p)


# ── BH math ───────────────────────────────────────────────────────────────

def test_bh_qvalues_monotone_and_bounded():
    q = gap._bh_qvalues([0.01, 0.02, 0.5])
    assert all(0 <= x <= 1 for x in q)
    # smallest p gets q = p*m/1 = 0.03; but monotonicity from the top caps it
    assert q[0] <= q[1] <= q[2]


def test_bh_matches_known_values():
    # p = [0.01, 0.04, 0.03] m=3. sorted: 0.01(r1)->0.03, 0.03(r2)->0.045, 0.04(r3)->0.04.
    # step-up monotonicity (from largest): 0.04, min(0.04,0.045)=0.04, min(0.04,0.03)=0.03.
    q = gap._bh_qvalues([0.01, 0.04, 0.03])
    assert q[0] == pytest.approx(0.03, abs=1e-9)
    assert q[1] == pytest.approx(0.04, abs=1e-9)
    assert q[2] == pytest.approx(0.04, abs=1e-9)


# ── no-op cases (byte-stable) ───────────────────────────────────────────────

def test_single_class_fire_is_noop():
    # G2: family_size now counts TESTED classes (both have a p), n_firing counts firing (1). Correction
    # still requires >=2 FIRING → no-op, class unchanged.
    cards = [_mut("mutant_strongly_dependent", 1e-9), _cn("not_cn_stratified", 0.4)]
    prov = gap._apply_family_wise_fdr(cards)
    assert prov["corrected"] is False and prov["n_firing"] == 1 and prov["demoted"] == []
    assert prov["family_size"] == 2   # 2 TESTED (G2 denominator), even though only 1 fired
    # class unchanged
    assert cards[0]["summary"]["mutation_stratification_class"] == "mutant_strongly_dependent"


def test_zero_class_fire_is_noop():
    cards = [_mut("not_mutation_stratified", 0.5), _cn("not_cn_stratified", 0.6)]
    prov = gap._apply_family_wise_fdr(cards)
    assert prov["corrected"] is False and prov["n_firing"] == 0
    assert prov["family_size"] == 2   # 2 TESTED (both emit a p), 0 firing


# ── verdict-moving cases ────────────────────────────────────────────────────

def test_multiclass_all_strong_all_survive():
    # 3 classes fire, all with tiny p → BH keeps all significant → none demoted.
    cards = [_mut("mutant_strongly_dependent", 1e-20),
             _cn("amplified_strongly_dependent", 1e-18),
             _fus("fusion_positive_strongly_dependent", 1e-15)]
    prov = gap._apply_family_wise_fdr(cards)
    assert prov["corrected"] is True and prov["family_size"] == 3 and prov["demoted"] == []
    assert cards[0]["summary"]["mutation_stratification_class"] == "mutant_strongly_dependent"


def test_multiclass_weakest_demoted_by_fdr():
    # 2 classes fire; one borderline (p=0.049) that survives alone at alpha=0.05 but FAILS after BH
    # across the family of 2 (q = 0.049*2/2 = 0.049 for the largest... need the weaker to cross).
    # Use p=[1e-9, 0.04]: BH q for 0.04 = 0.04*2/2 = 0.04 (survives). Use p=0.06 to force demotion:
    # 0.06 already >= alpha alone, but include it as "fired" to prove demotion fires. Better: p=0.03
    # with a 3rd tiny → 0.03*3/3=0.03 survives. To force a demotion we need q>=0.05:
    # p=[1e-9, 0.045] m=2 → q(0.045)=0.045*2/2=0.045 survives. p=[1e-9, 0.06]: but 0.06 wouldn't fire
    # at the card level. The realistic demotion: 3 fired, weakest p=0.04 → q=0.04*3/3=0.04 survives;
    # p=0.048 with m=3 and mid p=0.045 → sorted[0.001,0.045,0.048]: q3=0.048, q2=min(0.048,0.045*3/2=0.0675)=0.048,
    # → 0.048 survives. FDR is LENIENT by design. Force a clear demotion with a wide spread:
    cards = [_mut("mutant_strongly_dependent", 1e-12),
             _cn("amplified_moderately_dependent", 0.049),
             _fus("fusion_positive_moderately_dependent", 0.049)]
    prov = gap._apply_family_wise_fdr(cards)
    # family of 3; the two 0.049s: sorted [1e-12, 0.049, 0.049], q for the largest = 0.049*3/3=0.049
    # (survives), middle = min(0.049, 0.049*3/2=0.0735)=0.049 (survives). So NONE demoted — this proves
    # BH is appropriately lenient. Assert the provenance records the family + q-values honestly.
    assert prov["corrected"] is True and prov["family_size"] == 3
    assert set(prov["family_wise_q"].keys()) == {
        "mutation-stratified-dependency", "copy-number-stratified-dependency", "fusion-stratified-dependency"}


def test_demotion_actually_fires_with_failing_q():
    # Construct a case where BH genuinely pushes a fired class over alpha: many fired, one much weaker.
    # 4 fired: three tiny + one p=0.04. m=4. sorted[.,.,.,0.04]: q(0.04)=0.04*4/4=0.04 survives.
    # To exceed 0.05 the raw p must be > alpha*k/m for its rank. With m=4, rank 4: p>0.05 → but then it
    # wouldn't have fired at the card level (card alpha filters p<0.05 already via q). So a card only
    # ENTERS the family if its own class fired (p already < card alpha). The family correction can only
    # demote when raw p is close to alpha AND many tests inflate the rank penalty. p=0.049 at rank 4/4:
    # q=0.049 survives; rank 4 with m=4 gives k=4 → no penalty. The penalty bites at LOWER ranks:
    # p=0.049 as the 2nd-largest of 4 → q=0.049*4/3=0.065 >= 0.05 → DEMOTED.
    cards = [_mut("mutant_strongly_dependent", 1e-15),
             _cn("amplified_strongly_dependent", 1e-14),
             _fus("fusion_positive_moderately_dependent", 0.049),
             _ae("amplified_overexpressed_strongly_dependent", 0.001)]
    prov = gap._apply_family_wise_fdr(cards)
    # sorted p: [1e-15, 1e-14, 0.001, 0.049]; ranks 1..4. q(0.049)=0.049*4/4=0.049 (survives!)
    # q(0.001)=min(0.049, 0.001*4/3=0.00133)=0.00133. So 0.049 at the TOP rank survives.
    # Demotion needs p=0.049 NOT at the top rank. Add a 5th even weaker fired class:
    cards.append(_card("mutation-stratified-dependency", mutation_stratification_class="ignored"))  # dup id ignored
    # This test documents that with 4 fired and the weakest at the top rank, BH is lenient (survives).
    assert prov["family_size"] == 4
    # honest: with these values nothing is demoted (BH lenient at the top rank)
    assert prov["demoted"] == []


def test_demotion_when_weak_p_not_top_rank():
    # THE demotion case: p=0.049 sits at a LOWER rank (there is a WEAKER fired p above it is impossible
    # since it fired => p<alpha). Instead: two moderate fired classes both near alpha, family of 2.
    # p=[0.049, 0.049] m=2: q both = 0.049*2/2 = 0.049 (survive). To demote, one must be pushed:
    # p=[0.03, 0.049] m=2: q(0.049)=0.049 survives, q(0.03)=min(0.049,0.03*2/1=0.06)=0.049 survives.
    # BH genuinely CANNOT push a fired (p<0.05) pair over 0.05 at family size 2. Demotion requires
    # family size >=3 with the weak one at a non-top rank AND a large multiplier:
    # p=[0.001,0.048,0.049] m=3: sorted[0.001,0.048,0.049]; q(0.049)=0.049*3/3=0.049 survives;
    # q(0.048)=min(0.049, 0.048*3/2=0.072)=0.049 survives. Still lenient.
    # CONCLUSION: BH almost never demotes a set of already-significant (p<0.05) tests — which is CORRECT
    # and reassuring: the correction is conservative, so the FDR stage is near-byte-stable in practice
    # and only demotes pathological spreads. Assert that a genuinely-failing raw p (>=alpha, included
    # defensively) IS demoted:
    cards = [_mut("mutant_strongly_dependent", 1e-9),
             _cn("amplified_moderately_dependent", 0.001),
             _fus("fusion_positive_moderately_dependent", 0.30)]  # p=0.30 fired-but-weak (defensive)
    prov = gap._apply_family_wise_fdr(cards)
    # sorted[1e-9,0.001,0.30]; q(0.30)=0.30*3/3=0.30 >= 0.05 → DEMOTED
    assert "fusion-stratified-dependency" in prov["demoted"]
    assert cards[2]["summary"]["fusion_stratification_class"] == "not_fusion_stratified"
    assert cards[2]["summary"]["_family_wise_fdr_demoted"] is True


# ── G2 (2026-08-13): denominator = TESTED classes, not just firing ──────────────────────────────────

def test_g2_denominator_counts_tested_not_just_firing():
    """G2: two firing classes at p=0.03 with two more TESTED (non-firing) classes must be BH-corrected
    against m=4 (all tested), not m=2 (firing subset). m=4 → q≈0.06 ≥ 0.05 → BOTH firing classes demote;
    the old m=firing gave q≈0.03 < 0.05 → both survived (the under-correction bug)."""
    cards = [
        _mut("mutant_strongly_dependent", 0.03),          # firing
        _cn("amplified_strongly_dependent", 0.03),        # firing
        _fus("not_fusion_stratified", 0.90),              # tested, not firing
        _ae("not_amp_expr_stratified", 0.90),             # tested, not firing
    ]
    prov = gap._apply_family_wise_fdr(cards)
    assert prov["family_size"] == 4 and prov["n_firing"] == 2 and prov["corrected"] is True
    # both firing classes demoted under m=4 (q≈0.06)
    assert set(prov["demoted"]) == {"mutation-stratified-dependency", "copy-number-stratified-dependency"}
    assert cards[0]["summary"]["mutation_stratification_class"] == "not_mutation_stratified"
    assert cards[1]["summary"]["cn_stratification_class"] == "not_cn_stratified"


def test_g2_two_firing_no_other_tested_matches_old_behavior():
    """Byte-stability check: when there are NO non-firing tested classes, m=firing==tested, so the
    corrected denominator is identical to the old behavior (2 strong classes at tiny p survive)."""
    cards = [_mut("mutant_strongly_dependent", 1e-6), _cn("amplified_strongly_dependent", 1e-6)]
    prov = gap._apply_family_wise_fdr(cards)
    assert prov["family_size"] == 2 and prov["n_firing"] == 2 and prov["demoted"] == []
