"""surface_modality (strength, certainty) sidecar — CERTAINTY_MODEL 4th axis. Verdict-inert."""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

sm = load_run_py(Path(__file__).resolve().parent.parent, "smf_run_strength")


def _cards(density=None, confirm=None, n_lines=None):
    c = []
    if density is not None:
        c.append({"card_id": "surface-abundance-density", "summary": {"surface_density_class": density}})
    if confirm is not None:
        c.append(
            {
                "card_id": "protein-surface-evidence",
                "summary": {"surface_confirmation_class": confirm, "n_celllines_detected": n_lines},
            }
        )
    return c


def test_both_viable_confirmed_surface_high():
    sc = sm._strength_certainty(
        _cards(density="high", confirm="confirmed_high"), verdict_pair=("both_viable", "both-viable-supportive")
    )
    assert sc["strength"] == "strong_positive"
    assert sc["certainty"]["coverage"] == "high"
    assert sc["certainty"]["corroboration"] == "high"
    assert sc["certainty"]["level"] == "high"


def test_cspa_unmeasured_drops_from_level():
    sc = sm._strength_certainty(
        _cards(density="moderate", confirm=None), verdict_pair=("adc_preferred", "adc-preferred-supportive")
    )
    assert sc["certainty"]["corroboration"] == "unmeasured"
    assert sc["certainty"]["level"] == sc["certainty"]["coverage"] == "medium"


def test_not_surface_measured_negative_low():
    sc = sm._strength_certainty(_cards(density="high", confirm="not_surface"), verdict_pair=("both_viable", "x"))
    assert sc["certainty"]["corroboration"] == "low"  # CSPA disagrees with a surface-favorable fit
    assert sc["certainty"]["level"] == "low"


def test_neither_viable_negative_strength():
    sc = sm._strength_certainty(
        _cards(density="low", confirm=None), verdict_pair=("neither_viable", "neither-viable-killer")
    )
    assert sc["strength"] == "negative"
