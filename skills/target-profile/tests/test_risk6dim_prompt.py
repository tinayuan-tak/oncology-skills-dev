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

from tp_synthesis_prompt import _build_user_prompt, _render_risk_6dim_block  # noqa: E402


def _dims():
    return {
        "biological": {"pillar": "Right Target", "bin": "MED", "chain": [("dependency", "discordant", "MED")]},
        "druggability": {
            "pillar": "Right Molecule",
            "bin": "LOW",
            "chain": [("tractability-SM", "well_covered", "LOW")],
        },
        "safety": {
            "pillar": "Right Safety",
            "bin": "HIGH",
            "chain": [("on-target-safety", "highly_constrained", "HIGH")],
        },
        "clinical": {"pillar": "Right Patient", "bin": "ENGINE-BLIND", "chain": []},
        "commercial": {
            "pillar": "Right Commercial",
            "bin": "LOW",
            "chain": [("competitor-landscape", "no_known_competitor", "LOW")],
        },
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
    sr = {
        "safety": {
            "verdict": ("highly_constrained_safety_concern", "r"),
            "skill_dir": "on-target-safety-liability",
            "cards": [],
            "fired": [],
        }
    }
    with_risk = _build_user_prompt("KRAS", "COADREAD", sr, risk_6dim=_dims())
    without = _build_user_prompt("KRAS", "COADREAD", sr)
    assert "6-dimension risk roll-up" in with_risk
    assert "6-dimension risk roll-up" not in without  # additive — absent when not supplied


# (test_md_recommendation_is_advisory_and_surfaces_gate_disagreement was removed with the retirement of
# tp_render_md 2026-09-03 — it asserted the md renderer's advisory-recommendation + LLM↔gate-disagreement
# wording. That advisory framing is now report_render's responsibility (contract §llm_synthesis); flagged
# to the render owner as a parity item. The FEED-side invariant — risk_6dim is fed into the prompt — is
# still guarded by the prompt tests above.)
