"""hpa_subcellular_location.read — hermetic tests (injected HPA rows, no S3)."""

from __future__ import annotations

from onc_methods.hpa_subcellular_location import read as _hpa_read
from onc_methods.hpa_subcellular_location.read import read_surface_if_location


def _row(**kw):
    base = {
        "surface_if_location_class": "intracellular_only",
        "is_plasma_membrane": False,
        "plasma_membrane_is_main": False,
        "subcellular_main_location": "Cytosol",
        "subcellular_all_location": "Cytosol",
        "if_reliability": "Supported",
        "n_locations": 1,
    }
    base.update(kw)
    return base


def test_plasma_membrane_main():
    s = read_surface_if_location(
        "EGFR",
        hpa_row=_row(
            surface_if_location_class="plasma_membrane_main",
            is_plasma_membrane=True,
            plasma_membrane_is_main=True,
            subcellular_main_location="Golgi apparatus, Plasma membrane",
            if_reliability="Supported",
        ),
    )
    assert s["surface_if_location_class"] == "plasma_membrane_main"
    assert s["is_plasma_membrane"] is True and s["plasma_membrane_is_main"] is True


def test_intracellular_only_is_measured_non_surface():
    s = read_surface_if_location("KRAS", hpa_row=_row())
    assert s["surface_if_location_class"] == "intracellular_only"
    assert s["is_plasma_membrane"] is False


def test_absent_is_coverage_gap_not_non_surface(monkeypatch):
    # GENUINE absence: the per-gene HPA row reader finds no row (product read OK, gene not present).
    # Mock _read_hpa_row → None so the test stays hermetic (no S3); a live read here would surface a
    # creds/AccessDenied error now that the broad except no longer masks transient failures as absence.
    monkeypatch.setattr(_hpa_read, "_read_hpa_row", lambda sym: None)
    s = read_surface_if_location("NOTAGENE", hpa_row=None)
    assert s["surface_if_location_class"] == "location_unavailable"
    assert s["is_plasma_membrane"] is False
    assert "coverage gap" in s["_data_note"].lower()


def test_additional_location_grade():
    s = read_surface_if_location(
        "X",
        hpa_row=_row(
            surface_if_location_class="plasma_membrane_additional",
            is_plasma_membrane=True,
            plasma_membrane_is_main=False,
        ),
    )
    assert s["surface_if_location_class"] == "plasma_membrane_additional"
    assert s["is_plasma_membrane"] is True and s["plasma_membrane_is_main"] is False
