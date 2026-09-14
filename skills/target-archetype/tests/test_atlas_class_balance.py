"""CLASS BALANCE — the VARIANCE-axis companion to `reference_mask_fraction` (`build_atlas.class_balance`).

WHY this file exists, in one sentence: **the frozen gate that already ships rates the worst column in the
artifact PERFECT.** Consumers gate usable reference columns at `reference_mask_fraction >= 0.6`, which counts
cells MEASURED; nothing counts whether they DIFFER. So `dependency::claim::SEL::corrob` — 2 `moderate` cells
against 295 `high`, the most z-degenerate column in the frozen space — scores 1.0000 and sails through. When a
gate calls a known-bad column GOOD, the defect is the METRIC'S AXIS, not the threshold, so this adds an axis.

Two fields, not one, and `test_the_fraction_alone_ranks_a_healthy_continuous_column_BELOW_a_degenerate_one` is
the test that makes that non-negotiable: `min_class_fraction` is NON-MONOTONE in usability. A constant column's
single class holds 100% of the rows, so it reads **1.000** — the same flawless score being fixed — and a
continuous column's smallest class holds 1/n, which on this corpus is numerically LOWER than the degenerate
column's. `n_classes` is what separates constant / degenerate / continuous. Delete it and the gate inverts.

Scope of what CI can see. The shipped `atlas.json` predates this field and will not carry it until the next
hand-run re-freeze, so the tests split three ways:
  - the FUNCTION is unit-tested directly on synthetic columns (every regime, incl. the degenerate ones);
  - the WIRING into the emitted doc is asserted against `build_atlas.py`'s SOURCE, the same by-name idiom
    `test_atlas_embedding.py` uses for `PCA_SVD_SOLVER` — otherwise the computation could be correct and
    never reach the artifact (deferral-by-absence is invisible; see test_deferred_anchors.py);
  - the MOTIVATING DEFECT is measured on the shipped artifact by running the real function over the frozen
    `X`, so the claim "the coverage gate passes a degenerate column" is re-derived here, not quoted.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "atlas" / "atlas.json"
BUILD = ROOT / "scripts" / "build_atlas.py"

# Illustrative only — this is NOT a shipped constant. The fields are verdict-INERT: they supply the number and
# do not pick the threshold. A test that hardcoded a canonical `t` would be inventing policy.
T_ILLUSTRATIVE = 0.05

# Where the ORDINAL ladders end and the continuous block begins, used only to split populations for the
# artifact tests below. Empirical, not declared: the shipped `n_classes` distribution is 1, 2, 3, 4 and then
# jumps to 9 — the claim ladders are low/moderate/high (+ one 4-valued family) and every `::mask` is 0/1.
MAX_LADDER_CLASSES = 4


@pytest.fixture(scope="module")
def build_mod():
    spec = importlib.util.spec_from_file_location("build_atlas", BUILD)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["build_atlas"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def doc():
    return json.loads(ATLAS.read_text())


@pytest.fixture(scope="module")
def panel():
    """Five columns, one per regime, at the shipped corpus height so the fractions are the real ones.

    Column 2 is `dependency::claim::SEL::corrob` exactly (2 `moderate` + 295 `high`); column 3 is the
    continuous case that defeats a fraction-only gate.
    """
    return np.column_stack(
        [
            np.full(297, 3.0),  # 0: CONSTANT
            np.array([1.0] * 148 + [2.0] * 149),  # 1: balanced two-valued
            np.array([2.0] * 2 + [3.0] * 295),  # 2: NEAR-DEGENERATE (the real SEL column)
            np.arange(297, dtype=float),  # 3: CONTINUOUS
            np.array([5.0] * 100 + [np.nan] * 197),  # 4: constant, PARTLY NULL
        ]
    )


# --- the function, per regime ------------------------------------------------------------------------


def test_the_function_exists_at_all(build_mod):
    """Positive control. Every test below calls it; an absent symbol should fail loudly here rather than as
    five confusing AttributeErrors."""
    assert callable(getattr(build_mod, "class_balance", None)), "build_atlas.class_balance is gone"


def test_each_regime_reads_as_expected(build_mod, panel):
    n_classes, frac = build_mod.class_balance(panel, panel.shape[1])
    assert n_classes == [1, 2, 2, 297, 1]
    assert frac == [1.0, 0.498316, 0.006734, 0.003367, 1.0]
    # the SEL figure is 2/297 to six places — the same number quoted in the closed-form analysis
    assert frac[2] == round(2 / 297, 6)


def test_a_constant_column_scores_the_TOP_fraction(build_mod, panel):
    """★ The non-monotonicity that forces two fields. The single class of a constant column holds 100% of the
    rows, so `min_class_fraction` reads 1.000 — indistinguishable from ideal, and the identical failure mode as
    `reference_mask_fraction` rating SEL 1.0000. Only `n_classes` says which one it is."""
    n_classes, frac = build_mod.class_balance(panel, panel.shape[1])
    assert frac[0] == 1.0 and frac[0] == max(frac), "a constant column must score the TOP fraction, not the worst"
    assert n_classes[0] == 1, "n_classes no longer isolates the constant column ⇒ the two-field gate cannot fire"


def test_the_fraction_alone_ranks_a_healthy_continuous_column_BELOW_a_degenerate_one(build_mod, panel):
    """★★ THE test. A `::num::` column with ~n distinct values has a smallest class of 1/n, so on this corpus
    a perfectly healthy continuous column reads 0.003367 while the most degenerate ordinal column in the
    artifact reads 0.006734 — the fraction ORDERS THEM BACKWARDS. Any refactor that drops `n_classes` or gates
    on the fraction alone reintroduces exactly the defect this field was added to fix."""
    n_classes, frac = build_mod.class_balance(panel, panel.shape[1])
    degenerate, continuous = 2, 3
    assert frac[continuous] < frac[degenerate], "the inversion is gone ⇒ this test is no longer the argument"
    assert n_classes[continuous] > n_classes[degenerate] * 10, "n_classes must separate what the fraction fuses"


def test_the_two_field_gate_admits_exactly_the_usable_columns(build_mod, panel):
    """The gate consumers are meant to write: `n_classes >= 2 and min_class_fraction >= t`. Asserted as a
    PARTITION, so a change that widens or narrows it fails rather than merely shifting a number."""
    n_classes, frac = build_mod.class_balance(panel, panel.shape[1])
    passes = [n >= 2 and f >= T_ILLUSTRATIVE for n, f in zip(n_classes, frac)]
    assert passes == [False, True, False, False, False], (
        f"expected only the balanced two-valued column to clear a two-field gate: {list(zip(n_classes, frac, passes))}"
    )
    # and the anti-vacuity leg: the FRACTION-ONLY gate would admit three of them, two of them wrongly
    fraction_only = [f >= T_ILLUSTRATIVE for f in frac]
    assert sum(fraction_only) == 3 and fraction_only[0] and fraction_only[4]


def test_the_denominator_is_the_NON_NULL_count_not_the_row_count(build_mod):
    """The asymmetry against `reference_mask_fraction` is DELIBERATE and this is what fires if someone
    'harmonises' them: coverage divides by `n_rows` (all corpus targets), balance divides by the observed
    count, because `nanstd` ignores NaN and the non-null population is the one that sets the z denominator.
    50 of each value among 100 observed of 297 rows is BALANCED (0.5), not 50/297 = 0.168."""
    col = np.array([[v] for v in [1.0] * 50 + [2.0] * 50 + [np.nan] * 197])
    n_classes, frac = build_mod.class_balance(col, 1)
    assert n_classes == [2]
    assert frac == [0.5], "balance must be measured over OBSERVED cells, not over n_rows"
    assert frac != [round(50 / 297, 6)]


def test_it_is_aligned_positionally_to_feature_order(build_mod, panel):
    """Alignment is DECLARED, not assumed — the same reason `feature_correlation` ships its own `order`. Both
    lists are indexed by `feature_order` position, so a column's two scores must travel with its index."""
    n_classes, frac = build_mod.class_balance(panel, panel.shape[1])
    assert len(n_classes) == len(frac) == panel.shape[1]
    for j in range(panel.shape[1]):
        one_col = panel[:, [j]]
        assert build_mod.class_balance(one_col, 1) == ([n_classes[j]], [frac[j]])


def test_n_classes_one_is_exactly_the_population_the_sd_floor_fires_for(build_mod, panel):
    """`n_classes == 1` ⟺ `nanstd == 0` ⟺ the `sd = np.where(sd == 0, 1.0, sd)` floor substitutes 1.0. That
    makes the new field a READER for the floor: an `sd` of 1.0 in the artifact is otherwise ambiguous between
    a real dispersion and a floored one. Only the guaranteed direction is asserted — a genuinely balanced
    two-valued column with rung step 2 would also read `sd == 1.0` without being constant."""
    n_classes, _ = build_mod.class_balance(panel, panel.shape[1])
    sd_raw = np.nanstd(panel, axis=0)
    floored = np.where(sd_raw == 0, 1.0, sd_raw)
    assert any(n == 1 for n in n_classes), "no constant column in the panel ⇒ this test is vacuous"
    for j, n in enumerate(n_classes):
        if n == 1:
            assert sd_raw[j] == 0.0 and floored[j] == 1.0, f"col {j}: n_classes==1 but sd={sd_raw[j]}"


def test_a_degenerate_panel_does_not_read_as_BALANCED(build_mod):
    """Shape and fill for the empty cases. A zero-row panel and an over-declared column count must return
    correctly-sized fills; critically the fill is `n_classes 0 / fraction 0.0`, NOT the 1.0 a constant column
    scores — 'nothing was observed' must not be recorded as the top of the scale."""
    assert build_mod.class_balance(np.array([], dtype=float), 3) == ([0, 0, 0], [0.0, 0.0, 0.0])
    over = build_mod.class_balance(np.array([[1.0, 2.0]]), 4)
    assert over == ([1, 1, 0, 0], [1.0, 1.0, 0.0, 0.0])


# --- wiring: the computation must reach the emitted artifact ------------------------------------------


def test_the_builder_emits_both_fields_and_calls_the_helper():
    """Reachability, by-name against the SOURCE — the idiom `test_atlas_embedding.py` uses for
    `PCA_SVD_SOLVER`. The shipped `atlas.json` predates this field, so no artifact assertion can cover it
    yet; without this test the helper could be correct, tested, and never wired into `doc`."""
    src = BUILD.read_text()
    assert re.search(r"^def class_balance\(", src, re.M), "class_balance is no longer module-level"
    assert "class_balance(Xn, len(feature_order))" in src, "the builder no longer calls it over feature_order"
    for field in ("n_classes", "min_class_fraction"):
        assert f'"{field}": {field},' in src, f"{field} is computed but not emitted into the atlas doc"


def test_the_next_refreeze_must_pin_the_new_fields(doc):
    """States the coupling rather than asserting the future. `test_atlas_stability.py` compares
    `set(pinned['fields']) == set(doc)` by EXACT equality against the shipped artifact, so today's atlas
    (which lacks these fields) stays green — and the next re-freeze RED-FAILS until `atlas_stability.py
    --write` re-pins in the same commit. That red is the forcing function working, not a regression."""
    assert "n_classes" not in doc, (
        "the atlas now ships n_classes ⇒ atlas_freeze.json must be re-pinned in the same commit "
        "(atlas_stability.py --write) and this test should be replaced by a real artifact assertion"
    )


# --- the motivating defect, measured on the SHIPPED artifact -------------------------------------------


def test_the_coverage_gate_passes_a_column_this_axis_rejects(build_mod, doc):
    """★ The reason the field exists, re-derived from the frozen `X` rather than quoted: columns that clear the
    usable-reference gate (`reference_mask_fraction >= 0.6`) while being near-degenerate on the variance axis.

    The population is restricted to FEW-CLASS columns on purpose. `n_classes >= 2 and frac < t` alone is
    satisfied by 19 perfectly healthy CONTINUOUS columns as well, so a non-emptiness assertion over it would
    hold in a completely clean artifact — vacuous-pass by construction. The ladder bound is empirical: the
    shipped `n_classes` distribution runs 1, 2, 3, 4 then jumps straight to 9, so `<= 4` is the ordinal block.
    """
    order = doc["feature_order"]
    Xn = np.array([[np.nan if v is None else v for v in row] for row in doc["X"]], dtype=float)
    n_classes, frac = build_mod.class_balance(Xn, len(order))
    cov = doc["reference_mask_fraction"]
    assert len(cov) == len(order) == len(frac)

    hits = [
        k
        for j, k in enumerate(order)
        if cov[j] >= 0.6 and 2 <= n_classes[j] <= MAX_LADDER_CLASSES and frac[j] < T_ILLUSTRATIVE
    ]
    assert hits, (
        "no few-class shipped column clears the coverage gate while failing the variance gate — the "
        "orthogonality this field was added for is no longer demonstrable in the artifact"
    )
    # ★ and the population is NOT confined to `::corrob`, which is the only block the analysis behind this
    # field examined. Measured at the 2026-09-13 freeze: 34 columns, `::signal` 16 + `::corrob` 12 + `::mask` 6.
    # A guard written only for `::corrob` would leave two thirds of it uncovered.
    assert len({k.rsplit("::", 1)[-1] for k in hits}) >= 2, (
        f"the degenerate population collapsed to one column family: {sorted(hits)}"
    )

    # the specific column the whole analysis was built on, if it is still frozen
    if "dependency::claim::SEL::corrob" in order:
        j = order.index("dependency::claim::SEL::corrob")
        assert cov[j] == 1.0, "SEL::corrob no longer scores a perfect coverage fraction"
        assert n_classes[j] == 2 and frac[j] == round(2 / 297, 6)


def test_the_shipped_artifact_INTERLEAVES_healthy_and_degenerate_by_fraction_alone(build_mod, doc):
    """★★ The two-field design argument, measured on the real artifact instead of a synthetic panel. The
    continuous block's `min_class_fraction` range OVERLAPS the degenerate ordinal block's, so NO threshold on
    the fraction alone separates them: at the 2026-09-13 freeze 23 of 30 continuous columns score BELOW
    `dependency::claim::SEL::corrob`. A fraction-only gate would reject 23 healthy columns before it rejected
    the worst one in the atlas. `n_classes` is what makes the two populations distinguishable at all."""
    order = doc["feature_order"]
    Xn = np.array([[np.nan if v is None else v for v in row] for row in doc["X"]], dtype=float)
    n_classes, frac = build_mod.class_balance(Xn, len(order))

    continuous = [j for j in range(len(order)) if n_classes[j] > MAX_LADDER_CLASSES]
    degenerate = [j for j in range(len(order)) if 2 <= n_classes[j] <= MAX_LADDER_CLASSES]
    assert continuous and degenerate, "one of the two blocks is empty ⇒ this test proves nothing"

    assert min(frac[j] for j in continuous) < max(frac[j] for j in degenerate), (
        "the fraction ranges no longer overlap ⇒ a one-field gate would suffice and this design is overbuilt"
    )
    if "dependency::claim::SEL::corrob" in order:
        worst = frac[order.index("dependency::claim::SEL::corrob")]
        below = [j for j in continuous if frac[j] < worst]
        assert below, (
            "no continuous column scores below the most degenerate ordinal column — the inversion that "
            "motivates shipping n_classes alongside the fraction is no longer present"
        )


def test_a_constant_shipped_column_is_indistinguishable_on_coverage_alone(build_mod, doc):
    """The second half of the orthogonality: constant columns exist in the frozen space and the coverage
    fraction cannot see them either. This is what `n_classes` adds for a reader of the shipped artifact —
    including telling a floored `sd` of 1.0 from a real one."""
    order = doc["feature_order"]
    Xn = np.array([[np.nan if v is None else v for v in row] for row in doc["X"]], dtype=float)
    n_classes, frac = build_mod.class_balance(Xn, len(order))
    constant = [j for j, n in enumerate(n_classes) if n == 1]
    assert constant, "no constant column in the shipped atlas ⇒ this test is vacuous"
    assert all(frac[j] == 1.0 for j in constant), "a constant column must score the top fraction"
    # every one of them reads a stored sd of exactly 1.0, because the sd==0 floor fired for it
    assert all(doc["sd"][j] == 1.0 for j in constant), (
        "a constant column no longer carries the floored sd ⇒ the floor's population changed"
    )
