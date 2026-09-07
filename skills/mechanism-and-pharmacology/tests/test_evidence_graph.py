"""evidence_graph layer — mechanism-and-pharmacology's bespoke DATA assertions for its additive claim graph.

Ground truth is a committed KRAS·COADREAD decision.json fixture (a real mechanism-and-pharmacology run,
trimmed to only the fields build_evidence_graph reads). The shared decision/questions/graph fixtures + the
structural invariants (referential integrity, additivity, determinism, fail-soft, no-orphans) live in
skills/conftest.py and skills/tests/test_evidence_graph_invariants.py; this file keeps ONLY what is
specific to mechanism-and-pharmacology's graph.

GATELESS / DESCRIPTIVE skill: mechanism-and-pharmacology is mode=descriptive — top-level
decision["verdict"] is None and every verdict rung is NEUTRAL (network_class is ANNOTATION DENSITY, not
target quality). It STILL resolves a headline mechanism_verdict token via the shared resolver keyed only
on the signaling-network-mechanism card's network_class, and headline_block.verdict.phrase populates the
graph verdict node's display `call` — so the verdict node carries the resolved token (here
well_characterized) rather than None. The verdict asserts below are therefore NULL-TOLERANT: the
resolved-token path is pinned for this fixture. Nothing here touches the mechanism_verdict spine.
"""

from __future__ import annotations

import copy

# cards that FIRE a rule in the KRAS/COADREAD fixture (verdict-bearing at the CARD level) vs the pure
# display-only facets. Descriptive skill: even the "verdict-bearing" cards only INFORM the neutral
# mechanism_verdict token — none pushes a nomination.
VERDICT_BEARING = {
    "signaling-network-mechanism",
    "phospho-pathway-activity",
    "dependency-predictability",
}
DISPLAY_ONLY = {
    "tahoe-drug-perturbation",
    "pathway-activity-context",
}
ALL_CARDS = VERDICT_BEARING | DISPLAY_ONLY

# a synthetic literature_synthesis keyed by the mechanism-and-pharmacology lens axis KEYS (what
# make_literature_fn emits from narrator_lenses.MECHANISM_PHARMACOLOGY.axis_labels).
_SYNTH_LIT = {
    "axes": [
        {
            "axis_key": "NETWORK",
            "literature_read": "supports",
            "assertion": "KRAS is a well-curated MAPK signaling hub.",
            "agreement_vs_omics": "agree",
            "confidence": "high",
            "citations": [{"label": "Simanshu 2017", "pmid": "28666118", "verified": True}],
        },
        {
            "axis_key": "PHOSPHO",
            "literature_read": "mixed",
            "assertion": "Phospho-signaling context.",
            "agreement_vs_omics": "omics_blind",
            "confidence": "low",
            "citations": [],
        },
        {
            "axis_key": "PATHWAY",
            "literature_read": "supports",
            "assertion": "MAPK pathway active in CRC.",
            "agreement_vs_omics": "agree",
            "confidence": "moderate",
            "citations": [],
        },
        {
            "axis_key": "PERTURBATION",
            "literature_read": "mixed",
            "assertion": "Drug-perturbation MoA.",
            "agreement_vs_omics": "omics_blind",
            "confidence": "low",
            "citations": [],
        },
        {
            "axis_key": "PREDICTABILITY",
            "literature_read": "supports",
            "assertion": "Own-omics driven dependency.",
            "agreement_vs_omics": "agree",
            "confidence": "moderate",
            "citations": [],
        },
    ],
    "blind_spots": [],
    "overall_consistency": "consistent",
    "key_divergence": None,
}


# ── Phase 0 registry sanity ──────────────────────────────────────────────────────────────────────
def test_questions_registry_loads_five(eg_questions):
    ids = [q["id"] for q in eg_questions]
    assert ids == ["network_read", "phospho_read", "pathway_read", "perturbation_read", "predictability_read"]
    # unified axis vocabulary shared with the mechanism-and-pharmacology narrator lens
    axes = {q["axis_id"] for q in eg_questions if q.get("axis_id")}
    assert axes == {"NETWORK", "PHOSPHO", "PATHWAY", "PERTURBATION", "PREDICTABILITY"}
    # legacy_id join keys mirror the emitted mechanism_question_table (Q1..Q5)
    assert [q["legacy_id"] for q in eg_questions] == [f"Q{i}" for i in range(1, 6)]
    # descriptive skill → every question is a non-corroboration `context` read (owns its axis)
    assert {q["role"] for q in eg_questions} == {"context"}
    assert all(q["role"] != "corroboration" for q in eg_questions if q.get("axis_id"))


# ── role partition (CARD roles, derived by the builder from fired rules) ─────────────────────────────
def test_role_partition_3_verdict_bearing_2_display_only(eg_graph):
    vb = {c["id"] for c in eg_graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in eg_graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 3 and len(do) == 2 and len(eg_graph["cards"]) == 5


# ── reconstruction: questions with signal, each question's cards (1:1), no orphans ──────────────────
def test_reconstruct_questions_signal_and_cards(eg_graph):
    qs = {q["id"]: q for q in eg_graph["questions"]}
    assert len(qs) == 5
    # signal readable off the graph (no prose parsing), matching the emitted question_table. This
    # DESCRIPTIVE skill's question_table polarity is `informs` (never supports/opposes a nomination).
    assert qs["network_read"]["signal"]["tier"] == "moderate"
    assert qs["network_read"]["signal"]["polarity"] == "informs"
    assert qs["phospho_read"]["signal"]["tier"] == "absent"  # not_phosphoprotein
    # the card join (measurement_type membership) — the 5 cards map 1:1 onto the 5 axes.
    assert set(qs["network_read"]["card_ids"]) == {"signaling-network-mechanism"}
    assert set(qs["phospho_read"]["card_ids"]) == {"phospho-pathway-activity"}
    assert set(qs["pathway_read"]["card_ids"]) == {"pathway-activity-context"}
    assert set(qs["perturbation_read"]["card_ids"]) == {"tahoe-drug-perturbation"}
    assert set(qs["predictability_read"]["card_ids"]) == {"dependency-predictability"}
    # every card joins exactly one question (nothing collapses into the "Other" layer)
    assert all(c["question_ids"] for c in eg_graph["cards"])
    # the network leg materializes both edge directions
    net = next(c for c in eg_graph["cards"] if c["id"] == "signaling-network-mechanism")
    assert net["question_ids"] == ["network_read"]


# ── literature NETWORK/PHOSPHO/PATHWAY/PERTURBATION/PREDICTABILITY axis crosswalk ────────────────────
def test_literature_axis_crosswalk(eg_decision, eg_questions, eg_build):
    d = copy.deepcopy(eg_decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = eg_build(d, questions=eg_questions)
    axes = {ax["axis_id"]: ax for ax in g["literature"]["axes"]}
    assert set(axes) == {"NETWORK", "PHOSPHO", "PATHWAY", "PERTURBATION", "PREDICTABILITY"}
    assert axes["NETWORK"]["question_ids"] == ["network_read"]
    assert axes["PHOSPHO"]["question_ids"] == ["phospho_read"]
    assert axes["PATHWAY"]["question_ids"] == ["pathway_read"]
    assert axes["PERTURBATION"]["question_ids"] == ["perturbation_read"]
    assert axes["PREDICTABILITY"]["question_ids"] == ["predictability_read"]
    # crosswalk materialized on the question node too — every lens axis resolves (no corroboration
    # questions here, so no dangling literature axis)
    for qid, axis in [
        ("network_read", "NETWORK"),
        ("phospho_read", "PHOSPHO"),
        ("pathway_read", "PATHWAY"),
        ("perturbation_read", "PERTURBATION"),
        ("predictability_read", "PREDICTABILITY"),
    ]:
        q = next(q for q in g["questions"] if q["id"] == qid)
        assert q["literature_axis_ids"] == [axis]
    # citations hoisted + referentially intact
    cit_ids = {c["id"] for c in g["citations"]}
    assert "simanshu2017" in cit_ids
    assert axes["NETWORK"]["citation_ids"] == ["simanshu2017"]


# ── each card's dataset→data→rule→verdict chain (no .card.yaml, no prose) ───────────────────────────
def test_driving_card_chain(eg_graph):
    net = next(c for c in eg_graph["cards"] if c["id"] == "signaling-network-mechanism")
    assert net["chain"]["rule_id"] == "mechanism-well-characterized-supportive"
    assert net["chain"]["contributes_to_verdict"] is True
    assert net["chain"]["is_driving"] is True
    # exactly one driving card, and it matches the verdict's driving_rule_id
    driving = [c["id"] for c in eg_graph["cards"] if c["chain"]["is_driving"]]
    assert driving == ["signaling-network-mechanism"]
    # a display-only card never invents a rule
    do = next(c for c in eg_graph["cards"] if c["id"] == "pathway-activity-context")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(eg_graph, eg_decision):
    # NULL-TOLERANT: the top-level decision verdict is None (descriptive/verdict-inert), but the headline
    # resolves a mechanism_verdict token whose descriptive phrase populates the graph's verdict node.
    assert eg_decision.get("verdict") is None
    assert eg_decision["headline"]["mechanism_verdict"] == "well_characterized"
    assert eg_graph["verdict"]["id"] == "well_characterized"
    assert eg_graph["verdict"]["call"] == "Well-characterized signaling network"
    assert eg_graph["verdict"]["driving_rule_id"] == "mechanism-well-characterized-supportive"
    assert eg_graph["verdict"]["polarity"] == "neutral"  # descriptive — every rung neutral
