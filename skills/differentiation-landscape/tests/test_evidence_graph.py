"""evidence_graph layer — differentiation-landscape's bespoke DATA assertions for its additive claim graph.

Ground truth is a committed KRAS·COADREAD decision.json fixture (a real differentiation-landscape run,
trimmed to only the fields build_evidence_graph reads). The shared decision/questions/graph fixtures + the
structural invariants (referential integrity, additivity, determinism, fail-soft, no-orphans) live in
skills/conftest.py and skills/tests/test_evidence_graph_invariants.py; this file keeps ONLY what is
specific to differentiation-landscape's graph.

Cards partition 4 verdict-bearing / 5 display-only (verdict-bearing == cards that FIRED a rule — only the
co-mutation card feeds the differentiation token; the expression/alteration/subtype cards fire neutral
facet rules; the rest fire none), and the COMUT/SURVIVAL/PROGNOSIS/NODE literature axis→question crosswalk
resolves.

GATELESS / verdict-INERT: differentiation-landscape runs mode=verdict and DOES emit a resolved token
(both_patterns_present) with a driving_rule_id, but the token is DESCRIPTIVE and moves no nomination
gate — nothing here touches the differentiation_verdict spine.
"""
from __future__ import annotations

import copy

# cards that FIRE a rule in the KRAS/COADREAD fixture (graph role verdict_bearing) vs the pure
# display-only facets (fired no rule). Only the co-mutation card drives the differentiation token; the
# expression / alteration / subtype cards fire NEUTRAL facet rules (feed no resolver); the rest none.
VERDICT_BEARING = {
    "co-mutation-and-mutual-exclusivity", "expression-clinical-association",
    "alteration-clinical-association", "subtype-survival-association",
}
DISPLAY_ONLY = {
    "stemness-context", "precog-prognostic-association", "pathway-node-leverage",
    "clinical-precedent", "competitor-landscape",
}

# a synthetic literature_synthesis keyed by the differentiation lens axis LETTERS (what make_literature_fn
# emits: narrator_lenses.DIFFERENTIATION_LANDSCAPE.axis_labels COMUT/SURVIVAL/PROGNOSIS/NODE)
_SYNTH_LIT = {
    "axes": [
        {"axis_key": "COMUT", "literature_read": "supports",
         "assertion": "KRAS co-mutates with APC/TP53 in colorectal cancer.",
         "agreement_vs_omics": "agree", "confidence": "high",
         "citations": [{"label": "Vogelstein 2013", "pmid": "23539594", "verified": True}]},
        {"axis_key": "SURVIVAL", "literature_read": "mixed",
         "assertion": "CMS molecular subtypes stratify overall survival.",
         "agreement_vs_omics": "agree", "confidence": "moderate", "citations": []},
        {"axis_key": "PROGNOSIS", "literature_read": "supports",
         "assertion": "KRAS-mutant expression is prognostic in some cohorts.",
         "agreement_vs_omics": "mixed", "confidence": "low", "citations": []},
        {"axis_key": "NODE", "literature_read": "supports",
         "assertion": "KRAS is a dominant MAPK-pathway node.",
         "agreement_vs_omics": "agree", "confidence": "high", "citations": []},
    ],
    "blind_spots": [], "overall_consistency": "consistent", "key_divergence": None,
}


# ── Phase 0 registry sanity ──────────────────────────────────────────────────────────────────────
def test_questions_registry_loads_five(eg_questions):
    ids = [q["id"] for q in eg_questions]
    assert ids == ["comut_landscape", "subtype_survival", "prognostic_stratification",
                   "node_leverage", "clinical_precedent"]
    # unified axis vocabulary shared with the differentiation narrator lens
    # (narrator_lenses.DIFFERENTIATION_LANDSCAPE.axis_labels)
    axes = {q["axis_id"] for q in eg_questions if q.get("axis_id")}
    assert axes == {"COMUT", "SURVIVAL", "PROGNOSIS", "NODE"}
    # legacy_id join keys mirror the emitted differentiation_question_table (Q1..Q4); the SURVIVAL
    # question (subtype-survival) has NO emitted row → no legacy_id.
    by_id = {q["id"]: q for q in eg_questions}
    assert by_id["comut_landscape"]["legacy_id"] == "Q1"
    assert by_id["prognostic_stratification"]["legacy_id"] == "Q2"
    assert by_id["node_leverage"]["legacy_id"] == "Q3"
    assert by_id["clinical_precedent"]["legacy_id"] == "Q4"
    assert "legacy_id" not in by_id["subtype_survival"]
    # exactly one verdict_bearing question (the co-mutation token driver); the rest are render facets
    assert by_id["comut_landscape"]["role"] == "verdict_bearing"
    assert {q["id"] for q in eg_questions if q["role"] == "verdict_bearing"} == {"comut_landscape"}


# ── role partition ─────────────────────────────────────────────────────────────────────────────────
def test_role_partition_4_verdict_bearing_5_display_only(eg_graph):
    vb = {c["id"] for c in eg_graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in eg_graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 4 and len(do) == 5 and len(eg_graph["cards"]) == 9


# ── reconstruction: questions with signal+confidence, each question's cards, no orphans ─────────────
def test_reconstruct_questions_signal_confidence_and_cards(eg_graph):
    qs = {q["id"]: q for q in eg_graph["questions"]}
    assert len(qs) == 5
    # the co-mutation question carries the driving rule + a supportive read off the graph (no prose)
    assert qs["comut_landscape"]["signal"]["polarity"] == "informs"   # question_table Signal is descriptive
    assert qs["comut_landscape"]["confidence"]["level"] == "moderate"
    # the many-to-many card join (measurement_type membership)
    assert set(qs["comut_landscape"]["card_ids"]) == {"co-mutation-and-mutual-exclusivity"}
    assert set(qs["subtype_survival"]["card_ids"]) == {"subtype-survival-association"}
    assert set(qs["prognostic_stratification"]["card_ids"]) == {
        "expression-clinical-association", "precog-prognostic-association",
        "alteration-clinical-association"}
    assert set(qs["node_leverage"]["card_ids"]) == {"stemness-context", "pathway-node-leverage"}
    assert set(qs["clinical_precedent"]["card_ids"]) == {"clinical-precedent", "competitor-landscape"}
    # the subtype-survival question has no emitted question_table row → null signal (legacy_id omitted)
    assert qs["subtype_survival"]["signal"]["tier"] is None
    assert qs["subtype_survival"]["confidence"]["level"] is None
    # every card joins at least one question (nothing collapses into the "Other" layer)
    assert all(c["question_ids"] for c in eg_graph["cards"])
    # the prognostic question owns all three single-cohort / meta prognostic cards
    prog = next(c for c in eg_graph["cards"] if c["id"] == "precog-prognostic-association")
    assert prog["question_ids"] == ["prognostic_stratification"]


# ── literature COMUT/SURVIVAL/PROGNOSIS/NODE axis crosswalk ─────────────────────────────────────────
def test_literature_axis_crosswalk(eg_decision, eg_questions, eg_build):
    d = copy.deepcopy(eg_decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = eg_build(d, questions=eg_questions)
    axes = {ax["axis_id"]: ax for ax in g["literature"]["axes"]}
    assert set(axes) == {"COMUT", "SURVIVAL", "PROGNOSIS", "NODE"}
    assert axes["COMUT"]["question_ids"] == ["comut_landscape"]
    assert axes["SURVIVAL"]["question_ids"] == ["subtype_survival"]
    assert axes["PROGNOSIS"]["question_ids"] == ["prognostic_stratification"]
    assert axes["NODE"]["question_ids"] == ["node_leverage"]
    # the precedent question owns no axis, so no literature axis crosswalks onto it
    q = next(q for q in g["questions"] if q["id"] == "clinical_precedent")
    assert q["literature_axis_ids"] == []
    # crosswalk materialized on the axis-owning question nodes
    for qid, ax in (("comut_landscape", "COMUT"), ("subtype_survival", "SURVIVAL"),
                    ("prognostic_stratification", "PROGNOSIS"), ("node_leverage", "NODE")):
        node = next(q for q in g["questions"] if q["id"] == qid)
        assert node["literature_axis_ids"] == [ax]
    # citations hoisted + referentially intact
    cit_ids = {c["id"] for c in g["citations"]}
    assert "vogelstein2013" in cit_ids
    assert axes["COMUT"]["citation_ids"] == ["vogelstein2013"]


# ── each card's dataset→data→rule→verdict chain (no .card.yaml, no prose) ───────────────────────────
def test_driving_card_chain(eg_graph):
    cm = next(c for c in eg_graph["cards"] if c["id"] == "co-mutation-and-mutual-exclusivity")
    # class read off the first fired rule on the driving card
    assert cm["class"] == {"field": "has_cooccurring_driver", "value": True}
    assert cm["chain"]["contributes_to_verdict"] is True
    assert cm["chain"]["is_driving"] is True
    assert "cooccurrence-both-patterns-supportive" in cm["rule_ids"]
    # a display-only card never invents a rule
    do = next(c for c in eg_graph["cards"] if c["id"] == "pathway-node-leverage")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(eg_graph, eg_decision):
    assert eg_graph["verdict"]["id"] == eg_decision["headline"]["differentiation_verdict"] == "both_patterns_present"
    assert eg_graph["verdict"]["driving_rule_id"] == "cooccurrence-both-patterns-supportive"
    # descriptive skill — every verdict colours the hero badge neutral (direction lives in the atom)
    assert eg_graph["verdict"]["polarity"] == "neutral"
    # exactly one card is the driving card, and it matches the driving rule
    drv = [c["id"] for c in eg_graph["cards"] if c["chain"]["is_driving"]]
    assert drv == ["co-mutation-and-mutual-exclusivity"]
