"""target_call.v1 — the unified DECISION view AND canonical OWNER of the decision spine (full-nest
2026-09-03). Verdict-inert composition that nests recommendation_gate→gate / confidence_tier→confidence /
deciding_axis / gate_scorecard (the four are no longer top-level nomination keys) + target_rollup.block;
recommendation_gate stays the sole owner of the recommendation value. Pure over synthetic inputs.
"""
from __future__ import annotations
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SKILLS = SCRIPTS.parent.parent
for _p in (str(SKILLS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tp_facets import build_target_call  # noqa: E402


def test_composes_the_four_spine_objects_and_recommendation_value():
    rg = {"fired": True, "forced_recommendation": "hold", "llm_recommendation": "hold", "overridden": False}
    ct = {"tier": "moderate"}
    da = {"basis": "gate_fired", "routing": "safety"}
    sc = {"rows": []}
    tc = build_target_call(rg, ct, da, sc, overall_recommendation={"value": "hold"})
    assert tc["schema"] == "target_call.v1"
    assert tc["recommendation"] == "hold"
    assert tc["gate"] is rg and tc["confidence"] is ct and tc["deciding_axis"] is da
    assert tc["gate_scorecard"] is sc
    assert tc["dissent"] == []                       # gate and LLM agree, no block → no dissent


def test_dissent_when_gate_overrides_llm():
    rg = {"fired": True, "forced_recommendation": "kill", "llm_recommendation": "nominate", "overridden": True}
    tc = build_target_call(rg, {"tier": None}, {"basis": "gate_fired"},
                           overall_recommendation={"value": "kill"})
    d = [x for x in tc["dissent"] if x["source"] == "llm_synthesis"]
    assert d and d[0]["resolved_to"] == "kill"
    assert tc["recommendation"] == "kill"


def test_dissent_when_block_fires_but_gate_did_not():
    rg = {"fired": False}
    rollup = {"block": {"blocked": True, "status": "hard_block",
                        "blocking_axes": [{"axis": "deliverability", "kind": "no_viable_modality"}]}}
    tc = build_target_call(rg, {"tier": None}, {"basis": "abstention"},
                           overall_recommendation={"value": "hold"}, target_rollup=rollup)
    d = [x for x in tc["dissent"] if x["source"] == "target_rollup.block"]
    assert d and d[0]["blocking_axes"][0]["axis"] == "deliverability"


def test_recommendation_accepts_scalar_or_dict():
    rg = {"fired": False}
    assert build_target_call(rg, {}, {}, overall_recommendation="nominate")["recommendation"] == "nominate"
    assert build_target_call(rg, {}, {}, overall_recommendation={"value": "hold"})["recommendation"] == "hold"
    assert build_target_call(rg, {}, {})["recommendation"] is None
