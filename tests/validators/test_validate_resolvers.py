"""Tests for validate_resolvers.py (gap #5 static resolver validator).

Asserts both directions: the shipped dependency.resolver.yaml is clean, AND each failure
mode (dangling rung, bad driving_rule, missing default, structural) is caught — so a
typo'd/renamed rule_id in a rung fails CI (the silent-drift class an if-chain can't catch).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("validate_resolvers", REPO / "validators" / "validate_resolvers.py")
    m = importlib.util.module_from_spec(spec)
    sys.modules["validate_resolvers"] = m
    spec.loader.exec_module(m)
    return m


VR = _load()
_KNOWN = VR._all_rule_ids(REPO / "interpretation-rules")


def _write(tmp_path, spec: dict) -> Path:
    p = tmp_path / "x.resolver.yaml"
    p.write_text(yaml.safe_dump(spec))
    return p


def _base(**over) -> dict:
    spec = {
        "gate": "dependency",
        "version": "1.0.0",
        "resolve": [{"verdict": "non_dependent", "when_fired": "non-dependent-killer"}],
        "default": "insufficient",
    }
    spec.update(over)
    return spec


# --- the shipped spec is clean ---


def test_shipped_dependency_resolver_is_clean():
    r = VR.validate_resolver_file(REPO / "resolvers" / "dependency.resolver.yaml", _KNOWN)
    assert r.ok, f"shipped dependency resolver must validate: {r.errors}"


# --- dangling rung (typo / renamed rule) is caught ---


def test_dangling_rung_rule_id_fails(tmp_path):
    spec = _base(resolve=[{"verdict": "foo", "when_fired": "this-rule-does-not-exist"}])
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN)
    assert not r.ok
    assert any("DANGLING_RUNG" in e for e in r.errors)


def test_dangling_in_when_all_fired_caught(tmp_path):
    spec = _base(resolve=[{"verdict": "foo", "when_all_fired": ["non-dependent-killer", "nope-not-real"]}])
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN)
    assert not r.ok and any("DANGLING_RUNG" in e for e in r.errors)


# --- bad driving_rule (not one of the rung's own rules) is caught ---


def test_bad_driving_rule_fails(tmp_path):
    spec = _base(
        resolve=[
            {
                "verdict": "foo",
                "when_all_fired": ["non-dependent-killer", "strong-paralog-buffering-degrader-preferred"],
                "driving_rule": "lineage-selective-supportive",
            }
        ]
    )  # not in the rung
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN)
    assert not r.ok and any("BAD_DRIVING_RULE" in e for e in r.errors)


def test_valid_driving_rule_passes(tmp_path):
    spec = _base(
        resolve=[
            {
                "verdict": "foo",
                "when_all_fired": ["non-dependent-killer", "strong-paralog-buffering-degrader-preferred"],
                "driving_rule": "strong-paralog-buffering-degrader-preferred",
            }
        ]
    )
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN)
    assert r.ok, r.errors


# --- structural (schema) failures ---


def test_missing_default_fails(tmp_path):
    spec = _base()
    del spec["default"]
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN)
    assert not r.ok  # schema requires default → STRUCTURAL error


def test_rung_with_no_predicate_fails(tmp_path):
    spec = _base(resolve=[{"verdict": "foo"}])  # no when_* → schema oneOf fails
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN)
    assert not r.ok


# --- post-resolver clamp arms: the dead-arm class the clamp block used to escape ---


_SIGNALS = VR._rule_signals(REPO / "interpretation-rules")


def _clamp_base(**clamp_over) -> dict:
    """A minimal spec carrying a two-arm clamp whose rule_ids REALLY exist.

    tvn-no-full-normal-window-veto declares `adc: neutral` in its own rule; the
    no-therapeutic-window arm is `opposing` for every modality. That asymmetry is
    what the modality lens is scoped to, so it is also what these tests exercise.
    """
    clamp = {
        "module": "skills/_skills_common/selectivity_veto.py",
        "direction": "downgrade_only",
        "applies_to_input_verdicts": ["strong_tumor_selective"],
        "precedence": [
            {"when_fired": "tvn-no-therapeutic-window-veto", "verdict": "selective_but_broadly_normal"},
            {"when_fired": "tvn-no-full-normal-window-veto", "verdict": "selective_but_broadly_normal"},
        ],
    }
    clamp.update(clamp_over)
    return _base(
        clamp_verdicts=["selective_but_broadly_normal"],
        post_resolver_clamp=clamp,
    )


def _mc(**over) -> dict:
    mc = {
        "signal_source": "interpretation_rules.signals",
        "suppressing_signals": ["neutral", "supportive"],
        "suppressible_verdicts": ["selective_but_broadly_normal"],
        "on_suppression": "fall_through_to_next_arm",
        "no_modality_behavior": "worst_case_identical",
    }
    mc.update(over)
    return mc


def test_shipped_selectivity_resolver_with_the_clamp_is_clean():
    r = VR.validate_resolver_file(REPO / "resolvers" / "selectivity.resolver.yaml", _KNOWN, None, _SIGNALS)
    assert r.ok, f"shipped selectivity resolver must validate: {r.errors}"


def test_dangling_clamp_arm_rule_id_fails(tmp_path):
    spec = _clamp_base(precedence=[{"when_fired": "tvn-renamed-away", "verdict": "selective_but_broadly_normal"}])
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN, None, _SIGNALS)
    assert not r.ok
    assert any("DANGLING_CLAMP_ARM" in e and "tvn-renamed-away" in e for e in r.errors), r.errors


def test_clamp_arm_verdict_absent_from_clamp_verdicts_fails(tmp_path):
    spec = _clamp_base()
    spec["clamp_verdicts"] = ["something_else"]
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN, None, _SIGNALS)
    assert not r.ok
    assert any("UNDECLARED_CLAMP_VERDICT" in e for e in r.errors), r.errors


def test_clamp_without_modality_conditional_is_still_clean(tmp_path):
    """The lens is OPTIONAL — a modality-blind clamp must not be forced to declare one."""
    r = VR.validate_resolver_file(_write(tmp_path, _clamp_base()), _KNOWN, None, _SIGNALS)
    assert r.ok, r.errors


# --- modality lens soundness ---


def test_modality_lens_on_a_real_adc_neutral_arm_is_clean(tmp_path):
    spec = _clamp_base(modality_conditional=_mc())
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN, None, _SIGNALS)
    assert r.ok, r.errors


def test_vacuous_modality_lens_fails(tmp_path):
    """No suppressible arm declares a suppressing signal ⇒ the block can never act."""
    spec = _clamp_base(
        precedence=[{"when_fired": "tvn-no-therapeutic-window-veto", "verdict": "selective_but_broadly_normal"}],
        modality_conditional=_mc(),
    )
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN, None, _SIGNALS)
    assert not r.ok
    assert any("VACUOUS_MODALITY_LENS" in e for e in r.errors), r.errors


def test_insufficient_is_rejected_as_a_suppressing_signal(tmp_path):
    spec = _clamp_base(modality_conditional=_mc(suppressing_signals=["neutral", "supportive", "insufficient"]))
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN, None, _SIGNALS)
    assert not r.ok
    assert any("COVERAGE_TOKEN_AS_WAIVER" in e for e in r.errors), r.errors


def test_verdict_declared_both_suppressible_and_never_suppressed_fails(tmp_path):
    spec = _clamp_base(modality_conditional=_mc(never_suppressed_verdicts=["selective_but_broadly_normal"]))
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN, None, _SIGNALS)
    assert not r.ok
    assert any("CONTRADICTORY_SUPPRESSION" in e for e in r.errors), r.errors


def test_arm_verdict_classified_by_neither_set_fails(tmp_path):
    """Whether a lens may waive an arm must never be left undeclared."""
    spec = _clamp_base(
        precedence=[
            {"when_fired": "tvn-no-full-normal-window-veto", "verdict": "selective_but_broadly_normal"},
            {"when_fired": "tvn-sc-normal-critical-organ-veto", "verdict": "selective_with_normal_liability"},
        ],
        modality_conditional=_mc(),
    )
    spec["clamp_verdicts"] = ["selective_but_broadly_normal", "selective_with_normal_liability"]
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN, None, _SIGNALS)
    assert not r.ok
    assert any("UNCLASSIFIED_CLAMP_VERDICT" in e and "selective_with_normal_liability" in e for e in r.errors), r.errors
    # and it PASSES once the PRESERVING verdict is explicitly declared unwaivable
    spec["post_resolver_clamp"]["modality_conditional"] = _mc(
        never_suppressed_verdicts=["selective_with_normal_liability"]
    )
    r2 = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN, None, _SIGNALS)
    assert r2.ok, r2.errors


def test_suppressible_verdict_not_in_clamp_verdicts_fails(tmp_path):
    spec = _clamp_base(modality_conditional=_mc(suppressible_verdicts=["typo_verdict"]))
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN, None, _SIGNALS)
    assert not r.ok
    assert any("modality_conditional.suppressible_verdicts" in e for e in r.errors), r.errors


def test_inert_arm_is_a_WARNING_not_an_error(tmp_path):
    """An always-opposing arm inside a suppressible verdict is legitimate (the
    no-therapeutic-window arm) — flag it, but do not fail the contract."""
    spec = _clamp_base(modality_conditional=_mc())
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN, None, _SIGNALS)
    assert r.ok
    assert any("MODALITY_LENS_INERT_ARM" in w and "tvn-no-therapeutic-window-veto" in w for w in r.warnings), r.warnings


def test_unknown_signal_source_is_rejected_structurally(tmp_path):
    spec = _clamp_base(modality_conditional=_mc(signal_source="a_python_dict_in_the_executor"))
    r = VR.validate_resolver_file(_write(tmp_path, spec), _KNOWN, None, _SIGNALS)
    assert not r.ok
    assert any("STRUCTURAL" in e for e in r.errors), r.errors
