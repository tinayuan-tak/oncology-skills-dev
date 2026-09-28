"""Regression guard: the HPA-blind vital-organ safety rung (skills #1793 fail-open closure).

THE FAIL-OPEN THIS PINS AGAINST REOPENING. For on-target tox in endocrine/CNS/vascular organs the
safety gate had ONE verdict-bearing protein arm — the HPA-IHC essential-tissue rule
(`normal-tissue-protein-liability-safety-warning`) — and HPA's closed 16-name grouped-intensity
vocabulary structurally cannot represent thyroid / adrenal_gland / pituitary / nerve / blood. The
organ-covering TPHP card was resolved by the safety skill (since 1.19.0) but consumed for DISPLAY
only. Net: a target essential only in an HPA-blind organ produced a clean safety verdict.

The closure routes the TPHP HPA-blind vital-organ class (analysis-methods tphp_normal_protein
0.5.0, `tphp_hpa_blind_vital_organ_liability_class`) into a safety-resolver rung that reuses the
existing `normal_tissue_protein_safety_concern` HOLD verdict. These tests are the contracts-side
mutation teeth: each asserts one half of the add→consume chain, so reverting ANY half (rule,
rung, precedence, WT-loss conditioning, nomination-gate provenance, card declaration, coverage
caveat) fails RED here — a rule without its rung (or a rung above the soft band losing its
precedence) is exactly the "declaring the rule != declaring the verdict" trap.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
RULES = REPO / "interpretation-rules" / "intracellular-intrinsic.rules.yaml"
RESOLVER = REPO / "resolvers" / "safety.resolver.yaml"
COND = REPO / "vocabularies" / "wt_loss_safety_conditioning.yaml"
GATE = REPO / "vocabularies" / "nomination_verdict_gate.yaml"
TPHP_CARD = REPO / "cards" / "normal-tissue-protein-abundance-tphp.card.yaml"
HPA_CARD = REPO / "cards" / "normal-tissue-liability.card.yaml"

RULE_ID = "tphp-hpa-blind-vital-organ-protein-safety-warning"
HPA_RULE_ID = "normal-tissue-protein-liability-safety-warning"
VERDICT = "normal_tissue_protein_safety_concern"
FIELD = "tphp_hpa_blind_vital_organ_liability_class"


def _rules() -> list[dict]:
    doc = yaml.safe_load(RULES.read_text())
    return doc.get("rules", doc) if isinstance(doc, (list, dict)) else []


def _resolver() -> dict:
    return yaml.safe_load(RESOLVER.read_text())


def test_rule_defined_and_keys_on_the_hpa_blind_class():
    """The rule must key on the HPA-BLIND-SCOPED class, NOT the full vital-organ class — the full
    class double-fires organs the HPA killer already covers (measured: 32.0% of the TPHP product vs
    21.0% for the blind subset) and is not the coverage hole this closes."""
    rule = next((r for r in _rules() if isinstance(r, dict) and r.get("rule_id") == RULE_ID), None)
    assert rule is not None, f"{RULE_ID} must be defined in intracellular-intrinsic.rules.yaml"
    w = rule.get("when", {})
    assert w.get("card_id") == "normal-tissue-protein-abundance-tphp"
    assert w.get("field") == FIELD, (
        f"rule must key on the HPA-blind-scoped class, got {w.get('field')} — keying on the full "
        "vital-organ class double-covers organs the HPA killer already owns"
    )
    assert w.get("equals") == "vital_organ_abundant"
    # same signal shape as its HPA sibling: opposing on the full-KO channels, dominant.
    sig = rule.get("signals", {})
    assert sig.get("small_molecule") == "opposing" and sig.get("degrader") == "opposing", sig
    assert rule.get("dominant") is True


def test_resolver_rung_routes_the_rule_to_the_hold_verdict():
    """DECLARING THE RULE != DECLARING THE VERDICT: without this rung the rule fires into nothing
    and the fail-open silently reopens."""
    spec = _resolver()
    rungs = [r for r in spec["resolve"] if r.get("when_fired") == RULE_ID]
    assert rungs, f"safety resolver has NO rung consuming {RULE_ID} — the rule is verdict-inert again"
    assert len(rungs) == 1
    assert rungs[0]["verdict"] == VERDICT, (
        f"rung must reuse the existing {VERDICT} token (every downstream closed-set consumer already "
        f"handles it); got {rungs[0]['verdict']} — a NEW token would be unseen by the nomination gate"
    )


def test_rung_precedence_above_every_soft_and_reassurance_rung():
    """The HOLD must outrank the soft gnomAD band, the tolerant co-condition rungs and
    data_unavailable — in match_all_reduce, MIN priority wins, so this rung's priority must be
    strictly below (i.e. stronger than) every tolerant_reduced_safety_risk / moderately /
    data_unavailable rung. Otherwise an HPA-`absent` gene (whose measured-clear witness fires the
    tolerant co-condition) with a TPHP-blind-organ liability would resolve REASSURING."""
    spec = _resolver()
    mine = next(r for r in spec["resolve"] if r.get("when_fired") == RULE_ID)
    soft = [
        r
        for r in spec["resolve"]
        if r["verdict"] in ("tolerant_reduced_safety_risk", "moderately_constrained_safety", "data_unavailable")
    ]
    assert soft, "expected soft/reassurance rungs in the safety resolver"
    assert all(mine["priority"] < r["priority"] for r in soft), (
        f"HPA-blind HOLD priority {mine['priority']} must beat every soft rung "
        f"{[(r['verdict'], r['priority']) for r in soft]}"
    )
    # and it sits in the same measured-HOLD band as its HPA sibling (directly below it).
    hpa = next(r for r in spec["resolve"] if r.get("when_fired") == HPA_RULE_ID)
    assert mine["priority"] == hpa["priority"] + 1, (mine["priority"], hpa["priority"])


def test_wt_loss_conditioning_covers_the_new_rule():
    """Same WT-loss/full-KO conditioning as the HPA sibling: absent from concern_rules, the
    per-modality safety composition would treat the fired rule as unconditioned — divergent
    modality verdicts between two arms of the SAME concern."""
    cond = yaml.safe_load(COND.read_text())
    concern = cond.get("concern_rules") or []
    assert HPA_RULE_ID in concern  # the sibling this mirrors
    assert RULE_ID in concern, f"{RULE_ID} missing from wt_loss_safety_conditioning concern_rules"


def test_nomination_gate_provenance_names_both_protein_arms():
    """The gate's HOLD row for the shared verdict must list BOTH driving rules — the gate's
    driving_rule_ids is the provenance contract consumers read to know WHICH arm raised the hold."""
    gate = yaml.safe_load(GATE.read_text())
    rows = [
        r
        for block in ("gates",)
        for r in (gate.get(block) or [])
        if isinstance(r, dict) and r.get("verdict") == VERDICT
    ]
    assert rows, f"nomination gate has no row for {VERDICT}"
    ids = {i for r in rows for i in (r.get("driving_rule_ids") or [])}
    assert HPA_RULE_ID in ids and RULE_ID in ids, ids
    assert all(r.get("action") == "hold" for r in rows), rows


def test_tphp_card_declares_the_field_its_vocab_and_the_coverage_caveat():
    """The card must declare (a) all four HPA-blind summary fields, (b) the class vocabulary with
    vital_organ_abundant reachable, and (c) the explicit coverage-gap warning — 'where an organ is
    un-covered by every verdict-bearing arm, emit a caveat rather than silent absence'."""
    card = yaml.safe_load(TPHP_CARD.read_text())
    fields = set(card["outputs"]["summary_fields"])
    for f in (
        FIELD,
        "n_hpa_blind_vital_organs_above_abundance_floor",
        "hpa_blind_vital_organs_above_floor",
        "hpa_blind_vital_organs_uncovered",
    ):
        assert f in fields, f"card must declare {f}"
    vocab = card["outputs"]["summary_fields_vocabulary"][FIELD]
    assert set(vocab) == {"vital_organ_abundant", "vital_organ_low", "no_vital_organ_signal", "data_unavailable"}
    warns = {w["warning_id"]: w for w in card.get("warning_predicates") or []}
    gap = warns.get("tphp_hpa_blind_organ_coverage_gap")
    assert gap is not None, "the organ-coverage-gap warning predicate is the caveat half of skills #1793"
    assert FIELD in gap["if"] and "data_unavailable" in gap["if"]
    liab = warns.get("tphp_hpa_blind_vital_organ_liability")
    assert liab is not None and "vital_organ_abundant" in liab["if"]


def test_hpa_card_discloses_its_vocabulary_scope_on_measured_clear():
    """The silent-absence half on the HPA side: an `absent` (measured-clear) read must carry the
    vocabulary-scope disclosure — the clear spans HPA's 16 nameable groups only, never the blind
    organs."""
    card = yaml.safe_load(HPA_CARD.read_text())
    warns = {w["warning_id"]: w for w in card.get("warning_predicates") or []}
    scope = warns.get("essential_tissue_vocab_scope")
    assert scope is not None, "normal-tissue-liability must disclose its vocabulary scope on `absent`"
    assert "essential_tissue_flag == 'absent'" in scope["if"]
    for organ_word in ("thyroid", "adrenal", "pituitary", "nerve", "blood"):
        assert organ_word in scope["message"], f"scope message must name {organ_word}"
