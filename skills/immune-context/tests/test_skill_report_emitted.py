"""immune-context emits the unified skill_report (Wave-3, DESCRIPTIVE role → polarity=not_scored)."""
from __future__ import annotations
from pathlib import Path

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent
ic = load_run_py(SKILL_DIR, "ic_run_sr")
def _cards():
    return [{"card_id": c, "summary": {}} for c in ic.CARDS]
def test_immune_emits_descriptive_skill_report():
    hl = ic._headline(_cards(), [], ("immune_hot", "r"))
    sr = hl.get("skill_report")
    assert isinstance(sr, dict)
    assert sr["role"] == "descriptive" and sr["polarity"] == "not_scored"
    assert sr["call"] == hl.get("immune_context_verdict")
    assert "skill_report" in ic._SYNTHESIS_FACET_KEYS
