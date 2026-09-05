"""evidence_graph layer — tumor-selectivity's bespoke DATA assertions for its additive claim graph.

Ground truth is a committed KRAS·COADREAD decision.json fixture (a real tumor-selectivity run, trimmed
to only the fields build_evidence_graph reads). The shared decision/questions/graph fixtures + the
structural invariants (referential integrity, additivity, determinism, fail-soft, no-orphans) live in
skills/conftest.py and skills/tests/test_evidence_graph_invariants.py; this file keeps ONLY what is
specific to tumor-selectivity's graph.

Cards partition 7 verdict-bearing / 6 display-only, and the WIN/DIST/INT/SAFE literature axis→question
crosswalk resolves. VERDICT-INERT: nothing here touches the selectivity_class spine or the normal-breadth
/ stromal-confound veto.
"""
from __future__ import annotations

import copy

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


# ── Phase 0 registry sanity ──────────────────────────────────────────────────────────────────────
def test_questions_registry_loads_eight(eg_questions):
    ids = [q["id"] for q in eg_questions]
    assert ids == ["overexpressed_vs_origin", "comparator_robust", "per_sample_separation",
                   "absolute_allgene_rank", "window_vs_worst_normal", "malignant_intrinsic",
                   "absolute_surface_density", "spatial_bystander_risk"]
    # unified axis vocabulary shared with the tumor-selectivity narrator lens (WIN/DIST/INT/SAFE)
    axes = {q["axis_id"] for q in eg_questions if q.get("axis_id")}
    assert axes == {"WIN", "DIST", "INT", "SAFE"}
    # legacy_id join keys mirror the emitted selectivity_question_table (Q1..Q8)
    assert [q["legacy_id"] for q in eg_questions] == [f"Q{i}" for i in range(1, 9)]


# ── role partition (card role = fired-a-rule, not the editorial question role) ──────────────────────
def test_role_partition_7_verdict_bearing_6_display_only(eg_graph):
    vb = {c["id"] for c in eg_graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in eg_graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 7 and len(do) == 6 and len(eg_graph["cards"]) == 13


# ── reconstruction: questions with signal, each question's cards, no orphans ────────────────────────
def test_reconstruct_questions_signal_and_cards(eg_graph):
    qs = {q["id"]: q for q in eg_graph["questions"]}
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
    assert all(c["question_ids"] for c in eg_graph["cards"])
    # the driving card resolves to exactly its WIN question
    drv = next(c for c in eg_graph["cards"] if c["id"] == "tumor-vs-normal-selectivity")
    assert set(drv["question_ids"]) == {"overexpressed_vs_origin"}


# ── literature WIN/DIST/INT/SAFE axis crosswalk ─────────────────────────────────────────────────────
def test_literature_axis_crosswalk(eg_decision, eg_questions, eg_build):
    d = copy.deepcopy(eg_decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = eg_build(d, questions=eg_questions)
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
def test_driving_card_chain(eg_graph):
    tvn = next(c for c in eg_graph["cards"] if c["id"] == "tumor-vs-normal-selectivity")
    assert tvn["class"] == {"field": "selectivity_class", "value": "discordant_across_comparators"}
    assert tvn["chain"]["rule_id"] == "tvn-discordant-neutral-flagged"
    assert tvn["chain"]["contributes_to_verdict"] is True
    assert tvn["chain"]["is_driving"] is True
    # exactly one driving card, and it matches the verdict spine
    driving = [c for c in eg_graph["cards"] if c["chain"]["is_driving"]]
    assert [c["id"] for c in driving] == ["tumor-vs-normal-selectivity"]
    # a display-only card never invents a rule
    do = next(c for c in eg_graph["cards"] if c["id"] == "surface-abundance-density")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(eg_graph, eg_decision):
    hb_call = eg_decision["headline"]["headline_block"]["verdict"]["call"]
    assert eg_graph["verdict"]["id"] == hb_call == "discordant_across_comparators"
    assert eg_graph["verdict"]["driving_rule_id"] == eg_decision["headline"]["driving_rule_id"] \
        == "tvn-discordant-neutral-flagged"
    assert eg_graph["verdict"]["polarity"] == "neutral"
