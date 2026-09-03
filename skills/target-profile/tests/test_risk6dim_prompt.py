"""ABSORB (feed-only): the deterministic 6-dim risk roll-up (target_report.risk_6dim) is fed into the
advisory synthesis prompt so executive_summary/tension_analysis NARRATE the governance-category risk —
and the md recommendation renders as advisory (the deterministic gate is the recommendation of record),
surfacing any LLM↔gate disagreement. Pure/synthetic — no Bedrock, no data.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SKILLS = SCRIPTS.parent.parent
for _p in (str(SKILLS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tp_synthesis_prompt import _render_risk_6dim_block, _build_user_prompt  # noqa: E402
from tp_render_md import _render_target_profile_md  # noqa: E402


def _dims():
    return {
        "biological": {"pillar": "Right Target", "bin": "MED", "chain": [("dependency", "discordant", "MED")]},
        "druggability": {"pillar": "Right Molecule", "bin": "LOW", "chain": [("tractability-SM", "well_covered", "LOW")]},
        "safety": {"pillar": "Right Safety", "bin": "HIGH", "chain": [("on-target-safety", "highly_constrained", "HIGH")]},
        "clinical": {"pillar": "Right Patient", "bin": "ENGINE-BLIND", "chain": []},
        "commercial": {"pillar": "Right Commercial", "bin": "LOW", "chain": [("competitor-landscape", "no_known_competitor", "LOW")]},
        "translational": {"pillar": "Right Patient", "bin": "ENGINE-BLIND", "chain": []},
    }


def test_risk_block_renders_dims_verdict_inert_and_engine_blind_honest():
    block = _render_risk_6dim_block(_dims())
    assert block is not None
    # every dim named, with its bin
    for dim in ("biological", "druggability", "safety", "clinical", "commercial", "translational"):
        assert dim in block
    assert "HIGH" in block and "MED" in block and "LOW" in block
    # verdict-inert framing + the honest engine-blind gloss (absence != low risk)
    assert "FACET, not a gate" in block
    assert "target_call" in block
    assert "engine-blind" in block and "not low risk" in block


def test_risk_block_none_and_wrapped():
    assert _render_risk_6dim_block(None) is None
    assert _render_risk_6dim_block("nope") is None
    assert _render_risk_6dim_block({"not": "dims"}) is None
    # accepts a {"dims": ...} wrapper
    assert _render_risk_6dim_block({"dims": _dims()}) is not None


def test_build_user_prompt_includes_risk_block_when_passed():
    sr = {"safety": {"verdict": ("highly_constrained_safety_concern", "r"),
                     "skill_dir": "on-target-safety-liability", "cards": [], "fired": []}}
    with_risk = _build_user_prompt("KRAS", "COADREAD", sr, risk_6dim=_dims())
    without = _build_user_prompt("KRAS", "COADREAD", sr)
    assert "6-dimension risk roll-up" in with_risk
    assert "6-dimension risk roll-up" not in without    # additive — absent when not supplied


def _min_llm_output(rec="nominate"):
    return {"executive_summary": {"value": "x"}, "tension_analysis": {"value": "y"},
            "overall_recommendation": {"value": rec}, "confidence": {"value": "moderate"},
            "top_arguments_for": {"value": []}, "top_arguments_against": {"value": []}}


def test_md_recommendation_is_advisory_and_surfaces_gate_disagreement():
    sr = {"safety": {"verdict": ("highly_constrained_safety_concern", "r"), "skill_dir": "d"}}
    # gate OVERRODE the LLM (LLM said nominate; gate forced hold)
    rg = {"fired": True, "overridden": True, "llm_recommendation": "nominate", "forced_recommendation": "hold"}
    md = _render_target_profile_md("KRAS", "COADREAD", sr, _min_llm_output("hold"), {},
                                   recommendation_gate=rg)
    assert "advisory (does not set the call)" in md
    assert "recommendation of record" in md
    assert "LLM↔gate disagreement" in md and "nominate" in md and "hold" in md
    # no disagreement line when the gate did not override
    md2 = _render_target_profile_md("KRAS", "COADREAD", sr, _min_llm_output("nominate"), {},
                                    recommendation_gate={"fired": False})
    assert "LLM↔gate disagreement" not in md2
    assert "advisory (does not set the call)" in md2
