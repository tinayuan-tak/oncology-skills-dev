"""End-to-end tests for compose-dashboard's full 3-phase orchestrator.

These tests verify the architectural commitments of iter-1b end-to-end:
  - phase-1 → phase-2 → phase-3 pipeline produces a schema-valid evidence_package
  - KRAS-COADREAD (positive case) produces non-trivial card outputs + meaningful synthesis
  - TG-COADREAD (negative-control) gracefully refuses with structured message
  - Modality enumeration produces per-modality fit assessment
  - The orchestrator's invariance commitment holds (same inputs → byte-identical output)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SCRIPTS_DIR))

from scripts.compose_dashboard import compose  # noqa: E402


# ============================================================================
# E2E Test 1: KRAS-COADREAD full pipeline (POSITIVE CASE)
# ============================================================================

def test_e2e_kras_coadread_full_pipeline():
    run_plan, ep, errors = compose(
        target="KRAS", indication="COADREAD",
        data_mode="pinned", release_pin="2026-Q2",
        modality=None, subgroup_spec="all",
        execution_mode="stub",
        deterministic_timestamps=True,
    )
    assert errors == [], f"evidence_package validation errors: {errors}"

    # Phase-1 commitments
    assert run_plan["axis_resolution"]["status"] == "resolved"
    assert run_plan["axis_resolution"]["resolved_axis"] == "intracellular_intrinsic"
    assert len(run_plan["loaded_modality_modules"]) == 2  # small_molecule + degrader

    # Phase-2 commitments
    vs = ep["governance"]["validation_summary"]
    assert vs["n_cards_passed"] + vs["n_cards_passed_with_warnings"] >= 6  # at least all base cards
    assert vs["n_cards_failed"] == 0, "no card should have failed in stub mode"

    # Phase-3 commitments — meaningful synthesis.
    # D2 RE-POINT (2026-08-12): the headline now reads from the PRIMARY resolver gate verdict
    # (tractability_small_molecule), not the per-modality fit_level (which is a demoted lens).
    # Pre-swap this asserted the fit_level phrasing ("small_molecule ... strong/moderate") was the
    # verdict; post-swap we assert the resolver verdict spine + keep the lens as a secondary check.
    pgv = ep["synthesis"]["primary_gate_verdict"]
    assert pgv["gate"] == "tractability_small_molecule"
    assert pgv["verdict"] == "well_covered"
    assert "well_covered" in ep["synthesis"]["headline"]
    # LENS (secondary): both loaded modalities still score strong.
    lens = {f["modality"]: f["fit_level"] for f in ep["synthesis"]["modality_fit_assessment"]}
    assert lens == {"small_molecule": "strong", "degrader": "strong"}
    assert len(ep["synthesis"]["modality_fit_assessment"]) == 2

    # Each loaded modality has a fit assessment
    modalities_in_fit = {f["modality"] for f in ep["synthesis"]["modality_fit_assessment"]}
    assert modalities_in_fit == {"small_molecule", "degrader"}

    # Evidence package structure
    assert ep["framework_version"] == "2.0.0"
    assert ep["context"]["target"]["symbol"] == "KRAS"
    assert ep["context"]["indication"]["oncotree_code"] == "COADREAD"
    assert ep["context"]["scope"] == "cancer_type"
    assert ep["governance"]["data_mode"] == "pinned"


# ============================================================================
# E2E Test 2: TG-COADREAD negative-control (UNKNOWN AXIS)
# ============================================================================

def test_e2e_tg_coadread_negative_control_unknown_axis():
    run_plan, ep, errors = compose(
        target="TG", indication="COADREAD",
        data_mode="pinned", release_pin="2026-Q2",
        modality=None, subgroup_spec="all",
        execution_mode="stub",
        deterministic_timestamps=True,
    )
    # L4 fix (post-adversarial-review): refusal packages with unknown axis NOW correctly
    # produce a hgnc_id=-1 sentinel which fails evidence_package schema validation
    # (schema requires hgnc_id >= 1). This is the right behavior — a package missing
    # target identity is structurally NOT a valid governance-grade artifact. Test
    # asserts errors include the hgnc_id-must-be-≥1 message AND nothing else.
    assert any("hgnc_id" in e for e in errors), \
        f"expected hgnc_id-must-be->=1 schema error for refusal package; got: {errors}"
    # The schema error count should be exactly 1 (hgnc_id only) — every other field is valid
    assert len(errors) == 1, \
        f"expected exactly 1 validation error (hgnc_id sentinel); got {len(errors)}: {errors}"

    # Axis resolution status
    assert run_plan["axis_resolution"]["status"] == "unknown"
    assert run_plan["axis_resolution"]["resolved_axis"] == "unknown"

    # No cards executed
    assert ep["cards"] == []
    vs = ep["governance"]["validation_summary"]
    assert vs["n_cards_attempted"] == 0
    assert vs["n_cards_passed"] == 0

    # Synthesis must convey refusal
    headline = ep["synthesis"]["headline"]
    assert "cannot evaluate" in headline.lower() or "insufficient evidence" in headline.lower()
    assert "TG" in headline
    assert "not in target_biology_axis_lookup" in headline or "axis_resolution.status='unknown'" in headline

    # Caveats_summary should mention how to fix
    assert "lookup" in ep["synthesis"]["caveats_summary"].lower()

    # Empty modality_fit_assessment (no modules loaded for unknown axis)
    assert ep["synthesis"]["modality_fit_assessment"] == []


# ============================================================================
# E2E Test 3: KRAS+small_molecule explicit modality
# ============================================================================

def test_e2e_kras_explicit_small_molecule():
    _, ep, errors = compose(
        target="KRAS", indication="COADREAD",
        data_mode="pinned", release_pin="2026-Q2",
        modality="small_molecule", subgroup_spec="all",
        execution_mode="stub",
        deterministic_timestamps=True,
    )
    assert errors == []

    # Only one modality in fit assessment (the lens)
    assert len(ep["synthesis"]["modality_fit_assessment"]) == 1
    assert ep["synthesis"]["modality_fit_assessment"][0]["modality"] == "small_molecule"

    # D2 RE-POINT (2026-08-12): headline reads from the resolver's tractability_small_molecule
    # gate verdict, not the fit_level. The gate is modality-independent (the small_molecule /
    # degrader lens restriction does not change the intracellular tractability gate), so the
    # verdict is the same well_covered as the both-modalities run.
    assert ep["synthesis"]["primary_gate_verdict"]["gate"] == "tractability_small_molecule"
    assert "small-molecule tractability verdict" in ep["synthesis"]["headline"]


# ============================================================================
# E2E Test 4: Invariance — same inputs produce byte-identical evidence_package
# ============================================================================

def test_e2e_invariance_byte_identical_reruns():
    """The card-invariance discipline (A2) extends to the full evidence_package
    when deterministic timestamps are used."""
    import json
    plans_eps = [
        compose(
            target="KRAS", indication="COADREAD",
            data_mode="pinned", release_pin="2026-Q2",
            modality=None, subgroup_spec="all",
            execution_mode="stub",
            deterministic_timestamps=True,
        )
        for _ in range(2)
    ]
    _, ep1, errors1 = plans_eps[0]
    _, ep2, errors2 = plans_eps[1]
    assert errors1 == [] and errors2 == []

    # Serialize and compare deterministic fields
    # Skip generated_at (timestamp), generated_by (could include run-time SHA) since
    # deterministic_timestamps already pins these.
    ep1_json = json.dumps(ep1, sort_keys=True, default=str)
    ep2_json = json.dumps(ep2, sort_keys=True, default=str)
    assert ep1_json == ep2_json, "evidence_package not byte-identical across reruns"


# ============================================================================
# E2E Test 5: KRAS+ADC incompatibility (handled at orchestrator level)
# ============================================================================

def test_e2e_kras_adc_incompatible_handled_gracefully():
    _, ep, errors = compose(
        target="KRAS", indication="COADREAD",
        data_mode="pinned", release_pin="2026-Q2",
        modality="adc", subgroup_spec="all",
        execution_mode="stub",
        deterministic_timestamps=True,
    )
    # L4 fix (post-adversarial-review): incompatibility refusals also produce hgnc_id=-1
    # sentinel → schema error is expected. The framework correctly refuses to ship a
    # package with unresolved target identity, signaled via schema validation failure.
    assert any("hgnc_id" in e for e in errors), \
        f"expected hgnc_id schema error for incompatibility refusal; got: {errors}"

    # Empty cards (no modules loaded → no cards composed)
    assert ep["cards"] == []
    # Synthesis indicates incompatibility
    assert "cannot evaluate" in ep["synthesis"]["headline"].lower()
    # Modality fit assessment is empty (no modules ran)
    assert ep["synthesis"]["modality_fit_assessment"] == []
