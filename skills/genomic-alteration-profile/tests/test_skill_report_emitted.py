"""Guard: `_build_headline` emits the UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — the
Wave-3 skill_report adoption for genomic-alteration-profile (5th GATING adopter). Pins role=gating,
call==the RECONCILED emitted verdict (genomic reconciles its one-word verdict; skill_report must inherit
the reconciled word, not the raw ladder), a canonical polarity, and best-effort degrade.
"""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent

gen = load_run_py(SKILL_DIR, "ga_run_sr")


def _cards():
    return [{"card_id": cid, "summary": {}} for cid in gen.CARDS]


def test_build_headline_emits_gating_skill_report_with_reconciled_call():
    hl = gen._build_headline(_cards(), "recurrent_driver", "genomic-recurrent-driver", {}, fired=[])
    sr = hl.get("skill_report")
    assert isinstance(sr, dict), f"expected a skill_report dict, got {sr!r}"
    assert sr["role"] == "gating"
    # call must equal the EMITTED (reconciled) verdict, not necessarily the raw input
    assert sr["call"] == hl["genomic_alteration_profile"]
    assert sr["polarity"] in ("supportive", "neutral", "opposing", "insufficient", "not_applicable")
    assert sr["polarity"] != "killer"                            # genomic has no veto-killer verdict
    assert isinstance(sr["question_table"], list)                # genomic HAS a question_table
    assert sr["provenance"]["driving_rule_id"] == "genomic-recurrent-driver"
    assert "skill_report" in gen._SYNTHESIS_FACET_KEYS


def test_skill_report_fault_degrades_not_aborts(monkeypatch):
    def _boom(*_a, **_k):
        raise ValueError("simulated skill_report fault")

    monkeypatch.setattr(gen, "build_skill_report", _boom)
    hl = gen._build_headline(_cards(), "insufficient", None, {}, fired=[])
    assert isinstance(hl.get("genomic_alteration_profile"), str)   # spine intact despite the fault
    assert hl["skill_report"] is None
    assert hl["_enrichment_errors"]["skill_report"].startswith("ValueError")
