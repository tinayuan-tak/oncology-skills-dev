"""F re-anchor regression matrix (2026-08-14, VERDICT-MOVING guard).

SKILL_VERSION 1.7.0 re-anchored _EXPRESSION_RANK so the TUMOR-tissue lens outranks the pan-cancer
CELL-LINE proxy for the collapsed headline. That change was justified by an offline A/B backtest over
43 target-indication pairs (10 indications): 23 flips, EVERY ONE -> tumor_broadly_expressed, zero
dangerous flips. The backtest harness was run out-of-tree (ephemeral); this test COMMITS its conclusion
as a permanent, credential-less regression matrix so a future ladder edit that reverts the re-anchor
(or reintroduces the cell-line-over-tumor precedence) fails here.

The collapsed presence_verdict is a pure function of the fired-rule list via run.py::_verdict, so each
row is a synthetic fired-set standing in for a real backtest exemplar (the rule_id that each card emits
is what actually drives the ladder — see CARD_CONTEXT / _EXPRESSION_RANK)."""

from __future__ import annotations

from pathlib import Path

import pytest
from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tp_run_matrix")


def _fr(rule_id, card_id):
    return {"rule_id": rule_id, "card_id": card_id, "field": "x", "value": "y", "signals": {}}


# The three cell-line vs tumor fired-set shapes that FLIPPED in the backtest — all must resolve to the
# tumor-tissue verdict now that the tumor lens outranks the cell-line proxy.
_CL_MODERATE = _fr("expression-broadly-moderate-neutral", "cellline-rna-distribution")
_CL_RESTRICTED = _fr("expression-lineage-restricted-supportive", "cellline-rna-distribution")
_CL_HIGH = _fr("expression-broadly-high-supportive", "cellline-rna-distribution")
_TVA_MODEST_UP = _fr("expression-modest-upregulation-neutral", "tumor-rna-vs-adjacent")
_TVA_STRONG_UP = _fr("expression-strong-upregulation-supportive", "tumor-rna-vs-adjacent")
_TUMOR_BROAD = _fr("tumor-expression-broadly-high-supportive", "tumor-rna-distribution")
_TUMOR_SPARSE = _fr("tumor-expression-broadly-low-neutral", "tumor-rna-distribution")


@pytest.mark.parametrize(
    "exemplar,fired,expected",
    [
        # FLIP class 1 — cell-line broadly_moderate + tumor broadly-expressed (EPCAM/FOLR1/KRAS/APC/BRAF/NAPSA)
        ("cellline_moderate_x_tumor_broad", [_CL_MODERATE, _TUMOR_BROAD], "tumor_broadly_expressed"),
        # FLIP class 2 — cell-line lineage_restricted + tumor broadly-expressed (CDH17/CEACAM5/TACSTD2/DLL3/NECTIN4/MUC13)
        ("cellline_restricted_x_tumor_broad", [_CL_RESTRICTED, _TUMOR_BROAD], "tumor_broadly_expressed"),
        # FLIP class 3 — tumor-vs-adjacent modest_up + tumor broadly-expressed (EGFR-LUAD/KRAS-LUAD/NOX1/STEAP1)
        ("tva_modest_up_x_tumor_broad", [_TVA_MODEST_UP, _TUMOR_BROAD], "tumor_broadly_expressed"),
    ],
)
def test_reanchor_flips_to_tumor_broadly_expressed(exemplar, fired, expected):
    """Backtest flip classes: whenever the tumor tissue reads broadly-expressed, the headline is the
    tumor verdict — the cell-line proxy no longer understates it."""
    v, _ = tp._verdict(fired)
    assert v == expected, f"{exemplar}: expected {expected}, got {v}"


@pytest.mark.parametrize(
    "exemplar,fired,expected",
    [
        # cell-line broadly_high + tumor broadly-expressed → BOTH high, headline unchanged (MET/ERBB2/MYC/TP53/PARP1)
        ("both_high_unchanged", [_CL_HIGH, _TUMOR_BROAD], "broadly_high_expression"),
        # tumor-vs-adjacent strong upregulation dominates (CEACAM5-LUAD/MSLN/HTR1D/TACSTD2-COADREAD)
        ("strong_up_unchanged", [_CL_RESTRICTED, _TVA_STRONG_UP], "strongly_upregulated_in_tumor"),
    ],
)
def test_reanchor_leaves_agreeing_and_strong_cases_unchanged(exemplar, fired, expected):
    """No gratuitous churn: cell-line broadly_high stays at rung 1 (both-high agreement) and a
    tumor-vs-adjacent strong-upregulation still wins outright."""
    v, _ = tp._verdict(fired)
    assert v == expected, f"{exemplar}: expected {expected}, got {v}"


def test_tumor_sparse_stays_below_cellline_positive():
    """Guard the deliberate NON-promotion: a per-indication NEUTRAL tumor_sparsely_expressed must NOT
    outrank a supportive cell-line-present signal (broadly_high) — only tumor broadly/moderately were
    promoted, not the sparse read."""
    v, _ = tp._verdict([_CL_HIGH, _TUMOR_SPARSE])
    assert v == "broadly_high_expression"


def test_reanchor_invariant_no_cellline_over_tumor_for_broad():
    """The core invariant, stated directly: given cell-line moderate/restricted AND tumor broadly-
    expressed both fired, the tumor rung must win (a regression that reverts the ladder would return a
    cell-line verdict here)."""
    for cl in (_CL_MODERATE, _CL_RESTRICTED):
        v, drv = tp._verdict([cl, _TUMOR_BROAD])
        assert v == "tumor_broadly_expressed"
        assert drv == "tumor-expression-broadly-high-supportive"


# ── subset_high split: the flip matrix for the rung added 2026-09-18 (phase 2 of 3) ─────────────────
# WHAT THIS MATRIX CAN AND CANNOT SHOW, stated so the gap is not mistaken for coverage.
#
# The plan for this phase asked for a REGENERATED live-panel flip matrix recording how many targets move
# from tumor_broadly_expressed to tumor_subset_high_expression. Two measurements say that belongs in
# phase 3, not here:
#   1. At phase 2 the answer is ZERO BY CONSTRUCTION — contracts still lists subset_high on the broad
#      rule, so the broad rung out-ranks the new one for every target. A live panel run now yields an
#      all-zero table, which is the vacuity signature, not evidence.
#   2. The committed corpus cannot substitute for a live run: `tumor_expression_class` appears in exactly
#      two frozen decision fixtures and BOTH read `broadly_high` (measured 2026-09-18 — grep the tree).
#      So re-scoring what is committed also cannot move a single row, and separately means the
#      subset_high path had NO exemplar anywhere in the tree before this file.
# The live-panel counterfactual (score the panel under narrowed rules, count the movers) is therefore
# phase 3's gating evidence and is listed as such in that PR's checklist. What phase 2 owes, and what is
# below, is the DETERMINISTIC flip semantics: which fired-set shapes move, which must NOT move, and
# what compensates where the collapsed word cannot carry the distinction. Credential-less, like the rest
# of this file, and mutated in BOTH directions so it cannot pass vacuously.
_TUMOR_SUBSET = _fr("tumor-expression-subset-high-supportive", "tumor-rna-distribution")
_SUBSET_VERDICT = "tumor_subset_high_expression"


@pytest.mark.parametrize(
    "exemplar,fired,expected",
    [
        # MOVES: the subset rung alone, and beside each cell-line proxy rung it out-ranks. The v1.7.0
        # re-anchor must hold for the NEW rung too — a tumor minority-high read still beats the proxy.
        ("subset_alone", [_TUMOR_SUBSET], _SUBSET_VERDICT),
        ("cellline_moderate_x_tumor_subset", [_CL_MODERATE, _TUMOR_SUBSET], _SUBSET_VERDICT),
        ("cellline_restricted_x_tumor_subset", [_CL_RESTRICTED, _TUMOR_SUBSET], _SUBSET_VERDICT),
        # DOES NOT MOVE (the other direction — the guard against a too-eager rung):
        # a broadly-expressed tumor keeps the broad word; the subset rung never steals it.
        ("tumor_broad_keeps_broad", [_TUMOR_BROAD], "tumor_broadly_expressed"),
        ("both_rungs_broad_wins", [_TUMOR_BROAD, _TUMOR_SUBSET], "tumor_broadly_expressed"),
        # cell-line broadly_high still anchors rung 1 (both-lenses-high agreement), exactly as it does
        # against tumor_broadly_expressed — see the compensation test below for why that is not a loss.
        ("cellline_high_x_tumor_subset", [_CL_HIGH, _TUMOR_SUBSET], "broadly_high_expression"),
        # a tumor-vs-adjacent STRONG upregulation still wins outright over a minority-high subset
        ("strong_up_beats_subset", [_TVA_STRONG_UP, _TUMOR_SUBSET], "strongly_upregulated_in_tumor"),
    ],
)
def test_subset_high_flip_matrix(exemplar, fired, expected):
    v, _drv = tp._verdict(fired)
    assert v == expected, f"{exemplar}: expected {expected}, got {v}"


def test_both_rungs_firing_is_the_phase_1_overlap_and_broad_wins():
    """The phase-1 safety property as a behavioural assertion: while contracts lists subset_high on BOTH
    rules, both fire and the BROAD rung drives — so phase 2 ships zero verdict movement. The paired row
    above pins the same thing on the verdict; this pins the DRIVER, which is what the audit spine and
    presence_signal_strength key on."""
    v, drv = tp._verdict([_TUMOR_BROAD, _TUMOR_SUBSET])
    assert v == "tumor_broadly_expressed"
    assert drv == "tumor-expression-broadly-high-supportive"


def test_cellline_high_over_subset_is_compensated_by_the_discordance_flag():
    """Where the collapsed word CANNOT carry the distinction, something else must. cell-line broadly_high
    (tier 3) out-ranks the subset rung (tier 2), so the headline reads `broadly_high_expression` and the
    minority-high tumor read is invisible in the one word — the same shape as the pre-existing
    cell-line-over-tumor_broadly_expressed case. The difference is the TIER INEQUALITY: this pair now
    reports cell_line_vs_tumor_discordant with direction `cell_line_overstates_tumor`, i.e. 'the panel
    reads uniformly high, the tumor is high in a subset'. Asserted as a PAIR against the broad case,
    which stays concordant — a one-sided check would pass on a flag that fired for everything."""
    subset_fired = [_CL_HIGH, _TUMOR_SUBSET]
    broad_fired = [_CL_HIGH, _TUMOR_BROAD]

    v_s, drv_s = tp._verdict(subset_fired)
    _lens_s, disc_s, dir_s = tp._headline_lens_discordance(drv_s, tp._per_modality_verdicts(subset_fired, None))
    v_b, drv_b = tp._verdict(broad_fired)
    _lens_b, disc_b, dir_b = tp._headline_lens_discordance(drv_b, tp._per_modality_verdicts(broad_fired, None))

    assert v_s == v_b == "broadly_high_expression", "both cases collapse to the cell-line word"
    assert disc_s is True and dir_s == "cell_line_overstates_tumor", "the subset case must be flagged"
    assert disc_b is False and dir_b is None, "the both-high case must stay concordant"
