"""Batch distance_to_cut meter rollout — the _BATCH_DISTANCE_TO_CUT_METERS table in evidence_salience.

Asserts each batched axis got a well-formed reference_frame whose value gauges against its card's named cut
(the cut is single-sourced from target-contracts, so the resolved-value assertion runs only when the
contracts checkout is present, matching the other ruler tests). Verdict-INERT / display-only.
"""
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.evidence_salience import (  # noqa: E402
    SALIENCE_SPECS, build_interpretation, contract_threshold, _BATCH_DISTANCE_TO_CUT_METERS,
)

# one representative in-range value per batched axis + the cut we expect to resolve from the card
_SAMPLE = {
    "rnai_lof_dependency": ({"rnai_median_dep_score": -0.7}, -0.25),
    "crispr_rnai_concordance": ({"fraction_agree": 0.8}, 0.85),
    "normal_tissue_rna_breadth": ({"highest_tissue_median": 6.5}, 5.672),
    "tumor_protein_abundance": ({"protein_effect_size": 1.2}, 0.5),
    "rna_protein_concordance": ({"rna_protein_r": 0.6}, 0.4),
}


def test_batch_table_attached_a_reference_frame_to_every_entry():
    for mt in _BATCH_DISTANCE_TO_CUT_METERS:
        rf = (SALIENCE_SPECS.get(mt) or {}).get("reference_frame")
        assert rf and rf["kind"] == "distance_to_cut", f"{mt}: batch loop did not attach a reference_frame"
        assert SALIENCE_SPECS[mt].get("direction"), f"{mt}: gauge needs a direction"


def test_each_batched_axis_gauges_value_and_resolves_its_cut():
    for mt, (summary, expected_cut) in _SAMPLE.items():
        spec = SALIENCE_SPECS[mt]
        gv = build_interpretation({}, summary, spec)
        assert len(gv) == 1, f"{mt}: expected one gauged value from {summary}"
        vf = spec["reference_frame"]["value_field"]
        assert gv[0]["metric"] == vf and gv[0]["value"] == summary[vf]
        assert gv[0]["scale"], f"{mt}: no bare number (scale required)"
        cut_key = spec["reference_frame"]["cut"]["threshold"]
        card = spec["reference_frame"]["cut"]["card_id"]
        if contract_threshold(card, cut_key) is not None:      # only when contracts is checked out
            assert {a["role"]: a["value"] for a in gv[0]["frame"]["anchors"]}.get("cut") == expected_cut


def test_absent_value_yields_no_bare_frame():
    for mt in _BATCH_DISTANCE_TO_CUT_METERS:
        assert build_interpretation({}, {}, SALIENCE_SPECS[mt]) == [], f"{mt}: emitted a frame with no value"
