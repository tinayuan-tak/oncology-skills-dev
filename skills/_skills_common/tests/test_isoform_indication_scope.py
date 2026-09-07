"""Indication-scoping of the isoform-selective modality suppression (2026-08-14 fix).

Druggability-axis backtest finding: `isoform-dependent-modality-suppression` collapsed the biologics
fit_class to `isoform_dependent_undefined` for ANY indication whenever the gene had a curated dominant
alt isoform — over-suppressing canonical ADC/mAb targets off-context (EGFRvIII is a GBM isoform, yet
EGFR/LUAD was suppressed identically to EGFR/GBM; METex14 is NSCLC, yet MET/COADREAD was suppressed).

Fix: IsoformWarning.applies_in_indication() gates the suppression on the entry's oncotree_codes.
These tests pin the gate directly on constructed warnings (no vocab file needed — fully offline)."""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.isoform_selective_targets import IsoformWarning  # noqa: E402


def _w(codes=(), pan=False, impact="", dominant=False):
    return IsoformWarning(
        target_symbol="X",
        dominant_isoform="iso",
        variant_type="v",
        warning_severity="high",
        caveat="",
        warning_conditional_on=None,
        primary_source_doi="",
        primary_source_citation="",
        vocabulary_version="1.3.0",
        oncotree_codes=tuple(codes),
        pan_applicable=pan,
        modality_epitope_impact=impact,
        alt_isoform_dominant=dominant,
    )


# --- Stage 3 (v1.3.0): dominance gate — suppresses_fit_class requires the alt isoform to DOMINATE ---


def test_minority_ablating_isoform_keeps_fit():
    """ERBB2/p95HER2 shape: in-context + ectodomain-ablating but MINORITY (alt_isoform_dominant=False)
    → does NOT hard-suppress fit_class (keep favorable + caveat)."""
    w = _w(codes=("BRCA", "STAD"), impact="ectodomain_ablating", dominant=False)
    assert w.suppresses_adc_epitope() is True  # mechanism still ablates
    assert w.suppresses_fit_class("STAD") is False  # but NOT dominant → fit stands
    assert w.suppresses_fit_class("BRCA") is False


def test_dominant_ablating_isoform_suppresses_fit():
    """A hypothetical dominant epitope-ablating isoform → hard-suppress (all three conditions hold)."""
    w = _w(codes=("STAD",), impact="ectodomain_ablating", dominant=True)
    assert w.suppresses_fit_class("STAD") is True
    assert w.suppresses_fit_class("LUAD") is False  # off-context → no suppress even if dominant


def test_dominance_gate_off_context_never_suppresses():
    w = _w(codes=("BRCA",), impact="ectodomain_ablating", dominant=True)
    assert w.suppresses_fit_class("COADREAD") is False  # off-context wins regardless of dominance


def test_in_context_indication_suppresses():
    w = _w(codes=("GBM", "GBMLGG"))  # EGFRvIII context
    assert w.applies_in_indication("GBM") is True


def test_off_context_indication_does_not_suppress():
    w = _w(codes=("GBM", "GBMLGG"))  # EGFRvIII: GBM-only
    assert w.applies_in_indication("LUAD") is False  # the over-suppression the fix removes
    w2 = _w(codes=("LUAD", "LUSC", "NSCLC"))  # METex14: NSCLC
    assert w2.applies_in_indication("COADREAD") is False


def test_case_insensitive_and_whitespace_tolerant():
    w = _w(codes=("BRCA", "STAD"))
    assert w.applies_in_indication(" brca ") is True
    assert w.applies_in_indication("prad") is False


def test_pan_applicable_always_in_context():
    """FGFR2 IIIb/IIIc is a pan-epithelial isoform axis → suppress in every indication."""
    w = _w(codes=("CHOL",), pan=True)
    assert w.applies_in_indication("LUAD") is True
    assert w.applies_in_indication("CHOL") is True


def test_backward_compat_missing_codes_is_in_context():
    """A pre-v1.1.0 vocab entry (no oncotree_codes, not pan) defaults to in-context — preserving the
    prior always-suppress behavior so the fix is safe against either merge order."""
    assert _w(codes=()).applies_in_indication("LUAD") is True
    assert _w(codes=()).applies_in_indication(None) is True


# --- Stage 2: mechanism-aware suppression (suppresses_adc_epitope) ---


def test_only_ectodomain_ablating_suppresses():
    """Only a mechanism that removes the extracellular antibody epitope (p95HER2) blanks the fit_class."""
    assert _w(impact="ectodomain_ablating").suppresses_adc_epitope() is True


def test_non_ablating_mechanisms_do_not_suppress():
    """METex14 (intracellular), EGFRvIII (neoepitope), CD19 delΔex2 (acquired resistance), FGFR2
    IIIb/IIIc (isoform-specific), and intracellular targets leave the surface epitope targetable."""
    for impact in (
        "ectodomain_intact",
        "neoepitope",
        "resistance_acquired",
        "ectodomain_isoform_specific",
        "intracellular",
    ):
        assert _w(impact=impact).suppresses_adc_epitope() is False, impact


def test_backward_compat_missing_impact_suppresses():
    """A pre-v1.2.0 vocab entry (no modality_epitope_impact) defaults to suppress — preserving the
    Stage-1 in-context always-suppress behavior so the fix is safe against either merge order."""
    assert _w(impact="").suppresses_adc_epitope() is True
