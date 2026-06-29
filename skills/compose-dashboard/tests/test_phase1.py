"""Phase-1 (compose) tests for compose-dashboard.

Five test cases exercising the architectural surface:

  1. KRAS-COADREAD, modality unspecified → enumerate plausible (small_molecule + degrader)
  2. KRAS-COADREAD, modality=small_molecule → user_specified, one module
  3. TROP2-COADREAD, modality unspecified → surface_intrinsic axis, 3 plausible modalities
  4. TG-COADREAD, modality unspecified → axis=unknown fallback (TG not in lookup)
  5. KRAS-COADREAD, modality=adc → incompatible_modality_for_axis (intracellular + adc)

Each test asserts:
  - run_plan validates against run_plan.schema.json
  - axis_resolution.status matches expectation
  - modality_resolution.mode matches expectation
  - cards-to-run set matches expectation
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR.parent))

from scripts.compose_phase1 import build_run_plan  # noqa: E402


def _card_ids_to_run(plan: dict) -> set[str]:
    return {entry["card_id"] for entry in plan["card_run_plan"]["to_run"]}


def _card_ids_excluded(plan: dict) -> set[str]:
    return {entry["card_id"] for entry in plan["card_run_plan"]["excluded_at_compose"]}


# ============================================================================
# Test 1: KRAS-COADREAD, modality unspecified
# Expected: axis=intracellular_intrinsic, modality enumerates [small_molecule, degrader],
# loads both modules, runs all intracellular-intrinsic-base cards
# ============================================================================

def test_kras_coadread_no_modality_enumerates_plausible():
    plan, errors = build_run_plan(
        target="KRAS", indication="COADREAD",
        data_mode="pinned", release_pin="2026-Q2",
        modality=None, subgroup_spec="all",
        deterministic_timestamps=True,
    )
    assert errors == [], f"run_plan validation errors: {errors}"
    assert plan["axis_resolution"]["status"] == "resolved"
    assert plan["axis_resolution"]["resolved_axis"] == "intracellular_intrinsic"
    assert plan["axis_resolution"]["selected_base_dashboard"] == "intracellular-intrinsic-base"
    assert plan["modality_resolution"]["mode"] == "enumerated_plausible"
    assert set(plan["modality_resolution"]["plausible_modalities"]) == {"small_molecule", "degrader"}
    assert len(plan["loaded_modality_modules"]) == 2

    # Cards from intracellular-intrinsic-base required_cards must all be in to_run
    cards = _card_ids_to_run(plan)
    expected_base_required = {
        "target-identity-summary", "expression-tumor-vs-adjacent",
        "dependency-lineage-selectivity", "mutation-hotspot-frequency",
        "normal-tissue-liability", "clinical-precedent",
    }
    assert expected_base_required.issubset(cards), f"missing: {expected_base_required - cards}"

    # subgroup-stratified-expression should be admitted because subgroup_spec="all" != null
    assert "subgroup-stratified-expression" in cards

    # No failures
    assert plan["card_run_plan"]["failed_at_compose"] == []


# ============================================================================
# Test 2: KRAS-COADREAD with explicit modality=small_molecule
# Expected: only small_molecule module loaded (not degrader)
# ============================================================================

def test_kras_coadread_explicit_small_molecule():
    plan, errors = build_run_plan(
        target="KRAS", indication="COADREAD",
        data_mode="pinned", release_pin="2026-Q2",
        modality="small_molecule", subgroup_spec="all",
        deterministic_timestamps=True,
    )
    assert errors == []
    assert plan["modality_resolution"]["mode"] == "user_specified"
    assert plan["modality_resolution"]["user_specified_modality"] == "small_molecule"
    assert plan["modality_resolution"]["plausible_modalities"] == ["small_molecule"]
    assert len(plan["loaded_modality_modules"]) == 1
    assert plan["loaded_modality_modules"][0]["modality"] == "small_molecule"


# ============================================================================
# Test 3: TROP2-COADREAD, modality unspecified
# Expected: axis=surface_intrinsic, modality enumerates 3 modalities, loads all 3
# ============================================================================

def test_trop2_coadread_surface_intrinsic_all_modalities():
    plan, errors = build_run_plan(
        target="TROP2", indication="COADREAD",
        data_mode="pinned", release_pin="2026-Q2",
        modality=None, subgroup_spec="all",
        deterministic_timestamps=True,
    )
    assert errors == []
    assert plan["axis_resolution"]["status"] == "resolved"
    assert plan["axis_resolution"]["resolved_axis"] == "surface_intrinsic"
    assert plan["axis_resolution"]["selected_base_dashboard"] == "surface-intrinsic-base"
    assert plan["modality_resolution"]["mode"] == "enumerated_plausible"
    assert set(plan["modality_resolution"]["plausible_modalities"]) == {"adc", "bite_tce", "antibody"}
    assert len(plan["loaded_modality_modules"]) == 3

    # Surface-intrinsic-base required_cards must all be in to_run
    cards = _card_ids_to_run(plan)
    expected_base_required = {
        "target-identity-summary", "expression-tumor-vs-adjacent",
        "tumor-vs-normal-selectivity", "protein-surface-evidence",
        "normal-tissue-liability", "antigen-prevalence", "clinical-precedent",
    }
    assert expected_base_required.issubset(cards), f"missing: {expected_base_required - cards}"

    # ADC module adds antigen-density-evidence (data_blocked) → should be EXCLUDED at compose
    excluded = _card_ids_excluded(plan)
    assert "antigen-density-evidence" in excluded, \
        "antigen-density-evidence should be excluded_at_compose (data_blocked status from ADC module)"


# ============================================================================
# Test 4: TG-COADREAD (NEGATIVE CONTROL — TG not in target_biology_axis_lookup)
# Expected: axis=unknown, no base dashboard loaded, fallback_reason populated
# This is the iter-1b critical negative-control test (T1.1 criterion 7 substrate).
# ============================================================================

def test_tg_coadread_unknown_axis_fallback():
    plan, errors = build_run_plan(
        target="TG", indication="COADREAD",
        data_mode="pinned", release_pin="2026-Q2",
        modality=None, subgroup_spec="all",
        deterministic_timestamps=True,
    )
    assert errors == [], f"unknown-axis fallback plan must still validate: {errors}"
    assert plan["axis_resolution"]["status"] == "unknown"
    assert plan["axis_resolution"]["resolved_axis"] == "unknown"
    assert plan["axis_resolution"]["selected_base_dashboard"] is None
    assert "fallback_reason" in plan["axis_resolution"]
    assert "not in target_biology_axis_lookup" in plan["axis_resolution"]["fallback_reason"]

    # No modality enumeration possible when axis is unknown
    assert plan["modality_resolution"]["mode"] == "not_applicable_axis_unresolved"
    assert plan["loaded_modality_modules"] == []

    # No cards to run — framework correctly refuses
    assert plan["card_run_plan"]["to_run"] == []
    assert plan["card_run_plan"]["failed_at_compose"] == []


# ============================================================================
# Test 5: KRAS-COADREAD with modality=adc (INCOMPATIBLE — adc is surface_intrinsic only)
# Expected: incompatible_modality_for_axis, no modules loaded, no cards to run
# ============================================================================

def test_kras_adc_incompatible_modality_for_axis():
    plan, errors = build_run_plan(
        target="KRAS", indication="COADREAD",
        data_mode="pinned", release_pin="2026-Q2",
        modality="adc", subgroup_spec="all",
        deterministic_timestamps=True,
    )
    assert errors == [], f"incompatibility plan must still validate: {errors}"
    assert plan["axis_resolution"]["status"] == "resolved"
    assert plan["axis_resolution"]["resolved_axis"] == "intracellular_intrinsic"
    assert plan["modality_resolution"]["mode"] == "incompatible_modality_for_axis"
    assert plan["modality_resolution"]["user_specified_modality"] == "adc"
    assert "incompatibility_reason" in plan["modality_resolution"]
    assert "intracellular_intrinsic" in plan["modality_resolution"]["incompatibility_reason"]

    # No modules loaded, no cards run
    assert plan["loaded_modality_modules"] == []
    assert plan["card_run_plan"]["to_run"] == []
