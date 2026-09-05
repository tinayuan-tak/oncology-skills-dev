"""EMITTED-verdict reconciliation (Phase 3) — reconcile_genomic_verdict.

The raw resolver ladder can name a biomarker-dependency verdict off a stratified-dependency rung whose
signal the ORTHOGONAL KO-dependency confidence cards contradict (TP53/COADREAD: cross-consortium
concordant_non_dependent + event-model event_matched_not_dependent). The ONE WORD a human/LLM reads is
reconciled so it can't over-read the signal package; the raw word is kept as the gate-bearing ladder.

CD19-safety is the point: the demotion requires BOTH orthogonal cards to contradict, so a real biomarker
dependency (both agree, or a single card is absent/agrees) is NEVER demoted. Verdict-INERT to the
nomination spine (the composed gate reads the raw resolve_verdict_for_gate output, not this emitted word).
"""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

gap = load_run_py(Path(__file__).resolve().parent.parent, "gap_run_rec")
UNCONFIRMED = "biomarker_dependency_unconfirmed"


def _h(cross, event):
    return {"cross_consortium_class": cross, "event_correspondence_class": event}


# ── DEMOTE: dependency-family verdict + BOTH orthogonal cards contradict (the TP53/COADREAD shape) ──
def test_demotes_biomarker_stratified_when_both_cards_contradict():
    h = _h("concordant_non_dependent", "event_matched_not_dependent")
    assert gap.reconcile_genomic_verdict("biomarker_stratified_dependency", h) == UNCONFIRMED
    assert gap.reconcile_genomic_verdict("moderate_biomarker_dependency", h) == UNCONFIRMED


# ── RETAIN: a real biomarker dependency (both cards agree) is never demoted (KRAS/ERBB2 shape) ──
def test_retains_when_cards_agree():
    h = _h("concordant_dependent", "event_matched_dependent_in_lineage")
    assert gap.reconcile_genomic_verdict("biomarker_stratified_dependency", h) == "biomarker_stratified_dependency"
    assert gap.reconcile_genomic_verdict("moderate_biomarker_dependency", h) == "moderate_biomarker_dependency"


# ── RETAIN: a SINGLE contradicting card is not enough (BRAF/COADREAD shape — event card absent, cross
#    says non_dependent for the WT gene, but V600E is a validated dependency). CD19-safety hinges on this. ──
def test_retains_when_only_one_card_contradicts():
    # cross contradicts, event absent/agrees → retain
    assert gap.reconcile_genomic_verdict(
        "biomarker_stratified_dependency", _h("concordant_non_dependent", None)) == "biomarker_stratified_dependency"
    assert gap.reconcile_genomic_verdict(
        "biomarker_stratified_dependency", _h("concordant_non_dependent", "event_matched_dependent_in_lineage")
    ) == "biomarker_stratified_dependency"
    # event contradicts, cross agrees/absent → retain
    assert gap.reconcile_genomic_verdict(
        "moderate_biomarker_dependency", _h("concordant_dependent", "event_matched_not_dependent")
    ) == "moderate_biomarker_dependency"


# ── RETAIN: only the dependency FAMILY is reconciled — driver/recurrence/passenger words pass through. ──
def test_non_dependency_verdicts_pass_through():
    both_oppose = _h("concordant_non_dependent", "event_matched_not_dependent")
    for v in ("multi_class_driver", "confirmed_lof_driver", "recurrent_snv_driver",
              "recurrent_amplification_driver", "missense_dominant_pattern", "passenger_pattern",
              "mixed_pattern", "insufficient", None):
        assert gap.reconcile_genomic_verdict(v, both_oppose) == v


def test_reconciled_token_has_a_neutral_phrase_and_polarity():
    assert UNCONFIRMED in gap._GENOMIC_VERDICT_PHRASE
    assert gap._genomic_verdict_polarity(UNCONFIRMED) == "neutral"
    # never a positive (must not read as a driver/dependency green-light) nor a measured negative
    assert UNCONFIRMED not in gap._GENOMIC_POSITIVE_VERDICTS
    assert UNCONFIRMED not in gap._GENOMIC_NEGATIVE_VERDICTS
