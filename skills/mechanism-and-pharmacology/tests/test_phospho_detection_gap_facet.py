"""Drift-guard: the phospho-pathway-activity card's detection-gap disambiguation fields
(phosphoprotein_detected_in_other_cohorts, phospho_axis_uninformative_reason) must reach the
composed synthesis facet (issue #1564).

The card's own caveats (contracts/cards/phospho-pathway-activity.card.yaml:88-89) MANDATE reading
these before inferring biology off a phospho_not_detected class: a target's total protein
undetected, or the phosphosite detected elsewhere in CPTAC but not this cohort, means the
not_detected class is a DETECTION GAP (antibody/cohort coverage), not a real no-signal. Before this
fix the skill's phospho facet surfaced neither field, so a downstream reader could not tell the two
apart. Verdict-INERT: mechanism_verdict never keys on phospho fields.

Offline: pure _headline / _synthesis_facet over synthetic cards, no S3/reader.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

me = load_run_py(Path(__file__).resolve().parent.parent, "me_run")

_PHOSPHO_DETECTION_GAP_SUMMARY = {
    "phospho_activity_class": "phospho_not_detected",
    "n_phosphosites": 0,
    "max_site_detection_fraction": None,
    "phosphoprotein_detected_in_other_cohorts": True,
    "phospho_axis_uninformative_reason": None,
}

_PHOSPHO_REAL_ABSENCE_SUMMARY = {
    "phospho_activity_class": "phospho_not_detected",
    "n_phosphosites": 0,
    "max_site_detection_fraction": None,
    "phosphoprotein_detected_in_other_cohorts": False,
    "phospho_axis_uninformative_reason": None,
}

_PHOSPHO_UNINFORMATIVE_SUMMARY = {
    "phospho_activity_class": "data_unavailable",
    "n_phosphosites": None,
    "max_site_detection_fraction": None,
    "phosphoprotein_detected_in_other_cohorts": None,
    "phospho_axis_uninformative_reason": "total_protein_not_detected_in_cohort",
}


def _cards(phospho_summary):
    """All cards the skill declares (empty summaries) with the phospho card populated — so every
    get_card_field lookup in _headline resolves."""
    cards = [{"card_id": cid, "summary": {}} for cid in me.CARDS]
    for c in cards:
        if c["card_id"] == "phospho-pathway-activity":
            c["summary"] = dict(phospho_summary)
    return cards


def test_headline_distinguishes_detection_gap_from_real_absence():
    detection_gap = me._headline(_cards(_PHOSPHO_DETECTION_GAP_SUMMARY), [], None)
    real_absence = me._headline(_cards(_PHOSPHO_REAL_ABSENCE_SUMMARY), [], None)
    # both read phospho_not_detected identically without the disambiguation field...
    assert detection_gap["phospho_activity_class"] == real_absence["phospho_activity_class"] == "phospho_not_detected"
    # ...but the disambiguation field itself must differ, so a reader can tell them apart.
    assert detection_gap["phosphoprotein_detected_in_other_cohorts"] is True
    assert real_absence["phosphoprotein_detected_in_other_cohorts"] is False


def test_headline_carries_uninformative_reason():
    h = me._headline(_cards(_PHOSPHO_UNINFORMATIVE_SUMMARY), [], None)
    assert h["phospho_axis_uninformative_reason"] == "total_protein_not_detected_in_cohort"


def test_detection_gap_fields_reach_synthesis_facet_keys():
    """Issue #1564: the fields were absent from the phospho facet entirely (stranded at the card),
    not merely missing from _SYNTHESIS_FACET_KEYS — pin both the emission and the propagation."""
    for key in ("phosphoprotein_detected_in_other_cohorts", "phospho_axis_uninformative_reason"):
        assert key in me._SYNTHESIS_FACET_KEYS


def test_synthesis_facet_carries_detection_gap_fields():
    facet = me._synthesis_facet(_cards(_PHOSPHO_DETECTION_GAP_SUMMARY), [], None)
    assert facet["phosphoprotein_detected_in_other_cohorts"] is True
    assert facet["phospho_axis_uninformative_reason"] is None


def test_phospho_detection_gap_fields_are_verdict_inert():
    """Display-only: mechanism_verdict identical regardless of the disambiguation fields' values,
    and both fields degrade to None (never raise) when the phospho card is empty."""
    vp = ("well_characterized", "some-rule")
    detection_gap = me._headline(_cards(_PHOSPHO_DETECTION_GAP_SUMMARY), [], vp)
    empty = me._headline(_cards({}), [], vp)
    assert detection_gap["mechanism_verdict"] == empty["mechanism_verdict"] == "well_characterized"
    assert empty["phosphoprotein_detected_in_other_cohorts"] is None
    assert empty["phospho_axis_uninformative_reason"] is None
