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

from pathlib import Path

from _test_support import load_run_py

SAFETY_RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"

_sf = load_run_py(SAFETY_RUN.parent.parent, "sf_run_mutsel")

# safety _headline calls get_card_field on ALL of these card_ids, and get_card_field RAISES KeyError
# on a missing card_id (a deliberate typo-guard). The P5 human-genetics cards were added to _headline
# after this test was written, so the fixtures below (which supplied only 2 cards) began raising. Every
# card_id _headline reads must be present; an empty summary is fine for the ones not under test.
_ALL_SAFETY_CARD_IDS = ["gnomad-lof-constraint", "alteration-role", "gene-burden-safety",
                        "clingen-dosage", "clinvar-pathogenicity-safety", "mouse-ko-phenotype",
                        # data-util expansion 2026-08-21 — _headline now also reads these cards
                        "pan-cancer-crispr-dependency-distribution", "normal-tissue-liability",
                        "drug-warning-safety",
                        "functional-gene-state",   # PR-4c — rarely-altered guard card
                        "onsides-adverse-event-safety",   # 2026-08-25 — OnSIDES drug-label ADE context (verdict-inert display)
                        "shet-lof-intolerance"]   # 2026-08-28 — continuous GeneBayes s_het (verdict-inert); _headline reads it


def _safety_cards(**summaries):
    """All card_ids _headline reads, present; `summaries` supplies real values per card_id under test."""
    return [{"card_id": cid, "summary": summaries.get(cid, {})} for cid in _ALL_SAFETY_CARD_IDS]


def test_gof_driver_resolves_raw_concern_and_vector_conditional():
    # RETIRED 2026-08-24: the resolver no longer downgrades a GoF driver to a mechanism-mismatch scalar.
    # It emits the RAW WT-loss concern; the modality-conditional downgrade moved to the per-modality
    # verdict — small_molecule=conditional (allele-selective escape) for a point-mutation GoF driver.
    fired = [{"rule_id": "highly-constrained-safety-warning"},
             {"rule_id": "activating-driver-role-safety-context"},
             {"rule_id": "oncogene-role-safety-context"}]
    assert _sf._verdict(fired) == ("highly_constrained_safety_concern", "highly-constrained-safety-warning")
    vbm = _sf.safety_verdict_by_modality(fired)
    assert vbm["small_molecule"]["action"] == "conditional"   # eligible, not disqualified
    assert vbm["degrader"]["action"] == "hold"


def test_constraint_alone_is_unchanged_concern():
    v = _sf._verdict([{"rule_id": "highly-constrained-safety-warning"}])
    assert v == ("highly_constrained_safety_concern", "highly-constrained-safety-warning")


def test_activating_role_alone_is_insufficient():
    # the context rule is not itself a safety verdict — no constraint warning → no safety call
    v = _sf._verdict([{"rule_id": "activating-driver-role-safety-context"}])
    assert v == ("insufficient", None)


def test_headline_surfaces_per_modality_verdict_for_gof_driver():
    # RETIRED 2026-08-24: no more scalar mismatch downgrade + conditioning note. The headline now surfaces
    # the per-modality safety verdict, which carries the modality-conditioning (small_molecule=conditional).
    cards = _safety_cards(
        **{"gnomad-lof-constraint": {"constraint_class": "highly_constrained", "pli_score": 0.99, "loeuf_score": 0.2},
           "alteration-role": {"functional_direction": "activating"}})
    fired = [{"rule_id": "highly-constrained-safety-warning"},
             {"rule_id": "activating-driver-role-safety-context"},
             {"rule_id": "oncogene-role-safety-context"}]
    h = _sf._headline(cards, fired, ("highly_constrained_safety_concern", "highly-constrained-safety-warning"))
    assert h["safety_verdict"] == "highly_constrained_safety_concern"
    assert h["mechanism_conditioning_note"] is None            # scalar downgrade retired
    vbm = h["safety_verdict_by_modality"]
    assert vbm["small_molecule"]["action"] == "conditional"
    assert vbm["adc"]["action"] == "not_applicable"


def test_headline_no_note_when_not_downgraded():
    cards = _safety_cards(
        **{"gnomad-lof-constraint": {"constraint_class": "highly_constrained"},
           "alteration-role": {"functional_direction": "loss_of_function"}})
    h = _sf._headline(cards, [{"rule_id": "highly-constrained-safety-warning"}],
                      ("highly_constrained_safety_concern", "highly-constrained-safety-warning"))
    assert h["mechanism_conditioning_note"] is None
    assert h["alteration_functional_direction"] == "loss_of_function"


# --- PR-4c: rarely-altered oncogene keeps the WT-loss HOLD (MCL1) ---

def test_rarely_altered_oncogene_not_rescued_by_vector():
    """MCL1-shape: an amplification/role-only oncogene (functional_state_class==rarely_altered) has NO
    selectable point mutation → NOT allele-selective-eligible. The resolver emits the raw concern (as it
    now does for every GoF driver); the DISQUALIFIER keeps small_molecule=hold so exists-safe-modality
    does NOT clear it (replaces the retired GROUP-0b resolver guard, same intent, at the per-modality layer)."""
    fired = [{"rule_id": "highly-constrained-safety-warning"},
             {"rule_id": "activating-driver-role-safety-context"},
             {"rule_id": "oncogene-role-safety-context"},
             {"rule_id": "functional-gene-state-rarely-altered-neutral"}]
    assert _sf._verdict(fired)[0] == "highly_constrained_safety_concern"
    assert _sf.safety_verdict_by_modality(fired)["small_molecule"]["action"] == "hold"  # disqualified


def test_human_genetics_rarely_altered_not_rescued_by_vector():
    """The disqualifier covers the human-genetics WT-loss warnings too (not just gnomAD)."""
    fired = [{"rule_id": "gene-burden-lof-safety-warning"},
             {"rule_id": "activating-driver-role-safety-context"},
             {"rule_id": "oncogene-role-safety-context"},
             {"rule_id": "functional-gene-state-rarely-altered-neutral"}]
    assert _sf._verdict(fired)[0] == "human_genetics_safety_concern"
    assert _sf.safety_verdict_by_modality(fired)["small_molecule"]["action"] == "hold"  # disqualified
