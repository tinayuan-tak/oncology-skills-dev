"""Tests for the framework predictive-validity / discrimination harness (scientific-gap #5).

Complements test_known_target_calibration.py (per-target gate assertions) with the AGGREGATE
discrimination metrics + a REGRESSION guard: the framework must not get worse on known targets, and
the curated headline numbers are pinned so a silent calibration-set edit that changes them is caught.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO / "validators"))

import validate_framework_discrimination as H  # noqa: E402

yaml = pytest.importorskip("yaml")


@pytest.fixture(scope="module")
def metrics():
    spec = yaml.safe_load((_REPO / "vocabularies" / "known_target_calibration_set.yaml").read_text())
    profiles = spec.get("reference_profiles") or {}
    assert profiles, "reference_profiles must be populated for the discrimination harness"
    return H.compute_metrics(profiles)


def test_cohort_has_positives_and_negatives(metrics):
    """A discrimination harness is meaningless without both classes."""
    assert metrics["by_outcome"].get("positive_approved", 0) >= 10
    assert metrics["by_outcome"].get("negative_declined", 0) >= 5


def test_headline_metrics_pinned(metrics):
    """Pin the 2026-08-14 curated headline so a calibration-set edit that shifts the framework's measured
    validity is a DELIBERATE, reviewed change (update these when it legitimately moves)."""
    assert metrics["n_approved"] == 18
    # 4 → 3 (2026-08-30): RBM39 corrected dangerous_false_positive → validated_lane — the pan-essential
    # axis is now captured (dependency pan_essential_killer VETO + pan-essential-broad-tox safety),
    # verified by a live run, so the framework declines it for the real window liability (matches outcome).
    assert len(metrics["dangerous_false_positives"]) == 3
    # 12 → 11 (2026-09-02): CNDP2 reclassified silent_false_negative → honest_blind (out_of_scope). It
    # was mislabeled neomorphic_gain_of_function; CNDP2 is WT (no somatic driver) and its actionability
    # is a NON-CELL-AUTONOMOUS secreted-enzyme metabolic dependency conditioned on trans KEAP1-LoF/NRF2-GoF
    # — genuinely out-of-scope (unmeasurable in monoculture DepMap), not a wiring false-negative.
    assert len(metrics["silent_false_negatives"]) == 11
    # blind on the deciding axis for the large majority of known targets.
    # 0.7 → 0.68 (2026-09-02): WRN (MSI-H synthetic-lethal molecular-subtype anchor) promoted into
    # reference_profiles as a CAPTURED advanced target (framework reads partner_conditional_dependent +
    # subtype_fit subtype_specific_non_dependence), which legitimately lowers the blind fraction
    # (0.705 → 0.689 at n=45). A captured add improving coverage is the intended direction.
    # 0.68 → 0.63 (2026-09-02): Tier-2 negative-class expansion — PLK1/AURKA/MMP9 promoted as CAPTURED
    # correctly-declined validated_lane negatives (framework reads the pan-essential/no-window/normal-tissue
    # liability that matches each decline) + IDO1 as an out_of_scope honest_blind. 4 non-blind adds at
    # unchanged blind count (31) drop blind_rate 0.689 → 0.633 at n=49. Adding negatives the framework CAN
    # correctly reject is the intended direction (specificity gain); the floor tracks the honest fraction.
    # 0.63 → 0.58 (2026-09-02 round-2): +4 more CAPTURED validated_lane negatives — MCL1 (safety-axis
    # load-bearing despite all-positive efficacy) + WEE1/CHEK1/KIF11 (pan-essential-veto family). 31/53 =
    # 0.585. Same intended direction (specificity-stress negatives the framework correctly declines).
    assert metrics["blind_rate"] >= 0.58


def test_silent_fn_split_by_outcome_trust(metrics):
    """The 11 silent-FNs are NOT 11 drug losses: only 5 have an approved-drug outcome (unambiguous),
    the other 6 are advanced/active PROGRAM-STATUS entries whose target quality is unvalidated
    (e.g. MARK2/3, which never beat YAP/TAZ efficacy). The harness must report them separately so the
    'would veto a drug' headline — and the regression floor — key off the drug-backed subset only.
    (2026-09-02: advanced_active 7 → 6 — CNDP2 reclassified out to honest_blind; see test above.)"""
    sfn_by = metrics["silent_false_negatives_by_outcome"]
    assert set(sfn_by["positive_approved"]) == {"PARP1", "BCL2", "XPO1", "PSMB5", "CDK4_6"}
    assert len(sfn_by["advanced_active"]) == 6
    # the two subsets partition the total, no leakage into negative_declined
    assert len(sfn_by["positive_approved"]) + len(sfn_by["advanced_active"]) == len(metrics["silent_false_negatives"])
    # home-turf engine: approved-drug deciding-axis capture is very low
    assert metrics["approved_deciding_axis_capture_rate"] <= 0.1


def test_no_regression_against_floors(metrics):
    """The whole point: after any framework change, the harness must not regress past the documented
    floors (more dangerous-FPs / silent-FNs, or a lower approved-agreement rate)."""
    violations = H.check_floors(metrics)
    assert not violations, f"framework discrimination regressed: {violations}"


def test_load_bearingness_ranks_surface_antigen_first(metrics):
    """The actionable output: surface-antigen biology is the highest-leverage MISSING axis (most blind
    known targets). Guards the build-priority signal the harness exists to produce."""
    load = metrics["blind_axis_load_bearingness"]
    top_family = next(iter(load))  # dict is insertion-ordered by most_common()
    assert "surface_antigen_biology" in top_family
    assert load[top_family] >= 10


@pytest.mark.parametrize(
    "axis,expected_fragment",
    [
        ("synthetic_lethal_BRCA_HRD", "synthetic_lethal"),
        ("pan_essential_with_window", "cell_state_window"),
        ("E2_antigen_density_CDx", "surface_antigen_biology"),
        ("interferon_IO_context", "IO / TME"),
        ("V600E_addiction", "captured_lane"),
    ],
)
def test_deciding_axis_family_classification(axis, expected_fragment):
    assert expected_fragment in H.deciding_axis_family(axis)


def test_check_mode_passes_at_current_values():
    """--check must exit 0 at the pinned current values (it only fails on regression)."""
    rc = H.main(["--check"])
    assert rc == 0
