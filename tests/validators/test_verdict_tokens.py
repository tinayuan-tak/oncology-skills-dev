"""Tests for validate_verdict_tokens.py (R1-class nomination-gate ↔ resolver drift guard).

Asserts both directions:
  (a) the SHIPPED vocabularies/nomination_verdict_gate.yaml is CLEAN against the shipped
      resolvers/ (post-#366, the R1 casing already fixed), and
  (b) a synthetic gate with a MIS-CASED verdict (the exact R1 bug: TitleCase `ADC_preferred`
      vs the resolver's lowercase `adc_preferred`) is FLAGGED, along with the plain-typo,
      stale-verdict, and no-false-positive-on-advisory-axis cases.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location(
        "validate_verdict_tokens", REPO / "validators" / "validate_verdict_tokens.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["validate_verdict_tokens"] = m
    spec.loader.exec_module(m)
    return m


VT = _load()
_EMITTED = VT.emitted_verdicts_by_gate(REPO / "resolvers")


# --- (a) the shipped tree is clean ---

def test_shipped_gate_is_clean():
    report = VT.validate(REPO / "vocabularies" / "nomination_verdict_gate.yaml",
                         REPO / "resolvers")
    assert report.ok, f"shipped nomination_verdict_gate must be token-consistent: {report.errors}"
    # And it actually exercised the check (guards against a vacuous pass if parsing broke).
    assert report.checked_count > 0


def test_resolvers_expose_expected_gates():
    # Sanity: the emitted-set index really discovered the resolvers we depend on.
    for gate in ("dependency", "safety", "selectivity", "genomic_alteration",
                 "surface_modality", "tractability_small_molecule"):
        assert gate in _EMITTED and _EMITTED[gate], f"missing emitted verdicts for gate {gate}"
    # The R1 site: surface_modality emits the LOWERCASE tokens.
    assert {"adc_preferred", "tce_preferred"} <= _EMITTED["surface_modality"]


# --- (b1) the R1 casing bug is flagged ---

def test_miscased_verdict_is_flagged():
    # The exact R1 bug: TitleCase in the gate, lowercase in the resolver.
    gate_spec = {
        "positive_signals_modality_scoped": [
            {"sub_skill": "surface_modality", "verdict": "ADC_preferred",
             "weight": "dominant", "when_modality_in": ["adc"]},
        ],
    }
    report = VT.validate_verdict_tokens(gate_spec, _EMITTED)
    assert not report.ok
    assert any("UNMATCHED_VERDICT" in e and "ADC_preferred" in e for e in report.errors)
    # The message names the case-exact neighbour so the fix is obvious.
    assert any("adc_preferred" in e for e in report.errors)


# --- (b2) a plain typo is flagged ---

def test_typo_verdict_is_flagged():
    gate_spec = {
        "positive_signals": [
            {"sub_skill": "dependency", "verdict": "concordant_dependnt"},  # typo
        ],
    }
    report = VT.validate_verdict_tokens(gate_spec, _EMITTED)
    assert not report.ok
    assert any("UNMATCHED_VERDICT" in e for e in report.errors)


# --- (b3) a stale verdict (no resolver emits it) is flagged in the `gates` block too ---

def test_stale_gate_verdict_is_flagged():
    gate_spec = {
        "gates": [
            {"sub_skill": "dependency", "verdict": "pan_essential_killer", "action": "veto"},  # real
            {"sub_skill": "safety", "verdict": "retired_safety_verdict", "action": "hold"},     # stale
        ],
    }
    report = VT.validate_verdict_tokens(gate_spec, _EMITTED)
    assert not report.ok
    assert any("retired_safety_verdict" in e for e in report.errors)
    # The valid entry did not produce an error.
    assert not any("pan_essential_killer" in e for e in report.errors)


# --- no false positive: a real token passes; advisory-only axes are UNCHECKED not errored ---

def test_valid_token_passes():
    gate_spec = {
        "positive_signals": [
            {"sub_skill": "tractability_sm", "verdict": "well_covered"},  # alias → tractability_small_molecule
        ],
    }
    report = VT.validate_verdict_tokens(gate_spec, _EMITTED)
    assert report.ok, report.errors
    assert report.checked_count == 1


def test_advisory_subskill_is_unchecked_not_errored():
    gate_spec = {
        "positive_signals": [
            {"sub_skill": "expression", "verdict": "anything_goes_here_no_resolver"},
        ],
    }
    report = VT.validate_verdict_tokens(gate_spec, _EMITTED)
    assert report.ok, report.errors               # advisory axis → not an error
    assert "expression" in report.unchecked_subskills
    assert report.checked_count == 0


def test_tractability_sm_alias_resolves():
    assert VT.resolver_gate_for_subskill("tractability_sm", _EMITTED) == "tractability_small_molecule"
    assert VT.resolver_gate_for_subskill("surface_modality", _EMITTED) == "surface_modality"
    assert VT.resolver_gate_for_subskill("subtype_fit", _EMITTED) is None


# --- (b4) exclusion blocks are now enforced (fix #5, 2026-08-15) — would have caught bug #2 ---

def test_exclusion_blocks_are_enforced():
    # The two excluded_* documentation blocks are in the enforced set.
    assert "excluded_positive_modality_scoped" in VT.ENFORCED_BLOCKS
    assert "excluded_modality_scoped" in VT.ENFORCED_BLOCKS


def test_stale_excluded_positive_token_is_flagged():
    # The EXACT 2026-08-15 bug #2: the excluded_positive block carried adc_favorable/
    # tce_favorable, which surface_modality.resolver.yaml never emits (it emits
    # adc_preferred/tce_preferred). Before this fix that inert guard passed silently.
    gate_spec = {
        "excluded_positive_modality_scoped": [
            {"sub_skill": "surface_modality", "verdict": "adc_favorable"},   # stale — never emitted
            {"sub_skill": "surface_modality", "verdict": "adc_preferred"},   # real
        ],
    }
    report = VT.validate_verdict_tokens(gate_spec, _EMITTED)
    assert not report.ok
    # Exactly one error — the stale adc_favorable — phrased as an inert guard.
    assert len(report.errors) == 1, report.errors
    err = report.errors[0]
    assert "UNMATCHED_VERDICT" in err and "verdict='adc_favorable'" in err and "INERT guard" in err
    # The real token in the same block did NOT produce an error of its own.
    assert not any("verdict='adc_preferred'" in e for e in report.errors)


def test_valid_exclusion_tokens_pass():
    gate_spec = {
        "excluded_modality_scoped": [
            {"sub_skill": "surface_modality", "verdict": "neither_viable"},  # real
        ],
        "excluded_positive_modality_scoped": [
            {"sub_skill": "surface_modality", "verdict": "tce_preferred"},   # real
            {"sub_skill": "mechanism", "verdict": "well_characterized"},     # real
        ],
    }
    report = VT.validate_verdict_tokens(gate_spec, _EMITTED)
    assert report.ok, report.errors
    assert report.checked_count == 3
