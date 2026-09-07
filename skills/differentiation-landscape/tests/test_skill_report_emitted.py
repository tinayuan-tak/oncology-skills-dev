"""Guard: `_headline` emits the UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — the Wave-3
skill_report adoption for differentiation-landscape (6th GATING adopter) — AND the newly-added
question_table (component parity with the other skills). Pins role=gating, call==the resolved verdict
verbatim, a canonical polarity, a NON-EMPTY question_table carried into the skill_report, and best-effort
degrade.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent

diff = load_run_py(SKILL_DIR, "diff_run_sr")


def _cards():
    return [{"card_id": cid, "summary": {}} for cid in diff.CARDS]


def test_headline_emits_gating_skill_report():
    hl = diff._headline(_cards(), [], ("insufficient", "differentiation-insufficient"))
    sr = hl.get("skill_report")
    assert isinstance(sr, dict), f"expected a skill_report dict, got {sr!r}"
    assert sr["role"] == "gating"
    assert sr["call"] == "insufficient"  # verbatim verdict — no recompute
    assert sr["polarity"] in ("supportive", "neutral", "opposing", "insufficient", "not_applicable")
    assert sr["polarity"] != "killer"  # differentiation has no veto-killer verdict
    # differentiation NOW has a question_table (component parity) — 4 rows (COMUT/SURVIVAL/NODE + precedent)
    assert isinstance(sr["question_table"], list) and len(sr["question_table"]) == 4
    assert [r["id"] for r in sr["question_table"]] == ["Q1", "Q2", "Q3", "Q4"]
    assert sr["provenance"]["driving_rule_id"] == "differentiation-insufficient"
    assert "_enrichment_errors" not in hl
    assert "skill_report" in diff._SYNTHESIS_FACET_KEYS
    assert "question_table" in diff._SYNTHESIS_FACET_KEYS


def test_question_table_rows_are_verdict_inert_landscape_signals():
    """The added differentiation question_table INFORMS (descriptive) — it never 'supports'/'opposes'
    the nomination (a co-mutation/survival landscape is patient-selection context, not a good/bad push)."""
    hl = diff._headline(_cards(), [], ("insufficient", "r"))
    qt = hl["question_table"]
    assert all(r["signal"]["polarity"] in ("informs", "none") for r in qt)
    assert all({"id", "question", "primary", "support", "signal", "confidence"} <= set(r) for r in qt)


def test_skill_report_fault_degrades_not_aborts(monkeypatch):
    def _boom(*_a, **_k):
        raise ValueError("simulated skill_report fault")

    monkeypatch.setattr(diff, "build_skill_report", _boom)
    hl = diff._headline(_cards(), [], ("insufficient", None))
    assert hl["differentiation_verdict"] == "insufficient"  # spine survives the projection fault
    assert hl["skill_report"] is None
    assert hl["_enrichment_errors"]["skill_report"].startswith("ValueError")
