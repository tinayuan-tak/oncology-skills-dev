"""Guard: `_build_headline` emits the per-question `question_table` (a verdict-INERT LEADING table).

genomic_question_table already existed in _skills_common but was never emitted into decision.headline;
this pins that it now is, and that a fault in that display-layer projection degrades to None + records
`_enrichment_errors` rather than aborting the multi-class genomic spine. (This skill hand-rolls main();
its headline builder is `_build_headline(cards, verdict, driving, fdr_provenance)`.)
"""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent

gap = load_run_py(SKILL_DIR, "gap_run_qt")


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
