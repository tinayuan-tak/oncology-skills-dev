"""phospho_pathway_activity (Q8) pure classifier — no cptac package / network."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.phospho_pathway_activity.read import (  # noqa: E402
    classify_phospho_activity,
    DETECTED_FRACTION_ACTIVE,
    MIN_TUMORS,
)


def test_no_sites_is_not_phosphoprotein():
    assert classify_phospho_activity(0, None, None, 100) == "not_phosphoprotein"


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
