"""Guard: `_headline` emits the UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — the Wave-3
skill_report adoption for mechanism-and-pharmacology (4th GATING adopter, after safety +
functional-requirement + tractability-small-molecule). Pins role=gating, call==the resolved verdict
verbatim, a canonical polarity, an EMPTY question_table (this skill has none), and best-effort degrade.
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
    spec = importlib.util.spec_from_file_location("mech_run_sr", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mech = _load()


def _cards():
    return [{"card_id": cid, "summary": {}} for cid in mech.CARDS]


def test_headline_emits_gating_skill_report():
    hl = mech._headline(_cards(), [], ("well_characterized", "mechanism-well-characterized"))
    sr = hl.get("skill_report")
    assert isinstance(sr, dict), f"expected a skill_report dict, got {sr!r}"
    assert sr["role"] == "gating"
    assert sr["call"] == "well_characterized"                    # verbatim verdict — no recompute
    assert sr["polarity"] in ("supportive", "neutral", "opposing", "insufficient", "not_applicable")
    assert sr["polarity"] != "killer"                            # mechanism has no veto-killer verdict
    assert sr["question_table"] == []                            # mechanism has no question_table
    assert sr["provenance"]["driving_rule_id"] == "mechanism-well-characterized"
    assert "_enrichment_errors" not in hl
    assert "skill_report" in mech._SYNTHESIS_FACET_KEYS


def test_skill_report_fault_degrades_not_aborts(monkeypatch):
    def _boom(*_a, **_k):
        raise ValueError("simulated skill_report fault")

    monkeypatch.setattr(mech, "build_skill_report", _boom)
    hl = mech._headline(_cards(), [], ("insufficient", None))
    assert hl["mechanism_verdict"] == "insufficient"             # spine survives the projection fault
    assert hl["skill_report"] is None
    assert hl["_enrichment_errors"]["skill_report"].startswith("ValueError")
