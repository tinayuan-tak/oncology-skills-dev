"""#2327 — teeth for the `reliability.powered` per-property-kind floors (epic #2210, #2306 rollout).

WHAT IS PINNED, and why each pin can FAIL (SK#2091 — no inertness proofs; every assertion has a named
mutant that reds it):

1. **Each calibrated floor IS its method's own admissibility constant**, both directions — `powered_floor_for`
   returns exactly `PAN_ESSENTIAL_MIN_PANEL_N` / `RNAI_PAN_ESSENTIAL_MIN_PANEL_N` / `MIN_PARTNER_DEFICIENT_CELLS`.
   A method that retunes its guard, or a floor table that hardcodes a second copy, reds. (MUTANT: change the
   table value -> the equality reds.)
2. **`powered` is RE-DERIVED from the stored `n`, never trusted from the matrix.** `powered = (n >= floor)`
   through the same `powered_floor_for` the deriver uses; the matrix's stored `at_floor` counts must match
   the recomputation. (MUTANT: a stale stored count reds; a broken `>=` reds.)
3. **The counterfactual is a REAL flip, not a vacuous no-op** — the raised floor strictly exceeds every
   committed observation, so `at_counterfactual` is all-false where `at_floor` is all-true. (MUTANT: a
   counterfactual floor below the max observation reds the strict-exceed guard.)
4. **The matrix is NON-VACUOUS** — the calibrated kinds carry committed observations (the whole flip is not
   empty). (MUTANT: an empty corpus reds.)
5. **The unmeasured kinds resolve NO floor** and match `POWERED_FLOOR_UNMEASURED` exactly. (MUTANT: adding a
   floor for an evidence-count kind reds.)
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from onc_methods.depmap_chronos_distribution.cli import PAN_ESSENTIAL_MIN_PANEL_N
from onc_methods.depmap_demeter_distribution.cli import RNAI_PAN_ESSENTIAL_MIN_PANEL_N
from onc_methods.depmap_partner_conditional_dependency.cli import MIN_PARTNER_DEFICIENT_CELLS
from onc_methods.reliability_calibration.powered_floors import (
    POWERED_FLOOR_UNMEASURED,
    calibrated_kinds,
    powered_floor_for,
)

HERE = Path(__file__).resolve().parent
MATRIX = json.loads((HERE / "matrix.json").read_text())
KINDS = MATRIX["kinds"]

_EXPECTED_FLOOR = {
    "n_cell_lines_evaluated": PAN_ESSENTIAL_MIN_PANEL_N,
    "rnai_n_cell_lines_evaluated": RNAI_PAN_ESSENTIAL_MIN_PANEL_N,
    "n_partner_deficient": MIN_PARTNER_DEFICIENT_CELLS,
}


def _powered(n: int, floor: "int | None") -> "bool | str":
    return (n >= floor) if floor is not None else "unmeasured"


# 1 — each calibrated floor is its method's constant, both directions ─────────────────────────────────
@pytest.mark.parametrize("kind", sorted(_EXPECTED_FLOOR))
def test_calibrated_floor_equals_its_method_admissibility_constant(kind):
    floor = powered_floor_for(kind)
    assert floor == _EXPECTED_FLOOR[kind], (
        f"{kind} floor {floor} != its method's admissibility constant {_EXPECTED_FLOOR[kind]} — the floor "
        f"is single-sourced from the method and must not drift from it"
    )
    assert KINDS[kind]["floor"] == _EXPECTED_FLOOR[kind], f"{kind} matrix floor is stale vs the live constant"


def test_calibrated_kinds_are_exactly_the_three_reasoned_kinds():
    assert set(calibrated_kinds()) == set(_EXPECTED_FLOOR)


# 2 — powered re-derived from the stored n; matrix counts must match ──────────────────────────────────
@pytest.mark.parametrize("kind", sorted(_EXPECTED_FLOOR))
def test_at_floor_counts_are_reproduced_from_the_stored_observations(kind):
    row = KINDS[kind]
    floor = powered_floor_for(kind)
    values = [o["value"] for o in row["observations"]]
    recomputed = {
        "true": sum(1 for v in values if _powered(v, floor) is True),
        "false": sum(1 for v in values if _powered(v, floor) is False),
        "unmeasured": sum(1 for v in values if _powered(v, floor) == "unmeasured"),
    }
    assert recomputed == row["at_floor"], (
        f"{kind}: stored at_floor {row['at_floor']} != recomputed {recomputed} from the stored n through "
        f"powered_floor_for — a stale answer or a broken comparison"
    )


# 3 — the counterfactual is a real flip, strictly above every observation ─────────────────────────────
@pytest.mark.parametrize("kind", sorted(_EXPECTED_FLOOR))
def test_counterfactual_floor_flips_true_to_false_and_is_not_vacuous(kind):
    row = KINDS[kind]
    values = [o["value"] for o in row["observations"]]
    if not values:  # partner: no committed observation — documented, nothing to flip here
        assert row["n_observations"] == 0
        pytest.skip(f"{kind} has no committed observation (documented); the false side is proven in the deriver teeth")
    cf = row["counterfactual_floor"]
    assert cf > max(values), (
        f"{kind}: counterfactual floor {cf} does not strictly exceed the max observation {max(values)} — "
        f"the flip would be vacuous"
    )
    # every observation clears the REAL floor and fails the raised one — the descriptive unmeasured->true
    # move at the calibrated floor is real, and the true->false move at the counterfactual is real.
    assert row["at_floor"]["true"] == len(values) and row["at_floor"]["false"] == 0
    assert row["at_counterfactual"]["false"] == len(values) and row["at_counterfactual"]["true"] == 0


# 4 — non-vacuity: the calibrated corpus is not empty ─────────────────────────────────────────────────
def test_matrix_carries_committed_observations_for_the_calibrated_kinds():
    total = sum(KINDS[k]["n_observations"] for k in _EXPECTED_FLOOR)
    assert total >= 10, f"only {total} committed calibrated observations — the flip matrix is too thin to be evidence"
    assert KINDS["n_cell_lines_evaluated"]["n_observations"] >= 8, "CRISPR panel observations went missing"


# 5 — mutation tooth: a mutant floor flips the derived powered on a real observation ──────────────────
def test_a_mutant_floor_flips_powered_on_a_committed_crispr_observation():
    # A committed CRISPR panel size clears the real floor (300) -> True. A mutant floor above it -> False.
    v = KINDS["n_cell_lines_evaluated"]["observations"][0]["value"]
    assert _powered(v, PAN_ESSENTIAL_MIN_PANEL_N) is True
    assert _powered(v, v + 1) is False, "raising the floor above the observation must flip powered True->False"
    # and dropping the floor away entirely (the uncalibrated outcome) is the string sentinel, not a bool
    assert _powered(v, None) == "unmeasured"


# 6 — the unmeasured kinds resolve no floor and match the documented set ──────────────────────────────
def test_unmeasured_kinds_resolve_no_floor_and_carry_a_reason():
    documented = set(POWERED_FLOOR_UNMEASURED)
    in_matrix = {k for k, row in KINDS.items() if not row["calibrated"]}
    assert in_matrix == documented, f"matrix uncalibrated set {in_matrix} != documented {documented}"
    for kind in documented:
        assert powered_floor_for(kind) is None, f"{kind} is documented unmeasured but resolves a floor"
        assert POWERED_FLOOR_UNMEASURED[kind].strip(), f"{kind} carries no reason for staying unmeasured"
