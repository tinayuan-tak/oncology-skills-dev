"""#983 copy-number gate on the fusion driver call.

A `recurrent_fusion_driver` whose confidence tier is `moderate_promiscuous` (target recurs, NO recurrent
partner — a MIXED bucket) AND whose locus is ALSO recurrently focally AMPLIFIED is an amplicon PASSENGER
SV (ERBB2/STAD, MDM2/SARC), not a competent fusion driver → demoted to `promiscuous_amplicon_fusion`
(fires no driver rung, drops out of the multi-class framing). Copy-number is the ORTHOGONAL signal that
separates it from a genuine promiscuous kinase fusion (ROS1/NTRK1/FGFR2 — NOT amplified → SPARED, the
load-bearing non-regression). Verdict-moving ONLY for the amplified amplicon-passenger subset.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.card_preprocessors import (  # noqa: E402
    apply_promiscuous_amplicon_fusion_demotion, preprocess_cards_for_gate,
)


def _cards(fusion_class="recurrent_fusion_driver", conf="moderate_promiscuous", cn=None):
    cards = [{"card_id": "fusion-rearrangement-landscape",
              "summary": {"fusion_class": fusion_class, "fusion_recurrence_confidence": conf}}]
    if cn is not None:
        cards.append({"card_id": "copy-number-distribution", "summary": {"patient_focal_cn_class": cn}})
    return cards


def _fclass(cards):
    return next(c["summary"]["fusion_class"] for c in cards if c["card_id"] == "fusion-rearrangement-landscape")


def test_demotes_amplicon_passenger_erbb2_stad_shape():
    # moderate_promiscuous fusion at a focally-amplified locus → amplicon passenger.
    cards = _cards(cn="recurrent_focal_amplification")
    prov = apply_promiscuous_amplicon_fusion_demotion(cards)
    assert prov["demoted"] is True
    assert _fclass(cards) == "promiscuous_amplicon_fusion"


def test_spares_promiscuous_kinase_fusion_not_amplified_ros1_ntrk1_shape():
    # THE LOAD-BEARING NON-REGRESSION: ROS1/NTRK1/FGFR2 are moderate_promiscuous (many partners) but NOT
    # focally amplified — the CN co-signal is absent, so they stay recurrent_fusion_driver.
    for cn in (None, "focal_neutral", "recurrent_focal_deletion", "no_focal_event"):
        cards = _cards(cn=cn)
        prov = apply_promiscuous_amplicon_fusion_demotion(cards)
        assert prov["demoted"] is False, f"wrongly demoted with cn={cn!r}"
        assert _fclass(cards) == "recurrent_fusion_driver"


def test_spares_high_recurrent_partner_even_when_amplified():
    # A recurrent-PARTNER driver (EML4-ALK/TMPRSS2-ERG) is high_recurrent_partner, not moderate_promiscuous
    # — never demoted, even at an amplified locus. Only the MIXED (promiscuous) bucket is gated.
    cards = _cards(conf="high_recurrent_partner", cn="recurrent_focal_amplification")
    assert apply_promiscuous_amplicon_fusion_demotion(cards)["demoted"] is False
    assert _fclass(cards) == "recurrent_fusion_driver"


def test_noop_when_not_a_recurrent_fusion_driver():
    for fc in ("sporadic_fusion", "no_recurrent_fusion", "data_unavailable"):
        cards = _cards(fusion_class=fc, conf=None, cn="recurrent_focal_amplification")
        assert apply_promiscuous_amplicon_fusion_demotion(cards)["demoted"] is False
        assert _fclass(cards) == fc


def test_noop_when_no_copy_number_card():
    cards = _cards(cn=None)
    assert apply_promiscuous_amplicon_fusion_demotion(cards)["demoted"] is False
    assert _fclass(cards) == "recurrent_fusion_driver"


def test_idempotent():
    cards = _cards(cn="recurrent_focal_amplification")
    apply_promiscuous_amplicon_fusion_demotion(cards)
    prov2 = apply_promiscuous_amplicon_fusion_demotion(cards)   # second pass sees the demoted class
    assert prov2["demoted"] is False
    assert _fclass(cards) == "promiscuous_amplicon_fusion"


def test_applied_via_the_composed_registry_preprocessor():
    # compose_core / tp_fanout apply the demotion through preprocess_cards_for_gate("genomic_alteration"),
    # so standalone (skill main) and composed converge on the same demoted cards.
    cards = _cards(cn="recurrent_focal_amplification")
    preprocess_cards_for_gate(cards, "genomic_alteration")
    assert _fclass(cards) == "promiscuous_amplicon_fusion"


def test_fus_claim_signal_reads_weak_for_demoted_class():
    # The demoted class is a real SV but a passenger → the FUS claim reads WEAK (never absent/strong).
    from _skills_common.genomic_claims import _fus_signal
    h = {"genomic_alteration_by_class": {"fusion": {"verdict": "promiscuous_amplicon_fusion"}}}
    sig, ev, _ = _fus_signal(h, {})
    assert sig == "weak"
    assert "amplicon passenger" in ev
