"""Guard: `_headline` emits the UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — the Wave-3
skill_report adoption for tractability-small-molecule (3rd GATING adopter, after safety +
functional-requirement). Pins role=gating, call==the resolved druggability verdict verbatim (no
recompute), a canonical polarity on the ordinal_view scale, and best-effort degrade (a fault → None +
_enrichment_errors, never a druggability-spine abort).
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent

tsm = load_run_py(SKILL_DIR, "tsm_run_sr")


def _cards():
    return [{"card_id": cid, "summary": {}} for cid in tsm.CARDS]


def test_headline_emits_gating_skill_report():
    hl = tsm._headline(_cards(), [], ("chemically_confirmed_genetic", "prism-crispr-confirmed-supportive"))
    sr = hl.get("skill_report")
    assert isinstance(sr, dict), f"expected a skill_report dict, got {sr!r}"
    assert sr["role"] == "gating"
    assert sr["call"] == "chemically_confirmed_genetic"  # verbatim verdict — no recompute
    assert sr["polarity"] in ("supportive", "neutral", "opposing", "insufficient", "not_applicable")
    assert sr["polarity"] != "killer"  # tractability has no veto-killer verdict
    assert sr["provenance"]["driving_rule_id"] == "prism-crispr-confirmed-supportive"
    assert "_enrichment_errors" not in hl  # happy path adds no error key
    assert "skill_report" in tsm._SYNTHESIS_FACET_KEYS


def test_negative_verdict_is_opposing_not_killer():
    """A 'no compound / intractable' call is OPPOSING (a within-axis negative), NOT a cross-target veto —
    so it must floor to opposing, never 'killer' (confirms no canonical_polarity_override was applied)."""
    hl = tsm._headline(_cards(), [], ("structurally_intractable", "structurally-intractable-opposing"))
    sr = hl["skill_report"]
    assert sr["call"] == "structurally_intractable"
    assert sr["polarity"] != "killer"


def test_skill_report_fault_degrades_not_aborts(monkeypatch):
    def _boom(*_a, **_k):
        raise ValueError("simulated skill_report fault")

    monkeypatch.setattr(tsm, "build_skill_report", _boom)
    hl = tsm._headline(_cards(), [], ("insufficient", None))
    assert hl["druggability_snapshot"] == "insufficient"  # spine survives the projection fault
    assert hl["skill_report"] is None
    assert hl["_enrichment_errors"]["skill_report"].startswith("ValueError")
