"""genomic-alteration-profile _verdict coverage (G test-gap + C exhaustiveness, 2026-07-20).

This v2 multi-class skill shipped with NO tests. It fuses a SNV/indel axis (primary) with
a copy-number modifier. These tests pin EVERY fired rule_id → verdict mapping and, crucially,
make the DELIBERATE non-driver choices explicit (mutation-stratified WT / not-stratified /
insufficient-rate are intentionally NOT genomic-alteration drivers — they fall through), so a
future SILENT drop of a class that SHOULD drive fails CI. Manual precursor to the gap-#5
exhaustiveness validator.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("gap_run", RUN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


gap = _load()


def _v(*rule_ids):
    return gap._verdict([{"rule_id": r} for r in rule_ids])


# --- mutation axis: driver classes ----------------------------------------

def test_biomarker_stratified_is_primary_driver():
    assert _v("mutant-strongly-dependent-supportive") == (
        "biomarker_stratified_dependency", "mutant-strongly-dependent-supportive")


def test_moderate_biomarker():
    assert _v("mutant-moderately-dependent-supportive")[0] == "moderate_biomarker_dependency"


def test_lof_and_missense_drivers():
    assert _v("mut-lof-dominant-supportive")[0] == "recurrent_lof_driver"
    assert _v("mut-missense-dominant-supportive")[0] == "recurrent_missense_driver"


# --- CN axis --------------------------------------------------------------

def test_cn_amplification_driver_when_mutation_passenger():
    # CN drives, mutation is passenger → CN driver (not collapsed to passenger)
    assert _v("cn-recurrently-amplified-supportive", "mut-no-mutations-neutral") == (
        "recurrent_amplification_driver", "cn-recurrently-amplified-supportive")


def test_cn_deletion_driver():
    assert _v("cn-recurrently-deleted-supportive")[0] == "recurrent_deletion_driver"


# --- multi-class ----------------------------------------------------------

def test_both_axes_drive_is_multi_class():
    assert _v("mut-missense-dominant-supportive",
              "cn-recurrently-amplified-supportive")[0] == "multi_class_driver"


# --- deliberate NON-drivers (documented fall-through — the C exhaustiveness pins) --

def test_mixed_and_passenger_are_non_driver_but_not_silent():
    # these ARE mapped (to their own verdict) — not a silent insufficient
    assert _v("mut-mixed-neutral")[0] == "mixed_pattern"
    assert _v("mut-no-mutations-neutral")[0] == "passenger_pattern"


def test_nothing_fired_is_insufficient():
    assert gap._verdict([]) == ("insufficient", None)


def test_stratified_non_driver_classes_are_intentionally_not_drivers():
    """DELIBERATE (documented): a WT-dependency / not-stratified / insufficient-mutation-
    rate is NOT a genomic-alteration DRIVER — the mutation axis maps only the mutant-*
    biomarker + lof/missense/mixed/passenger classes. If one of those stratified rules is
    the ONLY thing fired, the skill correctly falls through to insufficient (a genomic-
    alteration verdict shouldn't be manufactured from a WT dependency). This test PINS
    that intent so a future change that silently starts (or stops) driving is caught."""
    for rid in ("wt-strongly-dependent-neutral",       # if such a rule fires here
                "not-mutation-stratified-neutral"):
        # not in _mutation_verdict's map → mut_verdict None → falls through
        v, drv = _v(rid)
        assert v == "insufficient" and drv is None, (
            f"{rid} is intentionally a non-driver for genomic-alteration; if this should "
            f"change, update _mutation_verdict + this test together")
