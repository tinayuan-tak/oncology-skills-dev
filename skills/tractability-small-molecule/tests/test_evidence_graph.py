"""evidence_graph layer — acceptance tests for tractability-small-molecule's additive claim graph at
decision.headline.evidence_graph, plus a standalone-dashboard render smoke test.

Ground truth is a committed KRAS·COADREAD decision.json fixture (a real tractability-small-molecule run,
trimmed to only the fields build_evidence_graph reads — verified to yield a byte-identical graph vs the
full decision). The graph is BUILT from that fixture + the canonical questions.yaml registry, so these
tests prove the projection reconstructs the dashboard with zero .card.yaml reads / zero free-text parsing,
is referentially intact, byte-stable (purely additive), partitions cards 7 verdict-bearing / 1
display-only (gdsc-drug-activity fires no rule), and resolves the POTENCY/ACTIVITY/STRUCT/DRUG/DEGRADER
literature axis→question crosswalk (the tractability-small-molecule narrator-lens axes). VERDICT-INERT:
nothing here touches the druggability_snapshot spine.
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

# cards that fire a rule in the KRAS/COADREAD fixture (verdict-bearing) vs the pure display-only facet.
# gdsc-drug-activity is the 2nd-platform ORTHOGONAL corroboration — DISPLAY-ONLY / verdict-INERT by
# design (fires no rule, feeds no resolver rung; the druggability_snapshot spine is byte-stable).
VERDICT_BEARING = {
    "prism-compound-activity", "prism-crispr-concordance", "dependency-predictability",
    "structure-features-static", "known-drug-tractability", "measured-potency-tractability",
    "degradation-feasibility",
}
DISPLAY_ONLY = {"gdsc-drug-activity"}

# a synthetic literature_synthesis keyed by the tractability-small-molecule lens axis KEYS
# (narrator_lenses.TRACTABILITY_SM.axis_labels — what make_literature_fn emits as axis_key).
_SYNTH_LIT = {
    "axes": [
        {"axis_key": "POTENCY", "literature_read": "supports", "assertion": "Sub-uM binders reported.",
         "agreement_vs_omics": "agree", "confidence": "high",
         "citations": [{"label": "Ostrem 2013", "pmid": "24256730", "verified": True}]},
        {"axis_key": "ACTIVITY", "literature_read": "supports", "assertion": "Sotorasib clinically active.",
         "agreement_vs_omics": "agree", "confidence": "high", "citations": []},
        {"axis_key": "STRUCT", "literature_read": "supports", "assertion": "Switch-II pocket crystallized.",
         "agreement_vs_omics": "agree", "confidence": "moderate", "citations": []},
        {"axis_key": "DRUG", "literature_read": "supports", "assertion": "Approved KRAS-G12C drugs.",
         "agreement_vs_omics": "agree", "confidence": "high", "citations": []},
        {"axis_key": "DEGRADER", "literature_read": "mixed", "assertion": "PROTAC efforts nascent.",
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
def test_questions_registry_loads_seven(questions):
    ids = [q["id"] for q in questions]
    assert ids == ["measured_binding_potency", "has_active_compound",
                   "chemically_agrees_with_dependency", "ligandable_pocket",
                   "known_drug_pharmacology", "degrader_handle", "corroborated_predictable"]
    # unified axis vocabulary shared with the tractability-small-molecule narrator lens
    # (narrator_lenses.TRACTABILITY_SM.axis_labels + tractability_claims.SMALL_MOLECULE_CLAIM_SPEC)
    axes = {q["axis_id"] for q in questions if q.get("axis_id")}
    assert axes == {"POTENCY", "ACTIVITY", "STRUCT", "DRUG", "DEGRADER"}
    # legacy_id join keys mirror the emitted tractability_sm_question_table rows (Compound / Concordance /
    # Structure / Known-drug); POTENCY + DEGRADER + the corroboration row carry no emitted row (None).
    assert [q.get("legacy_id") for q in questions] == [
        None, "Compound", "Concordance", "Structure", "Known-drug", None, None]


# ── role partition ─────────────────────────────────────────────────────────────────────────────────
def test_role_partition_7_verdict_bearing_1_display_only(graph):
    vb = {c["id"] for c in graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 7 and len(do) == 1 and len(graph["cards"]) == 8


# ── reconstruction: questions with signal+confidence, each question's cards, no orphans ─────────────
def test_reconstruct_questions_signal_confidence_and_cards(graph):
    qs = {q["id"]: q for q in graph["questions"]}
    assert len(qs) == 7
    # signal + confidence readable off the graph (no prose parsing), matching the emitted question_table:
    # the Compound row (prism_activity_class=clinical_precedent_only) → strong/supportive.
    assert qs["has_active_compound"]["signal"]["tier"] == "strong"
    assert qs["has_active_compound"]["signal"]["polarity"] == "supportive"
    assert qs["has_active_compound"]["confidence"]["level"] == "moderate"
    # the Concordance row (triangulated_target_engaged) → strong/supportive
    assert qs["chemically_agrees_with_dependency"]["signal"]["polarity"] == "supportive"
    # POTENCY / DEGRADER / corroboration carry no emitted question_table row → empty signal (fail-soft)
    assert qs["measured_binding_potency"]["signal"]["polarity"] is None
    assert qs["degrader_handle"]["signal"]["polarity"] is None
    # the many-to-many card join (measurement_type membership)
    assert set(qs["has_active_compound"]["card_ids"]) == {
        "prism-compound-activity", "gdsc-drug-activity"}
    assert set(qs["chemically_agrees_with_dependency"]["card_ids"]) == {"prism-crispr-concordance"}
    assert set(qs["measured_binding_potency"]["card_ids"]) == {"measured-potency-tractability"}
    assert set(qs["ligandable_pocket"]["card_ids"]) == {"structure-features-static"}
    assert set(qs["known_drug_pharmacology"]["card_ids"]) == {"known-drug-tractability"}
    assert set(qs["degrader_handle"]["card_ids"]) == {"degradation-feasibility"}
    assert set(qs["corroborated_predictable"]["card_ids"]) == {"dependency-predictability"}
    # every card joins at least one question (nothing collapses into the "Other" layer)
    assert all(c["question_ids"] for c in graph["cards"])
    # the display-only 2nd-platform card shares the prism_compound_activity measurement_type → ACTIVITY
    gdsc = next(c for c in graph["cards"] if c["id"] == "gdsc-drug-activity")
    assert set(gdsc["question_ids"]) == {"has_active_compound"}


# ── literature POTENCY/ACTIVITY/STRUCT/DRUG/DEGRADER axis crosswalk ──────────────────────────────────
def test_literature_axis_crosswalk(decision, questions):
    d = copy.deepcopy(decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = build_evidence_graph(d, questions=questions)
    axes = {ax["axis_id"]: ax for ax in g["literature"]["axes"]}
    assert set(axes) == {"POTENCY", "ACTIVITY", "STRUCT", "DRUG", "DEGRADER"}
    assert axes["POTENCY"]["question_ids"] == ["measured_binding_potency"]
    # ACTIVITY owns BOTH the compound-activity + chemical-genetic-concordance questions
    assert axes["ACTIVITY"]["question_ids"] == [
        "has_active_compound", "chemically_agrees_with_dependency"]
    assert axes["STRUCT"]["question_ids"] == ["ligandable_pocket"]
    assert axes["DRUG"]["question_ids"] == ["known_drug_pharmacology"]
    assert axes["DEGRADER"]["question_ids"] == ["degrader_handle"]
    # crosswalk materialized on the question node too
    q_pot = next(q for q in g["questions"] if q["id"] == "measured_binding_potency")
    assert q_pot["literature_axis_ids"] == ["POTENCY"]
    # the corroboration question (corroborated_predictable) is NOT a literature target
    q_corr = next(q for q in g["questions"] if q["id"] == "corroborated_predictable")
    assert q_corr["literature_axis_ids"] == []
    # citations hoisted + referentially intact
    cit_ids = {c["id"] for c in g["citations"]}
    assert "ostrem2013" in cit_ids
    assert axes["POTENCY"]["citation_ids"] == ["ostrem2013"]


# ── each card's dataset→data→rule→verdict chain (no .card.yaml, no prose) ───────────────────────────
def test_driving_card_chain(graph):
    # the driving card is prism-crispr-concordance (carries e7-triangulated-target-engaged-supportive)
    concord = next(c for c in graph["cards"] if c["id"] == "prism-crispr-concordance")
    assert concord["class"] == {"field": "crispr_prism_concordance_class",
                                "value": "triangulated_target_engaged"}
    assert concord["chain"]["rule_id"] == "e7-triangulated-target-engaged-supportive"
    assert concord["chain"]["contributes_to_verdict"] is True
    assert concord["chain"]["is_driving"] is True
    # exactly one driving card, and it matches the verdict spine
    driving = [c["id"] for c in graph["cards"] if c["chain"]["is_driving"]]
    assert driving == ["prism-crispr-concordance"]
    # a display-only card never invents a rule
    do = next(c for c in graph["cards"] if c["id"] == "gdsc-drug-activity")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(graph, decision):
    assert graph["verdict"]["id"] == decision["headline"]["druggability_snapshot"] == "well_covered"
    assert graph["verdict"]["driving_rule_id"] == "e7-triangulated-target-engaged-supportive"
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
    assert len(g["questions"]) == 7 and len(g["cards"]) == 8
    for q in g["questions"]:
        assert q["literature_axis_ids"] == []


def test_graph_without_registry_is_referentially_intact(decision):
    g = build_evidence_graph(decision, questions=[])
    assert g["questions"] == []
    assert len(g["cards"]) == 8
    for c in g["cards"]:
        assert c["question_ids"] == []
        assert set(c["dataset_ids"]) <= {d["id"] for d in g["datasets"]}
