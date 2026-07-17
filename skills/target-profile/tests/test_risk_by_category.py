"""Tests for _risk_by_category_from_sub_verdicts (the 6-category risk reshape).

Regression guard for the 2026-07-17 key-drift bug: the reshape fetched sub-verdicts
by short keys (`mutation`, `tractability`) that the 2026-07-14 restructure had
renamed (`genomic_alteration`, `tractability_sm`), so `_v()` silently returned
(None, None) — druggability was dead-wired to insufficient_evidence and the mutation
signal was dropped from biological. Plus: safety was hardcoded insufficient_evidence
despite the gnomAD safety sub-skill being wired.

These tests pin (a) the short keys the reshape consumes actually match SUB_SKILLS,
and (b) each wired category maps its verdict rather than falling to a placeholder.

The reshape feeds the rendered 6-category governance table, NOT the nomination gate.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


tp = _load()


def _row(rows, cat):
    return next((level, driver) for c, level, driver in rows if c == cat)


def test_short_keys_consumed_by_reshape_exist_in_sub_skills():
    """Every short key the reshape reads MUST be a real SUB_SKILLS short — this is
    the invariant whose violation caused the silent key-drift bug."""
    sub_shorts = {short for _, short in tp.SUB_SKILLS}
    # keys the reshape consumes (fetched via _v(...)):
    consumed = {"expression", "selectivity", "dependency",
                "genomic_alteration", "tractability_sm", "safety"}
    missing = consumed - sub_shorts
    assert not missing, f"reshape reads short keys not in SUB_SKILLS: {missing}"


def test_druggability_maps_from_wired_tractability():
    """Regression: druggability must NOT be dead-wired to insufficient_evidence
    when the tractability_sm sub-verdict is present."""
    sr = {"tractability_sm": {"verdict": ("well_covered", "r")}}
    level, _ = _row(tp._risk_by_category_from_sub_verdicts(sr), "druggability")
    assert level == "LOW"


def test_biological_includes_mutation_signal():
    """Regression: the genomic_alteration (mutation) verdict must reach _biological()."""
    sr = {"genomic_alteration": {"verdict": ("biomarker_stratified_dependency", "r")}}
    level, _ = _row(tp._risk_by_category_from_sub_verdicts(sr), "biological")
    assert level == "LOW"


def test_safety_maps_from_wired_gnomad_verdict():
    """Regression: safety must map its wired verdict, not hardcode insufficient."""
    rows_hi = tp._risk_by_category_from_sub_verdicts(
        {"safety": {"verdict": ("highly_constrained_safety_concern", "r")}})
    assert _row(rows_hi, "safety")[0] == "HIGH"
    rows_lo = tp._risk_by_category_from_sub_verdicts(
        {"safety": {"verdict": ("tolerant_reduced_safety_risk", "r")}})
    assert _row(rows_lo, "safety")[0] == "LOW"


def test_absent_verdicts_still_insufficient():
    """Honest coverage: categories with no sub-verdict return insufficient_evidence
    (not a fabricated MEDIUM)."""
    rows = tp._risk_by_category_from_sub_verdicts({})
    for cat in ("biological", "druggability", "safety"):
        assert _row(rows, cat)[0] == "insufficient_evidence"


def test_unwired_categories_remain_placeholders():
    """translational / clinical / commercial have no wired source — stay insufficient."""
    rows = tp._risk_by_category_from_sub_verdicts(
        {"safety": {"verdict": ("highly_constrained_safety_concern", "r")}})
    for cat in ("translational", "clinical", "commercial"):
        assert _row(rows, cat)[0] == "insufficient_evidence"
