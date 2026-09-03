"""immune-context emits the unified skill_report (Wave-3, DESCRIPTIVE role → polarity=not_scored)."""
from __future__ import annotations
import importlib.util, sys
from pathlib import Path
SKILL_DIR = Path(__file__).resolve().parent.parent
if str(SKILL_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR.parent))
def _load():
    spec = importlib.util.spec_from_file_location("ic_run_sr", SKILL_DIR / "scripts" / "run.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
ic = _load()
def _cards():
    return [{"card_id": c, "summary": {}} for c in ic.CARDS]
def test_immune_emits_descriptive_skill_report():
    hl = ic._headline(_cards(), [], ("immune_hot", "r"))
    sr = hl.get("skill_report")
    assert isinstance(sr, dict)
    assert sr["role"] == "descriptive" and sr["polarity"] == "not_scored"
    assert sr["call"] == hl.get("immune_context_verdict")
    assert "skill_report" in ic._SYNTHESIS_FACET_KEYS
