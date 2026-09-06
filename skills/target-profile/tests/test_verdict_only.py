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

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run_vo")


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


# (test_render_md_with_skipped_stub_is_wellformed was removed with the retirement of tp_render_md
# 2026-09-03 — it asserted the md renderer degrades to a "synthesis skipped" note in verdict-only mode.
# report_render renders the skipped stub now; the MODE itself (_skipped_synthesis_output) is still
# guarded by the stub tests above.)


def test_synthesize_or_degrade_fail_closed_on_bedrock_error(monkeypatch):
    """FAIL-CLOSED: a raised Bedrock/import/tool error must NOT propagate out of the synthesis
    wrapper (which would crash main() before the nomination/evidence-package is written). It
    degrades to the --no-synthesis stub tagged _synthesis_error, so the deterministic spine below
    is still emitted. Regression for the unwrapped synthesize_structured call at run.py."""
    class _BedrockDown(RuntimeError):
        pass

    def _boom(*a, **k):
        raise _BedrockDown("no bedrock creds / model didn't use the tool")

    monkeypatch.setattr(tp, "synthesize_structured", _boom)
    out = tp._synthesize_or_degrade("sys", "user", {"type": "object"})  # must NOT raise
    # Degrades to the known-good stub shape the gate-clamp + renderers rely on...
    assert out["_synthesis_skipped"] is True
    assert isinstance(out["overall_recommendation"], dict) and "value" in out["overall_recommendation"]
    assert isinstance(out["confidence"], dict) and "value" in out["confidence"]
    # ...tagged as the ERROR path (not a clean skip) so main()'s guard skips anchor-validation and
    # the renderers show a "synthesis unavailable" note. The message preserves the exception type.
    assert "_synthesis_error" in out and "_BedrockDown" in out["_synthesis_error"]


def test_gate_clamps_into_degraded_error_stub():
    """The deterministic recommendation gate clamps a forced recommendation INTO the degraded
    error stub exactly as for a real synthesis — so a Bedrock outage still yields the auditable
    forced verdict rather than losing the whole run."""
    stub = tp._skipped_synthesis_output()
    stub["_synthesis_error"] = "BedrockAuthError: expired SSO"
    gate_action, _hits, _sup = tp._gate_recommendation(
        _sub("dependency", "pan_essential_killer", "pan-essential-killer"))
    assert gate_action == "veto"
    stub["overall_recommendation"]["value"] = gate_action
    assert stub["overall_recommendation"]["value"] == "veto"
