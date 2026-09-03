"""tumor-presence emits the unified skill_report (Wave-3, DESCRIPTIVE-role reference impl):
role=descriptive → polarity=not_scored, excluded from gate math; call = the reconciled presence_verdict.
"""
from __future__ import annotations
import importlib.util, sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
if str(SKILL_DIR.parent) not in sys.path:
    sys.path.insert(0, str(SKILL_DIR.parent))


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_sr", SKILL_DIR / "scripts" / "run.py")
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


tp = _load()


def _cards():
    return [{"card_id": c, "summary": {}} for c in tp.CARDS]


def test_presence_emits_descriptive_skill_report():
    hl = tp._headline(_cards(), [], ("broadly_high_expression", "r"))
    sr = hl.get("skill_report")
    assert isinstance(sr, dict)
    assert sr["role"] == "descriptive"
    assert sr["polarity"] == "not_scored"                 # descriptive is never scored
    assert sr["call"] == hl.get("presence_verdict")       # reconciled verdict verbatim
    assert isinstance(sr["question_table"], list)         # presence has a question_table
    assert "skill_report" in tp._SYNTHESIS_FACET_KEYS


def test_skill_report_fault_degrades_not_aborts(monkeypatch):
    monkeypatch.setattr(tp, "build_skill_report", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    hl = tp._headline(_cards(), [], ("insufficient", None))
    assert hl["skill_report"] is None
    assert hl["_enrichment_errors"]["skill_report"].startswith("ValueError")
