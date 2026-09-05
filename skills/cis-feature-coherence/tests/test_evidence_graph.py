"""evidence_graph layer — acceptance tests for cis-feature-coherence's additive claim graph at
decision.headline.evidence_graph, plus a standalone-dashboard render smoke test.

Ground truth is a committed KRAS·COADREAD decision.json fixture (a real cis-feature-coherence run,
trimmed to only the fields build_evidence_graph reads — verified at authoring time to yield a byte-
identical graph vs the full decision). The graph is BUILT from that fixture + the canonical questions.yaml
registry, so these tests prove the projection reconstructs the dashboard with zero .card.yaml reads / zero
free-text parsing, is referentially intact, byte-stable (purely additive), partitions cards 3 verdict-
bearing / 6 display-only (only the 3 rule-firing legs are verdict-bearing here), and resolves the
CIS_DOSAGE/SILENCING/EXPR_DEP/CONJOINT literature axis→question crosswalk.

GATELESS / DESCRIPTIVE skill: cis-feature-coherence is verdict-INERT at composition — top-level
decision["verdict"] is None. It STILL resolves a headline cis_coherence_verdict token via the shared 2×2
cross-tab resolver, so the graph's verdict node carries the resolved coherence class (here coherent_cis_
driver) rather than None. The verdict asserts below are therefore NULL-TOLERANT: the resolved-token path is
pinned for this fixture, and a dedicated test proves the deterministic Summary block + verdict header still
render when the token/headline_block are absent (a truly-inert run). Nothing here touches the
cis_coherence_verdict spine.
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

# cards that FIRE a cis_coherence rule in the KRAS/COADREAD fixture (verdict-bearing) vs the pure
# display-only facets (the verdict-INERT protein / abundance / patient / molecular-form legs).
VERDICT_BEARING = {
    "cis-feature-expression-coherence", "expression-dependency-correlation",
    "amp-expr-stratified-dependency",
}
DISPLAY_ONLY = {
    "cis-feature-protein-coherence", "cellline-methylation-expression-coherence",
    "abundance-dependency", "patient-cis-coherence", "cellline-isoform-dominance",
    "cellline-isoform-expression",
}
ALL_CARDS = VERDICT_BEARING | DISPLAY_ONLY

# a synthetic literature_synthesis keyed by the cis-feature-coherence lens axis KEYS (what
# make_literature_fn emits from narrator_lenses.CIS_FEATURE_COHERENCE.axis_labels).
_SYNTH_LIT = {
    "axes": [
        {"axis_key": "CIS_DOSAGE", "literature_read": "supports",
         "assertion": "KRAS amplification drives its own expression.",
         "agreement_vs_omics": "agree", "confidence": "high",
         "citations": [{"label": "Singh 2009", "pmid": "19490893", "verified": True}]},
        {"axis_key": "SILENCING", "literature_read": "n/a", "assertion": "No promoter silencing reported.",
         "agreement_vs_omics": "omics_blind", "confidence": "low", "citations": []},
        {"axis_key": "EXPR_DEP", "literature_read": "supports", "assertion": "Expression tracks dependency.",
         "agreement_vs_omics": "agree", "confidence": "moderate", "citations": []},
        {"axis_key": "CONJOINT", "literature_read": "mixed", "assertion": "Amp∩overexpr addiction context.",
         "agreement_vs_omics": "agree", "confidence": "moderate", "citations": []},
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
def test_questions_registry_loads_four(questions):
    ids = [q["id"] for q in questions]
    assert ids == ["cis_dosage_read", "silencing_read", "expr_dep_read", "conjoint_read"]
    # unified axis vocabulary shared with the cis-feature-coherence narrator lens
    axes = {q["axis_id"] for q in questions if q.get("axis_id")}
    assert axes == {"CIS_DOSAGE", "SILENCING", "EXPR_DEP", "CONJOINT"}
    # legacy_id join keys mirror the emitted cis_coherence_question_table (Q1..Q4)
    assert [q["legacy_id"] for q in questions] == [f"Q{i}" for i in range(1, 5)]
    # every axis-owning question is non-corroboration so every lens axis resolves in the crosswalk
    assert all(q["role"] != "corroboration" for q in questions if q.get("axis_id"))


# ── role partition (card-level: only rule-firing legs are verdict-bearing) ──────────────────────────
def test_role_partition_3_verdict_bearing_6_display_only(graph):
    vb = {c["id"] for c in graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 3 and len(do) == 6 and len(graph["cards"]) == 9


# ── reconstruction: questions with signal+confidence, each question's cards, no orphans ─────────────
def test_reconstruct_questions_signal_and_cards(graph):
    qs = {q["id"]: q for q in graph["questions"]}
    assert len(qs) == 4
    # signal readable off the graph (no prose parsing), matching the emitted question_table. This
    # verdict-INERT skill's question_table polarity is "informs" (never supports/opposes a nomination).
    assert qs["cis_dosage_read"]["signal"]["tier"] == "strong"
    assert qs["cis_dosage_read"]["signal"]["polarity"] == "informs"
    assert qs["silencing_read"]["signal"]["tier"] == "unmeasured"     # methylation_invariant_panel
    # the many-to-many card join (measurement_type membership) — protein sibling + molecular-form
    # context cards anchor to the CIS_DOSAGE leg they inform.
    assert set(qs["cis_dosage_read"]["card_ids"]) == {
        "cis-feature-expression-coherence", "cis-feature-protein-coherence",
        "cellline-isoform-dominance", "cellline-isoform-expression"}
    assert set(qs["silencing_read"]["card_ids"]) == {"cellline-methylation-expression-coherence"}
    assert set(qs["expr_dep_read"]["card_ids"]) == {
        "expression-dependency-correlation", "abundance-dependency"}
    assert set(qs["conjoint_read"]["card_ids"]) == {
        "amp-expr-stratified-dependency", "patient-cis-coherence"}
    # every card joins at least one question (nothing collapses into the "Other" layer)
    assert all(c["question_ids"] for c in graph["cards"])
    # the driving leg materializes both edge directions
    cis = next(c for c in graph["cards"] if c["id"] == "cis-feature-expression-coherence")
    assert cis["question_ids"] == ["cis_dosage_read"]


# ── literature CIS_DOSAGE/SILENCING/EXPR_DEP/CONJOINT axis crosswalk ─────────────────────────────────
def test_literature_axis_crosswalk(decision, questions):
    d = copy.deepcopy(decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = build_evidence_graph(d, questions=questions)
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
def test_driving_card_chain(graph):
    cis = next(c for c in graph["cards"] if c["id"] == "cis-feature-expression-coherence")
    assert cis["chain"]["rule_id"] == "cis-dosage-coupled-supportive"
    assert cis["chain"]["contributes_to_verdict"] is True
    assert cis["chain"]["is_driving"] is True
    # exactly one driving card, and it matches the verdict's driving_rule_id
    driving = [c["id"] for c in graph["cards"] if c["chain"]["is_driving"]]
    assert driving == ["cis-feature-expression-coherence"]
    # a display-only (verdict-inert) card never invents a rule
    do = next(c for c in graph["cards"] if c["id"] == "patient-cis-coherence")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(graph, decision):
    # NULL-TOLERANT: the top-level decision verdict is None (verdict-inert), but the headline resolves
    # a cis_coherence_verdict token that the graph's verdict node carries.
    assert decision.get("verdict") is None
    assert decision["headline"]["cis_coherence_verdict"] == "coherent_cis_driver"
    assert graph["verdict"]["id"] == "coherent_cis_driver"
    assert graph["verdict"]["driving_rule_id"] == "cis-dosage-coupled-supportive"
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
    assert len(g["questions"]) == 4 and len(g["cards"]) == 9
    for q in g["questions"]:
        assert q["literature_axis_ids"] == []


def test_graph_without_registry_is_referentially_intact(decision):
    g = build_evidence_graph(decision, questions=[])
    assert g["questions"] == []
    assert len(g["cards"]) == 9
    for c in g["cards"]:
        assert c["question_ids"] == []
        assert set(c["dataset_ids"]) <= {d["id"] for d in g["datasets"]}


# ── standalone dashboard render smoke test (evidence_graph_dashboard consumes the graph ONLY) ────────
def test_dashboard_renders_questions_and_driving_pill(decision, questions):
    d = copy.deepcopy(decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = build_evidence_graph(d, questions=questions)
    html = render_dashboard(g)
    assert "<!doctype html>" in html.lower()
    # all 4 question slugs render (fingerprint label + question-table row)
    for qid in ("cis_dosage_read", "silencing_read", "expr_dep_read", "conjoint_read"):
        assert qid in html
    # the driving card carries a DRIVING pill
    assert "DRIVING" in html and "cis-feature-expression-coherence" in html
    # verdict header + deterministic Summary block + literature crosswalk populated
    assert "Coherent cis-driven addiction" in html
    assert "Summary" in html
    assert "amplification drives its own expression" in html


def test_dashboard_renders_with_null_inert_verdict(decision, questions):
    """GATELESS guard: with the resolved token AND the headline_block stripped (a truly verdict-inert
    run), the graph's verdict node id/call/polarity are all None — the deterministic Summary block and
    the verdict header must STILL render without error."""
    d = copy.deepcopy(decision)
    d["headline"].pop("cis_coherence_verdict", None)
    d["headline"].pop("headline_block", None)
    g = build_evidence_graph(d, questions=questions)
    assert g["verdict"]["id"] is None
    assert g["verdict"]["call"] is None
    assert g["verdict"]["polarity"] is None
    html = render_dashboard(g)
    assert "<!doctype html>" in html.lower()
    assert "Summary" in html          # deterministic Summary block renders
    assert "Verdict" in html          # verdict header row renders
    # questions still anchor their cards regardless of the null verdict
    assert all(c["question_ids"] for c in g["cards"])
