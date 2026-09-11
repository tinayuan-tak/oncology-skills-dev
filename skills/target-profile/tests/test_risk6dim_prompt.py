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


def _dims_discordant():
    d = _dims()
    d["biological"]["engine_literature_discordance"] = True
    d["biological"]["grounded_findings"] = [
        {
            "finding": "KRAS dependency does not translate to CRC drug efficacy (EGFR feedback)",
            "kind": "efficacy",
            "severity": "high",
            "cited_pmids": ["32430388", "39762482"],
        },
        {"finding": "a moderate aside", "severity": "moderate", "cited_pmids": ["1"]},
    ]
    return d


def test_risk_block_surfaces_high_severity_grounded_findings_on_discordant_dim_992():
    # #992 SURFACE-not-move: a discordant dim shows the marker + the HIGH-severity finding text + PMIDs,
    # while the BIN is unchanged (MED, not re-binned) and the synthesis is instructed to surface it.
    block = _render_risk_6dim_block(_dims_discordant())
    assert "literature-discordant" in block
    assert "does not translate to CRC drug efficacy" in block
    assert "32430388" in block and "39762482" in block
    assert "a moderate aside" not in block  # HIGH only
    assert "**biological**: `MED`" in block  # bin NOT moved
    assert "surface" in block.lower() and "crux" in block.lower()  # synthesis directive


def test_risk_block_findings_not_forced_when_not_discordant_992():
    # grounded findings present but the dim is NOT flagged discordant → not force-surfaced as a contradiction.
    d = _dims()
    d["biological"]["grounded_findings"] = [{"finding": "x", "severity": "high", "cited_pmids": ["1"]}]
    block = _render_risk_6dim_block(d)
    assert "CONTRADICTS this bin" not in block


# (test_md_recommendation_is_advisory_and_surfaces_gate_disagreement was removed with the retirement of
# tp_render_md 2026-09-03 — it asserted the md renderer's advisory-recommendation + LLM↔gate-disagreement
# wording. That advisory framing is now report_render's responsibility (contract §llm_synthesis); flagged
# to the render owner as a parity item. The FEED-side invariant — risk_6dim is fed into the prompt — is
# still guarded by the prompt tests above.)
