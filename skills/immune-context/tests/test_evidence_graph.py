"""evidence_graph layer — acceptance tests for immune-context's additive claim graph at
decision.headline.evidence_graph, plus a standalone-dashboard render smoke test.

Ground truth is a committed KRAS·COADREAD decision.json fixture (a real immune-context run, trimmed to
only the fields build_evidence_graph reads — verified to yield a byte-identical graph vs the full
decision). The graph is BUILT from that fixture + the canonical questions.yaml registry, so these tests
prove the projection reconstructs the dashboard with zero .card.yaml reads / zero free-text parsing, is
referentially intact, byte-stable (purely additive), partitions cards 1 verdict-bearing / 5
display-only, and resolves the single IMMUNE literature axis→question crosswalk.

immune-context is a GATELESS-in-spirit but mode=verdict skill: a SINGLE immune-context rule fires
(immune_context_class → immune_context_verdict, a direct read), so exactly one card is verdict-bearing
(immune-context, the driving card) and the other five are verdict-inert display context. VERDICT-INERT:
nothing here touches the immune_context_verdict spine.
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

# the ONE card that fires a rule in the KRAS/COADREAD fixture (verdict-bearing) vs the pure display-only
# TME/immune context facets. immune-context's verdict is a direct read of immune_context_class, so only
# the immune-context card is verdict-bearing.
VERDICT_BEARING = {"immune-context"}
DISPLAY_ONLY = {
    "myeloid-compartment-expression-cheng", "caf-compartment-expression-luo",
    "ici-response-association", "ici-response-imvigor210", "tcga-til-fraction-saltz",
}

# a synthetic literature_synthesis keyed by the immune-context lens's SINGLE axis (what
# make_literature_fn(IMMUNE_CONTEXT) emits — narrator_lenses.IMMUNE_CONTEXT.axis_labels = {IMMUNE: ...}).
_SYNTH_LIT = {
    "axes": [
        {"axis_key": "IMMUNE", "literature_read": "supports",
         "assertion": "COADREAD carries a moderate CD8 effector infiltrate.",
         "agreement_vs_omics": "agree", "confidence": "moderate",
         "citations": [{"label": "Thorsson 2018", "pmid": "29628290", "verified": True}]},
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
def test_questions_registry_loads_three(questions):
    ids = [q["id"] for q in questions]
    assert ids == ["infiltration", "ici_response", "microenvironment"]
    # single lens axis, shared with the immune-context narrator lens (narrator_lenses.IMMUNE_CONTEXT)
    axes = {q["axis_id"] for q in questions if q.get("axis_id")}
    assert axes == {"IMMUNE"}
    # ONLY the infiltration question has an emitted question_table row (Q1); the display questions omit
    # legacy_id (no signal/confidence to join)
    by_id = {q["id"]: q for q in questions}
    assert by_id["infiltration"].get("legacy_id") == "Q1"
    assert "legacy_id" not in by_id["ici_response"]
    assert "legacy_id" not in by_id["microenvironment"]


# ── role partition ─────────────────────────────────────────────────────────────────────────────────
def test_role_partition_1_verdict_bearing_5_display_only(graph):
    vb = {c["id"] for c in graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 1 and len(do) == 5 and len(graph["cards"]) == 6


# ── reconstruction: question signal+confidence, each question's cards, no orphans ───────────────────
def test_reconstruct_questions_signal_confidence_and_cards(graph):
    qs = {q["id"]: q for q in graph["questions"]}
    assert len(qs) == 3
    # signal + confidence readable off the graph (no prose parsing), matching the emitted Q1 row. The
    # descriptive question_table emits polarity `informs` (never supports/opposes the nomination); the
    # canonical-polarity map passes an unknown token through unchanged.
    assert qs["infiltration"]["signal"]["tier"] == "moderate"
    assert qs["infiltration"]["signal"]["polarity"] == "informs"
    assert qs["infiltration"]["confidence"]["level"] == "moderate"
    # the display questions have no emitted question_table row → null signal/confidence (honest gap)
    assert qs["ici_response"]["signal"]["tier"] is None
    assert qs["microenvironment"]["confidence"]["level"] is None
    # the many-to-many card join (measurement_type membership)
    assert set(qs["infiltration"]["card_ids"]) == {"immune-context", "tcga-til-fraction-saltz"}
    assert set(qs["ici_response"]["card_ids"]) == {"ici-response-association", "ici-response-imvigor210"}
    assert set(qs["microenvironment"]["card_ids"]) == {
        "myeloid-compartment-expression-cheng", "caf-compartment-expression-luo"}
    # every card joins at least one question (nothing collapses into the "Other" layer)
    assert all(c["question_ids"] for c in graph["cards"])
    # a shared measurement_type (ici_response_expression) materializes both edge directions
    ici = next(c for c in graph["cards"] if c["id"] == "ici-response-imvigor210")
    assert set(ici["question_ids"]) == {"ici_response"}


# ── literature IMMUNE axis crosswalk ─────────────────────────────────────────────────────────────────
def test_literature_axis_crosswalk(decision, questions):
    d = copy.deepcopy(decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = build_evidence_graph(d, questions=questions)
    axes = {ax["axis_id"]: ax for ax in g["literature"]["axes"]}
    assert set(axes) == {"IMMUNE"}
    # the single lens axis resolves to the three non-corroboration effector-context questions
    assert axes["IMMUNE"]["question_ids"] == ["infiltration", "ici_response", "microenvironment"]
    # crosswalk materialized on every question node too
    for qid in ("infiltration", "ici_response", "microenvironment"):
        q = next(q for q in g["questions"] if q["id"] == qid)
        assert q["literature_axis_ids"] == ["IMMUNE"]
    # citations hoisted + referentially intact
    cit_ids = {c["id"] for c in g["citations"]}
    assert "thorsson2018" in cit_ids
    assert axes["IMMUNE"]["citation_ids"] == ["thorsson2018"]


# ── each card's dataset→data→rule→verdict chain (no .card.yaml, no prose) ───────────────────────────
def test_driving_card_chain(graph):
    ic = next(c for c in graph["cards"] if c["id"] == "immune-context")
    assert ic["class"] == {"field": "immune_context_class", "value": "immune_intermediate"}
    assert ic["chain"]["rule_id"] == "immune-context-intermediate-tce-neutral"
    assert ic["chain"]["contributes_to_verdict"] is True
    assert ic["chain"]["is_driving"] is True
    # a display-only card never invents a rule
    do = next(c for c in graph["cards"] if c["id"] == "tcga-til-fraction-saltz")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(graph, decision):
    assert graph["verdict"]["id"] == decision["headline"]["immune_context_verdict"] == "immune_intermediate"
    assert graph["verdict"]["driving_rule_id"] == "immune-context-intermediate-tce-neutral"
    assert graph["verdict"]["polarity"] == "neutral"


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
    assert "evidence_graph" not in decision["headline"]  # trimmed fixture predates the layer
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
    assert len(g["questions"]) == 3 and len(g["cards"]) == 6
    for q in g["questions"]:
        assert q["literature_axis_ids"] == []


def test_graph_without_registry_is_referentially_intact(decision):
    g = build_evidence_graph(decision, questions=[])
    assert g["questions"] == []
    assert len(g["cards"]) == 6
    for c in g["cards"]:
        assert c["question_ids"] == []
        assert set(c["dataset_ids"]) <= {d["id"] for d in g["datasets"]}


# ── standalone dashboard render smoke test (evidence_graph_dashboard consumes the graph ONLY) ────────
def test_dashboard_renders_summary_header_and_driving_pill(decision, questions):
    d = copy.deepcopy(decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = build_evidence_graph(d, questions=questions)
    html = render_dashboard(g)
    assert "<!doctype html>" in html
    # the deterministic Summary + verdict header render
    assert "Summary" in html
    assert "Immune-intermediate" in html
    # all 3 question slugs render (fingerprint label + question-table row)
    for qid in ("infiltration", "ici_response", "microenvironment"):
        assert qid in html
    # the driving card carries a DRIVING pill
    assert "DRIVING" in html and "immune-context" in html
    # literature crosswalk populated
    assert "CD8 effector infiltrate" in html
