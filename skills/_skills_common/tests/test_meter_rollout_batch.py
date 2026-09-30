"""Batch distance_to_cut meter rollout — the _BATCH_DISTANCE_TO_CUT_METERS table in evidence_salience.

Asserts each batched axis got a well-formed reference_frame whose value gauges against its card's named cut
(the cut is single-sourced from target-contracts, so the resolved-value assertion runs only when the
contracts checkout is present, matching the other ruler tests). Verdict-INERT / display-only.
"""

from _skills_common.evidence_salience import (  # noqa: E402
    _BATCH_DISTANCE_TO_CUT_METERS,
    SALIENCE_SPECS,
    build_interpretation,
    contract_threshold,
)

# one representative in-range value per batched axis + the cut we expect to resolve from the card
_SAMPLE = {
    "rnai_lof_dependency": ({"rnai_median_dep_score": -0.7}, -0.25),
    "crispr_rnai_concordance": ({"fraction_agree": 0.8}, 0.85),
    "normal_tissue_rna_breadth": ({"highest_tissue_median": 6.5}, 5.672),
    "tumor_protein_abundance": ({"protein_effect_size": 1.2}, 0.5),
    # (rna_protein_concordance graduated to an inline graded_band — covered by the graded-band tests)
}


def _primary_frame(mt):
    """The batch loop attaches its distance_to_cut as the PRIMARY frame; a later tranche may APPEND a
    second frame (reference_frame becomes a list). The batched meter is always frame[0]."""
    rf = (SALIENCE_SPECS.get(mt) or {}).get("reference_frame")
    return rf[0] if isinstance(rf, list) and rf else (rf if isinstance(rf, dict) else None)


def test_batch_table_attached_a_reference_frame_to_every_entry():
    for mt in _BATCH_DISTANCE_TO_CUT_METERS:
        rf = _primary_frame(mt)
        assert rf and rf["kind"] == "distance_to_cut", f"{mt}: batch loop did not attach a reference_frame"
        assert SALIENCE_SPECS[mt].get("direction"), f"{mt}: gauge needs a direction"


def test_each_batched_axis_gauges_value_and_resolves_its_cut():
    for mt, (summary, expected_cut) in _SAMPLE.items():
        spec = SALIENCE_SPECS[mt]
        rf = _primary_frame(mt)
        gv = build_interpretation({}, summary, spec)
        # the batched value is present; any APPENDED frame's value is absent from this sample → drops out
        vf = rf["value_field"]
        batched = next((g for g in gv if g["metric"] == vf), None)
        assert batched is not None, f"{mt}: batched meter {vf} not gauged from {summary}"
        assert batched["value"] == summary[vf] and batched["scale"], f"{mt}: no bare number"
        cut_key, card = rf["cut"]["threshold"], rf["cut"]["card_id"]
        if contract_threshold(card, cut_key) is not None:  # only when contracts is checked out
            assert {a["role"]: a["value"] for a in batched["frame"]["anchors"]}.get("cut") == expected_cut


def test_absent_value_yields_no_bare_frame():
    for mt in _BATCH_DISTANCE_TO_CUT_METERS:
        assert build_interpretation({}, {}, SALIENCE_SPECS[mt]) == [], f"{mt}: emitted a frame with no value"
