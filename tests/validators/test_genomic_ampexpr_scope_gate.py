"""Regression guard: amp-expr §0 biomarker rungs must require indication-scope (genomic redesign Stage 3a).

The framework-wide rule audit found MARK2/PAAD promoted to moderate_biomarker_dependency off an
amp-expr stratified-dependency signal computed from PAN-LINEAGE evidence only (evidence_scope=
pan_lineage_evidence_only; n=7 across DepMap, not PAAD-scoped). A pan-lineage signal is NOT an
indication-level biomarker. Fix: the §0 amp-expr biomarker rungs (biomarker_stratified_dependency /
moderate_biomarker_dependency, driven by amp-expr-{strongly,moderately}-dependent-supportive) now also
require `amp-expr-indication-scoped-context`, which fires only when evidence_scope is within_indication
or within_indication_mut_vs_pan_wt. This pins that gate so pan-lineage amp-expr can't re-promote.

Mutation-stratified veto-suppressor rescues (EGFR/IDH1/FLT3) do NOT use amp-expr and are unaffected.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_ROOT = Path(__file__).resolve().parents[2]
RESOLVER = _ROOT / "resolvers" / "genomic_alteration.resolver.yaml"
RULES = _ROOT / "interpretation-rules" / "intracellular-intrinsic.rules.yaml"
CARD = _ROOT / "cards" / "amp-expr-stratified-dependency.card.yaml"

_AMPEXPR_DRIVER_RULES = {"amp-expr-strongly-dependent-supportive", "amp-expr-moderately-dependent-supportive"}
_SCOPE_GATE = "amp-expr-indication-scoped-context"


def test_ampexpr_biomarker_rungs_require_indication_scope():
    resolver = yaml.safe_load(RESOLVER.read_text())
    ampexpr_rungs = [
        r
        for r in resolver["resolve"]
        if _AMPEXPR_DRIVER_RULES
        & set(r.get("when_all_fired", []) or ([r["when_fired"]] if r.get("when_fired") else []))
    ]
    assert ampexpr_rungs, "expected amp-expr-driven biomarker rungs in the genomic resolver"
    for r in ampexpr_rungs:
        waf = set(r.get("when_all_fired", []))
        assert _SCOPE_GATE in waf, (
            f"amp-expr biomarker rung {r.get('verdict')} (driving_rule={r.get('driving_rule')}) keys on an "
            f"amp-expr dependency rule but does NOT require {_SCOPE_GATE!r} — a PAN-LINEAGE amp-expr signal "
            f"(evidence_scope=pan_lineage_evidence_only, the MARK2/PAAD bug) could be promoted to an "
            f"indication-level biomarker verdict. Gate the rung via when_all_fired."
        )


def test_ampexpr_scope_gate_rule_is_indication_scoped():
    """The gate rule must fire ONLY on indication-scoped evidence (not pan-lineage)."""
    rules = yaml.safe_load(RULES.read_text())
    gate = next((r for r in rules["rules"] if r.get("rule_id") == _SCOPE_GATE), None)
    assert gate is not None, f"{_SCOPE_GATE} rule missing from intracellular-intrinsic.rules.yaml"
    when = gate["when"]
    assert when["card_id"] == "amp-expr-stratified-dependency"
    assert when["field"] == "evidence_scope"
    assert set(when["in"]) == {"within_indication", "within_indication_mut_vs_pan_wt"}, (
        "scope gate must admit ONLY within-indication scopes; admitting pan_lineage_evidence_only or "
        "pan_no_indication would defeat the gate."
    )


def test_evidence_scope_vocabulary_declared():
    """The `in:` comparison requires the card to declare evidence_scope's vocabulary."""
    card = yaml.safe_load(CARD.read_text())
    vocab = card["outputs"]["summary_fields_vocabulary"]
    assert "evidence_scope" in vocab, "amp-expr card must declare evidence_scope vocabulary for the scope gate"
    assert {
        "within_indication",
        "within_indication_mut_vs_pan_wt",
        "pan_lineage_evidence_only",
        "pan_no_indication",
    } <= set(vocab["evidence_scope"])
