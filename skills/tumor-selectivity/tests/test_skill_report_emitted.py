"""Guard: `_headline` emits the UNIFIED skill_report (docs/UNIFIED_OUTPUT_CONTRACT.md) — the Wave-3
skill_report adoption for tumor-selectivity (7th GATING adopter, and the FIRST with a killer-verdict
override). The two normal-breadth / stromal-confound VETO outcomes must surface as canonical
`killer` (not the 3-band→canonical `opposing` floor); a positive call maps to `supportive`; best-effort
degrade preserves the selectivity spine.
"""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

sel = load_run_py(Path(__file__).resolve().parent.parent, "sel_run_sr")


def _cards():
    return [{"card_id": cid, "summary": {}} for cid in sel.CARDS]


def _sr(verdict, rule="r"):
    hl = sel._headline(_cards(), [], (verdict, rule))
    return hl, hl.get("skill_report")


def test_broadly_normal_veto_is_canonical_killer():
    """The broadly-normal KILL (no therapeutic window) must read as canonical `killer`, NOT `opposing` —
    the override preserves the veto distinction the 3-band headline polarity would floor away."""
    hl, sr = _sr("selective_but_broadly_normal", "selectivity-broadly-normal-veto")
    assert isinstance(sr, dict)
    assert sr["role"] == "gating"
    assert sr["call"] == "selective_but_broadly_normal"
    assert sr["polarity"] == "killer"                    # NOT "opposing"


def test_stromal_confound_veto_is_canonical_killer():
    _hl, sr = _sr("selective_but_stromal_confound", "selectivity-stromal-confound-veto")
    assert sr["polarity"] == "killer"


def test_positive_maps_to_supportive_no_override():
    _hl, sr = _sr("strong_tumor_selective", "selectivity-strong-supportive")
    assert sr["call"] == "strong_tumor_selective"
    assert sr["polarity"] == "supportive"                # positive → supportive (no killer override)


def test_not_selective_is_opposing_not_killer():
    """A measured `not_selective` is a plain within-axis negative (opposing), NOT a veto (killer)."""
    _hl, sr = _sr("not_selective", "selectivity-not-selective")
    assert sr["polarity"] == "opposing"


def test_skill_report_fault_degrades_not_aborts(monkeypatch):
    def _boom(*_a, **_k):
        raise ValueError("simulated skill_report fault")

    monkeypatch.setattr(sel, "build_skill_report", _boom)
    hl = sel._headline(_cards(), [], ("insufficient", None))
    assert hl["selectivity_class"] == "insufficient"     # spine survives the projection fault
    assert hl["skill_report"] is None
    assert hl["_enrichment_errors"]["skill_report"].startswith("ValueError")
    assert "skill_report" in sel._SYNTHESIS_FACET_KEYS
