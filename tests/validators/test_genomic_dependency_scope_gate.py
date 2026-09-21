"""Regression guard: ALL FOUR stratified-dependency biomarker rungs must require indication-scope
(scope-coherence Phase 1 — harmonization).

Prior state: only the amp-expr §0 biomarker rungs required an indication-scope gate
(`amp-expr-indication-scoped-context`); the mutation / cn / fusion rungs — which LEAD the genomic
resolver ladder — fired on the pan-cancer/pan-lineage class alone. So a pan-lineage-only dependency in a
lineage the queried indication does not belong to could still set biomarker_stratified_dependency. This
harmonizes the treatment: each of the four biomarker rung families now requires its matching
`<class>-indication-scoped-context` gate (evidence_scope within_indication[_mut_vs_pan_wt]), so
pan-lineage-only evidence falls through to the confirmed_driver / *_dominant_pattern / recurrent_* rungs.

This pins the harmonized structure (all four gated) so a future edit can't silently un-gate one sibling.
The behavioral old→new flip is golden-tested in test_genomic_resolver_ordering.py.
Sibling of test_genomic_ampexpr_scope_gate.py (kept for its MARK2/PAAD provenance)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[2]
RESOLVER = yaml.safe_load((_ROOT / "resolvers" / "genomic_alteration.resolver.yaml").read_text())
RULES = yaml.safe_load((_ROOT / "interpretation-rules" / "intracellular-intrinsic.rules.yaml").read_text())

# (class, {strong,moderate} driver rule ids, gate rule id, card id) for all four stratified siblings.
_FAMILIES = [
    (
        "mutation",
        {"mutant-strongly-dependent-supportive", "mutant-moderately-dependent-supportive"},
        "mutant-indication-scoped-context",
        "mutation-stratified-dependency",
    ),
    (
        "copy_number",
        {"cn-amplified-strongly-dependent-supportive", "cn-amplified-moderately-dependent-supportive"},
        "cn-amplified-indication-scoped-context",
        "copy-number-stratified-dependency",
    ),
    (
        "fusion",
        {"fusion-positive-strongly-dependent-supportive", "fusion-positive-moderately-dependent-supportive"},
        "fusion-positive-indication-scoped-context",
        "fusion-stratified-dependency",
    ),
    (
        "amp_expr",
        {"amp-expr-strongly-dependent-supportive", "amp-expr-moderately-dependent-supportive"},
        "amp-expr-indication-scoped-context",
        "amp-expr-stratified-dependency",
    ),
]


@pytest.mark.parametrize("cls,driver_rules,gate,card_id", _FAMILIES, ids=[f[0] for f in _FAMILIES])
def test_biomarker_rungs_require_indication_scope(cls, driver_rules, gate, card_id):
    """Every biomarker rung keyed on this class's dependency rule must also require the class's scope gate."""
    rungs = [
        r
        for r in RESOLVER["resolve"]
        if driver_rules & set(r.get("when_all_fired", []) or ([r["when_fired"]] if r.get("when_fired") else []))
    ]
    assert rungs, f"expected {cls} biomarker rungs in the genomic resolver"
    for r in rungs:
        waf = set(r.get("when_all_fired", []))
        assert gate in waf, (
            f"{cls} biomarker rung {r.get('verdict')} (driving_rule={r.get('driving_rule')}) keys on a {cls} "
            f"dependency rule but does NOT require {gate!r} — a PAN-LINEAGE {cls} dependency could be promoted "
            f"to an indication-level biomarker verdict. Gate the rung via when_all_fired."
        )
        # driving_rule must stay explicit so the interpreter's rids[-1] fallback doesn't name the gate.
        assert r.get("driving_rule") in driver_rules, (
            f"{cls} gated rung must set driving_rule to the dependency rule (not the scope gate)."
        )


@pytest.mark.parametrize("cls,driver_rules,gate,card_id", _FAMILIES, ids=[f[0] for f in _FAMILIES])
def test_scope_gate_rule_is_indication_scoped(cls, driver_rules, gate, card_id):
    g = next((r for r in RULES["rules"] if r.get("rule_id") == gate), None)
    assert g is not None, f"{gate} missing from intracellular-intrinsic.rules.yaml"
    when = g["when"]
    assert when["card_id"] == card_id and when["field"] == "evidence_scope"
    assert set(when["in"]) == {"within_indication", "within_indication_mut_vs_pan_wt"}, (
        f"{gate} must admit ONLY within-indication scopes; admitting a pan_* scope would defeat the gate."
    )


# (class, strong rule, within gate, fallback gate, card id) — the #8 hybrid-scope demotion (v1.11.0).
_FALLBACK_FAMILIES = [
    (
        "mutation",
        "mutant-strongly-dependent-supportive",
        "mutant-indication-scoped-context",
        "mutant-indication-scoped-fallback-context",
    ),
    (
        "copy_number",
        "cn-amplified-strongly-dependent-supportive",
        "cn-amplified-indication-scoped-context",
        "cn-amplified-indication-scoped-fallback-context",
    ),
    (
        "fusion",
        "fusion-positive-strongly-dependent-supportive",
        "fusion-positive-indication-scoped-context",
        "fusion-positive-indication-scoped-fallback-context",
    ),
    (
        "amp_expr",
        "amp-expr-strongly-dependent-supportive",
        "amp-expr-indication-scoped-context",
        "amp-expr-indication-scoped-fallback-context",
    ),
]


@pytest.mark.parametrize("cls,strong,within,fallback", _FALLBACK_FAMILIES, ids=[f[0] for f in _FALLBACK_FAMILIES])
def test_fallback_gate_is_hybrid_scope_only(cls, strong, within, fallback):
    """Each #8 fallback gate must fire ONLY on the hybrid within_indication_mut_vs_pan_wt scope.

    If it also admitted within_indication (or a pan_* scope), the demotion rung would fire on a fully
    within-indication dependency too and demote the dominant band the locked decision keeps."""
    g = next((r for r in RULES["rules"] if r.get("rule_id") == fallback), None)
    assert g is not None, f"{fallback} missing from intracellular-intrinsic.rules.yaml"
    when = g["when"]
    within_rule = next(r for r in RULES["rules"] if r.get("rule_id") == within)
    assert when["card_id"] == within_rule["when"]["card_id"] and when["field"] == "evidence_scope"
    assert when.get("equals") == "within_indication_mut_vs_pan_wt" and "in" not in when, (
        f"{fallback} must match ONLY evidence_scope == within_indication_mut_vs_pan_wt (the hybrid scope); "
        f"admitting within_indication would demote fully-in-indication dependencies too."
    )


@pytest.mark.parametrize("cls,strong,within,fallback", _FALLBACK_FAMILIES, ids=[f[0] for f in _FALLBACK_FAMILIES])
def test_hybrid_demotion_rung_outranks_the_strong_biomarker_rung(cls, strong, within, fallback):
    """Exactly one demotion rung per class: {strong, within gate, fallback gate} → moderate, and it must
    out-prioritise (min-priority-wins) the strong biomarker rung it demotes. Stated as an ORDERING over
    derived priorities, never literals, so the priority placement can move without rotting."""
    demotion = [r for r in RESOLVER["resolve"] if set(r.get("when_all_fired", []) or []) == {strong, within, fallback}]
    assert len(demotion) == 1, f"expected exactly one {cls} hybrid demotion rung, found {len(demotion)}"
    d = demotion[0]
    assert d["verdict"] == "moderate_biomarker_dependency", (
        f"{cls} hybrid demotion must emit moderate_biomarker_dependency, not {d['verdict']!r}"
    )
    assert d.get("driving_rule") == strong, "demotion rung must anchor provenance to the dependency rule"

    biomarker = [
        r
        for r in RESOLVER["resolve"]
        if set(r.get("when_all_fired", []) or []) == {strong, within}
        and r["verdict"] == "biomarker_stratified_dependency"
    ]
    assert len(biomarker) == 1, f"expected exactly one {cls} strong biomarker rung, found {len(biomarker)}"
    assert d["priority"] < biomarker[0]["priority"], (
        f"the {cls} demotion rung @{d['priority']} must outrank the strong biomarker rung "
        f"@{biomarker[0]['priority']} (match_all_reduce picks min priority), or the demotion is dead."
    )


@pytest.mark.parametrize("cls,driver_rules,gate,card_id", _FAMILIES, ids=[f[0] for f in _FAMILIES])
def test_evidence_scope_vocabulary_declared(cls, driver_rules, gate, card_id):
    """The `in:` comparison requires each card to declare evidence_scope's vocabulary (else CI fails)."""
    card = yaml.safe_load((_ROOT / "cards" / f"{card_id}.card.yaml").read_text())
    vocab = card["outputs"]["summary_fields_vocabulary"]
    assert "evidence_scope" in vocab, f"{card_id} must declare evidence_scope vocabulary for the scope gate"
    assert {
        "within_indication",
        "within_indication_mut_vs_pan_wt",
        "pan_lineage_evidence_only",
        "pan_no_indication",
    } <= set(vocab["evidence_scope"])
