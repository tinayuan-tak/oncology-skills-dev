"""Fidelity: does this executor reproduce the roster the contract itself froze?

``dataset_fitness_resolution.yaml`` ships its own conformance suite -- ``roster_validation``
carries all 36 measured input rows, the expected class counts, named membership lists for every
non-``fit`` class, and the per-rung firing attribution. Replaying those inputs here is therefore
a genuine CROSS-IMPLEMENTATION check rather than a tautology: the contract's expectations were
derived by hand from the design intent and are validated in target-contracts by an independent
interpreter, and this module is a second, separately-written executor. If the two ever disagree,
one of them reds.

It matters that the stored rows are the measured INPUTS, not the derived classes. A fixture of
derived values can never fail -- it would assert a computation against its own output. The inputs
are the irreproducible part (a bounded parquet read over 36 S3 products); the classes are
re-derived on every run.

SIBLING-GATED, but NOT CI-invisible -- do not assume otherwise. ``.github/workflows/
methods-validate.yml`` checks target-contracts out beside this repo and deliberately leaves
``TARGET_CONTRACTS_ROOT`` UNSET, so the sibling-derived default is the branch CI exercises and
these tests GATE: measured CI-to-CI, main 3745 passed / 32 skipped vs this branch 3800 / 32 --
the skip column does not move, so all 55 ran. The gate therefore protects a clone that simply
has no sibling beside it, not the runner. If you weaken a check here, expect CI to catch it.

The engine's semantics -- operators, absence handling, ordering, structural validation -- are
additionally covered WITHOUT the sibling in ``test_resolve_engine.py``, so nothing here is the
only coverage of anything.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.dataset_fitness_signals import load_contract, resolve_fitness  # noqa: E402
from methods.dataset_fitness_signals.resolve import contract_path  # noqa: E402

CONTRACT = contract_path()

pytestmark = pytest.mark.skipif(
    not CONTRACT.exists(),
    reason=f"dataset-fitness resolution contract not on disk at {CONTRACT} -- it ships in the "
    "sibling target-contracts repo, absent from this clone. CI DOES check it out, so these "
    "tests gate there; a skip here means a local clone, not an unguarded merge.",
)

COLLAPSED = {"degraded_to_gtex_only", "degraded_to_adjacent_only", "single_comparator"}
SIGNALS = (
    "quality_measured_present",
    "sampling",
    "primary_value_missingness",
    "dynamic_range",
    "rows_measured",
    "comparator_status",
    "arm_below_floor",
    "discordant_fraction",
)


@pytest.fixture(scope="module")
def contract():
    return load_contract()


@pytest.fixture(scope="module")
def rows(contract):
    return contract["roster_validation"]["products"]


@pytest.fixture(scope="module")
def resolved(contract, rows):
    return {r["product_id"]: resolve_fitness(r, contract) for r in rows}


# ---------------------------------------------------------------- anti-vacuity


def test_the_roster_is_present_and_complete(contract, rows):
    """Asserted before any loop: a roster that silently shrank to zero rows would make every
    count and membership test below vacuously true."""
    rv = contract["roster_validation"]
    assert len(rows) == rv["n_products"] == 36, f"{len(rows)} rows vs declared {rv.get('n_products')}"
    assert len({r["product_id"] for r in rows}) == 36, "duplicate product_ids in the roster"


def test_every_read_signal_is_present_in_every_roster_row(contract, rows):
    """If a row omitted a signal the engine would read it as absent, and the conformance pass
    would be measuring absence handling rather than the ladder."""
    declared = {r["signal"] for r in contract["reads"]}
    assert declared == set(SIGNALS), f"contract reads drifted from this test's list: {declared ^ set(SIGNALS)}"
    for row in rows:
        missing = [s for s in SIGNALS if s not in row]
        assert not missing, f"{row['product_id']}: roster row omits {missing}"


# ---------------------------------------------------------------- the declared expectations


def test_class_counts_match_the_declared_expectation(contract, resolved):
    expected = contract["roster_validation"]["expected"]["class_counts"]
    actual = {}
    for out in resolved.values():
        actual[out["dataset_fitness_class"]] = actual.get(out["dataset_fitness_class"], 0) + 1
    for cls, n in expected.items():
        assert actual.get(cls, 0) == n, f"{cls}: executor says {actual.get(cls, 0)}, contract declares {n}"
    assert sum(expected.values()) == len(resolved)


def test_named_membership_matches_for_every_non_fit_class(contract, resolved):
    """Counts cannot catch a SWAP -- two products trading classes leaves every count intact.
    The contract names its members for exactly that reason."""
    expected = contract["roster_validation"]["expected"]
    checked = 0
    for cls, members in expected.items():
        if cls == "class_counts" or not isinstance(members, list):
            continue
        actual = sorted(p for p, out in resolved.items() if out["dataset_fitness_class"] == cls)
        assert actual == sorted(members), f"{cls}: {set(actual) ^ set(members)} differ"
        checked += 1
    assert checked >= 3, f"only {checked} named membership lists found -- expected several"


def _declared_key(contract, out: dict) -> str:
    """The contract's key for the rung a resolution fired on.

    Its ``rungs_fired_on_first_roster`` keys are ``priority_<n>_<class>`` and
    ``default_<class>``, so the key is DERIVED from the contract here rather than hardcoded --
    a renamed convention should red as a key-set mismatch, not be silently absorbed.
    """
    if out["priority"] is None:
        return f"default_{contract['default']['class']}"
    return f"priority_{out['priority']}_{out['dataset_fitness_class']}"


def test_rung_attribution_matches_the_declared_firing_counts(contract, resolved):
    """Not just the verdicts but WHICH rule produced each one. Two rungs emitting the same class
    can trade all their products with no change in any class count -- and on this roster three
    separate rungs emit ``not_measured`` (10, 15, and the fall-through), so the class counts
    genuinely cannot see the difference."""
    declared = contract["roster_validation"]["rungs_fired_on_first_roster"]

    expected_keys = {f"priority_{r['priority']}_{r['class']}" for r in contract["resolve"]}
    expected_keys.add(f"default_{contract['default']['class']}")
    assert set(declared) == expected_keys, (
        f"the declared firing block does not name every rung: {set(declared) ^ expected_keys}"
    )

    actual = dict.fromkeys(declared, 0)
    for out in resolved.values():
        key = _declared_key(contract, out)
        assert key in actual, f"resolution fired on an unnamed rung {key!r}"
        actual[key] += 1
    assert actual == declared, f"attribution differs: executor {actual} vs contract {declared}"


def test_the_default_is_unfired_on_the_first_roster(contract, resolved):
    """The contract states the fall-through is 0/36 by design, so that a future product reaching
    it forces an explicit decision. A default quietly doing real work is a rung nobody
    reviewed."""
    fell_through = [p for p, out in resolved.items() if out["resolved_by"] == "default"]
    assert fell_through == [], f"products reached the fall-through: {fell_through}"
    declared = contract["roster_validation"]["rungs_fired_on_first_roster"]
    default_key = f"default_{contract['default']['class']}"
    assert declared[default_key] == 0, f"{default_key} is declared as {declared[default_key]}, not 0"


def test_no_anomalies_on_the_first_roster(resolved):
    """The non-finite guard must be a FORWARD guard here, not load-bearing.

    If any roster value were inf/NaN the guard would be silently changing conformance results,
    and its inertness is what lets it be added without re-validating the roster.
    """
    noisy = {p: out["anomalies"] for p, out in resolved.items() if out["anomalies"]}
    assert noisy == {}, f"non-finite inputs in the frozen roster: {noisy}"


# ---------------------------------------------------------------- the arc's invariant, executed


def test_collapsed_products_are_not_promoted_by_their_pristine_value_signals(contract, rows, resolved):
    """The axis exists because of this.

    A product that lost a comparator lost the arm that was DILUTING its pooled value signals, so
    its missingness and discordance look BETTER than a healthy product's. Here: collapsed
    products report a perfect 0.0 missingness, and a ladder that scored on value signals would
    rank them top. Every one must still land on ``partially_fit``.
    """
    collapsed = [r for r in rows if r["comparator_status"] in COLLAPSED]
    assert len(collapsed) == 8, f"expected 8 collapsed products, found {len(collapsed)}"

    pristine = [r["product_id"] for r in collapsed if r["primary_value_missingness"] == 0.0]
    assert len(pristine) >= 5, (
        f"only {len(pristine)} collapsed products have a perfect 0.0 missingness -- if that is no "
        "longer the corpus's shape, this test has stopped demonstrating the confound"
    )

    for row in collapsed:
        out = resolved[row["product_id"]]
        assert out["dataset_fitness_class"] == "partially_fit", (
            f"{row['product_id']} (status={row['comparator_status']}, "
            f"missingness={row['primary_value_missingness']}) resolved to "
            f"{out['dataset_fitness_class']} -- a collapsed product was promoted"
        )
        assert out["resolved_by"] == "priority_30"


def test_removing_the_shape_rung_costs_the_report_but_not_the_fit_pin(contract, rows, resolved):
    """Proves the shape rung is load-bearing IN THIS EXECUTOR -- and measures what it carries.

    Deleting the ``comparator_set_collapsed`` rung and re-resolving shows the contract has TWO
    independent shape guards, doing different jobs:

      * the ``fit`` rung's own ``comparator_status == both_comparators`` clause still refuses to
        promote a collapsed product to the best class. So removing rung 30 does NOT manufacture a
        false ``fit`` -- worth knowing, because that is the failure everyone checks for.
      * what is lost instead is the REPORT. 7 of the 8 collapsed products become ``not_measured``:
        the silent degradation stops being named, which is the one thing the axis exists to say
        out loud. An abstention reads as "we did not look", not as "this product answers a
        narrower question than its name advertises".
      * and one product is actively MIS-GRADED. ``sclc`` has two arms serialized as all-NaN, so
        its 0.6667 missingness trips ``missingness_elevated`` at priority 40 and it comes back
        ``fit_with_caveats`` -- a reliability footnote in place of a collapsed comparator set.
        The most degraded product on the roster gets the gentlest label.

    Pinning the exact 7/1 split rather than a vague "something changes" is what makes this a
    measurement: if a future edit moves a product between those two fates, this reds.
    """
    mutated = copy.deepcopy(dict(contract))
    mutated["resolve"] = [r for r in mutated["resolve"] if r.get("reason_code") != "comparator_set_collapsed"]
    assert len(mutated["resolve"]) == len(contract["resolve"]) - 1, "the shape rung was not found to remove"

    collapsed = [r for r in rows if r["comparator_status"] in COLLAPSED]
    assert len(collapsed) == 8

    after = {}
    for row in collapsed:
        assert resolved[row["product_id"]]["dataset_fitness_class"] == "partially_fit"
        after[row["product_id"]] = resolve_fitness(row, mutated)["dataset_fitness_class"]

    assert not [p for p, cls in after.items() if cls == "fit"], (
        f"a collapsed product reached `fit` without rung 30: {[p for p, c in after.items() if c == 'fit']} "
        "-- the fit conjunction's both_comparators clause was supposed to prevent that"
    )
    unreported = sorted(p for p, cls in after.items() if cls == "not_measured")
    misgraded = sorted(p for p, cls in after.items() if cls == "fit_with_caveats")
    assert len(unreported) == 7, f"expected 7 degradations to go unreported, got {len(unreported)}: {unreported}"
    assert misgraded == ["sclc-dge-tumor-vs-normal-sensitivity-v1"], misgraded


def test_shape_undecidable_products_abstain_rather_than_being_scored(contract, rows, resolved):
    """``cohort_not_declared`` products ARE value-profiled, so without the priority-15 rung they
    keep descending and get scored on signals whose confounder was never checked. They must
    abstain, and specifically at the shape rung rather than at the not-profiled one."""
    undecidable = [r for r in rows if r["comparator_status"] == "cohort_not_declared"]
    assert undecidable, "no cohort_not_declared products in the roster -- this test is vacuous"
    for row in undecidable:
        out = resolved[row["product_id"]]
        assert out["dataset_fitness_class"] == "not_measured", (row["product_id"], out)
        assert out["reason_code"] in ("shape_undecidable", "not_value_profiled"), out


def test_fit_products_all_have_both_comparators(contract, resolved, rows):
    """The ``fit`` rung pins the comparator shape explicitly. Nothing may reach the best class
    without two live comparators, whatever its value signals say."""
    by_id = {r["product_id"]: r for r in rows}
    fit = [p for p, out in resolved.items() if out["dataset_fitness_class"] == "fit"]
    assert fit, "no fit products -- this test would be vacuous"
    for product in fit:
        assert by_id[product]["comparator_status"] == "both_comparators", (
            f"{product} is fit with comparator_status={by_id[product]['comparator_status']}"
        )


def test_every_product_carries_a_reason_code_and_a_rung(resolved):
    for product, out in resolved.items():
        assert out["reason_code"], f"{product}: no reason_code"
        assert out["resolved_by"], f"{product}: no rung attribution"
        assert out["dataset_fitness_class"], f"{product}: no class"
