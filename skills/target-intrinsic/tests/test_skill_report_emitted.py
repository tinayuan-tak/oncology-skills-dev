"""target-intrinsic emits the unified skill_report (Wave-3). It exposes NO _SYNTHESIS_FACET_KEYS tuple —
its self-contained _synthesis_facet dict is the fan-out carrier — so skill_report must be on the FACET
(GATELESS DESCRIPTIVE → call=None, polarity=not_scored)."""
from __future__ import annotations
import importlib.util, sys
from pathlib import Path
SKILL_DIR = Path(__file__).resolve().parent.parent
if str(SKILL_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR.parent))
def _load():
    spec = importlib.util.spec_from_file_location("ti_run_sr", SKILL_DIR / "scripts" / "run.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
ti = _load()
def _cards():
    return [{"card_id": c, "summary": {}} for c in ti.CARDS]
def test_facet_carries_descriptive_skill_report():
    facet = ti._synthesis_facet(_cards(), [])
    sr = facet.get("skill_report")
    assert isinstance(sr, dict)
    assert sr["role"] == "descriptive" and sr["polarity"] == "not_scored"
    assert sr["call"] is None
def test_headline_also_emits_skill_report():
    hl = ti._headline(_cards(), [], None)
    assert isinstance(hl.get("skill_report"), dict) and hl["skill_report"]["role"] == "descriptive"
