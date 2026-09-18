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

import collections
import json
from pathlib import Path

import pytest
from _test_support import load_module, load_run_py

HERE = Path(__file__).resolve().parent
tp = load_run_py(HERE.parent, "tp_run_matrix")


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


# ── subset_high split: the flip matrix for the rung added 2026-09-18 ────────────────────────────────
# TWO MATRICES FOLLOW, AND THE SPLIT BETWEEN THEM IS THE POINT.
#   § A (immediately below) — DETERMINISTIC flip semantics over SYNTHETIC fired-sets: which shapes move,
#     which must NOT move, and what compensates where the collapsed word cannot carry the distinction.
#   § B (end of file) — the LIVE-PANEL counterfactual: 58 real (target, indication) pairs measured off
#     S3, ranked under both rule arms, committed as fixtures/subset_high_live_flip_matrix.json.
#
# § B was deferred out of phase 2, and the reason is worth keeping because it is the vacuity argument.
# At phase 2 the live answer was ZERO BY CONSTRUCTION: contracts still listed subset_high on the broad
# rule, so the broad rung out-ranked the new one for every target and a live run yielded an all-zero
# table. Nor could the committed corpus substitute — `tumor_expression_class` appears in exactly two
# frozen decision fixtures and BOTH read `broadly_high` (measured 2026-09-18), so re-scoring what was
# committed could not move a row either, which separately means the subset_high path had no exemplar
# anywhere in the tree before this file. Phase 3b (contracts c3eec12) narrowed the broad rule and made
# the counterfactual measurable; § B is that measurement, committed rather than promised.
#
# What § A owes on its own is the deterministic semantics below — credential-less, like the rest of this
# file, and mutated in BOTH directions so it cannot pass vacuously.
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
    """The overlap safety property as a behavioural assertion: when BOTH rungs fire, the BROAD one drives
    — which is why phase 2 shipped zero verdict movement. The paired row above pins that on the verdict;
    this pins the DRIVER, which is what the audit spine and presence_signal_strength key on.

    STILL ASSERTED, BUT NOW A COUNTERFACTUAL. This docstring used to open "while contracts lists
    subset_high on BOTH rules", and that stopped being true when phase 3b (contracts c3eec12) removed
    subset_high from the broad rule: contracts no longer PRODUCES this fired-set from a subset_high card.
    The test is kept, and is not dead weight — this pair is exactly arm A of the live-panel matrix in
    § B, which reconstructs the overlap in memory to measure what the split moved. If this goes red,
    every arm-A column in that fixture is wrong too."""
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


# ── § B. THE LIVE-PANEL COUNTERFACTUAL — 58 measured pairs, both rule arms (2026-09-18) ─────────────
# CONTRACT.md conceded that the v1.7.0 re-anchor's 43-pair backtest data was never committed, so its
# conclusion was unreproducible. This section pays that debt forward for the subset_high split: the panel
# behind THIS verdict change is committed, and the verdicts are RE-DERIVED here rather than transcribed.
#
# WHAT IS GROUND TRUTH AND WHAT IS NOT. The fixture stores, per pair, four LIVE-MEASURED card fields
# (tumor_expression_class / high_fraction / detectable_fraction / distribution_pattern — S3 reads needing
# AWS_PROFILE=cbg) and, alongside them, the DERIVED verdict columns for both arms. Only the measurements
# are ground truth. A fixture that stored only derived values and asserted them back would be comparing a
# computation against a copy of its own output and could never fail for the right reason; so the columns
# are re-derived below — from the stored fired-sets in every environment (§ B.2) and all the way from the
# measured class through the real rules loader wherever a contracts checkout exists (§ B.5).
#
# WHICH MEASURED FIELD ACTUALLY DRIVES THE LADDER — measured, not assumed. Every tumor-expression rule in
# intracellular-intrinsic.rules.yaml keys on `field: tumor_expression_class`, and NO rule on that axis
# reads high_fraction, detectable_fraction or distribution_pattern (verified 2026-09-18 against contracts
# c475e69). So the rules-level re-derivation is class -> fired -> verdict, one field wide. The other three
# are kept because they are the inputs to the CLASSIFIER one layer upstream
# (methods/tcga_gtex_expression_distribution/read.py:840), which is what § B.4 exploits: it checks the
# committed measurements against the method's own documented conjunctive cut without a live read.
#
# REGENERATING IT: tests/regenerate_live_flip_matrix.py, `--rederive-only` for the credential-less half.
# The arms are one contracts tree plus a one-field in-memory mutation, so this is runnable today; the
# original two-checkout generator is not, because the #809 worktree was pruned when the PR landed.
_LIVE_MATRIX_PATH = HERE / "fixtures" / "subset_high_live_flip_matrix.json"
_TUMOR_CARD = "tumor-rna-distribution"

# A MISSING FIXTURE MUST BE A RED, NOT A SKIP — so this loads at import time. If the file is gone,
# collection fails loudly here instead of every test below quietly reporting nothing.
_LIVE_MATRIX = json.loads(_LIVE_MATRIX_PATH.read_text())
_LIVE_PAIRS = _LIVE_MATRIX["pairs"]

# THE MEASUREMENT, restated as constants so a hand-edit of the fixture cannot pass silently. These are
# the numbers the split is justified by; if the panel is legitimately re-measured, these move WITH it and
# the diff is the review artifact.
_PANEL_PAIRS = 58
_PANEL_TARGETS = 56
_PANEL_INDICATIONS = 12
_PANEL_MOVERS = {("MAGEA3", "SKCM"), ("MAGEA4", "LUSC")}
_PANEL_NON_MOVER_CLASSES = {
    "broadly_high": 21,
    "broadly_detected": 19,
    "broadly_moderate": 13,
    "broadly_low": 3,
}
# The method's conjunctive subset_high definition (read.py:840): a bimodal OR long_tail shape AND
# high_fraction >= 0.1. Both clauses, because either alone is satisfied by non-subset rows on this panel.
_SUBSET_SHAPES = {"bimodal", "long_tail"}
_SUBSET_HIGH_FLOOR = 0.1


def _fired_dicts(rule_ids):
    """The fixture stores fired rules as bare ids; _verdict takes rule dicts."""
    return [_fr(rid, _TUMOR_CARD) for rid in rule_ids]


def test_live_panel_matrix_is_the_measurement_it_claims_to_be():
    """ANTI-VACUITY FIRST. Every assertion in § B is a loop over `pairs`, and a loop over a truncated or
    emptied list passes while measuring nothing — the same failure shape as an empty parametrize reporting
    green. So pin the panel's size, its identity, and that the mover CLASS is present at all: if no row
    reads subset_high, the rung under test is unreachable and § B.3 is guarding an empty set."""
    assert len(_LIVE_PAIRS) == _PANEL_PAIRS, f"panel is {len(_LIVE_PAIRS)} rows, expected {_PANEL_PAIRS}"
    keys = [(r["target"], r["code"]) for r in _LIVE_PAIRS]
    assert len(set(keys)) == len(keys), "duplicate (target, indication) rows — a pair is counted twice"
    assert len({r["target"] for r in _LIVE_PAIRS}) == _PANEL_TARGETS
    assert len({r["code"] for r in _LIVE_PAIRS}) == _PANEL_INDICATIONS
    # the measured class drives the ladder, so it must be present on every row
    assert all(r["cls"] for r in _LIVE_PAIRS), "a row has no measured tumor_expression_class"
    assert any(r["cls"] == "subset_high" for r in _LIVE_PAIRS), (
        "no subset_high row on the panel — the rung this whole section tests is unreachable and every "
        "mover assertion below would be guarding an empty set"
    )
    # and the two arms must not be the same column, or the counterfactual collapsed
    assert any(r["A"] != r["B"] for r in _LIVE_PAIRS), "arms identical — the fixture records no flip"


def test_live_panel_ladder_reproduces_every_verdict_in_both_arms():
    """§ B.2 — the load-bearing, credential-less leg: re-run run.py::_verdict over all 58 stored
    fired-sets and reproduce BOTH columns, verdict and driver. This is what goes red if a future
    _EXPRESSION_RANK edit reverts the split or re-orders the new rung against the broad one, and it runs
    in every environment because it needs no contracts checkout."""
    for row in _LIVE_PAIRS:
        where = f"{row['target']}/{row['code']}"
        va, dva = tp._verdict(_fired_dicts(row["firedA"]))
        vb, dvb = tp._verdict(_fired_dicts(row["firedB"]))
        assert (va, dva) == (row["A"], row["drvA"]), (
            f"{where} arm A: got {(va, dva)}, fixture {(row['A'], row['drvA'])}"
        )
        assert (vb, dvb) == (row["B"], row["drvB"]), (
            f"{where} arm B: got {(vb, dvb)}, fixture {(row['B'], row['drvB'])}"
        )


def test_live_panel_movers_are_exactly_the_subset_high_rows_and_nothing_else_moved():
    """§ B.3 — BOTH DIRECTIONS, which is the whole reason a flip count is evidence rather than a headline.

    Forward: the 2 movers must move, from tumor_broadly_expressed (driven by the broad rung, because
    pre-3b it claimed subset_high too) to tumor_subset_high_expression (driven by the new rung).
    Reverse, and equally load-bearing: the other 56 must be BYTE-IDENTICAL across the arms. A split that
    silently re-worded 56 unrelated targets would be a regression dressed as a fix, and a mover-count-only
    test would report it as a bigger success.

    The identity `movers == subset_high rows` is asserted as a SET, not a count: 2-in-2-out with the wrong
    two targets is a different change with the same headline."""
    movers = {(r["target"], r["code"]) for r in _LIVE_PAIRS if r["A"] != r["B"]}
    subset_rows = {(r["target"], r["code"]) for r in _LIVE_PAIRS if r["cls"] == "subset_high"}
    assert movers == _PANEL_MOVERS, f"mover set changed: {movers} vs {_PANEL_MOVERS}"
    assert movers == subset_rows, (
        f"movers {movers} != subset_high rows {subset_rows} — the split moved a target whose class is not "
        "subset_high, or left a subset_high target on the broad word"
    )
    for row in _LIVE_PAIRS:
        where = f"{row['target']}/{row['code']}"
        if (row["target"], row["code"]) in _PANEL_MOVERS:
            assert row["A"] == "tumor_broadly_expressed" and row["drvA"] == _TUMOR_BROAD["rule_id"], where
            assert row["B"] == _SUBSET_VERDICT and row["drvB"] == _TUMOR_SUBSET["rule_id"], where
        else:
            assert (row["A"], row["drvA"]) == (row["B"], row["drvB"]), (
                f"{where} moved but is not a declared mover — the split changed an unrelated target's "
                f"headline from {row['A']} to {row['B']}"
            )
    non_movers = collections.Counter(r["cls"] for r in _LIVE_PAIRS if r["A"] == r["B"])
    assert dict(non_movers) == _PANEL_NON_MOVER_CLASSES, (
        f"the unchanged population's class mix moved: {dict(non_movers)} vs {_PANEL_NON_MOVER_CLASSES}"
    )


def test_live_panel_subset_high_rows_satisfy_the_methods_conjunctive_definition():
    """§ B.4 — the CLASSIFIER layer, one level upstream of the rules, checked credential-lessly.

    `subset_high` is conjunctive in the method (read.py:840): a bimodal/long_tail SHAPE and
    high_fraction >= 0.1. The rules never see either field, so nothing else in this repo can notice if the
    class stops meaning what the rung's rationale says it means. The committed measurements can.

    Both clauses are load-bearing ON THIS PANEL, which is why this is a check and not a tautology: of the
    four rows holding the shape clause, two pass the fraction clause (the movers, at 0.33 and 0.37) and
    two FAIL it — CTAG1B/SKCM at 0.058 and DLK1/LIHC at 0.097, the latter missing by 0.003. Drop the
    fraction clause and DLK1 becomes a patient-selection call on a 9.7%-of-patients read; drop the shape
    clause and 19 continuous rows with high_fraction above 0.1 would qualify. Asserted as an IFF over the
    shape-clause rows so it bites in both directions."""
    shape_rows = [r for r in _LIVE_PAIRS if r["pat"] in _SUBSET_SHAPES]
    assert len(shape_rows) >= 4, f"only {len(shape_rows)} shape-clause rows — too few to test either clause"
    # the fraction clause must be DECIDABLE wherever the shape clause holds. high_fraction is absent on 34
    # of 58 rows (the reader does not always emit it), so this is stated for the population where it decides
    # rather than asserted panel-wide — an unconditional non-null assert here would simply be false.
    assert all(r["high"] is not None for r in shape_rows), "a shape-clause row has no high_fraction"
    for row in shape_rows:
        where = f"{row['target']}/{row['code']}"
        passes = row["high"] >= _SUBSET_HIGH_FLOOR
        assert (row["cls"] == "subset_high") is passes, (
            f"{where}: class={row['cls']} but high_fraction={row['high']:.4f} "
            f"{'clears' if passes else 'misses'} the {_SUBSET_HIGH_FLOOR} floor — the committed panel no "
            "longer matches the method's conjunctive subset_high definition"
        )
    assert sum(r["cls"] == "subset_high" for r in shape_rows) == 2, "expected exactly 2 passing rows"
    assert sum(r["cls"] != "subset_high" for r in shape_rows) >= 2, (
        "no shape-clause row FAILS the fraction clause — the floor is untested on this panel"
    )
    # the shape clause, from the other side: no continuous row may be subset_high
    assert not [r for r in _LIVE_PAIRS if r["cls"] == "subset_high" and r["pat"] not in _SUBSET_SHAPES]


def test_live_panel_rederives_from_the_measured_class_through_the_live_rules():
    """§ B.5 — close the loop through the RULES, so the fixture guards the contracts pin and not just the
    ladder. § B.2 starts from stored fired-sets and therefore cannot see a rules change; this starts from
    the measured class, loads the real rules, and derives the fired-sets itself. Both arms must reproduce.

    Skips when the sibling contracts checkout is absent (checkout-only CI), which is why § B.2 exists and
    does not skip: the non-skipping leg is the guarantee, this one is the upgrade.

    COUNT THE CALLERS, NOT THE HELPER. arm A is built with `_restore_broad_overlap` from
    test_ladder_invariants.py rather than a local copy — reused deliberately, because that helper already
    had to INVERT direction when 3b landed and a second copy would have drifted. The cost is that this
    file is now a third caller, so a contracts change to the broad rule reds here too. That is the correct
    blast radius, not an accident."""
    from _skills_common import fired_rules

    helpers = load_module(HERE / "test_ladder_invariants.py", "tp_ladder_helpers")
    rules_b = helpers._live_rules()
    if rules_b is None:
        pytest.skip("target-contracts checkout absent — the rules-level re-derivation is not applicable")
    rules_a = helpers._restore_broad_overlap(rules_b)  # asserts it mutated exactly 1 rule

    derived = 0
    for row in _LIVE_PAIRS:
        card = {
            "card_id": _TUMOR_CARD,
            "summary": {
                "tumor_expression_class": row["cls"],
                "high_fraction": row["high"],
                "detectable_fraction": row["det"],
                "distribution_pattern": row["pat"],
            },
        }
        where = f"{row['target']}/{row['code']}"
        for arm, rules, expected_fired, expected_verdict in (
            ("A", rules_a, row["firedA"], row["A"]),
            ("B", rules_b, row["firedB"], row["B"]),
        ):
            fired = fired_rules([card], "intracellular-intrinsic", card_id_filter=[_TUMOR_CARD], rules=rules)
            assert sorted(r["rule_id"] for r in fired) == expected_fired, (
                f"{where} arm {arm}: live rules fire {sorted(r['rule_id'] for r in fired)}, fixture "
                f"recorded {expected_fired} — contracts changed under this fixture; regenerate it with "
                "tests/regenerate_live_flip_matrix.py --rederive-only and review the diff"
            )
            verdict, _drv = tp._verdict(fired)
            assert verdict == expected_verdict, f"{where} arm {arm}: {verdict} != {expected_verdict}"
            derived += 1
    assert derived == 2 * _PANEL_PAIRS, f"derived {derived} verdicts, expected {2 * _PANEL_PAIRS}"
