"""Phase-6 (VERDICT-MOVING): the surface_modality card preprocessor derive_surface_confirmation_state.

fit_class is composed from surfaceome-family + PREDICTED topology ONLY (never CSPA/HPA-IF measured surface
protein), so a positive fit can rest on annotation alone. The preprocessor classes it cross-card BEFORE
fired_rules. This pins:
  (1) annotation_only fires ONLY for a positive fit with NO confirmed protein AND NO clinical precedent
      (the LGR5/GPCR pattern) → drives surface-annotation-only-unconfirmed-opposing;
  (2) confirmed_protein (CSPA/HPA-IF) spares ERBB2/MSLN — never annotation_only;
  (3) clinically_precedented (endocytosis clinically_internalizing OR biologics_precedented OR CD/IO) spares
      DLL3/CEACAM5 — the CSPA-false-negative false-demote guard;
  (4) a non-positive fit_class → not_applicable (no-op);
  (5) the mutation is idempotent + writes onto the adc-tce-modality-fit summary in place.
All pure (no S3).
"""
from __future__ import annotations

from pathlib import Path

from _test_support import load_module

SKILLS_ROOT = Path(__file__).resolve().parents[2]

_M = load_module(SKILLS_ROOT / "_skills_common" / "card_preprocessors.py", "card_preprocessors_scs")


def _cards(fit_class="both_viable", cspa=None, multimodal=None, endo="unmeasured",
           biologics_precedented=False, cd_io=False):
    return [
        {"card_id": "adc-tce-modality-fit", "summary": {
            "fit_class": fit_class, "endocytosis_confidence": endo,
            "biologics_precedented": biologics_precedented}},
        {"card_id": "protein-surface-evidence", "summary": {
            "surface_confirmation_class": cspa, "surface_multimodal_support": multimodal}},
        {"card_id": "cd-antigen-backbone", "summary": {"established_io_precedent": cd_io}},
    ]


def _state(cards):
    _M.derive_surface_confirmation_state(cards)
    return next(c["summary"]["surface_confirmation_state"]
               for c in cards if c["card_id"] == "adc-tce-modality-fit")


# (1) the LGR5/GPCR over-call
def test_annotation_only_positive_fit_no_protein_no_precedent():
    assert _state(_cards(fit_class="TCE_preferred", cspa="not_surface")) == "annotation_only"
    assert _state(_cards(fit_class="both_viable", cspa="not_surface")) == "annotation_only"


# (2) confirmed_protein spares ERBB2/MSLN
def test_confirmed_protein_via_cspa_class():
    assert _state(_cards(cspa="confirmed_high")) == "confirmed_protein"
    assert _state(_cards(cspa="confirmed")) == "confirmed_protein"


def test_confirmed_protein_via_multimodal_even_without_cspa_class():
    assert _state(_cards(cspa=None, multimodal="corroborated_surface")) == "confirmed_protein"


# (3) clinically_precedented — the DLL3/CEACAM5 false-demote guard
def test_clinically_precedented_via_endocytosis():
    # CEACAM5-class: CSPA not_surface but endocytosis clinically_internalizing (curated ADC precedent)
    assert _state(_cards(fit_class="both_viable", cspa="not_surface",
                         endo="clinically_internalizing")) == "clinically_precedented"


def test_clinically_precedented_via_widened_biologics_vocab():
    # DLL3-class: CSPA not_surface, endo unmeasured (ADC failed), but biologics_precedented=True (TCE tarlatamab)
    assert _state(_cards(fit_class="both_viable", cspa="not_surface", endo="unmeasured",
                         biologics_precedented=True)) == "clinically_precedented"


def test_clinically_precedented_via_cd_io_backbone():
    assert _state(_cards(fit_class="TCE_preferred", cspa="not_surface", cd_io=True)) == "clinically_precedented"


# (4) non-positive fit → not_applicable
def test_not_applicable_for_nonpositive_fit():
    for fc in ("neither_viable", "modality_ambiguous", "isoform_dependent_undefined",
               "data_unavailable", "insufficient"):
        assert _state(_cards(fit_class=fc, cspa="not_surface")) == "not_applicable", fc


# (5) idempotent + in-place + registered
def test_idempotent_and_registered():
    cards = _cards(fit_class="TCE_preferred", cspa="not_surface")
    s1 = _state(cards)
    s2 = _state(cards)   # re-derive
    assert s1 == s2 == "annotation_only"
    assert "surface_modality" in _M.CARD_PREPROCESSORS
    prov = _M.preprocess_cards_for_gate(cards, "surface_modality")
    assert prov["surface_confirmation_state"]["state"] == "annotation_only"


def test_missing_adc_card_is_safe_noop():
    prov = _M.derive_surface_confirmation_state([{"card_id": "protein-surface-evidence", "summary": {}}])
    assert prov["applied"] is False
