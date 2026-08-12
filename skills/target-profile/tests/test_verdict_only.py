"""Tests for --verdict-only / --no-synthesis in target-profile/run.py.

--verdict-only skips the Tier-3 Bedrock synthesis + figures; the deterministic verdict spine
(sub-verdicts, recommendation gate, positive tier, deciding axis, scorecard, facets) is computed
independently of the LLM and MUST stay byte-identical to a full run. These tests exercise the pure
helpers (no Bedrock, no S3):
  1. the skipped-synthesis stub carries the shape the gate-clamp + renderers rely on;
  2. the deterministic gate clamps a forced recommendation INTO that stub exactly as main() does;
  3. the markdown renderer produces a well-formed, self-explanatory report from the stub (the LLM
     narrative degrades to the "synthesis skipped" note; the deterministic sections remain).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_vo", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()


def _fired(*sm):
    return [{"rule_id": f"r{i}", "card_id": "c", "field": "f", "value": "v", "signals": s}
            for i, s in enumerate(sm)]


def _sr():
    return {
        "dependency": {"skill_dir": "functional-requirement",
                       "cards": [{"card_id": "crispr", "summary": {}}],
                       "verdict": ("lineage_selective", "x"),
                       "fired": _fired({"small_molecule": "opposing", "degrader": "supportive"})},
        "safety": {"skill_dir": "on-target-safety-liability",
                   "cards": [{"card_id": "g", "summary": {}}],
                   "verdict": ("highly_constrained_safety_concern", "y"),
                   "fired": _fired({"small_molecule": "opposing"})},
    }


def _sub(short, verdict, rule="some-rule"):
    return {short: {"verdict": (verdict, rule) if verdict else None}}


def test_skipped_synthesis_output_contract():
    out = tp._skipped_synthesis_output()
    assert out["_synthesis_skipped"] is True
    # The gate clamps into these (main(): rec["value"] = gate_action) — mutable dicts with "value".
    assert isinstance(out["overall_recommendation"], dict) and "value" in out["overall_recommendation"]
    assert isinstance(out["confidence"], dict) and "value" in out["confidence"]
    # Renderers read executive_summary.value — must be a non-empty, self-explanatory note (not blank).
    note = out["executive_summary"]["value"]
    assert note.strip() and "verdict-only" in note.lower()
    # Distinct from the degraded-synthesis error path (so metric_legend + provenance hashes branch right).
    assert "_synthesis_error" not in out


def test_gate_clamps_into_skipped_stub_like_a_real_synthesis():
    """A killer forces overall_recommendation INTO the stub, exactly as main() clamps a real
    synthesis dict — so --verdict-only still yields the deterministic forced recommendation."""
    stub = tp._skipped_synthesis_output()
    gate_action, hits, _sup = tp._gate_recommendation(
        _sub("dependency", "pan_essential_killer", "pan-essential-killer"))
    assert gate_action == "veto"
    rec = stub["overall_recommendation"]          # main(): rec = llm_output.get("overall_recommendation")
    rec["value"] = gate_action                    # main(): rec["value"] = gate_action
    rec["_gated"] = True
    assert stub["overall_recommendation"]["value"] == "veto"


def test_render_md_with_skipped_stub_is_wellformed():
    """The markdown report renders from the skipped stub without a real synthesis: the narrative
    degrades to the skip note, and the render does not raise."""
    stub = tp._skipped_synthesis_output()
    sr = _sr()
    da = tp._deciding_axis(sr, None, [], positive_hits=[])
    mx = tp._ordinal_matrix(sr)
    md = tp._render_target_profile_md("KRAS", "COADREAD", sr, stub, {},
                                      deciding_axis=da, ordinal_matrix=mx)
    assert isinstance(md, str) and md
    assert "synthesis skipped" in md.lower()   # the reader sees WHY the narrative is absent
