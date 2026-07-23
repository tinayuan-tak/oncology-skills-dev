"""read_abundance_density_summary (surface-abundance-density card, Tier 1.2, 2026-07-23).

Estimated surface copies-per-cell: anchor an absolute scale on the HPA IHC intensity for the tumor
tissue-of-origin, then shift by the CPTAC tumor-vs-normal log2FC. RANGED + estimated-tier; the band
WIDENS when the anchor is weak (breadth-only) or CPTAC is absent, so the card's wide_uncertainty_band
warning fires honestly. `unmeasured` (never a fabricated number) when the HPA anchor is missing.

No S3: the HPA anchor (cli.load_and_classify) and the CPTAC row (read_target_summary) are both
monkeypatched to synthetic values so the calibration + band arithmetic is pinned deterministically.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

r = importlib.import_module("methods.cptac_protein_deg.read")
_hpa = importlib.import_module("methods.hpa_normal_tissue_liability.cli")


def _patch_hpa(monkeypatch, *, breadth, specific=None):
    """Stub HPA load_and_classify → a normal-tissue-liability summary shape."""
    monkeypatch.setattr(_hpa, "load_and_classify",
                        lambda gene, hpa_path=None: {
                            "normal_tissue_breadth_class": breadth,
                            "specific_tissues": specific or [],
                        })


def _patch_cptac(monkeypatch, *, cls, effect, cohort="COAD"):
    """Stub read_target_summary → a CPTAC per-cohort summary shape."""
    monkeypatch.setattr(r, "read_target_summary",
                        lambda target, indication=None: {
                            "cohort": cohort,
                            "protein_expression_class": cls,
                            "protein_effect_size": effect,
                        })


def test_tissue_specific_anchor_high_and_tce_viable(monkeypatch):
    # intestine enriched intensity 5e7 (> p66 7.43e6) → IHC 'high' (center 3e5); CPTAC modest_up.
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 5.0e7}])
    _patch_cptac(monkeypatch, cls="modest_up", effect=1.05)
    d = r.read_abundance_density_summary("CEACAM5", "COADREAD")
    assert d["hpa_ihc_intensity_class"] == "high"
    assert d["density_evidence_level"] == "D"   # inferred from priors, not calibrated flow
    assert d["_anchor_strength"] == "tissue_specific"
    assert d["_cptac_covered"] is True
    # 3e5 * 2**1.05 ~= 6.2e5 → > 10,000 → high; TCE + high-payload ADC both viable
    assert d["surface_density_class"] == "high"
    assert d["is_tce_viable"] is True
    assert d["is_adc_high_payload_viable"] is True
    # ordering + tight band (factor 12, both anchors strong)
    assert d["estimated_copies_per_cell_lower"] < d["estimated_copies_per_cell_median"] \
        < d["estimated_copies_per_cell_upper"]
    assert d["_band_factor"] == 12.0


def test_tissue_specific_tertiles(monkeypatch):
    # below p33 (8.05e5) → low; between p33 and p66 → medium
    _patch_cptac(monkeypatch, cls="ns", effect=0.0)
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 5.0e5}])
    assert r.read_abundance_density_summary("X", "COAD")["hpa_ihc_intensity_class"] == "low"
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 2.0e6}])
    assert r.read_abundance_density_summary("X", "COAD")["hpa_ihc_intensity_class"] == "medium"


def test_breadth_only_anchor_widens_band(monkeypatch):
    # BRCA tissue-of-origin is NOT in HPA's enriched vocab → breadth-only medium anchor, factor *1.6.
    _patch_hpa(monkeypatch, breadth="broad_normal_expression", specific=[])
    _patch_cptac(monkeypatch, cls="ns", effect=0.5, cohort="BRCA")
    d = r.read_abundance_density_summary("ERBB2", "BRCA")
    assert d["_anchor_strength"] == "breadth_only"
    assert d["hpa_ihc_intensity_class"] == "medium"
    assert d["_band_factor"] == pytest.approx(12.0 * 1.6)   # breadth-only widen, CPTAC covered
    assert d["hpa_ihc_anchor_used"].startswith("HPA broad_normal_expression")


def test_cptac_absent_is_anchor_only_not_unmeasured(monkeypatch):
    # HPA anchor present but the target has NO CPTAC coverage → anchor-only (shift=1), band widened,
    # still a real number (NOT unmeasured — the normal-tissue anchor alone is defensible first-pass).
    _patch_hpa(monkeypatch, breadth="broad_normal_expression",
               specific=[{"tissue": "intestine", "intensity": 5.0e7}])
    _patch_cptac(monkeypatch, cls="data_unavailable", effect=None)
    d = r.read_abundance_density_summary("CEACAM5", "COAD")
    assert d["surface_density_class"] != "unmeasured"
    assert d["_cptac_covered"] is False
    assert d["estimated_copies_per_cell_median"] == pytest.approx(3.0e5)  # shift = 1.0
    assert d["_band_factor"] == pytest.approx(12.0 * 1.6)                  # CPTAC-absent widen


def test_no_hpa_anchor_is_unmeasured(monkeypatch):
    # No HPA call at all → unmeasured; never fabricate a copies/cell number.
    _patch_hpa(monkeypatch, breadth="data_unavailable", specific=[])
    _patch_cptac(monkeypatch, cls="strong_up", effect=2.0)
    d = r.read_abundance_density_summary("GHOST", "COAD")
    assert d["surface_density_class"] == "unmeasured"
    assert d["density_evidence_level"] == "E"   # expression only; no density estimate
    assert d["hpa_ihc_intensity_class"] == "unmeasured"
    assert d["estimated_copies_per_cell_median"] is None
    assert d["is_tce_viable"] is False
    assert d["is_adc_high_payload_viable"] is False


def test_low_anchor_straddles_tce_threshold(monkeypatch):
    # restricted breadth → 'low' IHC class (center 3e3, straddles the 1,000/cell TCE threshold);
    # a slight CPTAC down-shift drops the median below threshold → moderate/low boundary honesty.
    _patch_hpa(monkeypatch, breadth="restricted_normal_expression", specific=[])
    _patch_cptac(monkeypatch, cls="modest_down", effect=-1.0)   # shift 0.5 → 1500/cell
    d = r.read_abundance_density_summary("X", "PRAD")
    assert d["hpa_ihc_intensity_class"] == "low"
    # 3e3 * 0.5 = 1500 → >= 1000 → moderate (TCE-viable, but wide band spans the threshold)
    assert d["surface_density_class"] == "moderate"
    assert d["is_adc_high_payload_viable"] is False


def test_not_detected_maps_very_low(monkeypatch):
    _patch_hpa(monkeypatch, breadth="not_detected_in_normal", specific=[])
    _patch_cptac(monkeypatch, cls="ns", effect=0.0)
    d = r.read_abundance_density_summary("X", "COAD")
    assert d["hpa_ihc_intensity_class"] == "not_detected"
    # center 3e2, shift 1 → 300/cell → very_low? no: 100 <= 300 < 1000 → low
    assert d["surface_density_class"] == "low"
    assert d["is_tce_viable"] is False
