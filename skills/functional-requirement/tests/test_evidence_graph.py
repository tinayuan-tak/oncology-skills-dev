"""evidence_graph layer — functional-requirement's bespoke DATA assertions for its additive claim graph.

Ground truth is a committed KRAS·COADREAD decision.json fixture (a real FR run, trimmed to only the
fields build_evidence_graph reads). The shared decision/questions/graph fixtures + the structural
invariants (referential integrity, additivity, determinism, fail-soft, no-orphans) live in
skills/conftest.py and skills/tests/test_evidence_graph_invariants.py; this file keeps ONLY what is
specific to functional-requirement's graph.

Cards partition 11 verdict-bearing / 4 display-only, and the DEP/SEL/COND/CHEM literature axis→question
crosswalk resolves. VERDICT-INERT: nothing here touches the dependency_verdict spine.
"""
from __future__ import annotations

import copy

# cards that fire a rule in the KRAS/COADREAD fixture (verdict-bearing) vs the pure display-only facets
VERDICT_BEARING = {
    "pan-cancer-crispr-dependency-distribution", "pan-cancer-rnai-dependency-distribution",
    "crispr-rnai-dependency-concordance", "dependency-lineage-selectivity", "paralog-buffering",
    "prism-crispr-concordance", "recommended-models", "expression-dependency-correlation",
    "abundance-dependency", "dependency-predictability", "organoid-crispr-dependency",
}
DISPLAY_ONLY = {
    "cross-consortium-dependency", "partner-conditional-dependency", "coessential-module",
    "genomic-event-model-match",
}

# a synthetic literature_synthesis keyed by the FR lens axis LETTERS (what make_literature_fn emits)
_SYNTH_LIT = {
    "axes": [
        {"axis_key": "DEP", "literature_read": "supports", "assertion": "KRAS is an established dependency.",
         "agreement_vs_omics": "agree", "confidence": "high",
         "citations": [{"label": "Singh 2009", "pmid": "19490893", "verified": True}]},
        {"axis_key": "SEL", "literature_read": "supports", "assertion": "Lineage-selective in colorectal.",
         "agreement_vs_omics": "agree", "confidence": "moderate", "citations": []},
        {"axis_key": "COND", "literature_read": "mixed", "assertion": "SL partners reported.",
         "agreement_vs_omics": "omics_blind", "confidence": "low", "citations": []},
        {"axis_key": "CHEM", "literature_read": "supports", "assertion": "G12C inhibitors clinically active.",
         "agreement_vs_omics": "agree", "confidence": "high", "citations": []},
    ],
    "blind_spots": [], "overall_consistency": "consistent", "key_divergence": None,
}


# ── Phase 0 registry sanity ──────────────────────────────────────────────────────────────────────
def test_questions_registry_loads_seven(eg_questions):
    ids = [q["id"] for q in eg_questions]
    assert ids == ["lethal_at_all", "selective_or_pan_essential", "selective_to_lineage",
                   "crispr_rnai_agree", "conditional_sl_rescue", "chemically_confirmable",
                   "corroborated_predictable"]
    # unified axis vocabulary shared with the FR narrator lens (narrator_lenses.FUNCTIONAL_REQUIREMENT)
    axes = {q["axis_id"] for q in eg_questions if q.get("axis_id")}
    assert axes == {"DEP", "SEL", "COND", "CHEM"}
    # legacy_id join keys mirror the emitted dependency_question_table (Q1..Q7)
    assert [q["legacy_id"] for q in eg_questions] == [f"Q{i}" for i in range(1, 8)]


# ── role partition ─────────────────────────────────────────────────────────────────────────────────
def test_role_partition_11_verdict_bearing_4_display_only(eg_graph):
    vb = {c["id"] for c in eg_graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in eg_graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 11 and len(do) == 4 and len(eg_graph["cards"]) == 15


# ── reconstruction: questions with signal+confidence, each question's cards, no orphans ─────────────
def test_reconstruct_questions_signal_confidence_and_cards(eg_graph):
    qs = {q["id"]: q for q in eg_graph["questions"]}
    assert len(qs) == 7
    # signal + confidence readable off the graph (no prose parsing), matching the emitted question_table
    assert qs["lethal_at_all"]["signal"]["tier"] == "strong"
    assert qs["lethal_at_all"]["signal"]["polarity"] == "supportive"
    assert qs["lethal_at_all"]["confidence"]["level"] == "high"
    assert qs["crispr_rnai_agree"]["signal"]["polarity"] == "opposing"   # canonical (was legacy "opposes")
    # the many-to-many card join (measurement_type membership)
    assert set(qs["lethal_at_all"]["card_ids"]) == {
        "pan-cancer-crispr-dependency-distribution", "pan-cancer-rnai-dependency-distribution",
        "dependency-lineage-selectivity", "organoid-crispr-dependency"}
    assert set(qs["crispr_rnai_agree"]["card_ids"]) == {"crispr-rnai-dependency-concordance"}
    assert set(qs["conditional_sl_rescue"]["card_ids"]) == {
        "paralog-buffering", "partner-conditional-dependency"}
    assert set(qs["corroborated_predictable"]["card_ids"]) == {
        "cross-consortium-dependency", "dependency-predictability", "coessential-module"}
    # the SEL question anchors both the lineage driver AND the biomarker/model facet cards
    assert set(qs["selective_to_lineage"]["card_ids"]) >= {
        "dependency-lineage-selectivity", "expression-dependency-correlation", "abundance-dependency",
        "recommended-models", "genomic-event-model-match"}
    # every card joins at least one question (nothing collapses into the "Other" layer)
    assert all(c["question_ids"] for c in eg_graph["cards"])
    # a shared measurement_type materializes both edge directions
    crispr = next(c for c in eg_graph["cards"] if c["id"] == "pan-cancer-crispr-dependency-distribution")
    assert set(crispr["question_ids"]) == {
        "lethal_at_all", "selective_or_pan_essential", "selective_to_lineage"}


# ── literature DEP/SEL/COND/CHEM axis crosswalk ─────────────────────────────────────────────────────
def test_literature_axis_crosswalk(eg_decision, eg_questions, eg_build):
    d = copy.deepcopy(eg_decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = eg_build(d, questions=eg_questions)
    axes = {ax["axis_id"]: ax for ax in g["literature"]["axes"]}
    assert set(axes) == {"DEP", "SEL", "COND", "CHEM"}
    assert axes["DEP"]["question_ids"] == ["lethal_at_all", "selective_or_pan_essential"]
    assert axes["SEL"]["question_ids"] == ["selective_to_lineage"]
    assert axes["COND"]["question_ids"] == ["conditional_sl_rescue"]
    assert axes["CHEM"]["question_ids"] == ["chemically_confirmable"]
    # crosswalk materialized on the question node too
    q1 = next(q for q in g["questions"] if q["id"] == "lethal_at_all")
    assert q1["literature_axis_ids"] == ["DEP"]
    # corroboration questions (crispr_rnai_agree, corroborated_predictable) are NOT literature targets
    for cid in ("crispr_rnai_agree", "corroborated_predictable"):
        q = next(q for q in g["questions"] if q["id"] == cid)
        assert q["literature_axis_ids"] == []
    # citations hoisted + referentially intact
    cit_ids = {c["id"] for c in g["citations"]}
    assert "singh2009" in cit_ids
    assert axes["DEP"]["citation_ids"] == ["singh2009"]


# ── each card's dataset→data→rule→verdict chain (no .card.yaml, no prose) ───────────────────────────
def test_driving_card_chain(eg_graph):
    lin = next(c for c in eg_graph["cards"] if c["id"] == "dependency-lineage-selectivity")
    assert lin["class"] == {"field": "enrichment_class", "value": "lineage_selective"}
    assert lin["chain"]["rule_id"] == "lineage-selective-supportive"
    assert lin["chain"]["contributes_to_verdict"] is True
    assert lin["chain"]["is_driving"] is True
    # a display-only card never invents a rule
    do = next(c for c in eg_graph["cards"] if c["id"] == "partner-conditional-dependency")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(eg_graph, eg_decision):
    assert eg_graph["verdict"]["id"] == eg_decision["headline"]["dependency_verdict"] == "lineage_selective"
    assert eg_graph["verdict"]["driving_rule_id"] == "lineage-selective-supportive"
    assert eg_graph["verdict"]["polarity"] == "supportive"   # canonical (was legacy "positive")
