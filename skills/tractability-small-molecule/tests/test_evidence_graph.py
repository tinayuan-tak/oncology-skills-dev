"""evidence_graph layer — tractability-small-molecule's bespoke DATA assertions for its additive claim graph.

Ground truth is a committed KRAS·COADREAD decision.json fixture (a real tractability-small-molecule run,
trimmed to only the fields build_evidence_graph reads). The shared decision/questions/graph fixtures + the
structural invariants (referential integrity, additivity, determinism, fail-soft, no-orphans) live in
skills/conftest.py and skills/tests/test_evidence_graph_invariants.py; this file keeps ONLY what is
specific to tractability-small-molecule's graph.

Cards partition 7 verdict-bearing / 1 display-only (gdsc-drug-activity fires no rule), and the
POTENCY/ACTIVITY/STRUCT/DRUG/DEGRADER literature axis→question crosswalk resolves. VERDICT-INERT: nothing
here touches the druggability_snapshot spine.
"""
from __future__ import annotations

import copy

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


# ── Phase 0 registry sanity ──────────────────────────────────────────────────────────────────────
def test_questions_registry_loads_seven(eg_questions):
    ids = [q["id"] for q in eg_questions]
    assert ids == ["measured_binding_potency", "has_active_compound",
                   "chemically_agrees_with_dependency", "ligandable_pocket",
                   "known_drug_pharmacology", "degrader_handle", "corroborated_predictable"]
    # unified axis vocabulary shared with the tractability-small-molecule narrator lens
    # (narrator_lenses.TRACTABILITY_SM.axis_labels + tractability_claims.SMALL_MOLECULE_CLAIM_SPEC)
    axes = {q["axis_id"] for q in eg_questions if q.get("axis_id")}
    assert axes == {"POTENCY", "ACTIVITY", "STRUCT", "DRUG", "DEGRADER"}
    # legacy_id join keys mirror the emitted tractability_sm_question_table rows (Compound / Concordance /
    # Structure / Known-drug); POTENCY + DEGRADER + the corroboration row carry no emitted row (None).
    assert [q.get("legacy_id") for q in eg_questions] == [
        None, "Compound", "Concordance", "Structure", "Known-drug", None, None]


# ── role partition ─────────────────────────────────────────────────────────────────────────────────
def test_role_partition_7_verdict_bearing_1_display_only(eg_graph):
    vb = {c["id"] for c in eg_graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in eg_graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 7 and len(do) == 1 and len(eg_graph["cards"]) == 8


# ── reconstruction: questions with signal+confidence, each question's cards, no orphans ─────────────
def test_reconstruct_questions_signal_confidence_and_cards(eg_graph):
    qs = {q["id"]: q for q in eg_graph["questions"]}
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
    assert all(c["question_ids"] for c in eg_graph["cards"])
    # the display-only 2nd-platform card shares the prism_compound_activity measurement_type → ACTIVITY
    gdsc = next(c for c in eg_graph["cards"] if c["id"] == "gdsc-drug-activity")
    assert set(gdsc["question_ids"]) == {"has_active_compound"}


# ── literature POTENCY/ACTIVITY/STRUCT/DRUG/DEGRADER axis crosswalk ──────────────────────────────────
def test_literature_axis_crosswalk(eg_decision, eg_questions, eg_build):
    d = copy.deepcopy(eg_decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = eg_build(d, questions=eg_questions)
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
def test_driving_card_chain(eg_graph):
    # the driving card is prism-crispr-concordance (carries e7-triangulated-target-engaged-supportive)
    concord = next(c for c in eg_graph["cards"] if c["id"] == "prism-crispr-concordance")
    assert concord["class"] == {"field": "crispr_prism_concordance_class",
                                "value": "triangulated_target_engaged"}
    assert concord["chain"]["rule_id"] == "e7-triangulated-target-engaged-supportive"
    assert concord["chain"]["contributes_to_verdict"] is True
    assert concord["chain"]["is_driving"] is True
    # exactly one driving card, and it matches the verdict spine
    driving = [c["id"] for c in eg_graph["cards"] if c["chain"]["is_driving"]]
    assert driving == ["prism-crispr-concordance"]
    # a display-only card never invents a rule
    do = next(c for c in eg_graph["cards"] if c["id"] == "gdsc-drug-activity")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(eg_graph, eg_decision):
    assert eg_graph["verdict"]["id"] == eg_decision["headline"]["druggability_snapshot"] == "well_covered"
    assert eg_graph["verdict"]["driving_rule_id"] == "e7-triangulated-target-engaged-supportive"
    assert eg_graph["verdict"]["polarity"] == "supportive"   # canonical (was legacy "positive")
