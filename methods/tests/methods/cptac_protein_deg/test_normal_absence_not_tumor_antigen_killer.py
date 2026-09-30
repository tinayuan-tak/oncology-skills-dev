"""Regression test for S1-2 (cards review 2026-08-17): the DLL3-class biologics false-kill.

A tumor-RESTRICTED antigen reads `not_detected_in_normal` in HPA (normal-tissue ABSENCE — the ideal
antigen profile). The HPA-breadth fallback in `_hpa_ihc_anchor` must NOT translate that normal-tissue
absence into a TUMOR-tissue `not_detected` IHC class, because `hpa_ihc_intensity_class == not_detected`
fires the surface `ihc-not-detected-killer` rung → the composed modality verdict collapses to
`neither_viable`. Normal-tissue absence says nothing about tumor abundance, so it must ABSTAIN
(`unmeasured`). Live-verified pre-fix on DLL3/LUAD (approved tarlatamab / Rova-T antigen).

No S3: `load_and_classify` is monkeypatched to a synthetic HPA summary.
"""

from onc_methods.cptac_protein_deg import read as r


def _patch_hpa(monkeypatch, breadth_class, specific_tissues=None):
    """Point _hpa_ihc_anchor's HPA load at a synthetic summary with the given normal-tissue breadth
    class and (optionally) tissue-of-origin enriched intensities."""
    import onc_methods.hpa_normal_tissue_liability.cli as hpa_cli

    def _fake_load_and_classify(target):
        return {
            "normal_tissue_breadth_class": breadth_class,
            "specific_tissues": specific_tissues or [],
        }

    monkeypatch.setattr(hpa_cli, "load_and_classify", _fake_load_and_classify)


def test_normal_absence_abstains_not_tumor_not_detected(monkeypatch):
    # Tumor-restricted antigen: absent from NORMAL, no tissue-of-origin enriched value → breadth fallback.
    _patch_hpa(monkeypatch, "not_detected_in_normal", specific_tissues=[])
    anchor = r._hpa_ihc_anchor("DLL3", "LUAD")
    # MUST abstain — never assert a TUMOR not_detected from a NORMAL-tissue absence.
    assert anchor["hpa_ihc_intensity_class"] == "unmeasured", anchor
    assert anchor["hpa_ihc_intensity_class"] != "not_detected"
    assert anchor["anchor_strength"] == "unmeasured", anchor


def test_not_detected_in_normal_absent_from_breadth_map():
    # The bug was a literal `not_detected_in_normal -> not_detected` entry; it must be gone, and no
    # breadth class may ever map to the killer-triggering `not_detected` IHC class.
    assert "not_detected_in_normal" not in r._BREADTH_TO_IHC_CLASS
    assert "not_detected" not in set(r._BREADTH_TO_IHC_CLASS.values())


def test_present_breadth_fallbacks_preserved(monkeypatch):
    # The defensible present-in-normal fallbacks are unchanged (normal presence ~ abundance proxy).
    _patch_hpa(monkeypatch, "broad_normal_expression", specific_tissues=[])
    a_broad = r._hpa_ihc_anchor("EPCAM", "COAD")
    assert a_broad["hpa_ihc_intensity_class"] == "medium"
    assert a_broad["anchor_strength"] == "breadth_only"

    _patch_hpa(monkeypatch, "restricted_normal_expression", specific_tissues=[])
    a_restr = r._hpa_ihc_anchor("CEACAM5", "COAD")
    assert a_restr["hpa_ihc_intensity_class"] == "low"


def test_density_estimate_does_not_emit_killer_class_for_tumor_restricted(monkeypatch):
    # End-to-end: a tumor-restricted antigen's density estimate must NOT carry
    # hpa_ihc_intensity_class == not_detected (the surface killer's trigger). It degrades honestly
    # to an unmeasured HPA anchor (grade-E), NOT a fabricated tumor-absent call.
    _patch_hpa(monkeypatch, "not_detected_in_normal", specific_tissues=[])
    est = r._hpa_cptac_estimate("DLL3", "LUAD")
    assert est.get("hpa_ihc_intensity_class") != "not_detected", est
