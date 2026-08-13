"""Type-contract tests for the shared composition spine (_skills_common/compose_core.py).

Stage 1 of the target-profile / compose-dashboard convergence. These tests pin the
SHAPE that both engines depend on:
  - GateVerdict.as_dict() key ORDER (the evidence_package on-disk golden pins it), and
  - CompositionResult's primary/additional accessors reproducing the legacy block dicts.

The full resolver INTEGRATION (fired_rules -> resolve_verdict_for_gate producing the right
verdict/driving_rule for real card states) is already pinned byte-for-byte by
compose-dashboard's tests/test_engine_equivalence.py + tests/test_end_to_end.py, which now
run THROUGH resolve_gate_spine. This file guards the type contract Stage 1b (target-profile)
will build against, and stays offline / resolver-free.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # .../skills
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.compose_core import (  # noqa: E402
    CompositionResult,
    GateVerdict,
    resolve_gate_spine,
    subskill_composition,
)


def test_gate_verdict_as_dict_shape_and_key_order():
    """as_dict() must reproduce the legacy _block shape EXACTLY — same keys, same order.

    The evidence_package.json is written with json.dump(indent=2) (no sort_keys), so key
    ORDER is observable on disk; the byte-identity golden would catch a reorder here.
    """
    gv = GateVerdict(
        gate="dependency",
        verdict="selective_dependency",
        driving_rule_id="dep-selective-01",
        fired_rule_ids=["dep-selective-01", "dep-expressed-02"],
    )
    d = gv.as_dict()
    assert list(d.keys()) == ["gate", "verdict", "driving_rule_id", "fired_rule_ids"]
    assert d == {
        "gate": "dependency",
        "verdict": "selective_dependency",
        "driving_rule_id": "dep-selective-01",
        "fired_rule_ids": ["dep-selective-01", "dep-expressed-02"],
    }


def test_gate_verdict_allows_none_driving_rule():
    """driving_rule_id is legitimately None for some resolver outcomes."""
    gv = GateVerdict(gate="selectivity", verdict="not_selective",
                     driving_rule_id=None, fired_rule_ids=[])
    assert gv.as_dict()["driving_rule_id"] is None


def test_composition_result_accessors_with_primary_and_additional():
    primary = GateVerdict("tractability_small_molecule", "well_covered", "sm-01", ["sm-01"])
    extra = [
        GateVerdict("dependency", "selective_dependency", "dep-01", ["sm-01"]),
        GateVerdict("selectivity", "tumor_selective", "sel-01", ["sm-01"]),
    ]
    res = CompositionResult(
        card_outputs=[{"card_id": "x"}],
        fired_rule_ids=["sm-01"],
        primary_gate_verdict=primary,
        additional_gate_verdicts=extra,
    )
    assert res.primary_dict() == primary.as_dict()
    assert res.additional_dicts() == [g.as_dict() for g in extra]
    # additional order preserved
    assert [g["gate"] for g in res.additional_dicts()] == ["dependency", "selectivity"]


def test_composition_result_none_primary():
    """primary_dict() is None when the axis had no mapped/resolvable headline gate —
    the graceful-degradation seam the caller falls back on."""
    res = CompositionResult(
        card_outputs=[],
        fired_rule_ids=[],
        primary_gate_verdict=None,
        additional_gate_verdicts=[],
    )
    assert res.primary_dict() is None
    assert res.additional_dicts() == []


def test_resolve_gate_spine_no_headline_gate_is_empty_and_resolver_free():
    """headline_gate=None (axis with no gate mapping) yields an empty result WITHOUT
    touching the resolver — no contracts_root needed, no gate resolution attempted."""
    res = resolve_gate_spine(
        [],
        headline_gate=None,
        additional_gates=None,
        rules=[],
        contracts_root=None,  # never consulted on this path
    )
    assert isinstance(res, CompositionResult)
    assert res.primary_gate_verdict is None
    assert res.additional_gate_verdicts == []
    assert res.fired_rule_ids == []


# ---------------------------------------------------------------------------
# subskill_composition — target-profile's Stage-1b carrier: wrap an ALREADY-decided
# verdict WITHOUT re-resolving (preserving each sub-skill's post-resolver logic).
# ---------------------------------------------------------------------------


def test_subskill_composition_gated_wraps_verdict_pair():
    """A gated sub-skill's (verdict, driving_rule_id) pair becomes the primary GateVerdict.
    fired_rule_ids follow compose_core's sorted-set convention (deduped + sorted)."""
    fired = [{"rule_id": "r-b"}, {"rule_id": "r-a"}, {"rule_id": "r-b"}]  # unsorted + dup
    comp = subskill_composition(
        card_outputs=[{"card_id": "c1"}],
        fired=fired,
        gate="dependency",
        verdict_pair=("selective_dependency", "dep-01"),
    )
    assert isinstance(comp, CompositionResult)
    assert comp.fired_rule_ids == ["r-a", "r-b"]  # sorted + deduped
    assert comp.primary_gate_verdict == GateVerdict(
        gate="dependency",
        verdict="selective_dependency",
        driving_rule_id="dep-01",
        fired_rule_ids=["r-a", "r-b"],
    )
    assert comp.additional_gate_verdicts == []
    # the pair round-trips through the typed carrier
    assert comp.primary_dict()["verdict"] == "selective_dependency"
    assert comp.primary_dict()["driving_rule_id"] == "dep-01"


def test_subskill_composition_gateless_has_no_primary():
    """A verdict-inert sub-skill with no resolver gate (e.g. tumor-presence `expression`) →
    empty primary; its presence verdict stays in the caller's own `verdict` field, not here."""
    comp = subskill_composition(
        card_outputs=[{"card_id": "c1"}],
        fired=[{"rule_id": "r-a"}],
        gate=None,
        verdict_pair=("tumor_broadly_expressed", "expr-01"),
    )
    assert comp.primary_gate_verdict is None
    assert comp.fired_rule_ids == ["r-a"]  # audit trail still carried


def test_subskill_composition_no_verdict_fn():
    """verdict_pair=None (sub-skill exposes no verdict function) → empty primary."""
    comp = subskill_composition(
        card_outputs=[], fired=[], gate="dependency", verdict_pair=None,
    )
    assert comp.primary_gate_verdict is None
    assert comp.fired_rule_ids == []


def test_subskill_composition_does_not_reresolve():
    """subskill_composition must NOT consult a resolver — it wraps the FINAL pair verbatim, so a
    sub-skill's post-resolver vetoes/downgrades survive. (contracts_root is never needed.)"""
    comp = subskill_composition(
        card_outputs=[{"card_id": "c1"}],
        fired=[{"rule_id": "r-a"}],
        gate="selectivity",
        # a value NO resolver would emit — proves the pair is passed through untouched
        verdict_pair=("POST_PROCESSED_SENTINEL", "veto-01"),
    )
    assert comp.primary_gate_verdict.verdict == "POST_PROCESSED_SENTINEL"
    assert comp.primary_gate_verdict.driving_rule_id == "veto-01"
