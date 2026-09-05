"""Guard: `_headline` emits the UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — the Wave-3
skill_report adoption for functional-requirement (the 2nd GATING adopter after the on-target-safety
pilot). Pins role=gating, call==the resolved verdict verbatim (no recompute), a canonical polarity on the
ordinal_view scale, and best-effort degrade (a fault → None + _enrichment_errors, never a spine abort).
"""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent

fr = load_run_py(SKILL_DIR, "fr_run_sr")


def _cards():
    return [{"card_id": cid, "summary": {}} for cid in fr.CARDS]


def test_headline_emits_gating_skill_report():
    hl = fr._headline(_cards(), [], ("lineage_selective", "dep-lineage-selective-supportive"))
    sr = hl.get("skill_report")
    assert isinstance(sr, dict), f"expected a skill_report dict, got {sr!r}"
    assert sr["role"] == "gating"
    assert sr["call"] == "lineage_selective"                 # verbatim verdict — no recompute
    # canonical polarity on the ordinal_view scale (dependency has no veto-killer, so never 'killer')
    assert sr["polarity"] in ("supportive", "neutral", "opposing", "insufficient", "not_applicable")
    assert sr["polarity"] != "killer"
    assert sr["provenance"]["driving_rule_id"] == "dep-lineage-selective-supportive"
    assert "_enrichment_errors" not in hl                    # happy path adds no error key
    assert "skill_report" in fr._SYNTHESIS_FACET_KEYS


def test_pan_essential_killer_verdict_is_not_killer_polarity():
    """pan_essential_killer is deliberately NEUTRAL (a broad-tox liability routed to safety, NOT a
    dependency veto), so the skill_report polarity must not read as 'killer' — confirms the safety
    template's negative→opposing floor with NO canonical_polarity_override is the right call for FR."""
    hl = fr._headline(_cards(), [], ("pan_essential_killer", "pan-essential-killer-liability"))
    sr = hl["skill_report"]
    assert sr["call"] == "pan_essential_killer"
    assert sr["polarity"] != "killer"


def test_skill_report_fault_degrades_not_aborts(monkeypatch):
    def _boom(*_a, **_k):
        raise ValueError("simulated skill_report fault")

    monkeypatch.setattr(fr, "build_skill_report", _boom)
    hl = fr._headline(_cards(), [], ("insufficient", None))
    assert hl["dependency_verdict"] == "insufficient"        # spine survives the projection fault
    assert hl["skill_report"] is None
    assert hl["_enrichment_errors"]["skill_report"].startswith("ValueError")
