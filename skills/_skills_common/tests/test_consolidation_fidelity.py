"""Consolidation-fidelity flag (2026-08-14).

Generalizes tumor-presence's cell_line_vs_tumor_discordant into a framework-wide, verdict-inert
signal: does the single collapsed verdict MASK a polarity conflict among the fired rules? Emitted by
the shared dispatcher into decision['consolidation'] for every wired skill."""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import _skills_common.dispatcher as D  # noqa: E402


def _fr(rule_id, card_id):
    return {"rule_id": rule_id, "card_id": card_id}


def test_polarity_from_suffix():
    assert D._rule_polarity("mutant-strongly-dependent-supportive") == "positive"
    assert D._rule_polarity("not-surface-adc-killer") == "negative"
    assert D._rule_polarity("expression-modest-downregulation-opposing") == "negative"
    assert D._rule_polarity("tvn-sc-normal-critical-organ-veto") == "negative"
    assert D._rule_polarity("tvn-discordant-neutral-flagged") == "neutral"
    assert D._rule_polarity("highly-constrained-safety-warning") == "neutral"
    assert D._rule_polarity(None) == "neutral"


def test_masked_conflict_when_driver_positive_but_negative_fired():
    """Headline verdict is positive (supportive drives) but a killer fired from another card and was
    overruled — the classic masked over-consolidation."""
    fired = [_fr("adc-supportive", "topology"), _fr("shed-ectodomain-clinical-opposing", "shed"),
             _fr("normal-tissue-broad-opposing", "normal")]
    c = D._consolidation_fidelity(fired, driving_rule_id="adc-supportive")
    assert c["driving_role"] == "positive"
    assert c["discordant"] is True
    assert c["masked_conflict"] is True
    assert "shed-ectodomain-clinical-opposing" in c["overruled_opposing_rules"]
    assert c["n_cards_contributing"] == 3


def test_no_masked_conflict_when_all_same_polarity():
    fired = [_fr("a-supportive", "c1"), _fr("b-supportive", "c2")]
    c = D._consolidation_fidelity(fired, driving_rule_id="a-supportive")
    assert c["discordant"] is False
    assert c["masked_conflict"] is False
    assert c["overruled_opposing_rules"] == []


def test_negative_driver_with_overruled_positive_is_masked():
    """Headline is a killer verdict but a supportive signal fired and was buried."""
    fired = [_fr("not-surface-adc-killer", "family"), _fr("ecd-large-biologics-supportive", "topo")]
    c = D._consolidation_fidelity(fired, driving_rule_id="not-surface-adc-killer")
    assert c["driving_role"] == "negative"
    assert c["masked_conflict"] is True


def test_single_card_passthrough_flagged():
    fired = [_fr("sl-experimental-partner-context-conditional", "combo-crispr-screen")]
    c = D._consolidation_fidelity(fired, driving_rule_id="sl-experimental-partner-context-conditional")
    assert c["single_card_passthrough"] is True
    assert c["masked_conflict"] is False


def test_empty_fired_is_safe():
    c = D._consolidation_fidelity([], driving_rule_id=None)
    assert c["discordant"] is False and c["masked_conflict"] is False
    assert c["n_rules_fired"] == 0 and c["single_card_passthrough"] is True
