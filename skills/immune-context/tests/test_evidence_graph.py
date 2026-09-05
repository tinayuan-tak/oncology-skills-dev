"""evidence_graph layer — immune-context's bespoke DATA assertions for its additive claim graph.

Ground truth is a committed KRAS·COADREAD decision.json fixture (a real immune-context run, trimmed to
only the fields build_evidence_graph reads). The shared decision/questions/graph fixtures + the
structural invariants (referential integrity, additivity, determinism, fail-soft, no-orphans) live in
skills/conftest.py and skills/tests/test_evidence_graph_invariants.py; this file keeps ONLY what is
specific to immune-context's graph.

immune-context is a mode=verdict skill where a SINGLE rule fires (immune_context_class →
immune_context_verdict, a direct read), so exactly one card is verdict-bearing and the other five are
verdict-inert display context. VERDICT-INERT: nothing here touches the immune_context_verdict spine.
"""
from __future__ import annotations

import copy

# the ONE card that fires a rule in the KRAS/COADREAD fixture (verdict-bearing) vs the pure display-only
# TME/immune context facets. immune-context's verdict is a direct read of immune_context_class.
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


# ── Phase 0 registry sanity ──────────────────────────────────────────────────────────────────────
def test_questions_registry_loads_three(eg_questions):
    ids = [q["id"] for q in eg_questions]
    assert ids == ["infiltration", "ici_response", "microenvironment"]
    # single lens axis, shared with the immune-context narrator lens (narrator_lenses.IMMUNE_CONTEXT)
    axes = {q["axis_id"] for q in eg_questions if q.get("axis_id")}
    assert axes == {"IMMUNE"}
    # ONLY the infiltration question has an emitted question_table row (Q1); the display questions omit
    # legacy_id (no signal/confidence to join)
    by_id = {q["id"]: q for q in eg_questions}
    assert by_id["infiltration"].get("legacy_id") == "Q1"
    assert "legacy_id" not in by_id["ici_response"]
    assert "legacy_id" not in by_id["microenvironment"]


# ── role partition ─────────────────────────────────────────────────────────────────────────────────
def test_role_partition_1_verdict_bearing_5_display_only(eg_graph):
    vb = {c["id"] for c in eg_graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in eg_graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 1 and len(do) == 5 and len(eg_graph["cards"]) == 6


# ── reconstruction: question signal+confidence, each question's cards ───────────────────────────────
def test_reconstruct_questions_signal_confidence_and_cards(eg_graph):
    qs = {q["id"]: q for q in eg_graph["questions"]}
    assert len(qs) == 3
    # signal + confidence readable off the graph (no prose parsing), matching the emitted Q1 row. The
    # descriptive question_table emits polarity `informs` (never supports/opposes the nomination).
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
    assert all(c["question_ids"] for c in eg_graph["cards"])
    # a shared measurement_type (ici_response_expression) materializes both edge directions
    ici = next(c for c in eg_graph["cards"] if c["id"] == "ici-response-imvigor210")
    assert set(ici["question_ids"]) == {"ici_response"}


# ── literature IMMUNE axis crosswalk ─────────────────────────────────────────────────────────────────
def test_literature_axis_crosswalk(eg_decision, eg_questions, eg_build):
    d = copy.deepcopy(eg_decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = eg_build(d, questions=eg_questions)
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
def test_driving_card_chain(eg_graph):
    ic = next(c for c in eg_graph["cards"] if c["id"] == "immune-context")
    assert ic["class"] == {"field": "immune_context_class", "value": "immune_intermediate"}
    assert ic["chain"]["rule_id"] == "immune-context-intermediate-tce-neutral"
    assert ic["chain"]["contributes_to_verdict"] is True
    assert ic["chain"]["is_driving"] is True
    # a display-only card never invents a rule
    do = next(c for c in eg_graph["cards"] if c["id"] == "tcga-til-fraction-saltz")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(eg_graph, eg_decision):
    assert eg_graph["verdict"]["id"] == eg_decision["headline"]["immune_context_verdict"] == "immune_intermediate"
    assert eg_graph["verdict"]["driving_rule_id"] == "immune-context-intermediate-tce-neutral"
    assert eg_graph["verdict"]["polarity"] == "neutral"
