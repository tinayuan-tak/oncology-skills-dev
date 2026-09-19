"""The shape-conditioned roster-relative cut, and the confound it exists to prevent.

Split deliberately: everything that can be tested without the sibling target-contracts checkout
(the percentile primitives and ``reanchor``'s refusals, which take a contract MAPPING and touch
no disk) runs in CI. Only the tests that re-measure the real frozen roster are gated.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.dataset_fitness_signals import (  # noqa: E402
    conditioned_values,
    load_contract,
    percentile_cut,
    reanchor,
    roster_relative_cut,
)
from methods.dataset_fitness_signals.resolve import ContractInvalid, contract_path  # noqa: E402

CONTRACT = contract_path()
needs_contract = pytest.mark.skipif(
    not CONTRACT.exists(),
    reason=f"resolution contract not on disk at {CONTRACT} (sibling target-contracts absent from "
    "this clone); the primitives and refusals in this file are covered sibling-free",
)

COLLAPSED = ("degraded_to_gtex_only", "degraded_to_adjacent_only", "single_comparator")


# ---------------------------------------------------------------- primitives (CI-visible)


def test_an_empty_reference_class_yields_no_cut_rather_than_zero():
    """A cut derived from no data is not a cut. Zero would be the most permissive possible
    threshold -- failing OPEN exactly where the reference class turned out to be empty."""
    assert percentile_cut([], 75) is None
    assert roster_relative_cut([{"x": 1.0}], "x", 75, where={"status": "never_matches"}) is None


def test_a_bad_percentile_raises_even_when_there_is_nothing_to_measure():
    """Validated BEFORE the empty-input short circuit, so an out-of-range percentile cannot be
    masked by an empty reference class and silently return None."""
    with pytest.raises(ValueError, match=r"\[0, 100\]"):
        percentile_cut([], 150)
    with pytest.raises(ValueError, match=r"\[0, 100\]"):
        percentile_cut([0.1, 0.2], -1)


def test_non_finite_values_are_dropped_from_the_distribution():
    """An inf would dominate any upper quantile and a NaN poisons a sort, so neither may enter
    the reference distribution. Booleans are excluded too -- True is not a measurement of 1.0."""
    rows = [{"x": v} for v in (0.1, 0.2, float("inf"), float("nan"), float("-inf"), None, "0.3", True, 0.3)]
    assert conditioned_values(rows, "x") == [0.1, 0.2, 0.3]


def test_conditioning_accepts_a_scalar_or_a_membership_predicate():
    rows = [
        {"x": 1.0, "status": "both"},
        {"x": 2.0, "status": "gtex_only"},
        {"x": 3.0, "status": "adjacent_only"},
    ]
    assert conditioned_values(rows, "x", {"status": "both"}) == [1.0]
    assert conditioned_values(rows, "x", {"status": ["gtex_only", "adjacent_only"]}) == [2.0, 3.0]
    assert conditioned_values(rows, "x", None) == [1.0, 2.0, 3.0]
    assert conditioned_values(rows, "x", {"missing_field": "anything"}) == []


# ---------------------------------------------------------------- reanchor refusals (CI-visible)


def _synthetic(use="within_shape_only", shape_confounded=True, basis="roster_relative"):
    return {
        "thresholds": [{"id": "cut", "signal": "s", "op": "gt", "value": 0.10, "basis": basis}],
        "reads": [{"signal": "s", "use": use, "shape_confounded": shape_confounded}],
    }


def test_reanchor_refuses_a_within_shape_signal_without_a_conditioning_predicate():
    """The discipline is STRUCTURAL, not the caller's obligation to remember -- the whole finding
    is that the naive pooled read looks perfectly reasonable."""
    rows = [{"s": 0.1, "status": "both"}, {"s": 0.0, "status": "collapsed"}]
    with pytest.raises(ContractInvalid, match="requires a conditioning predicate"):
        reanchor(_synthetic(), "cut", rows, percentile=75)
    with pytest.raises(ContractInvalid, match="requires a conditioning predicate"):
        reanchor(_synthetic(), "cut", rows, percentile=75, where={})  # empty is not a predicate

    # ...and it proceeds once the partition is named, so the refusal is not unconditional.
    out = reanchor(_synthetic(), "cut", rows, percentile=75, where={"status": "both"})
    assert out["n_conditioned"] == 1 and out["n_pooled"] == 2


def test_reanchor_allows_an_unconfounded_signal_without_conditioning():
    rows = [{"s": 0.1}, {"s": 0.3}]
    out = reanchor(_synthetic(use="primary", shape_confounded=False), "cut", rows, percentile=75)
    assert out["n_conditioned"] == out["n_pooled"] == 2


def test_reanchor_refuses_to_move_an_absolute_threshold():
    """An absolute floor is not supposed to move when the corpus does -- that is exactly what
    makes it a forward guard rather than a calibration."""
    with pytest.raises(ContractInvalid, match="only roster_relative"):
        reanchor(_synthetic(basis="absolute"), "cut", [{"s": 0.5}], percentile=75, where={"a": 1})


def test_reanchor_rejects_an_undeclared_threshold():
    with pytest.raises(ContractInvalid, match="not declared"):
        reanchor(_synthetic(), "typo", [{"s": 0.5}], percentile=75, where={"a": 1})


def test_reanchor_reports_the_pooled_value_alongside_the_conditioned_one():
    """The magnitude of the avoided confound is REPORTED, not merely avoided -- a caller that
    cannot see the difference cannot tell whether the conditioning mattered."""
    rows = [{"s": v, "status": "both"} for v in (0.10, 0.12, 0.15, 0.20)]
    rows += [{"s": 0.0, "status": "collapsed"} for _ in range(6)]
    out = reanchor(_synthetic(), "cut", rows, percentile=75, where={"status": "both"})
    assert out["n_conditioned"] == 4 and out["n_pooled"] == 10
    assert out["pooled"] < out["remeasured"], (out["pooled"], out["remeasured"])


# ---------------------------------------------------------------- the real roster (gated)


@pytest.fixture(scope="module")
def contract():
    return load_contract()


@pytest.fixture(scope="module")
def rows(contract):
    return contract["roster_validation"]["products"]


@needs_contract
def test_the_conditioned_distribution_reproduces_what_the_contract_declared(rows):
    """Re-derived from the frozen inputs, not copied from the contract's prose. The declared
    ``distribution`` string records p50 0.1210 / p75 0.1502 / p90 0.1662 over n=21."""
    values = conditioned_values(rows, "discordant_fraction", {"comparator_status": "both_comparators"})
    assert len(values) == 21, f"both_comparators partition is n={len(values)}, declared n=21"
    assert round(percentile_cut(values, 50), 4) == 0.1210
    assert round(percentile_cut(values, 75), 4) == 0.1502
    assert round(percentile_cut(values, 90), 4) == 0.1662
    assert round(max(values), 4) == 0.2124


@needs_contract
def test_a_single_armed_product_reports_absence_as_a_measured_zero(rows):
    """The mechanism behind the confound, pinned on the data.

    Discordance is the fraction of genes whose two arms disagree in sign. One live arm cannot
    disagree with itself, so a collapsed product's 0.0 is an ABSENCE wearing a measured value,
    not a good result. Seven of the eight report exactly 0.0 for that reason; ``hnsc`` is the
    instructive exception -- ``degraded_to_adjacent_only`` but with two adjacent-derived arms
    still live, so one COMPARATOR yet two ARMS, and its 0.0035 is genuinely measured.
    """
    collapsed = conditioned_values(rows, "discordant_fraction", {"comparator_status": list(COLLAPSED)})
    assert len(collapsed) == 8
    assert sum(1 for v in collapsed if v == 0.0) == 7, collapsed
    hnsc = next(r for r in rows if r["product_id"].startswith("hnsc-"))
    assert hnsc["comparator_status"] == "degraded_to_adjacent_only"
    assert 0.0 < hnsc["discordant_fraction"] < 0.01, hnsc["discordant_fraction"]


@needs_contract
def test_pooling_the_roster_moves_the_cut_and_misgrades_a_product(contract, rows):
    """Why the conditioning is enforced rather than recommended.

    Re-anchoring by pooling the whole roster drags the p75 from 0.1502 down to 0.1432, because
    the reference class is diluted by products that had nothing to disagree with. That is not
    cosmetic: it fires on 7 of 21 both-arm products instead of 6, so a healthy product is
    labelled high-discordance by a threshold calibrated against structural absence. The confound
    reaches the CALIBRATION, not just a ranking.
    """
    conditioned = conditioned_values(rows, "discordant_fraction", {"comparator_status": "both_comparators"})
    pooled = conditioned_values(rows, "discordant_fraction", None)
    assert len(pooled) == 32, len(pooled)

    cut_conditioned = percentile_cut(conditioned, 75)
    cut_pooled = percentile_cut(pooled, 75)
    assert round(cut_conditioned, 4) == 0.1502
    assert round(cut_pooled, 4) == 0.1432
    assert cut_pooled < cut_conditioned

    declared = next(t for t in contract["thresholds"] if t["id"] == "discordance_high")["value"]
    fires_declared = sum(1 for v in conditioned if v > declared)
    fires_pooled = sum(1 for v in conditioned if v > cut_pooled)
    assert fires_declared == 6, fires_declared
    assert fires_pooled == 7, fires_pooled

    # and the median is understated by more than a third, which is the size of the dilution
    assert round(np.median(conditioned), 4) == 0.1210
    assert round(np.median(pooled), 4) == 0.0763


@needs_contract
def test_reanchor_against_the_frozen_roster_shows_only_the_declared_rounding(contract, rows):
    """The declared cut 0.15 is the measured p75 0.1502 rounded down, so at exact tolerance
    ``drifted`` is True -- the honest default. A caller asking "has the corpus moved?" passes the
    rounding it accepted, and then the answer is no."""
    exact = reanchor(contract, "discordance_high", rows, percentile=75, where={"comparator_status": "both_comparators"})
    assert exact["declared"] == 0.15
    assert round(exact["remeasured"], 4) == 0.1502
    assert exact["n_conditioned"] == 21 and exact["n_pooled"] == 32
    assert exact["drifted"] is True, "exact tolerance should surface the deliberate rounding"

    tolerant = reanchor(
        contract,
        "discordance_high",
        rows,
        percentile=75,
        where={"comparator_status": "both_comparators"},
        tolerance=0.01,
    )
    assert tolerant["drifted"] is False, "the corpus has not moved beyond the accepted rounding"


@needs_contract
def test_reanchor_refuses_the_real_contracts_discordance_cut_unconditioned(contract, rows):
    """The refusal on the real declaration, not only on a synthetic one: ``discordant_fraction``
    ships ``use: within_shape_only``, so the pooled re-anchoring above is unreachable by
    accident."""
    with pytest.raises(ContractInvalid, match="requires a conditioning predicate"):
        reanchor(contract, "discordance_high", rows, percentile=75)


@needs_contract
def test_every_absolute_threshold_refuses_reanchoring(contract, rows):
    """Anti-vacuity on the basis check: the contract has four absolute thresholds and one
    roster-relative one, and all four absolutes must refuse."""
    absolutes = [t["id"] for t in contract["thresholds"] if t.get("basis") == "absolute"]
    assert len(absolutes) == 4, absolutes
    for tid in absolutes:
        with pytest.raises(ContractInvalid, match="only roster_relative"):
            reanchor(contract, tid, rows, percentile=75, where={"comparator_status": "both_comparators"})
