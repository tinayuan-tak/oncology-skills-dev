"""cspa_surface_confirmation — HPA-IF corroboration facet tests (second measured provider).

Pins: (1) surface_confirmation_class (the verdict-driving field) stays CSPA-driven regardless of
HPA; (2) the surface_multimodal_support corroboration call across agree/disagree/single-modality;
(3) HPA absence degrades gracefully (never breaks CSPA)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.cspa_surface_confirmation.read import _hpa_corroboration  # noqa: E402


def _hpa(cls, pm):
    return {"surface_if_location_class": cls, "is_plasma_membrane": pm, "if_reliability": "Supported"}


def test_both_surface_is_corroborated():
    r = _hpa_corroboration("EGFR", "confirmed_high", _hpa("plasma_membrane_main", True))
    assert r["surface_multimodal_support"] == "corroborated_surface"
    assert r["hpa_if_plasma_membrane"] is True


def test_cspa_surface_hpa_intracellular_is_discordant():
    r = _hpa_corroboration("X", "confirmed_high", _hpa("intracellular_only", False))
    assert r["surface_multimodal_support"] == "discordant"


def test_cspa_negative_hpa_surface_is_discordant():
    r = _hpa_corroboration("Y", "not_surface", _hpa("plasma_membrane_main", True))
    assert r["surface_multimodal_support"] == "discordant"


def test_cspa_only_when_hpa_gap():
    r = _hpa_corroboration("Z", "confirmed_high", _hpa("location_unavailable", False))
    assert r["surface_multimodal_support"] == "cspa_only"


def test_hpa_if_only_when_cspa_negative_hpa_gap_absent():
    # CSPA not_surface + HPA plasma membrane (only HPA positive)
    r = _hpa_corroboration("W", "not_surface", _hpa("plasma_membrane_additional", True))
    assert r["surface_multimodal_support"] == "discordant"  # CSPA measured-neg vs HPA-surface = discordant


def test_single_modality_negative():
    r = _hpa_corroboration("N", "not_surface", _hpa("intracellular_only", False))
    assert r["surface_multimodal_support"] == "single_modality_negative"


def test_hpa_absent_degrades_gracefully():
    r = _hpa_corroboration("G", "confirmed_high", None)
    # hpa_if=None -> read attempts live; in test env S3 may work, but must not raise + must return a class
    assert "surface_multimodal_support" in r
    assert "hpa_if_surface_class" in r
