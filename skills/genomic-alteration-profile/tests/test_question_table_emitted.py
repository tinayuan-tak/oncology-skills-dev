"""Guard: `_build_headline` emits the per-question `question_table` (a verdict-INERT LEADING table).

genomic_question_table already existed in _skills_common but was never emitted into decision.headline;
this pins that it now is, and that a fault in that display-layer projection degrades to None + records
`_enrichment_errors` rather than aborting the multi-class genomic spine. (This skill hand-rolls main();
its headline builder is `_build_headline(cards, verdict, driving, fdr_provenance)`.)
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"

if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))


def _load():
    spec = importlib.util.spec_from_file_location("gap_run_qt", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gap = _load()


def test_headline_emits_nonempty_question_table():
    cards = [{"card_id": cid, "summary": {}} for cid in gap.CARDS]
    hl = gap._build_headline(cards, "multi_class", None, {})
    qt = hl.get("question_table")
    assert isinstance(qt, list) and len(qt) > 0, f"expected a non-empty question_table list, got {qt!r}"
    assert "_enrichment_errors" not in hl, "happy path must add no _enrichment_errors key"
    assert "question_table" in gap._SYNTHESIS_FACET_KEYS


def test_question_table_fault_degrades_not_aborts(monkeypatch):
    cards = [{"card_id": cid, "summary": {}} for cid in gap.CARDS]

    def _boom(*_a, **_k):
        raise ValueError("simulated table fault")

    monkeypatch.setattr(gap, "genomic_question_table", _boom)
    hl = gap._build_headline(cards, "multi_class", None, {})
    assert hl["genomic_alteration_profile"] == "multi_class"   # spine survives
    assert hl["question_table"] is None
    assert hl["_enrichment_errors"]["question_table"].startswith("ValueError")
