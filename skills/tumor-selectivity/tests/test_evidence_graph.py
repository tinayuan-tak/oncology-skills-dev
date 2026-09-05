"""evidence_graph layer — acceptance tests for tumor-selectivity's additive claim graph at
decision.headline.evidence_graph, plus a standalone-dashboard render smoke test.

Ground truth is a committed KRAS·COADREAD decision.json fixture (a real tumor-selectivity run, trimmed
to only the fields build_evidence_graph reads — verified to yield a byte-identical graph vs the full
decision). The graph is BUILT from that fixture + the canonical questions.yaml registry, so these tests
prove the projection reconstructs the dashboard with zero .card.yaml reads / zero free-text parsing, is
referentially intact, byte-stable (purely additive), partitions the 13 cards 7 verdict-bearing / 6
display-only, and resolves the WIN/DIST/INT/SAFE literature axis→question crosswalk. VERDICT-INERT:
nothing here touches the selectivity_class spine or the normal-breadth / stromal-confound veto.
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
    "tumor-vs-normal-selectivity", "tumor-vs-normal-percentile-crossing",
    "modality-therapeutic-window", "sc-normal-celltype-expression",
    "normal-tissue-protein-abundance-tphp", "tumor-scrna-celltype-expression",
    "expression-purity-confound",
}
DISPLAY_ONLY = {
    "tumor-protein-abundance-cptac", "tumor-vs-normal-protein-abundance-tphp",
    "surface-abundance-density", "spatial-region-rna-expression",
    "spatial-tumor-normal-colocalization", "spatial-surface-protein-abundance",
}

# a synthetic literature_synthesis keyed by the tumor-selectivity lens axis LETTERS (what
# make_literature_fn(_LENS) emits: WIN/DIST/INT/SAFE)
_SYNTH_LIT = {
    "axes": [
        {"axis_key": "WIN", "literature_read": "supports",
         "assertion": "KRAS shows a tumor-enriched window in colorectal.",
         "agreement_vs_omics": "agree", "confidence": "high",
         "citations": [{"label": "Smith 2020", "pmid": "12345678", "verified": True}]},
        {"axis_key": "DIST", "literature_read": "mixed",
         "assertion": "Per-sample separation reported in a subset.",
         "agreement_vs_omics": "agree", "confidence": "moderate", "citations": []},
        {"axis_key": "INT", "literature_read": "supports",
         "assertion": "Signal is malignant-cell-intrinsic in single-cell atlases.",
         "agreement_vs_omics": "agree", "confidence": "moderate", "citations": []},
        {"axis_key": "SAFE", "literature_read": "opposes",
         "assertion": "Broad normal-tissue expression noted.",
         "agreement_vs_omics": "omics_blind", "confidence": "low", "citations": []},
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
def test_questions_registry_loads_eight(questions):
    ids = [q["id"] for q in questions]
    assert ids == ["overexpressed_vs_origin", "comparator_robust", "per_sample_separation",
                   "absolute_allgene_rank", "window_vs_worst_normal", "malignant_intrinsic",
                   "absolute_surface_density", "spatial_bystander_risk"]
    # unified axis vocabulary shared with the tumor-selectivity narrator lens (WIN/DIST/INT/SAFE)
    axes = {q["axis_id"] for q in questions if q.get("axis_id")}
    assert axes == {"WIN", "DIST", "INT", "SAFE"}
    # legacy_id join keys mirror the emitted selectivity_question_table (Q1..Q8)
    assert [q["legacy_id"] for q in questions] == [f"Q{i}" for i in range(1, 9)]


# ── role partition (card role = fired-a-rule, not the editorial question role) ──────────────────────
def test_role_partition_7_verdict_bearing_6_display_only(graph):
    vb = {c["id"] for c in graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 7 and len(do) == 6 and len(graph["cards"]) == 13


# ── reconstruction: questions with signal, each question's cards, no orphans ────────────────────────
def test_reconstruct_questions_signal_and_cards(graph):
    qs = {q["id"]: q for q in graph["questions"]}
    assert len(qs) == 8
    # signal readable off the graph (no prose parsing), matching the emitted question_table rows
    assert qs["overexpressed_vs_origin"]["signal"]["tier"] == "weak"
    assert qs["overexpressed_vs_origin"]["signal"]["polarity"] == "supportive"
    assert qs["malignant_intrinsic"]["signal"]["tier"] == "moderate"
    # the normal-tissue window row is a measured negative (canonical opposing, was legacy "opposes")
    assert qs["window_vs_worst_normal"]["signal"]["tier"] == "negative"
    assert qs["window_vs_worst_normal"]["signal"]["polarity"] == "opposing"
    # the many-to-many card join (measurement_type membership)
    assert set(qs["overexpressed_vs_origin"]["card_ids"]) == {
        "tumor-vs-normal-selectivity", "tumor-protein-abundance-cptac",
        "tumor-vs-normal-protein-abundance-tphp"}
    assert set(qs["per_sample_separation"]["card_ids"]) == {"tumor-vs-normal-percentile-crossing"}
    assert set(qs["window_vs_worst_normal"]["card_ids"]) == {
        "modality-therapeutic-window", "sc-normal-celltype-expression",
        "normal-tissue-protein-abundance-tphp"}
    assert set(qs["malignant_intrinsic"]["card_ids"]) == {
        "expression-purity-confound", "tumor-scrna-celltype-expression",
        "spatial-region-rna-expression"}
    assert set(qs["absolute_surface_density"]["card_ids"]) == {"surface-abundance-density"}
    assert set(qs["spatial_bystander_risk"]["card_ids"]) == {
        "spatial-tumor-normal-colocalization", "spatial-surface-protein-abundance"}
    # the card-less corroboration / relative-frame rows still anchor their emitted signal
    assert qs["comparator_robust"]["card_ids"] == []
    assert qs["absolute_allgene_rank"]["card_ids"] == []
    # every card joins at least one question (nothing collapses into the "Other" layer)
    assert all(c["question_ids"] for c in graph["cards"])
    # the driving card resolves to exactly its WIN question
    drv = next(c for c in graph["cards"] if c["id"] == "tumor-vs-normal-selectivity")
    assert set(drv["question_ids"]) == {"overexpressed_vs_origin"}


# ── literature WIN/DIST/INT/SAFE axis crosswalk ─────────────────────────────────────────────────────
def test_literature_axis_crosswalk(decision, questions):
    d = copy.deepcopy(decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = build_evidence_graph(d, questions=questions)
    axes = {ax["axis_id"]: ax for ax in g["literature"]["axes"]}
    assert set(axes) == {"WIN", "DIST", "INT", "SAFE"}
    assert axes["WIN"]["question_ids"] == ["overexpressed_vs_origin"]
    assert axes["DIST"]["question_ids"] == ["per_sample_separation"]
    assert axes["INT"]["question_ids"] == ["malignant_intrinsic"]
    assert axes["SAFE"]["question_ids"] == ["window_vs_worst_normal"]
    # crosswalk materialized on the question node too
    q1 = next(q for q in g["questions"] if q["id"] == "overexpressed_vs_origin")
    assert q1["literature_axis_ids"] == ["WIN"]
    # the WIN corroboration question + the axis-less display rows are NOT literature targets
    for cid in ("comparator_robust", "absolute_allgene_rank", "absolute_surface_density",
                "spatial_bystander_risk"):
        q = next(q for q in g["questions"] if q["id"] == cid)
        assert q["literature_axis_ids"] == []
    # citations hoisted + referentially intact
    cit_ids = {c["id"] for c in g["citations"]}
    assert "smith2020" in cit_ids
    assert axes["WIN"]["citation_ids"] == ["smith2020"]


# ── each card's dataset→data→rule→verdict chain (no .card.yaml, no prose) ───────────────────────────
def test_driving_card_chain(graph):
    tvn = next(c for c in graph["cards"] if c["id"] == "tumor-vs-normal-selectivity")
    assert tvn["class"] == {"field": "selectivity_class", "value": "discordant_across_comparators"}
    assert tvn["chain"]["rule_id"] == "tvn-discordant-neutral-flagged"
    assert tvn["chain"]["contributes_to_verdict"] is True
    assert tvn["chain"]["is_driving"] is True
    # exactly one driving card, and it matches the verdict spine
    driving = [c for c in graph["cards"] if c["chain"]["is_driving"]]
    assert [c["id"] for c in driving] == ["tumor-vs-normal-selectivity"]
    # a display-only card never invents a rule
    do = next(c for c in graph["cards"] if c["id"] == "surface-abundance-density")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(graph, decision):
    hb_call = decision["headline"]["headline_block"]["verdict"]["call"]
    assert graph["verdict"]["id"] == hb_call == "discordant_across_comparators"
    assert graph["verdict"]["driving_rule_id"] == decision["headline"]["driving_rule_id"] \
        == "tvn-discordant-neutral-flagged"
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
    assert len(g["questions"]) == 8 and len(g["cards"]) == 13
    for q in g["questions"]:
        assert q["literature_axis_ids"] == []


def test_graph_without_registry_is_referentially_intact(decision):
    g = build_evidence_graph(decision, questions=[])
    assert g["questions"] == []
    assert len(g["cards"]) == 13
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
    # all four axis-owning question slugs render (fingerprint label + question-table row)
    for qid in ("overexpressed_vs_origin", "per_sample_separation", "window_vs_worst_normal",
                "malignant_intrinsic", "spatial_bystander_risk"):
        assert qid in html
    # the driving card carries a DRIVING pill
    assert "DRIVING" in html and "tumor-vs-normal-selectivity" in html
    # verdict header + literature crosswalk populated
    assert "Discordant across normal comparators" in html
    assert "tumor-enriched window" in html
