"""phospho_pathway_activity (Q8) pure classifier — no cptac package / network."""

from __future__ import annotations

from onc_methods.phospho_pathway_activity.read import (
    DETECTED_FRACTION_ACTIVE,
    MIN_TUMORS,
    classify_phospho_activity,
)


def test_no_sites_with_protein_detected_is_phospho_not_detected():
    """1.2.0: zero sites + total protein DETECTED in the cohort = a MEASURED no-detection."""
    assert (
        classify_phospho_activity(0, None, None, 100, total_protein_detected_in_cohort=True) == "phospho_not_detected"
    )


def test_no_sites_with_protein_absent_is_data_unavailable():
    """The ALK/LUAD fix: zero sites AND the total protein undetected → the axis is UNINFORMATIVE, not
    negative. Absence of phosphopeptides is unreadable when the protein itself is undetected."""
    assert classify_phospho_activity(0, None, None, 100, total_protein_detected_in_cohort=False) == "data_unavailable"


def test_no_sites_with_unprobed_protein_fails_soft_to_not_detected():
    """The probe failing (None) must NOT silently demote the axis — fail soft to the measured token."""
    assert classify_phospho_activity(0, None, None, 100) == "phospho_not_detected"
    assert (
        classify_phospho_activity(0, None, None, 100, total_protein_detected_in_cohort=None) == "phospho_not_detected"
    )


def test_retired_token_is_unreachable():
    """`not_phosphoprotein` is RETIRED: no input combination may return it (it asserted a biological
    negative off a coverage floor — ~48-55% of protein-detected genes per cohort have zero sites)."""
    for n_sites in (0, 1, 5):
        for det in (None, 0.0, 0.05, 0.4, 0.9):
            for over in (None, True, False):
                for prot in (None, True, False):
                    for n_t in (0, 19, 100):
                        assert (
                            classify_phospho_activity(n_sites, det, over, n_t, total_protein_detected_in_cohort=prot)
                            != "not_phosphoprotein"
                        )


def test_frequent_and_exceeds_abundance_is_active():
    assert classify_phospho_activity(10, 0.8, True, 100) == "phospho_active"


def test_frequent_but_not_exceeding_abundance_is_present():
    # substantial detection but phospho does NOT exceed total protein → present, not active
    assert classify_phospho_activity(10, 0.8, False, 100) == "phospho_present"


def test_frequent_with_protein_unavailable_is_active():
    # high detection, no protein comparison available → active (benefit of the doubt on detection)
    assert classify_phospho_activity(10, 0.7, None, 100) == "phospho_active"


def test_moderate_detection_is_present():
    # detected but below the "frequent/active" fraction → present
    assert classify_phospho_activity(5, 0.3, None, 100) == "phospho_present"


def test_rare_detection_is_low():
    assert classify_phospho_activity(3, 0.05, None, 100) == "phospho_low"


def test_too_few_tumors_is_data_unavailable():
    assert classify_phospho_activity(10, 0.9, True, MIN_TUMORS - 1) == "data_unavailable"


def test_frequent_threshold_boundary():
    # exactly at the active fraction with exceedance → active
    assert classify_phospho_activity(4, DETECTED_FRACTION_ACTIVE, True, 100) == "phospho_active"
