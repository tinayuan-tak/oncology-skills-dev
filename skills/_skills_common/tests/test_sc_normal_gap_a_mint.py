"""Emission PR 1 — the sc_normal_celltype_expression Gap-A mint.

sc-normal-celltype-expression drove the ONLY modality-varying edge in the whole run
(sc_normal_safety_essential_class) yet shipped with no descriptor. This mints its SALIENCE_SPEC.
The load-bearing risks these tests defend:

  * DIRECTION SIGN — this is a normal-tissue SAFETY axis: higher normal-cell detection = MORE
    liability = worse. Getting the sign wrong INVERTS the ruler on a safety axis, so we assert the
    exact token, not merely that a direction is present.
  * CUT ORDER — the graded band's three cuts are the card's own liability cutpoints and must ascend.
  * DELETION SAFETY (ER2) — the cuts single-source the card's thresholds via contract_threshold,
    which fail-softs to None. Assert they resolve, so a future threshold deletion reds THIS build
    instead of silently nulling the ruler. (Skills-side net; the contracts reader_gate declaration is
    deferred behind parked peer PR #786 on the same card.)
"""

from __future__ import annotations

import pytest
from _skills_common import evidence_salience as es
from _skills_common import field_descriptor as fd

MT = "sc_normal_celltype_expression"
CARD = "sc-normal-celltype-expression"
EFFECT = "sc_normal_essential_max_detection_fraction"
CUTS = ["not_expressed_ceiling", "moderate_liability_median_det", "high_liability_median_det"]
# the two Gap-A dark fields this mint describes
GAP_A_FIELDS = ["sc_normal_safety_essential_class", "sc_normal_expression_class"]


def test_spec_exists():
    assert MT in es.SALIENCE_SPECS


def test_direction_is_higher_is_worse_not_stronger():
    # THE SIGN GUARD. higher normal-tissue detection = worse safety liability (mirrors the sibling
    # sc_normal_surface_protein). A `*_stronger` token here would invert the ruler.
    d = fd.descriptors_for(MT)[EFFECT]
    assert d["role"] == "effect"
    assert d["direction"] == "higher_is_worse", d["direction"]
    assert "worse" in (d["direction_phrase"] or "")


def _primary_frame():
    rf = es.SALIENCE_SPECS[MT]["reference_frame"]
    frames = rf if isinstance(rf, list) else [rf]
    return frames[0], frames


def test_graded_band_cuts_are_ascending():
    frame, _ = _primary_frame()
    assert frame["kind"] == "graded_band"
    assert frame["position_field"] == "sc_normal_safety_essential_class"
    values = [es.contract_threshold(c["card_id"], c["threshold"]) for c in frame["cuts"]]
    assert all(v is not None for v in values), values
    assert values == sorted(values), values  # ascending
    assert values == [0.01, 0.2, 0.5], values  # the card's liability cutpoints


def test_display_only_no_atlas_column_minted():
    # DISPLAY-ONLY (atlas deferred): the primary frame carries atlas_numeric False, so the fleet
    # cohort-roll must NOT append a cohort_percentile frame (which would mint a frozen atlas column).
    primary, frames = _primary_frame()
    assert primary.get("atlas_numeric") is False
    assert not any(f.get("kind") == "cohort_percentile" for f in frames), frames


def test_gap_a_fields_are_now_described():
    d = fd.descriptors_for(MT)
    for field in GAP_A_FIELDS:
        assert field in d, f"{field} still has no descriptor"
        assert d[field]["role"] == "categorical"
    # and via the measurement-type-aware classifier
    for field in GAP_A_FIELDS:
        assert fd.classify_field(field, MT) == "categorical"


@pytest.mark.parametrize("threshold", CUTS)
def test_cut_thresholds_resolve_not_none(threshold):
    # ER2: a live read of the card's thresholds. If a future edit deletes one, contract_threshold
    # fail-softs to None and the ruler silently loses its band — this assertion makes that a red build.
    assert es.contract_threshold(CARD, threshold) is not None
