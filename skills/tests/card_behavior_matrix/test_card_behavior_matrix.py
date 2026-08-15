"""Card-behavior matrix (#5) — offline replay of frozen real-data fixtures.

For each (pair, card) the matrix asserts the card lands in the correct one of FOUR states:
  informative       — a real primary class value (assert observed in the cell's `match` value-set)
  measured_negative — a real negative call (also a value-set match; the label is documentation)
  data_unavailable  — no data (no shard / read error / data_unavailable sentinel)
  not_in_scope      — a subtype-gated card invoked without a resolved subgroup scope
This is the guard for the reachable-but-dead-reader class (a card that stops FIRING on real data)
and the subgroup null-strata traps — things golden snapshots + synthetic reachability can't catch.

Offline: replays fixtures frozen by freeze.py (run against live S3). A nightly-live workflow re-freezes
to catch drift. Assertions are class-BUCKET / state level, never numeric bytes (re-pin robust) and
never the resolver verdict (would test the framework against itself). Skips a pair with no fixture.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

HERE = Path(__file__).resolve().parent
SKILLS = HERE.parent.parent
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common import _primary_class_value, _is_data_unavailable  # noqa: E402

_MATRIX = yaml.safe_load((HERE / "matrix.yaml").read_text())
_FIXTURES = HERE / "fixtures"


def _observed(summary, field):
    """Observed four-state for a frozen summary, reading the cell's DECLARED primary `field`.

    Returns ("data_unavailable"|"not_in_scope", None) for the null flavors, or ("value", <class>)
    for a real answer. Reading an explicit `field` (not a heuristic over *_class fields) avoids the
    multi-class primary-identification ambiguity that the #359 bug was about — e.g. the dependency
    card carries both dependency_class (primary) and dep_control_position_class (a facet).
    """
    if not isinstance(summary, dict):
        return "data_unavailable", None
    if summary.get("_freeze_error") or summary.get("_live_read_error") or summary.get("_dispatcher_returned_none"):
        return "data_unavailable", None
    if "requires resolved subgroups" in str(summary.get("_data_note", "")):
        return "not_in_scope", None
    if field == "per_subgroup_metrics":                  # subtype/panorama card
        rows = summary.get("per_subgroup_metrics") or []
        measured = [r for r in rows if isinstance(r, dict) and r.get("evidence_state") == "measured"]
        if measured:
            return "value", "subtype_measured"
        if rows:
            return "value", "subtype_no_signal"          # strata present, none measured (real negative)
        return "data_unavailable", None                  # empty panorama → no shard / broken join
    v = summary.get(field) if field else _primary_class_value(summary)
    if v is None or _is_data_unavailable(v):
        return "data_unavailable", v if isinstance(v, str) else None
    return "value", v


def _cells():
    out = []
    for pair in _MATRIX["pairs"]:
        fx = _FIXTURES / f"{pair['id']}.yaml"
        if not fx.exists():
            continue                                     # not yet frozen — skip (nightly/freeze.py populates)
        frozen = yaml.safe_load(fx.read_text()) or {}
        for cell in pair["expect"]:
            out.append((pair["id"], cell["card"], cell, frozen.get(cell["card"])))
    return out


_CELLS = _cells()


@pytest.mark.skipif(not _CELLS, reason="no frozen fixtures yet (run freeze.py against live S3)")
@pytest.mark.parametrize("pair_id,card,cell,summary", _CELLS,
                         ids=[f"{p}:{c}" for p, c, _cell, _s in _CELLS])
def test_card_behavior(pair_id, card, cell, summary):
    match = cell["match"]                                # list[str] | "data_unavailable" | "not_in_scope"
    obs_state, obs_cls = _observed(summary, cell.get("field"))
    if match in ("data_unavailable", "not_in_scope"):
        assert obs_state == match, (
            f"{pair_id}:{card} expected {match} but observed {obs_state} (class={obs_cls!r}). "
            f"A wrong null-flavor here is exactly the silent-death class the matrix guards.")
    else:                                                # value-set: informative / measured_negative
        assert obs_state == "value", (
            f"{pair_id}:{card} expected a real class in {match} but the card was {obs_state} "
            f"(dead reader / wrong null?).")
        assert obs_cls in match, (
            f"{pair_id}:{card} class {obs_cls!r} not in expected {match}")


def test_matrix_is_nonvacuous():
    # guard against a silently-empty run (all fixtures missing) reading as green
    frozen_pairs = [p["id"] for p in _MATRIX["pairs"] if (_FIXTURES / f"{p['id']}.yaml").exists()]
    assert frozen_pairs, "no pairs frozen — freeze.py must run (live S3) before this gate is meaningful"


# The negative CONTROLS + canonical POSITIVES are the whole point of the matrix: a ≥1-fixture floor
# let them be silently `continue`'d (never run), so a dead reader on ANY of them read green. Require
# these specific pairs to carry a fixture — a missing one FAILS (not skips), making the gap visible.
_REQUIRED_PAIRS = {
    # negative controls
    "gapdh_coadread", "or2t35_coadread",
    # canonical positives
    "dll3_sclc", "folr1_ov", "erbb2_brca", "alk_nsclc", "ceacam5_coadread",
}


def test_control_and_canonical_pairs_have_fixtures():
    declared = {p["id"] for p in _MATRIX["pairs"]}
    # the required set must actually be declared in the matrix (guards a rename drifting the floor)
    missing_from_matrix = _REQUIRED_PAIRS - declared
    assert not missing_from_matrix, (
        f"required control/canonical pairs not declared in matrix.yaml: {sorted(missing_from_matrix)}")
    missing_fixtures = sorted(
        pid for pid in _REQUIRED_PAIRS if not (_FIXTURES / f"{pid}.yaml").exists())
    assert not missing_fixtures, (
        f"required control/canonical pairs lack a frozen fixture: {missing_fixtures}. "
        f"Run freeze.py (live S3) for them — these negative controls + canonical positives MUST run "
        f"(a missing fixture would silently skip the exact silent-death guard the matrix exists for).")
