"""evidence_graph layer — acceptance tests for genomic-alteration-profile's additive claim graph at
decision.headline.evidence_graph, plus a standalone-dashboard render smoke test.

genomic-alteration-profile hand-rolls main() (no run_wired_skill), so it wires BOTH the evidence-capsule
seam (headline.evidence_capsules — WITHOUT which no card carries a measurement_type and the card↔question
join collapses) AND the evidence_graph attach itself. Ground truth is a committed KRAS·COADREAD
decision.json fixture (a real run with those seams live, trimmed to the fields build_evidence_graph
reads — verified byte-identical graph vs the full decision, with evidence_capsules baked in).

These tests prove the projection reconstructs the per-alteration-class dashboard with zero .card.yaml
reads / zero prose parsing, is referentially intact, byte-stable, partitions cards 11 verdict-bearing /
13 display-only, and resolves the SNV/CN/FUS/SPL/DEP literature axis→question crosswalk. VERDICT-INERT:
nothing here touches the genomic_alteration_profile spine.
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

VERDICT_BEARING = {
    "alteration-role", "amp-expr-stratified-dependency", "copy-number-distribution",
    "copy-number-stratified-dependency", "dependency-predictability", "functional-gene-state",
    "fusion-stratified-dependency", "mutation-drug-response", "mutation-hotspot-frequency",
    "mutation-stratified-dependency", "mutation-type-counts",
}

_SYNTH_LIT = {
    "axes": [
        {"axis_key": "SNV", "literature_read": "supports", "assertion": "KRAS is a recurrent CRC driver.",
         "agreement_vs_omics": "agree", "confidence": "high",
         "citations": [{"label": "Wood 2007", "pmid": "17932254", "verified": True}]},
        {"axis_key": "CN", "literature_read": "mixed", "assertion": "No recurrent focal KRAS CN driver.",
         "agreement_vs_omics": "agree", "confidence": "moderate", "citations": []},
        {"axis_key": "FUS", "literature_read": "mixed", "assertion": "KRAS fusions rare.",
         "agreement_vs_omics": "omics_blind", "confidence": "low", "citations": []},
        {"axis_key": "SPL", "literature_read": "mixed", "assertion": "No exon-skip driver.",
         "agreement_vs_omics": "agree", "confidence": "low", "citations": []},
        {"axis_key": "DEP", "literature_read": "supports", "assertion": "Mutant-KRAS dependency validated.",
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


# ── §3 capsule wiring guard: the hand-rolled main must carry measurement_type on every capsule ──────
def test_fixture_capsules_carry_measurement_type(decision):
    caps = ((decision["headline"].get("evidence_capsules") or {}).get("capsules")) or {}
    assert caps, "fixture headline.evidence_capsules is empty — the hand-rolled main() §3a wiring regressed"
    assert all(c.get("measurement_type") for c in caps.values()), \
        "a capsule lacks measurement_type — the evidence_graph card↔question join would collapse to Other"


# ── Phase 0 registry sanity ──────────────────────────────────────────────────────────────────────
def test_questions_registry_loads_five(questions):
    ids = [q["id"] for q in questions]
    assert ids == ["snv_indel_class", "copy_number_driver", "fusion_driver", "splice_driver",
                   "alteration_conferred_dependency"]
    axes = {q["axis_id"] for q in questions if q.get("axis_id")}
    assert axes == {"SNV", "CN", "FUS", "SPL", "DEP"}
    # class questions mirror the emitted genomic_question_table ids; the DEP question has no class row
    legacy = {q["id"]: q.get("legacy_id") for q in questions}
    assert legacy["snv_indel_class"] == "SNV" and legacy["copy_number_driver"] == "CN"
    assert legacy["fusion_driver"] == "Fusion" and legacy["splice_driver"] == "Splice"
    assert legacy["alteration_conferred_dependency"] is None


# ── role partition ─────────────────────────────────────────────────────────────────────────────────
def test_role_partition(graph):
    vb = {c["id"] for c in graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert len(vb) == 11 and len(do) == 13 and len(graph["cards"]) == 24


# ── reconstruction: questions → cards (per-alteration-class), no orphans ────────────────────────────
def test_reconstruct_questions_and_cards(graph):
    qs = {q["id"]: q for q in graph["questions"]}
    assert len(qs) == 5
    assert set(qs["copy_number_driver"]["card_ids"]) == {
        "copy-number-distribution", "copy-number-stratified-dependency", "amp-expr-stratified-dependency"}
    assert set(qs["fusion_driver"]["card_ids"]) == {
        "fusion-rearrangement-landscape", "fusion-stratified-dependency"}
    assert set(qs["splice_driver"]["card_ids"]) == {
        "splice-exon-skip-landscape", "tumor-splice-dysregulation", "tumor-splice-expression"}
    assert set(qs["alteration_conferred_dependency"]["card_ids"]) == {
        "cross-consortium-dependency", "dependency-predictability", "genomic-event-model-match"}
    # the SNV question anchors the driving mutation-stratified-dependency card + the mutation facets
    assert {"mutation-stratified-dependency", "mutation-type-counts", "mutation-hotspot-frequency"} \
        <= set(qs["snv_indel_class"]["card_ids"])
    # every card joins at least one question (nothing collapses into the "Other" layer)
    assert all(c["question_ids"] for c in graph["cards"])


# ── literature SNV/CN/FUS/SPL/DEP axis crosswalk (DEP has no emitted class row but still resolves) ───
def test_literature_axis_crosswalk(decision, questions):
    d = copy.deepcopy(decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = build_evidence_graph(d, questions=questions)
    axes = {ax["axis_id"]: ax for ax in g["literature"]["axes"]}
    assert set(axes) == {"SNV", "CN", "FUS", "SPL", "DEP"}
    assert axes["SNV"]["question_ids"] == ["snv_indel_class"]
    assert axes["CN"]["question_ids"] == ["copy_number_driver"]
    assert axes["FUS"]["question_ids"] == ["fusion_driver"]
    assert axes["SPL"]["question_ids"] == ["splice_driver"]
    assert axes["DEP"]["question_ids"] == ["alteration_conferred_dependency"]
    assert "wood2007" in {c["id"] for c in g["citations"]}


# ── driving card chain (SNV mutation-stratified-dependency) + display-only never invents a rule ─────
def test_driving_card_chain(graph):
    drv = next(c for c in graph["cards"] if c["id"] == "mutation-stratified-dependency")
    assert drv["chain"]["rule_id"] == "mutant-strongly-dependent-supportive"
    assert drv["chain"]["is_driving"] is True
    assert drv["chain"]["contributes_to_verdict"] is True
    do = next(c for c in graph["cards"] if c["id"] == "variant-level-interpretation")
    assert do["role"] == "display_only"
    assert do["chain"]["rule_id"] is None and do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(graph, decision):
    assert graph["verdict"]["id"] == decision["headline"]["genomic_alteration_profile"]
    assert graph["verdict"]["driving_rule_id"] == "mutant-strongly-dependent-supportive"


# ── referential integrity ────────────────────────────────────────────────────────────────────────
def test_referential_integrity(graph):
    q_ids = {q["id"] for q in graph["questions"]}
    c_ids = {c["id"] for c in graph["cards"]}
    r_ids = {r["id"] for r in graph["rules"]}
    d_ids = {d["id"] for d in graph["datasets"]}
    axis_ids = {q["axis_id"] for q in graph["questions"] if q.get("axis_id")}
    for q in graph["questions"]:
        assert set(q["card_ids"]) <= c_ids and set(q["rule_ids"]) <= r_ids, q["id"]
    for c in graph["cards"]:
        assert set(c["question_ids"]) <= q_ids, c["id"]
        assert set(c["rule_ids"]) <= r_ids and set(c["dataset_ids"]) <= d_ids, c["id"]
        if c["chain"]["rule_id"] is not None:
            assert c["chain"]["rule_id"] in r_ids
        if c.get("axis_id"):
            assert c["axis_id"] in axis_ids
    for r in graph["rules"]:
        assert r["card_id"] in c_ids


# ── byte-stability / determinism / fail-soft / no-registry ──────────────────────────────────────────
def test_builder_does_not_mutate_decision(decision, questions):
    before = copy.deepcopy(decision)
    build_evidence_graph(decision, questions=questions)
    assert decision == before


def test_additive_only(decision, graph):
    enriched = copy.deepcopy(decision)
    enriched["headline"]["evidence_graph"] = graph
    assert "evidence_graph" not in decision["headline"]
    enriched["headline"].pop("evidence_graph")
    assert enriched == decision


def test_build_is_deterministic(decision, questions):
    a = json.dumps(build_evidence_graph(decision, questions=questions), default=str)
    b = json.dumps(build_evidence_graph(decision, questions=questions), default=str)
    assert a == b


def test_fail_soft_and_no_registry(decision, questions):
    g = build_evidence_graph(decision, questions=[])
    assert g["questions"] == [] and len(g["cards"]) == 24
    for c in g["cards"]:
        assert c["question_ids"] == []
