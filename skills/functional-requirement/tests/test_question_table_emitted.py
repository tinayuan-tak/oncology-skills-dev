"""Guard: `_headline` emits the per-question `question_table` (a verdict-INERT LEADING table).

The dependency_question_table function already existed in _skills_common but was never emitted into
decision.headline; this pins that it now is, and that a fault in that display-layer projection degrades
to None + records `_enrichment_errors` rather than aborting the dependency spine.
"""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent

fr = load_run_py(SKILL_DIR, "fr_run_qt")


def test_headline_emits_nonempty_question_table():
    cards = [{"card_id": cid, "summary": {}} for cid in fr.CARDS]
    hl = fr._headline(cards, [], ("insufficient", None))
    qt = hl.get("question_table")
    assert isinstance(qt, list) and len(qt) > 0, f"expected a non-empty question_table list, got {qt!r}"
    assert "_enrichment_errors" not in hl, "happy path must add no _enrichment_errors key"
    assert "question_table" in fr._SYNTHESIS_FACET_KEYS


def test_question_table_fault_degrades_not_aborts(monkeypatch):
    cards = [{"card_id": cid, "summary": {}} for cid in fr.CARDS]

    def _boom(*_a, **_k):
        raise ValueError("simulated table fault")

    monkeypatch.setattr(fr, "dependency_question_table", _boom)
    hl = fr._headline(cards, [], ("insufficient", None))
    assert hl["dependency_verdict"] == "insufficient"      # spine survives
    assert hl["question_table"] is None
    assert hl["_enrichment_errors"]["question_table"].startswith("ValueError")
