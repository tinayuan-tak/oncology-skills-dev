"""evidence_graph layer — acceptance tests for target-intrinsic's additive claim graph at
decision.headline.evidence_graph, plus a standalone-dashboard render smoke test.

Ground truth is a committed KRAS decision.json fixture (a real target-intrinsic run, trimmed to only
the fields build_evidence_graph reads — verified to yield a byte-identical graph vs the full decision).
The graph is BUILT from that fixture + the canonical questions.yaml registry, so these tests prove the
projection reconstructs the dashboard with zero .card.yaml reads / zero free-text parsing, is
referentially intact, byte-stable (purely additive), and resolves the MODALITY_ROUTING /
TRACTABILITY_PRECEDENT literature axis→question crosswalk.

GATELESS / DESCRIPTIVE: target-intrinsic is an indication-INDEPENDENT dossier (verdict_fn=None). So the
graph's verdict.id is None and driving_rule_id is None (verdict.call carries the deterministic descriptive
phrase) — EXPECTED and null-safe. Rules DO fire on the loaded intracellular_intrinsic axis (10 cards →
role=verdict_bearing) but NO driving_rule_id is selected (no verdict_fn), so no card is is_driving. These
tests therefore drop the non-null-verdict spine-equality asserts (there is no verdict token) and instead
assert the null verdict is tolerated end-to-end and the deterministic Summary block still renders.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
FIXTURE = SKILL_DIR / "tests" / "fixtures" / "kras_target_intrinsic_decision.json"
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common.evidence_graph import build_evidence_graph, load_questions  # noqa: E402

# cards that fire a rule in the KRAS fixture (role=verdict_bearing) vs the pure display-only facets.
# target-intrinsic is gateless — a fired rule NEVER selects a driving_rule_id (no verdict_fn), so none of
# these is is_driving; the partition is purely "did any rule fire on this card".
VERDICT_BEARING = {
    "gnomad-lof-constraint", "gene-burden-safety", "clingen-dosage", "clinvar-pathogenicity-safety",
    "mouse-ko-phenotype", "structure-features-static", "signaling-network-mechanism",
    "measured-potency-tractability", "domain-modality-relevance", "paralog-buffering",
}
DISPLAY_ONLY = {
    "target-identity-summary", "target-safety-prioritisation", "surfaceome-family-classification",
    "shed-ectodomain-liability", "gene-ontology-annotation", "reactome-pathway-membership",
    "ppi-interactome", "protein-domains-class", "target-development-level", "normal-tissue-liability",
}

# the deterministic descriptive dominant-signal phrase target-intrinsic mints in DESCRIPTIVE MODE
# (headline_block.verdict.phrase); verdict.id / verdict.call.id / driving_rule_id are all None (gateless).
DESCRIPTIVE_PHRASE = "Target-intrinsic modality/tractability context present."

# a synthetic literature_synthesis keyed by the target-intrinsic lens axis KEYS (what make_literature_fn
# emits — narrator_lenses.TARGET_INTRINSIC.axis_labels: MODALITY_ROUTING / TRACTABILITY_PRECEDENT).
_SYNTH_LIT = {
    "axes": [
        {"axis_key": "MODALITY_ROUTING", "literature_read": "supports",
         "assertion": "KRAS G12C covalent pocket is co-crystal confirmed.",
         "agreement_vs_omics": "agree", "confidence": "high",
         "citations": [{"label": "Ostrem 2013", "pmid": "24256730", "verified": True}]},
        {"axis_key": "TRACTABILITY_PRECEDENT", "literature_read": "supports",
         "assertion": "Sotorasib approved (Tclin precedent).",
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
    assert ids == ["modality_route", "tractability_precedent", "biology_context",
                   "safety_genetics", "normal_context"]
    # the two lens axes shared with the target-intrinsic narrator lens (narrator_lenses.TARGET_INTRINSIC)
    axes = {q["axis_id"] for q in questions if q.get("axis_id")}
    assert axes == {"MODALITY_ROUTING", "TRACTABILITY_PRECEDENT"}
    # legacy_id join keys are present ONLY on the two questions with an emitted question_table row
    assert [q.get("legacy_id") for q in questions] == ["Q1", "Q2", None, None, None]
    # descriptive skill — no verdict → no verdict_bearing / corroboration question roles
    assert {q["role"] for q in questions} == {"display_only"}


# ── GATELESS null-verdict is tolerated (no non-null spine assert) ───────────────────────────────────
def test_gateless_null_verdict_is_tolerant(graph):
    v = graph["verdict"]
    # verdict.id / driving_rule_id are None (indication-independent dossier — no nomination)
    assert v["id"] is None
    assert v["driving_rule_id"] is None
    # verdict.call carries the deterministic descriptive dominant-signal phrase (non-empty → header renders)
    assert v["call"] == DESCRIPTIVE_PHRASE
    assert v["polarity"] == "neutral"
    # no card is driving (a pure-descriptive skill selects no driving_rule_id even though rules fire)
    assert not [c for c in graph["cards"] if c["chain"]["is_driving"]]


# ── role partition (from fired_rules; gateless → is_driving never set) ──────────────────────────────
def test_role_partition_10_verdict_bearing_10_display_only(graph):
    vb = {c["id"] for c in graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 10 and len(do) == 10 and len(graph["cards"]) == 20


# ── reconstruction: each question's cards, no orphans, capsules carry measurement_type ──────────────
def test_reconstruct_questions_and_cards(graph):
    qs = {q["id"]: q for q in graph["questions"]}
    assert len(qs) == 5
    # the two lens-axis questions carry the emitted question_table signal ("informs" — descriptive)
    assert qs["modality_route"]["signal"]["tier"] == "moderate"
    assert qs["modality_route"]["signal"]["polarity"] == "informs"
    assert qs["tractability_precedent"]["signal"]["tier"] == "strong"
    # the three context questions have no emitted row (no legacy_id) → empty question-level signal
    assert qs["biology_context"]["signal"]["tier"] is None
    assert qs["safety_genetics"]["signal"]["tier"] is None
    # the many-to-many card join (measurement_type membership)
    assert set(qs["modality_route"]["card_ids"]) == {
        "surfaceome-family-classification", "structure-features-static", "shed-ectodomain-liability",
        "protein-domains-class", "domain-modality-relevance"}
    assert set(qs["tractability_precedent"]["card_ids"]) == {
        "target-development-level", "measured-potency-tractability"}
    assert set(qs["biology_context"]["card_ids"]) == {
        "target-identity-summary", "gene-ontology-annotation", "signaling-network-mechanism",
        "reactome-pathway-membership", "ppi-interactome"}
    assert set(qs["safety_genetics"]["card_ids"]) == {
        "gnomad-lof-constraint", "gene-burden-safety", "clingen-dosage",
        "clinvar-pathogenicity-safety", "mouse-ko-phenotype", "target-safety-prioritisation"}
    assert set(qs["normal_context"]["card_ids"]) == {"paralog-buffering", "normal-tissue-liability"}
    # every card joins at least one question (nothing collapses into an "Other" layer) + carries a mt
    assert all(c["question_ids"] for c in graph["cards"])
    assert all(c["measurement_type"] for c in graph["cards"])
    # a card's question membership materializes both edge directions
    struct = next(c for c in graph["cards"] if c["id"] == "structure-features-static")
    assert struct["question_ids"] == ["modality_route"]


# ── literature MODALITY_ROUTING / TRACTABILITY_PRECEDENT axis crosswalk ─────────────────────────────
def test_literature_axis_crosswalk(decision, questions):
    d = copy.deepcopy(decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = build_evidence_graph(d, questions=questions)
    axes = {ax["axis_id"]: ax for ax in g["literature"]["axes"]}
    assert set(axes) == {"MODALITY_ROUTING", "TRACTABILITY_PRECEDENT"}
    # MODALITY_ROUTING owns BOTH the modality_route (Q1) and the biology_context (no legacy_id) questions
    assert axes["MODALITY_ROUTING"]["question_ids"] == ["modality_route", "biology_context"]
    assert axes["TRACTABILITY_PRECEDENT"]["question_ids"] == ["tractability_precedent"]
    # crosswalk materialized on the question node too
    for qid in ("modality_route", "biology_context"):
        q = next(q for q in g["questions"] if q["id"] == qid)
        assert q["literature_axis_ids"] == ["MODALITY_ROUTING"]
    tp = next(q for q in g["questions"] if q["id"] == "tractability_precedent")
    assert tp["literature_axis_ids"] == ["TRACTABILITY_PRECEDENT"]
    # the null-axis context questions are NOT literature targets
    for cid in ("safety_genetics", "normal_context"):
        q = next(q for q in g["questions"] if q["id"] == cid)
        assert q["literature_axis_ids"] == []
    # citations hoisted + referentially intact
    cit_ids = {c["id"] for c in g["citations"]}
    assert "ostrem2013" in cit_ids
    assert axes["MODALITY_ROUTING"]["citation_ids"] == ["ostrem2013"]


# ── each card's dataset→data→rule chain; a display-only card never invents a rule ───────────────────
def test_card_chains_no_driving_rule(graph):
    # a fired card contributes but is NOT driving (gateless — no driving_rule_id)
    fired = next(c for c in graph["cards"] if c["id"] == "structure-features-static")
    assert fired["role"] == "verdict_bearing"
    assert fired["rule_ids"]                       # rules fired
    assert fired["chain"]["rule_id"] is not None
    assert fired["chain"]["contributes_to_verdict"] is True
    assert fired["chain"]["is_driving"] is False   # gateless — never driving
    # a display-only card never invents a rule
    do = next(c for c in graph["cards"] if c["id"] == "target-development-level")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


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
    assert len(g["questions"]) == 5 and len(g["cards"]) == 20
    for q in g["questions"]:
        assert q["literature_axis_ids"] == []


def test_graph_without_registry_is_referentially_intact(decision):
    g = build_evidence_graph(decision, questions=[])
    assert g["questions"] == []
    assert len(g["cards"]) == 20
    for c in g["cards"]:
        assert c["question_ids"] == []
        assert set(c["dataset_ids"]) <= {d["id"] for d in g["datasets"]}
