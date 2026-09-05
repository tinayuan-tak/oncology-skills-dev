"""evidence_graph layer — on-target-safety-liability's bespoke DATA assertions for its additive claim graph.

Ground truth is a committed KRAS·COADREAD decision.json fixture (a real safety run, trimmed to only the
fields build_evidence_graph reads). The shared decision/questions/graph fixtures + the structural
invariants (referential integrity, additivity, determinism, fail-soft, no-orphans) live in
skills/conftest.py and skills/tests/test_evidence_graph_invariants.py; this file keeps ONLY what is
specific to on-target-safety-liability's graph.

Cards partition 10 verdict-bearing / 5 display-only, the sole PHARMACOVIGILANCE literature axis→question
crosswalk resolves (the safety lens' axis_labels is PHARMACOVIGILANCE-only), and a LIABILITY-class card
flags with killer polarity. The skill's signal is INVERSE-valence (strength of a safety LIABILITY): a
highly-constrained gene reads as an "absent"/opposing signal on the "is this leg safe?" hero. VERDICT-INERT:
nothing here touches the safety_verdict spine.
"""
from __future__ import annotations

import copy

# cards that fire a rule in the KRAS/COADREAD fixture (verdict-bearing) vs the pure display-only facets
VERDICT_BEARING = {
    "gnomad-lof-constraint", "gene-burden-safety", "clingen-dosage", "mouse-ko-phenotype",
    "clinvar-pathogenicity-safety", "pan-cancer-crispr-dependency-distribution",
    "normal-tissue-liability-gtex", "alteration-role", "copy-number-distribution",
    "functional-gene-state",
}
DISPLAY_ONLY = {
    "shet-lof-intolerance", "target-safety-prioritisation", "normal-tissue-liability",
    "drug-warning-safety", "onsides-adverse-event-safety",
}

# a synthetic literature_synthesis keyed by the safety lens' SOLE axis LETTER (what make_literature_fn
# emits — ON_TARGET_SAFETY.axis_labels is PHARMACOVIGILANCE-only)
_SYNTH_LIT = {
    "axes": [
        {"axis_key": "PHARMACOVIGILANCE", "literature_read": "mixed",
         "assertion": "RAS/MEK-pathway agents carry on-target dermatologic + GI class toxicity.",
         "agreement_vs_omics": "omics_blind", "confidence": "moderate",
         "citations": [{"label": "Smith 2021", "pmid": "33333333", "verified": True}]},
    ],
    "blind_spots": [], "overall_consistency": "consistent", "key_divergence": None,
}


# ── Phase 0 registry sanity ──────────────────────────────────────────────────────────────────────
def test_questions_registry_loads_nine(eg_questions):
    ids = [q["id"] for q in eg_questions]
    assert ids == ["constraint_read", "burden_read", "dosage_read", "mouse_ko_read", "clinvar_read",
                   "pan_essential_read", "normal_tissue_read", "pharmacovigilance_context",
                   "mechanism_context"]
    # unified axis vocabulary: the 7 question-hierarchy sub_group axes + the sole lens axis
    axes = {q["axis_id"] for q in eg_questions if q.get("axis_id")}
    assert axes == {"CONSTRAINT", "BURDEN", "DOSAGE", "CLINVAR", "MOUSE_KO", "PAN_ESSENTIAL",
                    "NORMAL_TISSUE", "PHARMACOVIGILANCE"}
    # the 5 human-genetics legs anchor to the emitted safety_question_table rows by legacy_id
    legacy = {q["id"]: q.get("legacy_id") for q in eg_questions}
    assert legacy["constraint_read"] == "Constraint" and legacy["clinvar_read"] == "ClinVar"
    assert legacy["mouse_ko_read"] == "Mouse-KO"
    # the additive legs carry NO leading-table row (empty signal, still anchor cards)
    assert legacy["pan_essential_read"] is None and legacy["pharmacovigilance_context"] is None


# ── role partition (which cards fired a rule in the fixture) ─────────────────────────────────────────
def test_role_partition_10_verdict_bearing_5_display_only(eg_graph):
    vb = {c["id"] for c in eg_graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in eg_graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 10 and len(do) == 5 and len(eg_graph["cards"]) == 15


# ── reconstruction: questions with signal+confidence, each question's cards, no orphans ─────────────
def test_reconstruct_questions_signal_confidence_and_cards(eg_graph):
    qs = {q["id"]: q for q in eg_graph["questions"]}
    assert len(qs) == 9
    # INVERSE-valence hero: a highly-constrained gene reads as an "absent"/opposing signal on the
    # "is this leg LoF-tolerant (safe)?" question (from the emitted safety_question_table row)
    assert qs["constraint_read"]["signal"]["tier"] == "absent"
    assert qs["constraint_read"]["signal"]["polarity"] == "opposing"
    assert qs["clinvar_read"]["signal"]["polarity"] == "opposing"      # germline_pathogenic → liability
    assert qs["mouse_ko_read"]["signal"]["polarity"] == "supportive"   # developmental_only → tolerant
    # the constraint question anchors BOTH the gnomAD driver AND the s_het complement
    assert set(qs["constraint_read"]["card_ids"]) == {"gnomad-lof-constraint", "shet-lof-intolerance"}
    # the normal-tissue question anchors the GTEx-RNA + HPA-protein breadth pair
    assert set(qs["normal_tissue_read"]["card_ids"]) == {
        "normal-tissue-liability", "normal-tissue-liability-gtex"}
    # the pharmacovigilance question anchors the two verdict-inert clinical-precedent cards
    assert set(qs["pharmacovigilance_context"]["card_ids"]) == {
        "drug-warning-safety", "onsides-adverse-event-safety"}
    # the mechanism-context question mops up the modality-conditioning + priority context cards
    assert set(qs["mechanism_context"]["card_ids"]) == {
        "alteration-role", "copy-number-distribution", "functional-gene-state",
        "target-safety-prioritisation"}
    # the additive legs carry no leading-table row (empty signal), but still anchor their cards
    assert qs["pan_essential_read"]["signal"]["tier"] is None
    assert qs["pan_essential_read"]["card_ids"] == ["pan-cancer-crispr-dependency-distribution"]
    # every card joins at least one question (nothing collapses into the "Other" layer)
    assert all(c["question_ids"] for c in eg_graph["cards"])


# ── literature PHARMACOVIGILANCE axis crosswalk (the sole axis the safety lens emits) ────────────────
def test_literature_axis_crosswalk(eg_decision, eg_questions, eg_build):
    d = copy.deepcopy(eg_decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = eg_build(d, questions=eg_questions)
    axes = {ax["axis_id"]: ax for ax in g["literature"]["axes"]}
    assert set(axes) == {"PHARMACOVIGILANCE"}
    assert axes["PHARMACOVIGILANCE"]["question_ids"] == ["pharmacovigilance_context"]
    # crosswalk materialized on the question node too (a display_only question is a valid lit target)
    qpv = next(q for q in g["questions"] if q["id"] == "pharmacovigilance_context")
    assert qpv["literature_axis_ids"] == ["PHARMACOVIGILANCE"]
    # the human-genetics/data-util axes own NO literature lane
    for cid in ("constraint_read", "pan_essential_read", "normal_tissue_read"):
        q = next(q for q in g["questions"] if q["id"] == cid)
        assert q["literature_axis_ids"] == []
    # citations hoisted + referentially intact
    cit_ids = {c["id"] for c in g["citations"]}
    assert "smith2021" in cit_ids
    assert axes["PHARMACOVIGILANCE"]["citation_ids"] == ["smith2021"]


# ── each card's dataset→data→rule→verdict chain (no .card.yaml, no prose) ───────────────────────────
def test_driving_card_chain(eg_graph):
    gn = next(c for c in eg_graph["cards"] if c["id"] == "gnomad-lof-constraint")
    assert gn["class"] == {"field": "constraint_class", "value": "highly_constrained"}
    assert gn["chain"]["rule_id"] == "highly-constrained-safety-warning"
    assert gn["chain"]["contributes_to_verdict"] is True
    assert gn["chain"]["is_driving"] is True
    # a display-only card never invents a rule
    do = next(c for c in eg_graph["cards"] if c["id"] == "drug-warning-safety")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(eg_graph, eg_decision):
    assert eg_graph["verdict"]["id"] == eg_decision["headline"]["safety_verdict"] == "highly_constrained_safety_concern"
    assert eg_graph["verdict"]["driving_rule_id"] == "highly-constrained-safety-warning"
    # a safety-liability HOLD is UNdesirable for a drug program → opposing (canonicalised from "negative")
    assert eg_graph["verdict"]["polarity"] == "opposing"
    # exactly one card carries the driving flag, and it is the verdict's driving rule's card
    driving = [c["id"] for c in eg_graph["cards"] if c["chain"]["is_driving"]]
    assert driving == ["gnomad-lof-constraint"]


# ── LIABILITY-flag polarity (the skill's signature: signal = STRENGTH of a safety liability) ─────────
def test_liability_class_card_is_flagged_killer(eg_decision, eg_questions, eg_build):
    # KRAS itself has no liability-CLASS card; inject a critical_organ_liability normal-tissue read to
    # exercise the builder's liability path + confirm the dashboard renders the killer/liability glyph.
    d = copy.deepcopy(eg_decision)
    d["headline"]["evidence_capsules"]["capsules"]["normal-tissue-liability-gtex"]["class"] = \
        "critical_organ_liability"
    g = eg_build(d, questions=eg_questions)
    c = next(x for x in g["cards"] if x["id"] == "normal-tissue-liability-gtex")
    assert c["signal"]["liability"] is True
    assert c["signal"]["polarity"] == "killer"
    assert c["signal"]["label"] == "critical_organ_liability"
