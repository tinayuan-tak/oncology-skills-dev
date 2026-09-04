"""evidence_graph layer — acceptance tests (spec §7) for the additive claim graph at
decision.headline.evidence_graph.

Ground truth is the committed EPCAM·COADREAD decision.json fixture (a real tumor-presence run,
pre-evidence_graph). The graph is BUILT from that fixture + the canonical questions.yaml registry, so
these tests prove the projection reconstructs the dashboard with zero .card.yaml reads and zero
free-text parsing, is referentially intact, is byte-stable (purely additive), and partitions cards
9 verdict-bearing / 8 display-only. VERDICT-INERT: nothing here touches the presence_verdict spine.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
FIXTURE = SKILL_DIR / "tests" / "fixtures" / "epcam_coadread_decision.json"
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common.evidence_graph import build_evidence_graph, load_questions  # noqa: E402


# ── the 9/8 role partition (spec §7.4 + appendix) ──
VERDICT_BEARING = {
    "cellline-rna-distribution", "tumor-rna-vs-adjacent", "tumor-rna-distribution",
    "cellline-protein-abundance", "tumor-elevation-breadth", "tumor-scrna-celltype-expression",
    "expression-purity-confound", "cellline-rna-protein-concordance", "sc-normal-celltype-expression",
}
DISPLAY_ONLY = {
    "tumor-protein-abundance-cptac", "cellline-protein-abundance-procan", "hpa-pathology-cancer-ihc",
    "rna-protein-concordance-tumor", "tumor-rna-distribution-by-subtype",
    "cellline-rna-distribution-by-subtype", "tumor-protein-distribution-by-subtype",
    "normal-tissue-liability",
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
    assert ids == ["expressed_at_all", "vs_other_cancers", "elevated_vs_normal", "subtypes_differ",
                   "absolute_abundance", "rna_protein_agree", "malignant_intrinsic"]
    # unified axis vocabulary present incl. the missing presence axis B (tumor-vs-normal)
    axes = {q["axis_id"] for q in questions if q.get("axis_id")}
    assert axes == {"A", "B", "C", "D"}


# ── §7.4 role partition ──────────────────────────────────────────────────────────────────────────
def test_role_partition_9_verdict_bearing_8_display_only(graph):
    vb = {c["id"] for c in graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 9 and len(do) == 8 and len(graph["cards"]) == 17


# ── §7.1 reconstruction: 7 questions with signal+confidence, each question's cards ──────────────────
def test_reconstruct_questions_signal_confidence_and_cards(graph):
    qs = {q["id"]: q for q in graph["questions"]}
    assert len(qs) == 7
    # signal + confidence readable off the graph (no prose parsing)
    assert qs["expressed_at_all"]["signal"]["tier"] == "strong"
    assert qs["expressed_at_all"]["confidence"]["level"] == "moderate"
    assert qs["elevated_vs_normal"]["signal"]["polarity"] == "opposes"
    assert qs["subtypes_differ"]["signal"]["tier"] == "uniform"
    assert qs["malignant_intrinsic"]["confidence"]["level"] == "high"
    # each question's card list (the many-to-many join) matches the curated dashboard exactly
    assert set(qs["expressed_at_all"]["card_ids"]) == {
        "tumor-rna-distribution", "hpa-pathology-cancer-ihc", "cellline-rna-distribution",
        "cellline-protein-abundance", "cellline-protein-abundance-procan", "tumor-protein-abundance-cptac"}
    assert set(qs["elevated_vs_normal"]["card_ids"]) == {
        "tumor-rna-vs-adjacent", "tumor-protein-abundance-cptac", "normal-tissue-liability",
        "sc-normal-celltype-expression"}
    assert set(qs["subtypes_differ"]["card_ids"]) == {
        "tumor-rna-distribution-by-subtype", "cellline-rna-distribution-by-subtype",
        "tumor-protein-distribution-by-subtype", "expression-purity-confound"}
    # a card appearing in TWO questions (many-to-many) is materialized both directions
    assert set(qs["absolute_abundance"]["card_ids"]) >= {"tumor-rna-distribution"}
    trd = next(c for c in graph["cards"] if c["id"] == "tumor-rna-distribution")
    assert set(trd["question_ids"]) == {"expressed_at_all", "absolute_abundance"}


# ── §7.1/§7.5 each question's literature, incl. axis B → elevated_vs_normal ──────────────────────────
def test_literature_axis_crosswalk_including_axis_B(graph):
    axes = {ax["axis_id"]: ax for ax in graph["literature"]["axes"]}
    assert set(axes) == {"A", "B", "C", "D"}
    assert axes["A"]["question_ids"] == ["expressed_at_all", "absolute_abundance"]
    assert axes["B"]["question_ids"] == ["elevated_vs_normal"]          # the missing link
    assert axes["C"]["question_ids"] == ["malignant_intrinsic"]
    assert axes["D"]["question_ids"] == ["vs_other_cancers"]
    assert axes["B"]["read"] == "mixed" and axes["B"]["agreement_vs_omics"] == "agree"
    assert graph["literature"]["overall_consistency"] == "concordant"
    # the crosswalk is materialized on the question node too
    q3 = next(q for q in graph["questions"] if q["id"] == "elevated_vs_normal")
    assert q3["literature_axis_ids"] == ["B"]
    # corroboration question (rna_protein_agree, axis A) is NOT a literature target
    q6 = next(q for q in graph["questions"] if q["id"] == "rna_protein_agree")
    assert q6["literature_axis_ids"] == []


# ── §7.1 each card's dataset→data→rule→verdict chain (no .card.yaml, no prose) ──────────────────────
def test_driving_card_chain(graph):
    trd = next(c for c in graph["cards"] if c["id"] == "tumor-rna-distribution")
    assert trd["class"] == {"field": "tumor_expression_class", "value": "broadly_high"}
    assert "tcga-tumor-tpm-recount3-long-v1" in trd["chain"]["dataset_ids"]
    assert trd["chain"]["rule_id"] == "tumor-expression-broadly-high-supportive"
    assert trd["chain"]["contributes_to_verdict"] is True
    assert trd["chain"]["is_driving"] is True
    assert trd["key_fields"].get("allgene_percentile") == pytest.approx(99.74, abs=0.1)
    # a display-only card never invents a rule (spec §6)
    do = next(c for c in graph["cards"] if c["id"] == "hpa-pathology-cancer-ihc")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(graph, decision):
    assert graph["verdict"]["id"] == decision["headline"]["presence_verdict"] == "tumor_broadly_expressed"
    assert graph["verdict"]["driving_rule_id"] == "tumor-expression-broadly-high-supportive"
    assert graph["verdict"]["polarity"] == "positive"


# ── §7.2 referential integrity ─────────────────────────────────────────────────────────────────────
def test_referential_integrity(graph):
    q_ids = {q["id"] for q in graph["questions"]}
    c_ids = {c["id"] for c in graph["cards"]}
    r_ids = {r["id"] for r in graph["rules"]}
    d_ids = {d["id"] for d in graph["datasets"]}
    cit_ids = {c["id"] for c in graph["citations"]}
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
        assert set(c["chain"]["dataset_ids"]) <= d_ids
    for r in graph["rules"]:
        assert r["card_id"] in c_ids
    for ax in graph["literature"]["axes"]:
        assert set(ax["question_ids"]) <= q_ids
        assert set(ax["citation_ids"]) <= cit_ids
        assert ax["axis_id"] in axis_ids
    for bs in graph["literature"]["blind_spots"]:
        assert set(bs["citation_ids"]) <= cit_ids
    for c in graph["cards"] + graph["questions"]:
        if c.get("axis_id"):
            assert c["axis_id"] in axis_ids


# ── §7.3 byte-stability: the layer is purely additive (touches nothing else) ────────────────────────
def test_builder_does_not_mutate_decision(decision, questions):
    before = copy.deepcopy(decision)
    build_evidence_graph(decision, questions=questions)
    assert decision == before  # build reads only; never writes back into the decision


def test_additive_only_no_preexisting_key_changes(decision, graph):
    """Simulate the dispatcher wiring: attach evidence_graph under headline, then assert that popping
    it yields a decision byte-identical to the original (evidence_graph is the ONLY new key)."""
    enriched = copy.deepcopy(decision)
    enriched["headline"]["evidence_graph"] = graph
    assert "evidence_graph" not in decision["headline"]  # fixture predates the layer
    popped = enriched["headline"].pop("evidence_graph")
    assert popped is graph
    assert enriched == decision
    # and JSON serialization of every pre-existing key is unchanged
    assert json.dumps(enriched, indent=2, default=str) == json.dumps(decision, indent=2, default=str)


def test_build_is_deterministic(decision, questions):
    a = json.dumps(build_evidence_graph(decision, questions=questions), default=str)
    b = json.dumps(build_evidence_graph(decision, questions=questions), default=str)
    assert a == b


# ── §7.5 schema validation ─────────────────────────────────────────────────────────────────────────
def _contracts_schema_path() -> Path | None:
    root = os.environ.get("TARGET_CONTRACTS_ROOT")
    candidates = []
    if root:
        candidates.append(Path(root) / "schemas" / "evidence_graph.schema.json")
    candidates.append(Path.home() / "rnd-computational-biology-oncology-target-contracts"
                      / "schemas" / "evidence_graph.schema.json")
    for c in candidates:
        if c.exists():
            return c
    return None


def test_graph_validates_against_schema(graph):
    schema_path = _contracts_schema_path()
    if schema_path is None:
        pytest.skip("evidence_graph.schema.json not found (set TARGET_CONTRACTS_ROOT)")
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(graph, json.loads(schema_path.read_text()))


# ── fail-soft: absent literature/synthesis → empty sub-objects, still valid & intact ────────────────
def test_fail_soft_without_optional_inputs(decision, questions):
    stripped = copy.deepcopy(decision)
    stripped.pop("literature_synthesis", None)
    stripped.pop("llm_synthesis", None)
    g = build_evidence_graph(stripped, questions=questions)
    assert g["literature"] == {}
    assert g["citations"] == []
    assert g["narrative"] == {}
    # honest-negative: questions/cards still emitted with empty (never dropped) literature edges
    assert len(g["questions"]) == 7 and len(g["cards"]) == 17
    for q in g["questions"]:
        assert q["literature_axis_ids"] == []


def test_narrative_fail_soft_on_error_stub(graph):
    # the committed fixture carries an llm_synthesis error stub → narrative must be empty, not error
    assert graph["narrative"] == {}


def test_graph_without_registry_is_referentially_intact(decision):
    """A skill with no questions.yaml still emits a valid, referentially-intact graph (best-effort:
    no questions, cards carry empty question_ids, but every edge still resolves)."""
    g = build_evidence_graph(decision, questions=[])
    assert g["questions"] == []
    assert len(g["cards"]) == 17
    c_ids = {c["id"] for c in g["cards"]}
    for c in g["cards"]:
        assert c["question_ids"] == []
        assert set(c["dataset_ids"]) <= {d["id"] for d in g["datasets"]}
    # literature axes still emit but crosswalk to no questions (honest empty)
    for ax in g["literature"]["axes"]:
        assert ax["question_ids"] == []
