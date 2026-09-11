"""Hermetic tests for tp_fanout._subtype_verdict — the bi-directional subtype tier (2026-08-19,
subtype-verdict-shifting review \u00a75). Pure over a synthetic `fired` list; no data / no fan-out.

Guards: NEGATIVE (opposing) -> subtype_specific_non_dependence (HOLD); POSITIVE (supportive-only) ->
subtype_restricted_dependency; BOTH -> negative precedence (HOLD wins); neither / no subtype tier -> None
(so a default no--subtypes run is unaffected).
"""

import sys
from pathlib import Path

from _test_support import load_module

_F = Path(__file__).resolve().parent.parent / "scripts" / "tp_fanout.py"
sys.path.insert(0, str(_F.parent))  # scripts/ (tp_common etc.)
mod = load_module(_F, "_tp_fanout_uc")
_subtype_verdict = mod._subtype_verdict


def _row(sig, rid="r"):
    return {"tier": "subtype", "signals": {"subtype_fit_genomic": sig}, "rule_id": rid}


def _sel_row(sig, rid="sel"):
    # tumor-tissue selectivity channel (2026-09-11, STAD subtype-shard wiring)
    return {"tier": "subtype", "signals": {"subtype_fit_selectivity": sig}, "rule_id": rid}


def test_opposing_holds():
    assert _subtype_verdict([_row("opposing", "neg")]) == ("subtype_specific_non_dependence", "neg")


def test_supportive_only_positively_supports():
    assert _subtype_verdict([_row("supportive", "pos")]) == ("subtype_restricted_dependency", "pos")


def test_negative_precedence_when_both_fire():
    # a non-dependent subtype forecloses even if another subtype is strongly dependent
    out = _subtype_verdict([_row("supportive", "pos"), _row("opposing", "neg")])
    assert out == ("subtype_specific_non_dependence", "neg")


def test_no_subtype_tier_is_none():
    # default run (no --subtypes): no subtype-tier rows -> None (byte-stable, unchanged)
    assert _subtype_verdict([{"tier": "dependency", "signals": {}}]) is None
    assert _subtype_verdict([]) is None


def test_null_signal_does_not_crash():
    assert _subtype_verdict([{"tier": "subtype", "signals": {"subtype_fit_genomic": None}}]) is None


# --- tumor-tissue selectivity rung (2026-09-11, STAD subtype-shard wiring) -------------------------


def test_selectivity_supportive_only_supports():
    # the data-blocked-dependency case (STAD/ESCA): a strong per-subtype tumor-selectivity stratum
    # with NO dependency/opposing signal -> the new tumor-tissue positive.
    assert _subtype_verdict([_sel_row("supportive", "sel1")]) == ("subtype_restricted_selectivity", "sel1")


def test_dependency_supportive_outranks_selectivity_supportive():
    # both positives fire -> the STRONGER (KO-proven) dependency verdict wins; selectivity is the
    # weaker corroborator, not reported when dependency already supports.
    out = _subtype_verdict([_sel_row("supportive", "sel"), _row("supportive", "dep")])
    assert out == ("subtype_restricted_dependency", "dep")


def test_opposing_outranks_selectivity_supportive():
    # a measured non-dependent subtype forecloses even if another subtype is strongly tumor-selective.
    out = _subtype_verdict([_sel_row("supportive", "sel"), _row("opposing", "neg")])
    assert out == ("subtype_specific_non_dependence", "neg")


def test_null_selectivity_signal_does_not_crash():
    assert _subtype_verdict([{"tier": "subtype", "signals": {"subtype_fit_selectivity": None}}]) is None
