"""Shared factored-record assembler (M1). Pins the invariants the assembler enforces in ONE place
for all 10 axes: open-world => non-committal finding, no bare numbers, provenance mirrors the
resolver's fired set. Consumed-by-nothing shadow; these are the guards that let per-axis builders
trust the shape."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SKILLS))
from _skills_common.claim_record import (  # noqa: E402
    assemble_claim_record,
    render_verdict,
    OPEN_WORLD_AVAILABILITY,
)

_CERT = {"level": "medium", "coverage": "medium", "corroboration": "unmeasured", "unknown_mass": 0.0}
_FIRED = [
    {"rule_id": "b-rule", "card_id": "c1"},
    {"rule_id": "a-rule", "card_id": "c2"},
    {"rule_id": "a-rule", "card_id": "c2"},
]  # duplicate a-rule
_CARDS = [{"card_id": "c2"}, {"card_id": "c1"}]


def _closed():
    return assemble_claim_record(
        axis="genomic_alteration",
        state="multi_class_driver",
        direction="supports",
        availability="measured_positive",
        magnitude={"level": "strong", "value": 0.3, "scale": "freq"},
        mechanism={"role": "GoF"},
        certainty=_CERT,
        fired=_FIRED,
        cards=_CARDS,
    )


def test_shape_and_provenance_mirrors_fired():
    rec = _closed()
    assert set(rec) >= {"axis", "finding", "certainty", "provenance"}
    assert set(rec["finding"]) == {"state", "direction", "magnitude", "availability"}
    # provenance.fired_rule_ids == the resolver fired set, sorted-unique (the M1 cross-check anchor)
    assert rec["provenance"]["fired_rule_ids"] == ["a-rule", "b-rule"]
    assert rec["provenance"]["cards"] == ["c1", "c2"]
    assert rec["certainty"] is _CERT


@pytest.mark.parametrize("avail", sorted(OPEN_WORLD_AVAILABILITY))
def test_open_world_forces_noncommittal(avail):
    rec = assemble_claim_record(
        axis="selectivity",
        state="strong_tumor_selective",
        direction="supports",
        availability=avail,
        magnitude={"level": "strong", "value": 2.0, "scale": "log2fc"},
        certainty=_CERT,
        fired=[],
        cards=[],
    )
    f = rec["finding"]
    assert f["state"] == "unknown" and f["direction"] == "neutral"  # ignorance != negation
    assert f["magnitude"] == {"level": "none", "value": None, "scale": None, "distance_to_cut": None}


def test_bare_number_rejected():
    with pytest.raises(ValueError, match="no bare numbers"):
        assemble_claim_record(
            axis="x",
            state="s",
            direction="supports",
            availability="measured_positive",
            magnitude={"level": "strong", "value": 1.0},
            certainty=_CERT,
            fired=[],
            cards=[],
        )


def test_bad_availability_and_direction_rejected():
    with pytest.raises(ValueError):
        assemble_claim_record(
            axis="x", state="s", direction="supports", availability="bogus", certainty=_CERT, fired=[], cards=[]
        )
    with pytest.raises(ValueError):
        assemble_claim_record(
            axis="x",
            state="s",
            direction="sideways",
            availability="measured_positive",
            certainty=_CERT,
            fired=[],
            cards=[],
        )


def test_provenance_carries_legacy_verdict():
    rec = _closed()
    assert rec["provenance"]["legacy_verdict"] == "multi_class_driver"  # == state (measured)


def test_render_identity_on_measured_finding():
    rec = _closed()
    assert render_verdict(rec) == "multi_class_driver"  # rho = state


def test_render_reads_legacy_verdict_on_open_world():
    # open-world: state forced to 'unknown', but the raw token was 'data_unavailable' -> render reads it back
    rec = assemble_claim_record(
        axis="selectivity",
        state="data_unavailable",
        direction="opposes",
        availability="not_wired",
        certainty=_CERT,
        fired=[],
        cards=[],
    )
    assert rec["finding"]["state"] == "unknown"
    assert rec["provenance"]["legacy_verdict"] == "data_unavailable"
    assert render_verdict(rec) == "data_unavailable"  # rho reproduces the exact token


def test_optional_blocks_omitted_when_absent():
    rec = assemble_claim_record(
        axis="x", state="s", direction="neutral", availability="insufficient", certainty=_CERT, fired=[], cards=[]
    )
    assert "mechanism" not in rec and "modality_scope" not in rec
    assert rec["finding"]["magnitude"]["level"] == "none"
