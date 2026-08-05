"""Dispatcher synthesize_fn routing + backward-compat.

The bug this fixes: run_wired_skill used to HARDCODE `from .synthesis import synthesize_presence`,
so a --synthesize tumor-selectivity run was narrated by the PRESENCE narrator (wrong lens). The
dispatcher now takes an optional synthesize_fn; when omitted it falls back to synthesize_presence
(so tumor-presence is unchanged). These tests pin BOTH paths + the two-slot byte-stability.
Bedrock fully mocked.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

COMMON_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON_DIR.parent))  # skills/

from _skills_common import dispatcher as D  # noqa: E402


def _run(tmp_path, *, synthesize, synthesize_fn=None):
    card_outputs = [
        {"card_id": "tumor-vs-normal-selectivity", "summary": {
            "selectivity_class": "strong_tumor_selective"}, "_missing": False},
    ]

    def _headline(cards, fired, vp):
        return {"selectivity_class": "strong_tumor_selective", "driving_rule_id": None}

    argv = ["--target", "MSLN", "--indication", "PAAD", "--out", str(tmp_path)]
    if synthesize:
        argv.append("--synthesize")

    with patch.object(D, "resolve_cards", return_value=card_outputs), \
         patch.object(D, "fired_rules", return_value=[]):
        D.run_wired_skill(
            skill_name="tumor-selectivity", skill_version="9.9.9",
            cards=["tumor-vs-normal-selectivity"], axis="intracellular_intrinsic",
            question="How selective is {target} in {indication}?",
            headline_fn=_headline, synthesize_fn=synthesize_fn, argv=argv)
    return json.loads((tmp_path / "decision.json").read_text())


def test_synthesize_fn_is_invoked_not_presence(tmp_path):
    """When a skill passes synthesize_fn, THAT narrator runs — not the presence fallback."""
    calls = {"n": 0}

    def _fake_selectivity(decision, model_id=None, subtype_query=None):
        calls["n"] += 1
        return {"selectivity_relevance_for_target": {
            "value": "strongly_supports", "_source": "llm_synthesized",
            "_model_id": "m", "_prompt_hash": "h"}}

    # If the dispatcher wrongly fell back to presence, this patch would make it explode.
    with patch("_skills_common.synthesis.synthesize_presence",
               side_effect=AssertionError("presence narrator must NOT be used when synthesize_fn is set")):
        d = _run(tmp_path / "sel", synthesize=True, synthesize_fn=_fake_selectivity)
    assert calls["n"] == 1
    assert "selectivity_relevance_for_target" in d["llm_synthesis"]


def test_no_synthesize_fn_falls_back_to_presence(tmp_path):
    """Backward-compat: a skill that passes no synthesize_fn (tumor-presence today) still narrates."""
    with patch("_skills_common.synthesis.synthesize_presence",
               return_value={"expression_relevance_for_target": {
                   "value": "supports_with_caveats", "_source": "llm_synthesized"}}) as m:
        d = _run(tmp_path / "pres", synthesize=True, synthesize_fn=None)
    assert m.called
    assert "expression_relevance_for_target" in d["llm_synthesis"]


def test_two_slot_byte_stability_with_custom_synthesizer(tmp_path):
    """--synthesize with a custom synthesize_fn adds ONLY llm_synthesis; the spine is identical."""
    def _fake(decision, model_id=None, subtype_query=None):
        return {"selectivity_relevance_for_target": {"value": "strongly_supports",
                "_source": "llm_synthesized", "_model_id": "m", "_prompt_hash": "h"}}

    base = _run(tmp_path / "a", synthesize=False)
    synth = _run(tmp_path / "b", synthesize=True, synthesize_fn=_fake)
    base.pop("generated_at", None); synth.pop("generated_at", None)
    assert "llm_synthesis" not in base
    assert "llm_synthesis" in synth
    assert {k: v for k, v in synth.items() if k != "llm_synthesis"} == base


def test_synthesize_fn_failure_degrades_to_note(tmp_path):
    def _boom(decision, model_id=None, subtype_query=None):
        raise RuntimeError("bedrock down")
    d = _run(tmp_path / "c", synthesize=True, synthesize_fn=_boom)
    assert "_synthesis_error" in d["llm_synthesis"]
    assert d["headline"]["selectivity_class"] == "strong_tumor_selective"
