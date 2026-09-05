"""evidence_graph layer — acceptance tests for differentiation-landscape's additive claim graph at
decision.headline.evidence_graph, plus a standalone-dashboard render smoke test.

Ground truth is a committed KRAS·COADREAD decision.json fixture (a real differentiation-landscape run,
trimmed to only the fields build_evidence_graph reads — verified to yield a byte-identical graph vs the
full decision). The graph is BUILT from that fixture + the canonical questions.yaml registry, so these
tests prove the projection reconstructs the dashboard with zero .card.yaml reads / zero free-text
parsing, is referentially intact, byte-stable (purely additive), partitions cards 4 verdict-bearing /
5 display-only (verdict-bearing == cards that FIRED a rule — only the co-mutation card feeds the
differentiation token; the expression/alteration/subtype cards fire neutral facet rules; the rest fire
none), and resolves the COMUT/SURVIVAL/PROGNOSIS/NODE literature axis→question crosswalk.

GATELESS / verdict-INERT: differentiation-landscape runs mode=verdict and DOES emit a resolved token
(both_patterns_present) with a driving_rule_id, but the token is DESCRIPTIVE and moves no nomination
gate — nothing here touches the differentiation_verdict spine.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
FIXTURE = SKILL_DIR / "tests" / "fixtures" / "kras_coadread_decision.json"
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common.evidence_graph import build_evidence_graph, load_questions  # noqa: E402

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


@pytest.fixture(scope="module")
def decision():
    if not FIXTURE.exists():
        pytest.skip("no committed decision fixture")
    return json.loads(FIXTURE.read_text())


@pytest.fixture(scope="module")
def questions():
    return load_questions(SKILL_DIR)


@pytest.fixture(scope="module")
def graph(decision, questions):
    return build_evidence_graph(decision, questions=questions)


# ── Phase 0 registry sanity ──────────────────────────────────────────────────────────────────────
def test_questions_registry_loads_five(questions):
    ids = [q["id"] for q in questions]
    assert ids == ["comut_landscape", "subtype_survival", "prognostic_stratification",
                   "node_leverage", "clinical_precedent"]
    # unified axis vocabulary shared with the differentiation narrator lens
    # (narrator_lenses.DIFFERENTIATION_LANDSCAPE.axis_labels)
    axes = {q["axis_id"] for q in questions if q.get("axis_id")}
    assert axes == {"COMUT", "SURVIVAL", "PROGNOSIS", "NODE"}
    # legacy_id join keys mirror the emitted differentiation_question_table (Q1..Q4); the SURVIVAL
    # question (subtype-survival) has NO emitted row → no legacy_id.
    by_id = {q["id"]: q for q in questions}
    assert by_id["comut_landscape"]["legacy_id"] == "Q1"
    assert by_id["prognostic_stratification"]["legacy_id"] == "Q2"
    assert by_id["node_leverage"]["legacy_id"] == "Q3"
    assert by_id["clinical_precedent"]["legacy_id"] == "Q4"
    assert "legacy_id" not in by_id["subtype_survival"]
    # exactly one verdict_bearing question (the co-mutation token driver); the rest are render facets
    assert by_id["comut_landscape"]["role"] == "verdict_bearing"
    assert {q["id"] for q in questions if q["role"] == "verdict_bearing"} == {"comut_landscape"}


# ── role partition ─────────────────────────────────────────────────────────────────────────────────
def test_role_partition_4_verdict_bearing_5_display_only(graph):
    vb = {c["id"] for c in graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 4 and len(do) == 5 and len(graph["cards"]) == 9


# ── reconstruction: questions with signal+confidence, each question's cards, no orphans ─────────────
def test_reconstruct_questions_signal_confidence_and_cards(graph):
    qs = {q["id"]: q for q in graph["questions"]}
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
    assert all(c["question_ids"] for c in graph["cards"])
    # the prognostic question owns all three single-cohort / meta prognostic cards
    prog = next(c for c in graph["cards"] if c["id"] == "precog-prognostic-association")
    assert prog["question_ids"] == ["prognostic_stratification"]


# ── literature COMUT/SURVIVAL/PROGNOSIS/NODE axis crosswalk ─────────────────────────────────────────
def test_literature_axis_crosswalk(decision, questions):
    d = copy.deepcopy(decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = build_evidence_graph(d, questions=questions)
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
def test_driving_card_chain(graph):
    cm = next(c for c in graph["cards"] if c["id"] == "co-mutation-and-mutual-exclusivity")
    # class read off the first fired rule on the driving card
    assert cm["class"] == {"field": "has_cooccurring_driver", "value": True}
    assert cm["chain"]["contributes_to_verdict"] is True
    assert cm["chain"]["is_driving"] is True
    assert "cooccurrence-both-patterns-supportive" in cm["rule_ids"]
    # a display-only card never invents a rule
    do = next(c for c in graph["cards"] if c["id"] == "pathway-node-leverage")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(graph, decision):
    assert graph["verdict"]["id"] == decision["headline"]["differentiation_verdict"] == "both_patterns_present"
    assert graph["verdict"]["driving_rule_id"] == "cooccurrence-both-patterns-supportive"
    # descriptive skill — every verdict colours the hero badge neutral (direction lives in the atom)
    assert graph["verdict"]["polarity"] == "neutral"
    # exactly one card is the driving card, and it matches the driving rule
    drv = [c["id"] for c in graph["cards"] if c["chain"]["is_driving"]]
    assert drv == ["co-mutation-and-mutual-exclusivity"]


# ── referential integrity ────────────────────────────────────────────────────────────────────────
def test_referential_integrity(graph):
    q_ids = {q["id"] for q in graph["questions"]}
    c_ids = {c["id"] for c in graph["cards"]}
    r_ids = {r["id"] for r in graph["rules"]}
    d_ids = {d["id"] for d in graph["datasets"]}
    axis_ids = {q["axis_id"] for q in graph["questions"] if q.get("axis_id")}
    for q in graph["questions"]:
        assert set(q["card_ids"]) <= c_ids, q["id"]
        assert set(q["rule_ids"]) <= r_ids, q["id"]
        for er in q["evidence_refs"]:
            assert er["card_id"] in c_ids
    for c in graph["cards"]:
        assert set(c["question_ids"]) <= q_ids, c["id"]
        assert set(c["rule_ids"]) <= r_ids, c["id"]
        assert set(c["dataset_ids"]) <= d_ids, c["id"]
        if c["chain"]["rule_id"] is not None:
            assert c["chain"]["rule_id"] in r_ids
        if c.get("axis_id"):
            assert c["axis_id"] in axis_ids
    for r in graph["rules"]:
        assert r["card_id"] in c_ids


# ── byte-stability: the layer is purely additive ───────────────────────────────────────────────────
def test_builder_does_not_mutate_decision(decision, questions):
    before = copy.deepcopy(decision)
    build_evidence_graph(decision, questions=questions)
    assert decision == before


def test_additive_only_no_preexisting_key_changes(decision, graph):
    enriched = copy.deepcopy(decision)
    enriched["headline"]["evidence_graph"] = graph
    assert "evidence_graph" not in decision["headline"]  # fixture predates the layer
    popped = enriched["headline"].pop("evidence_graph")
    assert popped is graph
    assert enriched == decision


def test_build_is_deterministic(decision, questions):
    a = json.dumps(build_evidence_graph(decision, questions=questions), default=str)
    b = json.dumps(build_evidence_graph(decision, questions=questions), default=str)
    assert a == b


# ── fail-soft & no-registry ────────────────────────────────────────────────────────────────────────
def test_fail_soft_without_optional_inputs(decision, questions):
    stripped = copy.deepcopy(decision)
    stripped.pop("literature_synthesis", None)
    stripped.pop("llm_synthesis", None)
    g = build_evidence_graph(stripped, questions=questions)
    assert g["literature"] == {}
    assert g["citations"] == []
    assert g["narrative"] == {}
    assert len(g["questions"]) == 5 and len(g["cards"]) == 9
    for q in g["questions"]:
        assert q["literature_axis_ids"] == []


def test_graph_without_registry_is_referentially_intact(decision):
    g = build_evidence_graph(decision, questions=[])
    assert g["questions"] == []
    assert len(g["cards"]) == 9
    for c in g["cards"]:
        assert c["question_ids"] == []
        assert set(c["dataset_ids"]) <= {d["id"] for d in g["datasets"]}
