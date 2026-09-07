"""claim_record.magnitude ↔ key_evidence.interpretation convergence (interpretation-encoding Stage 3).

The factored-record magnitude and the display ruler must speak ONE vocabulary: magnitude_from_interpretation
maps a gauged_value's value/scale/distance_to_cut onto the magnitude coordinate, and magnitude_for_card
derives it from the SAME SALIENCE_SPEC reference_frame the graph uses. Multi-class axes (no single value)
stay level-only.
"""

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.claim_record import assemble_claim_record, magnitude_from_interpretation, magnitude_for_card


def test_from_interpretation_comparator_delta_keeps_surfaced_delta():
    gv = {
        "metric": "median_chronos_hotspot_mutant",
        "value": -1.729,
        "scale": "chronos",
        "distance_to_cut": -1.142,
        "frame": {
            "kind": "comparator_delta",
            "anchors": [{"role": "comparator", "value": -0.5864}, {"role": "cut", "value": -0.5}],
        },
    }
    assert magnitude_from_interpretation(gv) == {"value": -1.729, "scale": "chronos", "distance_to_cut": -1.142}


def test_from_interpretation_floor_cut_ceiling_computes_distance_to_cut():
    gv = {
        "metric": "median_chronos_panel",
        "value": -0.4574,
        "scale": "chronos",
        "frame": {
            "kind": "floor_cut_ceiling",
            "anchors": [
                {"role": "floor", "value": -0.038},
                {"role": "ceiling", "value": -1.499},
                {"role": "cut", "value": -0.5},
            ],
        },
    }
    out = magnitude_from_interpretation(gv)
    assert out["value"] == -0.4574 and out["scale"] == "chronos"
    assert out["distance_to_cut"] == 0.0426  # value - cut, both pinned


def test_from_interpretation_no_value_or_scale_is_empty():
    assert magnitude_from_interpretation({"metric": "x"}) == {}
    assert magnitude_from_interpretation({"value": -1.0}) == {}  # no scale -> no bare number
    assert magnitude_from_interpretation(None) == {}


def test_for_card_present_summary_converges():
    cards = [
        {
            "card_id": "pan-cancer-crispr-dependency-distribution",
            "summary": {
                "median_chronos_panel": -0.4574,
                "dep_control_non_essential_floor": -0.038,
                "dep_control_pan_essential_ceiling": -1.499,
                "dep_control_position_class": "between_controls",
            },
        }
    ]
    mag = magnitude_for_card(cards, "pan-cancer-crispr-dependency-distribution", "crispr_lof_dependency", "moderate")
    assert mag == {"level": "moderate", "value": -0.4574, "scale": "chronos", "distance_to_cut": 0.0426}


def test_for_card_degrades_to_level_only():
    # stripped summary
    assert magnitude_for_card([{"card_id": "c", "summary": {}}], "c", "crispr_lof_dependency", "weak") == {
        "level": "weak"
    }
    # level none
    assert magnitude_for_card([], "c", "crispr_lof_dependency", "none") == {"level": "none"}
    # un-spec'd measurement_type (no reference_frame) -> level-only even with a value present
    assert magnitude_for_card([{"card_id": "c", "summary": {"x": 1}}], "c", "rnai_lof_dependency", "moderate") == {
        "level": "moderate"
    }


def test_converged_magnitude_passes_the_no_bare_number_guard():
    # the assembler re-checks value-implies-scale; a converged magnitude must satisfy it
    cards = [
        {
            "card_id": "pan-cancer-crispr-dependency-distribution",
            "summary": {
                "median_chronos_panel": -0.4574,
                "dep_control_non_essential_floor": -0.038,
                "dep_control_pan_essential_ceiling": -1.499,
            },
        }
    ]
    mag = magnitude_for_card(cards, "pan-cancer-crispr-dependency-distribution", "crispr_lof_dependency", "strong")
    rec = assemble_claim_record(
        axis="dependency",
        state="concordant_dependent",
        direction="supports",
        availability="measured_positive",
        certainty={"level": "high"},
        fired=[],
        cards=cards,
        magnitude=mag,
    )
    assert rec["finding"]["magnitude"]["scale"] == "chronos"  # no ValueError raised
