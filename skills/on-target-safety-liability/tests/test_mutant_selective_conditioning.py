"""Mutant-selective safety conditioning (2026-07-23).

gnomAD LoF constraint measures WILD-TYPE intolerance. A GoF driver (KRAS) is drugged
mutant-selectively (spares WT in normal tissue), so the WT-constraint safety concern is largely
nullified. The safety RESOLVER combines highly-constrained-safety-warning + activating-driver-role-
safety-context (when_all_fired) → wt_constraint_mechanism_mismatch. These tests pin:
  - both rules fired → the downgrade verdict (NOT the raw concern);
  - constraint alone → the raw concern (unchanged, no false downgrade);
  - activating-role alone → insufficient (context rule is not itself a safety verdict);
  - the headline surfaces the mechanism_conditioning_note + functional_direction on the downgrade.

Reads the LIVE safety resolver from target-contracts (via resolve_verdict_for_gate), so this test is
green only when the resolver's mutant-selective rung is present (target-contracts resolver PR).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

SAFETY_RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load(p, name):
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_sf = _load(SAFETY_RUN, "sf_run_mutsel")

# safety _headline calls get_card_field on ALL of these card_ids, and get_card_field RAISES KeyError
# on a missing card_id (a deliberate typo-guard). The P5 human-genetics cards were added to _headline
# after this test was written, so the fixtures below (which supplied only 2 cards) began raising. Every
# card_id _headline reads must be present; an empty summary is fine for the ones not under test.
_ALL_SAFETY_CARD_IDS = ["gnomad-lof-constraint", "alteration-role", "gene-burden-safety",
                        "clingen-dosage", "clinvar-pathogenicity-safety", "mouse-ko-phenotype"]


def _safety_cards(**summaries):
    """All card_ids _headline reads, present; `summaries` supplies real values per card_id under test."""
    return [{"card_id": cid, "summary": summaries.get(cid, {})} for cid in _ALL_SAFETY_CARD_IDS]


def test_both_fired_downgrades_to_mechanism_mismatch():
    v = _sf._verdict([{"rule_id": "highly-constrained-safety-warning"},
                      {"rule_id": "activating-driver-role-safety-context"}])
    assert v == ("wt_constraint_mechanism_mismatch", "highly-constrained-safety-warning")


def test_constraint_alone_is_unchanged_concern():
    v = _sf._verdict([{"rule_id": "highly-constrained-safety-warning"}])
    assert v == ("highly_constrained_safety_concern", "highly-constrained-safety-warning")


def test_activating_role_alone_is_insufficient():
    # the context rule is not itself a safety verdict — no constraint warning → no safety call
    v = _sf._verdict([{"rule_id": "activating-driver-role-safety-context"}])
    assert v == ("insufficient", None)


def test_headline_surfaces_conditioning_note_on_downgrade():
    cards = _safety_cards(
        **{"gnomad-lof-constraint": {"constraint_class": "highly_constrained", "pli_score": 0.99, "loeuf_score": 0.2},
           "alteration-role": {"functional_direction": "activating"}})
    fired = [{"rule_id": "highly-constrained-safety-warning"},
             {"rule_id": "activating-driver-role-safety-context"}]
    h = _sf._headline(cards, fired, ("wt_constraint_mechanism_mismatch", "highly-constrained-safety-warning"))
    assert h["safety_verdict"] == "wt_constraint_mechanism_mismatch"
    assert h["alteration_functional_direction"] == "activating"
    assert h["mechanism_conditioning_note"] is not None
    assert "MUTANT-SELECTIVELY" in h["mechanism_conditioning_note"]
    assert "WILD-TYPE" in h["mechanism_conditioning_note"]


def test_headline_no_note_when_not_downgraded():
    cards = _safety_cards(
        **{"gnomad-lof-constraint": {"constraint_class": "highly_constrained"},
           "alteration-role": {"functional_direction": "loss_of_function"}})
    h = _sf._headline(cards, [{"rule_id": "highly-constrained-safety-warning"}],
                      ("highly_constrained_safety_concern", "highly-constrained-safety-warning"))
    assert h["mechanism_conditioning_note"] is None
    assert h["alteration_functional_direction"] == "loss_of_function"
