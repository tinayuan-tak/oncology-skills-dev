"""evidence_graph layer — target-intrinsic's bespoke DATA assertions for its additive claim graph.

Ground truth is a committed KRAS decision.json fixture (a real target-intrinsic run, trimmed to only
the fields build_evidence_graph reads). The shared decision/questions/graph fixtures + the structural
invariants (referential integrity, additivity, determinism, fail-soft, no-orphans) live in
skills/conftest.py and skills/tests/test_evidence_graph_invariants.py; this file keeps ONLY what is
specific to target-intrinsic's graph.

GATELESS / DESCRIPTIVE: target-intrinsic is an indication-INDEPENDENT dossier (verdict_fn=None). So the
graph's verdict.id is None and driving_rule_id is None (verdict.call carries the deterministic descriptive
phrase) — EXPECTED and null-safe. Rules DO fire on the loaded intracellular_intrinsic axis (10 cards →
role=verdict_bearing) but NO driving_rule_id is selected (no verdict_fn), so no card is is_driving. These
tests therefore drop the non-null-verdict spine-equality asserts (there is no verdict token) and instead
assert the null verdict is tolerated end-to-end and the deterministic Summary block still renders.
"""
from __future__ import annotations

import copy

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


# ── Phase 0 registry sanity ──────────────────────────────────────────────────────────────────────
def test_questions_registry_loads_five(eg_questions):
    ids = [q["id"] for q in eg_questions]
    assert ids == ["modality_route", "tractability_precedent", "biology_context",
                   "safety_genetics", "normal_context"]
    # the two lens axes shared with the target-intrinsic narrator lens (narrator_lenses.TARGET_INTRINSIC)
    axes = {q["axis_id"] for q in eg_questions if q.get("axis_id")}
    assert axes == {"MODALITY_ROUTING", "TRACTABILITY_PRECEDENT"}
    # legacy_id join keys are present ONLY on the two questions with an emitted question_table row
    assert [q.get("legacy_id") for q in eg_questions] == ["Q1", "Q2", None, None, None]
    # descriptive skill — no verdict → no verdict_bearing / corroboration question roles
    assert {q["role"] for q in eg_questions} == {"display_only"}


# ── GATELESS null-verdict is tolerated (no non-null spine assert) ───────────────────────────────────
def test_gateless_null_verdict_is_tolerant(eg_graph):
    v = eg_graph["verdict"]
    # verdict.id / driving_rule_id are None (indication-independent dossier — no nomination)
    assert v["id"] is None
    assert v["driving_rule_id"] is None
    # verdict.call carries the deterministic descriptive dominant-signal phrase (non-empty → header renders)
    assert v["call"] == DESCRIPTIVE_PHRASE
    assert v["polarity"] == "neutral"
    # no card is driving (a pure-descriptive skill selects no driving_rule_id even though rules fire)
    assert not [c for c in eg_graph["cards"] if c["chain"]["is_driving"]]


# ── role partition (from fired_rules; gateless → is_driving never set) ──────────────────────────────
def test_role_partition_10_verdict_bearing_10_display_only(eg_graph):
    vb = {c["id"] for c in eg_graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in eg_graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 10 and len(do) == 10 and len(eg_graph["cards"]) == 20


# ── reconstruction: each question's cards, no orphans, capsules carry measurement_type ──────────────
def test_reconstruct_questions_and_cards(eg_graph):
    qs = {q["id"]: q for q in eg_graph["questions"]}
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
    assert all(c["question_ids"] for c in eg_graph["cards"])
    assert all(c["measurement_type"] for c in eg_graph["cards"])
    # a card's question membership materializes both edge directions
    struct = next(c for c in eg_graph["cards"] if c["id"] == "structure-features-static")
    assert struct["question_ids"] == ["modality_route"]


# ── literature MODALITY_ROUTING / TRACTABILITY_PRECEDENT axis crosswalk ─────────────────────────────
def test_literature_axis_crosswalk(eg_decision, eg_questions, eg_build):
    d = copy.deepcopy(eg_decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = eg_build(d, questions=eg_questions)
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
def test_card_chains_no_driving_rule(eg_graph):
    # a fired card contributes but is NOT driving (gateless — no driving_rule_id)
    fired = next(c for c in eg_graph["cards"] if c["id"] == "structure-features-static")
    assert fired["role"] == "verdict_bearing"
    assert fired["rule_ids"]                       # rules fired
    assert fired["chain"]["rule_id"] is not None
    assert fired["chain"]["contributes_to_verdict"] is True
    assert fired["chain"]["is_driving"] is False   # gateless — never driving
    # a display-only card never invents a rule
    do = next(c for c in eg_graph["cards"] if c["id"] == "target-development-level")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False
