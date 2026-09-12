"""evidence_graph layer — genomic-alteration-profile's bespoke DATA assertions for its additive claim graph.

genomic-alteration-profile hand-rolls main() (no run_wired_skill), so it wires BOTH the evidence-capsule
seam (headline.evidence_capsules — WITHOUT which no card carries a measurement_type and the card↔question
join collapses) AND the evidence_graph attach itself. Ground truth is a committed KRAS·COADREAD
decision.json fixture (a real run with those seams live, trimmed to the fields build_evidence_graph
reads, with evidence_capsules baked in). The shared decision/questions/graph fixtures + the structural
invariants (referential integrity, additivity, determinism, fail-soft, no-orphans) live in
skills/conftest.py and skills/tests/test_evidence_graph_invariants.py; this file keeps ONLY what is
specific to genomic-alteration-profile's graph.

Cards partition 11 verdict-bearing / 12 display-only, and the SNV/CN/FUS/SPL/DEP literature axis→question
crosswalk resolves. VERDICT-INERT: nothing here touches the genomic_alteration_profile spine.
"""

from __future__ import annotations

import copy

VERDICT_BEARING = {
    "alteration-role",
    "amp-expr-stratified-dependency",
    "copy-number-distribution",
    "copy-number-stratified-dependency",
    "dependency-predictability",
    "functional-gene-state",
    "fusion-stratified-dependency",
    "mutation-drug-response",
    "mutation-hotspot-frequency",
    "mutation-stratified-dependency",
    "mutation-type-counts",
}

_SYNTH_LIT = {
    "axes": [
        {
            "axis_key": "SNV",
            "literature_read": "supports",
            "assertion": "KRAS is a recurrent CRC driver.",
            "agreement_vs_omics": "agree",
            "confidence": "high",
            "citations": [{"label": "Wood 2007", "pmid": "17932254", "verified": True}],
        },
        {
            "axis_key": "CN",
            "literature_read": "mixed",
            "assertion": "No recurrent focal KRAS CN driver.",
            "agreement_vs_omics": "agree",
            "confidence": "moderate",
            "citations": [],
        },
        {
            "axis_key": "FUS",
            "literature_read": "mixed",
            "assertion": "KRAS fusions rare.",
            "agreement_vs_omics": "omics_blind",
            "confidence": "low",
            "citations": [],
        },
        {
            "axis_key": "SPL",
            "literature_read": "mixed",
            "assertion": "No exon-skip driver.",
            "agreement_vs_omics": "agree",
            "confidence": "low",
            "citations": [],
        },
        {
            "axis_key": "DEP",
            "literature_read": "supports",
            "assertion": "Mutant-KRAS dependency validated.",
            "agreement_vs_omics": "agree",
            "confidence": "high",
            "citations": [],
        },
    ],
    "blind_spots": [],
    "overall_consistency": "consistent",
    "key_divergence": None,
}


# ── §3 capsule wiring guard: the hand-rolled main must carry measurement_type on every capsule ──────
def test_fixture_capsules_carry_measurement_type(eg_decision):
    caps = ((eg_decision["headline"].get("evidence_capsules") or {}).get("capsules")) or {}
    assert caps, "fixture headline.evidence_capsules is empty — the hand-rolled main() §3a wiring regressed"
    assert all(c.get("measurement_type") for c in caps.values()), (
        "a capsule lacks measurement_type — the evidence_graph card↔question join would collapse to Other"
    )


# ── Phase 0 registry sanity ──────────────────────────────────────────────────────────────────────
def test_questions_registry_loads_six(eg_questions):
    ids = [q["id"] for q in eg_questions]
    # splice is TWO questions: the exon-skip DRIVER (verdict) + a display_only splice-form DYSREGULATION
    # context question (no axis_id) so dysregulation cards don't read as evidence against "no driver".
    assert ids == [
        "snv_indel_class",
        "copy_number_driver",
        "fusion_driver",
        "splice_driver",
        "splice_dysregulation",
        "alteration_conferred_dependency",
    ]
    axes = {q["axis_id"] for q in eg_questions if q.get("axis_id")}
    assert axes == {"SNV", "CN", "FUS", "SPL", "DEP"}  # splice_dysregulation has NO axis_id
    roles = {q["id"]: q.get("role") for q in eg_questions}
    assert roles["splice_driver"] == "verdict_bearing" and roles["splice_dysregulation"] == "display_only"
    assert next(q for q in eg_questions if q["id"] == "splice_dysregulation").get("axis_id") is None
    # class questions mirror the emitted genomic_question_table ids; DEP + splice_dysregulation have no class row
    legacy = {q["id"]: q.get("legacy_id") for q in eg_questions}
    assert legacy["snv_indel_class"] == "SNV" and legacy["copy_number_driver"] == "CN"
    assert legacy["fusion_driver"] == "Fusion" and legacy["splice_driver"] == "Splice"
    assert legacy["alteration_conferred_dependency"] is None and legacy.get("splice_dysregulation") is None


# ── role partition ─────────────────────────────────────────────────────────────────────────────────
def test_role_partition(eg_graph):
    vb = {c["id"] for c in eg_graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in eg_graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    # 12 display-only (was 13; tumor-splice-expression dedup'd into tumor-splice-dysregulation 2026-09-06)
    assert len(vb) == 11 and len(do) == 12 and len(eg_graph["cards"]) == 23


# ── reconstruction: questions → cards (per-alteration-class), no orphans ────────────────────────────
def test_reconstruct_questions_and_cards(eg_graph):
    qs = {q["id"]: q for q in eg_graph["questions"]}
    assert len(qs) == 6
    assert set(qs["copy_number_driver"]["card_ids"]) == {
        "copy-number-distribution",
        "copy-number-stratified-dependency",
        "amp-expr-stratified-dependency",
    }
    assert set(qs["fusion_driver"]["card_ids"]) == {"fusion-rearrangement-landscape", "fusion-stratified-dependency"}
    # the DRIVER question anchors ONLY the exon-skip card; the splice-FORM cards route to the display_only
    # dysregulation question so "no driver" is not conflated with "dysregulation present".
    assert set(qs["splice_driver"]["card_ids"]) == {"splice-exon-skip-landscape"}
    # tumor-splice-expression was a duplicate collapsed into tumor-splice-dysregulation (2026-09-06)
    assert set(qs["splice_dysregulation"]["card_ids"]) == {"tumor-splice-dysregulation"}
    # The mutation-stratified dependency + its drug-response card route HERE, not to the SNV question.
    # They were on SNV until 2026-09-12, which is what made the SNV row display 13 cards while
    # subgroup_signals — reading the GENERATED question_hierarchy.yaml, where both types sit under DEP —
    # scored the SNV axis from 8. The two files disagreed inside one published nomination.json; the
    # hierarchy is the governed side, and `run.py`'s own `_DEP_RULE_SCOPE_CARD` already treated
    # `mutation-stratified-dependency` as a dependency rung. Guarded fleet-wide by
    # skills/tests/test_questions_yaml_hierarchy_agreement.py.
    assert set(qs["alteration_conferred_dependency"]["card_ids"]) == {
        "mutation-stratified-dependency",
        "mutation-drug-response",
        "cross-consortium-dependency",
        "dependency-predictability",
        "genomic-event-model-match",
    }
    # the SNV question anchors the mutation facets; the dependency cards above are NOT among them
    assert {"mutation-type-counts", "mutation-hotspot-frequency"} <= set(qs["snv_indel_class"]["card_ids"])
    assert not {"mutation-stratified-dependency", "mutation-drug-response"} & set(qs["snv_indel_class"]["card_ids"])
    # every card joins at least one question (nothing collapses into the "Other" layer)
    assert all(c["question_ids"] for c in eg_graph["cards"])


# ── literature SNV/CN/FUS/SPL/DEP axis crosswalk (DEP has no emitted class row but still resolves) ───
def test_literature_axis_crosswalk(eg_decision, eg_questions, eg_build):
    d = copy.deepcopy(eg_decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = eg_build(d, questions=eg_questions)
    axes = {ax["axis_id"]: ax for ax in g["literature"]["axes"]}
    assert set(axes) == {"SNV", "CN", "FUS", "SPL", "DEP"}
    assert axes["SNV"]["question_ids"] == ["snv_indel_class"]
    assert axes["CN"]["question_ids"] == ["copy_number_driver"]
    assert axes["FUS"]["question_ids"] == ["fusion_driver"]
    assert axes["SPL"]["question_ids"] == ["splice_driver"]
    assert axes["DEP"]["question_ids"] == ["alteration_conferred_dependency"]
    assert "wood2007" in {c["id"] for c in g["citations"]}


# ── driving card chain (SNV mutation-stratified-dependency) + display-only never invents a rule ─────
def test_driving_card_chain(eg_graph):
    drv = next(c for c in eg_graph["cards"] if c["id"] == "mutation-stratified-dependency")
    assert drv["chain"]["rule_id"] == "mutant-strongly-dependent-supportive"
    assert drv["chain"]["is_driving"] is True
    assert drv["chain"]["contributes_to_verdict"] is True
    do = next(c for c in eg_graph["cards"] if c["id"] == "variant-level-interpretation")
    assert do["role"] == "display_only"
    assert do["chain"]["rule_id"] is None and do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(eg_graph, eg_decision):
    assert eg_graph["verdict"]["id"] == eg_decision["headline"]["genomic_alteration_profile"]
    assert eg_graph["verdict"]["driving_rule_id"] == "mutant-strongly-dependent-supportive"
