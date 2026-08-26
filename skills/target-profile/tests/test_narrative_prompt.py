"""Tier-3 synthesis prompt — per-verdict narrative block + citation instruction.

Asserts _render_narrative_block emits the movers/dissenters/flip anchors, that _build_user_prompt
includes it, and that the tool schema requests inline [rule_id]/[card_id] citations while keeping
`citations` OPTIONAL (so the deterministic skip-stub / salvage path is unaffected).
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SKILLS = Path(__file__).resolve().parents[2]   # .../skills — for `_skills_common`
for _p in (str(SKILLS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tp_synthesis_prompt as tp  # noqa: E402

_NBA = {"safety": {
    "verdict": "highly_constrained_safety_concern",
    "driving_rule_id": "highly-constrained-safety-warning",
    "movers": [{"rule_id": "highly-constrained-safety-warning", "card_id": "gnomad-lof-constraint",
                "role": "driver"}],
    "dissenters": [
        {"rule_id": "clingen-recessive-only-safety-reassurance", "channel": "small_molecule",
         "sentence": "Recessive-only reassurance."},
        {"rule_id": "clingen-recessive-only-safety-reassurance", "channel": "degrader",
         "sentence": "Recessive-only reassurance."}],
    "flip_conditions": [{"rule_id": "highly-constrained-safety-warning", "present": True,
                         "to_verdict": "insufficient", "recommendation_flip": True}],
    "gaps": [{"kind": "strengthen", "availability": "insufficient", "missing_cards": []}]}}


def test_narrative_block_renders_anchors_and_dissent():
    blk = "\n".join(tp._render_narrative_block(_NBA))
    assert "Per-verdict narrative" in blk
    assert "[highly-constrained-safety-warning]" in blk           # driver anchor
    assert "DESPITE (dissent on small_molecule, degrader)" in blk  # deduped channels
    assert "crosses GO/NO-GO" in blk                              # recommendation flip flag
    assert "GAP (strengthen" in blk


def test_empty_narrative_renders_nothing():
    assert tp._render_narrative_block(None) == []
    assert tp._render_narrative_block({}) == []


def test_user_prompt_includes_narrative_block():
    sr = {"safety": {"skill_dir": "safety", "fired": [],
                     "verdict": ("highly_constrained_safety_concern", "highly-constrained-safety-warning"),
                     "cards": []}}
    up = tp._build_user_prompt("BRAF", "COADREAD", sr, narrative_by_axis=_NBA)
    assert "Per-verdict narrative" in up and "CITE" in up


def test_tool_schema_requests_citations_but_keeps_them_optional():
    tool = tp._build_synthesis_tool()
    props, req = tool["properties"], tool["required"]
    assert "citations" in props and "citations" not in req      # optional — skip-stub safe
    assert "[rule_id]" in props["executive_summary"]["description"]
    assert "[brackets]" in props["tension_analysis"]["description"]
    # the audit-critical enums are unchanged
    assert props["overall_recommendation"]["enum"] == ["nominate", "hold", "veto", "insufficient_evidence"]
