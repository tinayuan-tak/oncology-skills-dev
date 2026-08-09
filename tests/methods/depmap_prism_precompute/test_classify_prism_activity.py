"""classify_prism_activity — the PRISM cell-panel activity classifier (verdict-driving).

Pins the priority ladder, focused on the T1.2 split (2026-08-09): a phase-1+ compound ANNOTATED
against the target but with NO measured cell-panel activity now reads `clinical_precedent_only`
(honestly weaker), NOT the strong `clinically_active` — which is reserved for a clinical anchor WITH
measured Log2AUC below the clinically-active threshold. Hermetic (pure function, no I/O).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_prism_precompute.cli import (  # noqa: E402
    classify_prism_activity,
    CLINICALLY_ACTIVE_LOG2AUC_THRESHOLD as CA_THR,
    WEAKLY_ACTIVE_LOG2AUC_THRESHOLD as WA_THR,
)


def test_no_compounds_is_first_in_class_not_killer():
    assert classify_prism_activity(0, "none", None) == "no_compounds_found"


def test_clinical_plus_measured_activity_is_clinically_active():
    # phase-1+ AND median Log2AUC below the clinically-active threshold → the STRONG verdict
    assert classify_prism_activity(3, "phase_1_plus", CA_THR - 0.5) == "clinically_active"
    assert classify_prism_activity(2, "approved", CA_THR - 0.01) == "clinically_active"


def test_clinical_annotation_without_measured_activity_is_precedent_only():
    """T1.2 CORE: a clinical compound annotated to the target but NO measured activity
    (Log2AUC absent) → clinical_precedent_only, NOT clinically_active."""
    assert classify_prism_activity(2, "phase_1_plus", None) == "clinical_precedent_only"
    assert classify_prism_activity(1, "approved", None) == "clinical_precedent_only"


def test_clinical_annotation_with_weak_activity_above_threshold_is_precedent_only():
    """Clinical + a measured Log2AUC that does NOT clear the clinically-active threshold →
    still precedent_only (the measured signal isn't strong enough to be chemically_active)."""
    assert classify_prism_activity(2, "phase_1_plus", CA_THR + 0.2) == "clinical_precedent_only"


def test_tool_compound_with_activity_is_weakly_active():
    assert classify_prism_activity(2, "tool", WA_THR - 0.1) == "weakly_active"


def test_tool_compound_without_activity_is_tool_compound_only():
    assert classify_prism_activity(2, "tool", None) == "tool_compound_only"
    # tool + measured but not below the weakly-active threshold → tool_compound_only
    assert classify_prism_activity(2, "preclinical", WA_THR + 0.1) == "tool_compound_only"


def test_precedent_only_is_distinct_from_clinically_active():
    """Regression guard: the two clinical buckets must NOT collapse — the split is the whole point."""
    strong = classify_prism_activity(2, "approved", CA_THR - 0.3)
    weak = classify_prism_activity(2, "approved", None)
    assert strong == "clinically_active"
    assert weak == "clinical_precedent_only"
    assert strong != weak
