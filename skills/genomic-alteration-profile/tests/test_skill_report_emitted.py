"""Guard: `_build_headline` emits the UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — the
Wave-3 skill_report adoption for genomic-alteration-profile (5th GATING adopter). Pins role=gating,
call==the RECONCILED emitted verdict (genomic reconciles its one-word verdict; skill_report must inherit
the reconciled word, not the raw ladder), a canonical polarity, and best-effort degrade.
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
    spec = importlib.util.spec_from_file_location("ga_run_sr", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = _load()


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
