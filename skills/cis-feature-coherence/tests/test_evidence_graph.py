"""evidence_graph layer — cis-feature-coherence's bespoke DATA assertions for its additive claim graph.

Ground truth is a committed KRAS·COADREAD decision.json fixture (a real cis-feature-coherence run,
trimmed to only the fields build_evidence_graph reads). The shared decision/questions/graph fixtures + the
structural invariants (referential integrity, additivity, determinism, fail-soft, no-orphans) live in
skills/conftest.py and skills/tests/test_evidence_graph_invariants.py; this file keeps ONLY what is
specific to cis-feature-coherence's graph.

GATELESS / DESCRIPTIVE skill: cis-feature-coherence is verdict-INERT at composition — top-level
decision["verdict"] is None. It STILL resolves a headline cis_coherence_verdict token via the shared 2×2
cross-tab resolver, so the graph's verdict node carries the resolved coherence class (here coherent_cis_
driver) rather than None. The verdict asserts below are therefore NULL-TOLERANT: the resolved-token path is
pinned for this fixture. Nothing here touches the cis_coherence_verdict spine.
"""

from __future__ import annotations

import copy

# cards that FIRE a cis_coherence rule in the KRAS/COADREAD fixture (verdict-bearing) vs the pure
# display-only facets (the verdict-INERT protein / abundance / patient / molecular-form legs).
VERDICT_BEARING = {
    "cis-feature-expression-coherence",
    "expression-dependency-correlation",
    "amp-expr-stratified-dependency",
}
DISPLAY_ONLY = {
    "cis-feature-protein-coherence",
    "cellline-methylation-expression-coherence",
    "abundance-dependency",
    "patient-cis-coherence",
    "cellline-isoform-dominance",
    "cellline-isoform-expression",
}
ALL_CARDS = VERDICT_BEARING | DISPLAY_ONLY

# a synthetic literature_synthesis keyed by the cis-feature-coherence lens axis KEYS (what
# make_literature_fn emits from narrator_lenses.CIS_FEATURE_COHERENCE.axis_labels).
_SYNTH_LIT = {
    "axes": [
        {
            "axis_key": "CIS_DOSAGE",
            "literature_read": "supports",
            "assertion": "KRAS amplification drives its own expression.",
            "agreement_vs_omics": "agree",
            "confidence": "high",
            "citations": [{"label": "Singh 2009", "pmid": "19490893", "verified": True}],
        },
        {
            "axis_key": "SILENCING",
            "literature_read": "n/a",
            "assertion": "No promoter silencing reported.",
            "agreement_vs_omics": "omics_blind",
            "confidence": "low",
            "citations": [],
        },
        {
            "axis_key": "EXPR_DEP",
            "literature_read": "supports",
            "assertion": "Expression tracks dependency.",
            "agreement_vs_omics": "agree",
            "confidence": "moderate",
            "citations": [],
        },
        {
            "axis_key": "CONJOINT",
            "literature_read": "mixed",
            "assertion": "Amp∩overexpr addiction context.",
            "agreement_vs_omics": "agree",
            "confidence": "moderate",
            "citations": [],
        },
    ],
    "blind_spots": [],
    "overall_consistency": "consistent",
    "key_divergence": None,
}


# ── Phase 0 registry sanity ──────────────────────────────────────────────────────────────────────
def test_questions_registry_loads_four(eg_questions):
    ids = [q["id"] for q in eg_questions]
    assert ids == ["cis_dosage_read", "silencing_read", "expr_dep_read", "conjoint_read"]
    # unified axis vocabulary shared with the cis-feature-coherence narrator lens
    axes = {q["axis_id"] for q in eg_questions if q.get("axis_id")}
    assert axes == {"CIS_DOSAGE", "SILENCING", "EXPR_DEP", "CONJOINT"}
    # legacy_id join keys mirror the emitted cis_coherence_question_table (Q1..Q4)
    assert [q["legacy_id"] for q in eg_questions] == [f"Q{i}" for i in range(1, 5)]
    # every axis-owning question is non-corroboration so every lens axis resolves in the crosswalk
    assert all(q["role"] != "corroboration" for q in eg_questions if q.get("axis_id"))


# ── role partition (card-level: only rule-firing legs are verdict-bearing) ──────────────────────────
def test_role_partition_3_verdict_bearing_6_display_only(eg_graph):
    vb = {c["id"] for c in eg_graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in eg_graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 3 and len(do) == 6 and len(eg_graph["cards"]) == 9


# ── reconstruction: questions with signal+confidence, each question's cards, no orphans ─────────────
def test_reconstruct_questions_signal_and_cards(eg_graph):
    qs = {q["id"]: q for q in eg_graph["questions"]}
    assert len(qs) == 4
    # signal readable off the graph (no prose parsing), matching the emitted question_table. This
    # verdict-INERT skill's question_table polarity is "informs" (never supports/opposes a nomination).
    assert qs["cis_dosage_read"]["signal"]["tier"] == "strong"
    assert qs["cis_dosage_read"]["signal"]["polarity"] == "informs"
    assert qs["silencing_read"]["signal"]["tier"] == "unmeasured"  # methylation_invariant_panel
    # the many-to-many card join (measurement_type membership) — protein sibling + molecular-form
    # context cards anchor to the CIS_DOSAGE leg they inform.
    assert set(qs["cis_dosage_read"]["card_ids"]) == {
        "cis-feature-expression-coherence",
        "cis-feature-protein-coherence",
        "cellline-isoform-dominance",
        "cellline-isoform-expression",
    }
    assert set(qs["silencing_read"]["card_ids"]) == {"cellline-methylation-expression-coherence"}
    assert set(qs["expr_dep_read"]["card_ids"]) == {"expression-dependency-correlation", "abundance-dependency"}
    assert set(qs["conjoint_read"]["card_ids"]) == {"amp-expr-stratified-dependency", "patient-cis-coherence"}
    # every card joins at least one question (nothing collapses into the "Other" layer)
    assert all(c["question_ids"] for c in eg_graph["cards"])
    # the driving leg materializes both edge directions
    cis = next(c for c in eg_graph["cards"] if c["id"] == "cis-feature-expression-coherence")
    assert cis["question_ids"] == ["cis_dosage_read"]


# ── literature CIS_DOSAGE/SILENCING/EXPR_DEP/CONJOINT axis crosswalk ─────────────────────────────────
def test_literature_axis_crosswalk(eg_decision, eg_questions, eg_build):
    d = copy.deepcopy(eg_decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = eg_build(d, questions=eg_questions)
    axes = {ax["axis_id"]: ax for ax in g["literature"]["axes"]}
    assert set(axes) == {"CIS_DOSAGE", "SILENCING", "EXPR_DEP", "CONJOINT"}
    assert axes["CIS_DOSAGE"]["question_ids"] == ["cis_dosage_read"]
    assert axes["SILENCING"]["question_ids"] == ["silencing_read"]
    assert axes["EXPR_DEP"]["question_ids"] == ["expr_dep_read"]
    assert axes["CONJOINT"]["question_ids"] == ["conjoint_read"]
    # crosswalk materialized on the question node too — every lens axis resolves (no corroboration
    # questions here, so no dangling literature axis)
    q1 = next(q for q in g["questions"] if q["id"] == "cis_dosage_read")
    assert q1["literature_axis_ids"] == ["CIS_DOSAGE"]
    # citations hoisted + referentially intact
    cit_ids = {c["id"] for c in g["citations"]}
    assert "singh2009" in cit_ids
    assert axes["CIS_DOSAGE"]["citation_ids"] == ["singh2009"]


# ── each card's dataset→data→rule→verdict chain (no .card.yaml, no prose) ───────────────────────────
def test_driving_card_chain(eg_graph):
    cis = next(c for c in eg_graph["cards"] if c["id"] == "cis-feature-expression-coherence")
    assert cis["chain"]["rule_id"] == "cis-dosage-coupled-supportive"
    assert cis["chain"]["contributes_to_verdict"] is True
    assert cis["chain"]["is_driving"] is True
    # exactly one driving card, and it matches the verdict's driving_rule_id
    driving = [c["id"] for c in eg_graph["cards"] if c["chain"]["is_driving"]]
    assert driving == ["cis-feature-expression-coherence"]
    # a display-only (verdict-inert) card never invents a rule
    do = next(c for c in eg_graph["cards"] if c["id"] == "patient-cis-coherence")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(eg_graph, eg_decision):
    # NULL-TOLERANT: the top-level decision verdict is None (verdict-inert), but the headline resolves
    # a cis_coherence_verdict token that the graph's verdict node carries.
    assert eg_decision.get("verdict") is None
    assert eg_decision["headline"]["cis_coherence_verdict"] == "coherent_cis_driver"
    assert eg_graph["verdict"]["id"] == "coherent_cis_driver"
    assert eg_graph["verdict"]["driving_rule_id"] == "cis-dosage-coupled-supportive"
    assert eg_graph["verdict"]["polarity"] == "supportive"  # canonical (was legacy "positive")
