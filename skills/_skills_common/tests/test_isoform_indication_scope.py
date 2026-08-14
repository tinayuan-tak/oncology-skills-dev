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


def _w(codes=(), pan=False):
    return IsoformWarning(
        target_symbol="X", dominant_isoform="iso", variant_type="v", warning_severity="high",
        caveat="", warning_conditional_on=None, primary_source_doi="", primary_source_citation="",
        vocabulary_version="1.1.0", oncotree_codes=tuple(codes), pan_applicable=pan)


def test_in_context_indication_suppresses():
    w = _w(codes=("GBM", "GBMLGG"))          # EGFRvIII context
    assert w.applies_in_indication("GBM") is True


def test_off_context_indication_does_not_suppress():
    w = _w(codes=("GBM", "GBMLGG"))          # EGFRvIII: GBM-only
    assert w.applies_in_indication("LUAD") is False    # the over-suppression the fix removes
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
