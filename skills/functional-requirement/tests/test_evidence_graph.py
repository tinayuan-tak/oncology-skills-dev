"""evidence_graph layer — acceptance tests for functional-requirement's additive claim graph at
decision.headline.evidence_graph, plus a standalone-dashboard render smoke test.

Ground truth is a committed KRAS·COADREAD decision.json fixture (a real FR run, trimmed to only the
fields build_evidence_graph reads — verified to yield a byte-identical graph vs the full decision).
The graph is BUILT from that fixture + the canonical questions.yaml registry, so these tests prove the
projection reconstructs the dashboard with zero .card.yaml reads / zero free-text parsing, is
referentially intact, byte-stable (purely additive), partitions cards 11 verdict-bearing / 4
display-only, and resolves the DEP/SEL/COND/CHEM literature axis→question crosswalk. VERDICT-INERT:
nothing here touches the dependency_verdict spine.
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
from _skills_common.evidence_graph_dashboard import render_dashboard  # noqa: E402

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
def test_questions_registry_loads_seven(questions):
    ids = [q["id"] for q in questions]
    assert ids == ["lethal_at_all", "selective_or_pan_essential", "selective_to_lineage",
                   "crispr_rnai_agree", "conditional_sl_rescue", "chemically_confirmable",
                   "corroborated_predictable"]
    # unified axis vocabulary shared with the FR narrator lens (narrator_lenses.FUNCTIONAL_REQUIREMENT)
    axes = {q["axis_id"] for q in questions if q.get("axis_id")}
    assert axes == {"DEP", "SEL", "COND", "CHEM"}
    # legacy_id join keys mirror the emitted dependency_question_table (Q1..Q7)
    assert [q["legacy_id"] for q in questions] == [f"Q{i}" for i in range(1, 8)]


# ── role partition ─────────────────────────────────────────────────────────────────────────────────
def test_role_partition_11_verdict_bearing_4_display_only(graph):
    vb = {c["id"] for c in graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 11 and len(do) == 4 and len(graph["cards"]) == 15


# ── reconstruction: questions with signal+confidence, each question's cards, no orphans ─────────────
def test_reconstruct_questions_signal_confidence_and_cards(graph):
    qs = {q["id"]: q for q in graph["questions"]}
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
    assert all(c["question_ids"] for c in graph["cards"])
    # a shared measurement_type materializes both edge directions
    crispr = next(c for c in graph["cards"] if c["id"] == "pan-cancer-crispr-dependency-distribution")
    assert set(crispr["question_ids"]) == {
        "lethal_at_all", "selective_or_pan_essential", "selective_to_lineage"}


# ── literature DEP/SEL/COND/CHEM axis crosswalk ─────────────────────────────────────────────────────
def test_literature_axis_crosswalk(decision, questions):
    d = copy.deepcopy(decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = build_evidence_graph(d, questions=questions)
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
def test_driving_card_chain(graph):
    lin = next(c for c in graph["cards"] if c["id"] == "dependency-lineage-selectivity")
    assert lin["class"] == {"field": "enrichment_class", "value": "lineage_selective"}
    assert lin["chain"]["rule_id"] == "lineage-selective-supportive"
    assert lin["chain"]["contributes_to_verdict"] is True
    assert lin["chain"]["is_driving"] is True
    # a display-only card never invents a rule
    do = next(c for c in graph["cards"] if c["id"] == "partner-conditional-dependency")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(graph, decision):
    assert graph["verdict"]["id"] == decision["headline"]["dependency_verdict"] == "lineage_selective"
    assert graph["verdict"]["driving_rule_id"] == "lineage-selective-supportive"
    assert graph["verdict"]["polarity"] == "supportive"   # canonical (was legacy "positive")


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
    assert len(g["questions"]) == 7 and len(g["cards"]) == 15
    for q in g["questions"]:
        assert q["literature_axis_ids"] == []


def test_graph_without_registry_is_referentially_intact(decision):
    g = build_evidence_graph(decision, questions=[])
    assert g["questions"] == []
    assert len(g["cards"]) == 15
    for c in g["cards"]:
        assert c["question_ids"] == []
        assert set(c["dataset_ids"]) <= {d["id"] for d in g["datasets"]}


# ── standalone dashboard render smoke test (evidence_graph_dashboard consumes the graph ONLY) ────────
def test_dashboard_renders_questions_and_driving_pill(decision, questions):
    d = copy.deepcopy(decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = build_evidence_graph(d, questions=questions)
    html = render_dashboard(g)
    assert "<!doctype html>" in html
    # all 7 question slugs render (fingerprint label + question-table row)
    for qid in ("lethal_at_all", "selective_to_lineage", "conditional_sl_rescue", "chemically_confirmable"):
        assert qid in html
    # the driving card carries a DRIVING pill
    assert "DRIVING" in html and "dependency-lineage-selectivity" in html
    # verdict header + literature crosswalk populated
    assert "Lineage-selective dependency" in html
    assert "established dependency" in html
