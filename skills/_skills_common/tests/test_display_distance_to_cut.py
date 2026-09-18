"""Emission PR 3 (distance_to_cut half) — the display gauged_value now carries value−cut.

_project_frame surfaces distance_to_cut on the DISPLAY ruler, computed the same way
claim_record.magnitude_from_interpretation does it (first `cut` anchor, sig_round'd value, round(,4)),
so the display ruler and the factored record speak ONE coordinate. Guards:
  * computed = value − cut for a cut-anchored frame;
  * byte-aligned with claim_record (the convergence goal);
  * a frame with NO cut anchor keeps it ABSENT/NULL, never 0;
  * an already-surfaced delta (distance_field) is preferred, never overwritten.
Hermetic: cut anchors are read from the summary (not contract_threshold), so no contracts checkout.
"""

from __future__ import annotations

from _skills_common import claim_record as cr
from _skills_common import evidence_salience as es


def _project(spec, summary):
    gvs = es.build_interpretation({}, summary, spec, card_id="x", contracts_repo=None)
    return gvs[0] if gvs else None


def _cut_frame_spec():
    return {
        "direction": "higher_is_stronger",
        "reference_frame": {
            "kind": "distance_to_cut",
            "value_field": "my_value",
            "scale": "log2fc",
            "anchors": [{"field": "my_cut", "role": "cut", "label": "cut"}],
        },
    }


def test_distance_to_cut_is_value_minus_cut():
    gv = _project(_cut_frame_spec(), {"my_value": 2.0, "my_cut": 0.5})
    assert gv["distance_to_cut"] == round(2.0 - 0.5, 4) == 1.5


def test_negative_distance_is_signed_not_absolute():
    gv = _project(_cut_frame_spec(), {"my_value": 0.2, "my_cut": 0.5})
    assert gv["distance_to_cut"] == round(0.2 - 0.5, 4)  # -0.3, signed


def test_byte_aligned_with_claim_record():
    # the convergence goal: the factored record reads the SAME distance the display ruler shows.
    gv = _project(_cut_frame_spec(), {"my_value": 1.4, "my_cut": 0.5})
    mag = cr.magnitude_from_interpretation(gv)
    assert mag["distance_to_cut"] == gv["distance_to_cut"]


def test_no_cut_anchor_keeps_distance_null_not_zero():
    # a frame with no `cut` anchor (only a value+scale) must NOT fabricate a 0 distance.
    spec = {
        "direction": "higher_is_stronger",
        "reference_frame": {"kind": "distance_to_cut", "value_field": "my_value", "scale": "log2fc"},
    }
    gv = _project(spec, {"my_value": 2.0})
    assert "distance_to_cut" not in gv  # ABSENT, not 0.0


def test_surfaced_delta_is_preferred_not_overwritten():
    # if the card surfaces its own delta (distance_field), that wins — we do not recompute value−cut.
    spec = {
        "direction": "higher_is_stronger",
        "reference_frame": {
            "kind": "distance_to_cut",
            "value_field": "my_value",
            "scale": "log2fc",
            "distance_field": "my_surfaced_delta",
            "anchors": [{"field": "my_cut", "role": "cut", "label": "cut"}],
        },
    }
    gv = _project(spec, {"my_value": 2.0, "my_cut": 0.5, "my_surfaced_delta": 0.9})
    assert gv["distance_to_cut"] == 0.9  # the surfaced delta, NOT value−cut (1.5)


def test_graded_band_uses_first_cut_matching_claim_record():
    # a multi-cut graded_band takes its FIRST cut (matching claim_record's next(...) pick), so the
    # display and the record agree even when the choice is arbitrary.
    spec = {
        "direction": "higher_is_worse",
        "reference_frame": {
            "kind": "graded_band",
            "value_field": "my_value",
            "scale": "detection_fraction",
            "anchors": [
                {"field": "cut_lo", "role": "cut", "label": "lo"},
                {"field": "cut_hi", "role": "cut", "label": "hi"},
            ],
        },
    }
    gv = _project(spec, {"my_value": 0.9, "cut_lo": 0.2, "cut_hi": 0.5})
    first_cut = next(a["value"] for a in gv["frame"]["anchors"] if a.get("role") == "cut")
    assert gv["distance_to_cut"] == round(0.9 - first_cut, 4)
    assert cr.magnitude_from_interpretation(gv)["distance_to_cut"] == gv["distance_to_cut"]
