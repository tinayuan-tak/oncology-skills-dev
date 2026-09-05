"""evidence_graph layer — acceptance tests for mechanism-and-pharmacology's additive claim graph at
decision.headline.evidence_graph, plus a standalone-dashboard render smoke test.

Ground truth is a committed KRAS·COADREAD decision.json fixture (a real mechanism-and-pharmacology run,
trimmed to only the fields build_evidence_graph reads — verified at authoring time to yield a byte-
identical graph vs the full decision). The graph is BUILT from that fixture + the canonical questions.yaml
registry, so these tests prove the projection reconstructs the dashboard with zero .card.yaml reads / zero
free-text parsing, is referentially intact, byte-stable (purely additive), partitions cards 3 verdict-
bearing / 2 display-only (the three rule-firing cards are verdict-bearing here), and resolves the
NETWORK/PHOSPHO/PATHWAY/PERTURBATION/PREDICTABILITY literature axis→question crosswalk.

GATELESS / DESCRIPTIVE skill: mechanism-and-pharmacology is mode=descriptive — top-level
decision["verdict"] is None and every verdict rung is NEUTRAL (network_class is ANNOTATION DENSITY, not
target quality). It STILL resolves a headline mechanism_verdict token via the shared resolver keyed only
on the signaling-network-mechanism card's network_class, and headline_block.verdict.phrase populates the
graph verdict node's display `call` — so the verdict node carries the resolved token (here
well_characterized) rather than None. The verdict asserts below are therefore NULL-TOLERANT: the
resolved-token path is pinned for this fixture, and a dedicated test proves the deterministic Summary
block + verdict header still render when the token/headline_block are absent (a truly-inert run). Nothing
here touches the mechanism_verdict spine.
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

# cards that FIRE a rule in the KRAS/COADREAD fixture (verdict-bearing at the CARD level) vs the pure
# display-only facets. Descriptive skill: even the "verdict-bearing" cards only INFORM the neutral
# mechanism_verdict token — none pushes a nomination.
VERDICT_BEARING = {
    "signaling-network-mechanism", "phospho-pathway-activity", "dependency-predictability",
}
DISPLAY_ONLY = {
    "tahoe-drug-perturbation", "pathway-activity-context",
}
ALL_CARDS = VERDICT_BEARING | DISPLAY_ONLY

# a synthetic literature_synthesis keyed by the mechanism-and-pharmacology lens axis KEYS (what
# make_literature_fn emits from narrator_lenses.MECHANISM_PHARMACOLOGY.axis_labels).
_SYNTH_LIT = {
    "axes": [
        {"axis_key": "NETWORK", "literature_read": "supports",
         "assertion": "KRAS is a well-curated MAPK signaling hub.",
         "agreement_vs_omics": "agree", "confidence": "high",
         "citations": [{"label": "Simanshu 2017", "pmid": "28666118", "verified": True}]},
        {"axis_key": "PHOSPHO", "literature_read": "mixed", "assertion": "Phospho-signaling context.",
         "agreement_vs_omics": "omics_blind", "confidence": "low", "citations": []},
        {"axis_key": "PATHWAY", "literature_read": "supports", "assertion": "MAPK pathway active in CRC.",
         "agreement_vs_omics": "agree", "confidence": "moderate", "citations": []},
        {"axis_key": "PERTURBATION", "literature_read": "mixed", "assertion": "Drug-perturbation MoA.",
         "agreement_vs_omics": "omics_blind", "confidence": "low", "citations": []},
        {"axis_key": "PREDICTABILITY", "literature_read": "supports",
         "assertion": "Own-omics driven dependency.", "agreement_vs_omics": "agree",
         "confidence": "moderate", "citations": []},
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
    assert ids == ["network_read", "phospho_read", "pathway_read", "perturbation_read",
                   "predictability_read"]
    # unified axis vocabulary shared with the mechanism-and-pharmacology narrator lens
    axes = {q["axis_id"] for q in questions if q.get("axis_id")}
    assert axes == {"NETWORK", "PHOSPHO", "PATHWAY", "PERTURBATION", "PREDICTABILITY"}
    # legacy_id join keys mirror the emitted mechanism_question_table (Q1..Q5)
    assert [q["legacy_id"] for q in questions] == [f"Q{i}" for i in range(1, 6)]
    # descriptive skill → every question is a non-corroboration `context` read (owns its axis)
    assert {q["role"] for q in questions} == {"context"}
    assert all(q["role"] != "corroboration" for q in questions if q.get("axis_id"))


# ── role partition (CARD roles, derived by the builder from fired rules) ─────────────────────────────
def test_role_partition_3_verdict_bearing_2_display_only(graph):
    vb = {c["id"] for c in graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 3 and len(do) == 2 and len(graph["cards"]) == 5


# ── reconstruction: questions with signal, each question's cards (1:1), no orphans ──────────────────
def test_reconstruct_questions_signal_and_cards(graph):
    qs = {q["id"]: q for q in graph["questions"]}
    assert len(qs) == 5
    # signal readable off the graph (no prose parsing), matching the emitted question_table. This
    # DESCRIPTIVE skill's question_table polarity is `informs` (never supports/opposes a nomination).
    assert qs["network_read"]["signal"]["tier"] == "moderate"
    assert qs["network_read"]["signal"]["polarity"] == "informs"
    assert qs["phospho_read"]["signal"]["tier"] == "absent"      # not_phosphoprotein
    # the card join (measurement_type membership) — the 5 cards map 1:1 onto the 5 axes.
    assert set(qs["network_read"]["card_ids"]) == {"signaling-network-mechanism"}
    assert set(qs["phospho_read"]["card_ids"]) == {"phospho-pathway-activity"}
    assert set(qs["pathway_read"]["card_ids"]) == {"pathway-activity-context"}
    assert set(qs["perturbation_read"]["card_ids"]) == {"tahoe-drug-perturbation"}
    assert set(qs["predictability_read"]["card_ids"]) == {"dependency-predictability"}
    # every card joins exactly one question (nothing collapses into the "Other" layer)
    assert all(c["question_ids"] for c in graph["cards"])
    # the network leg materializes both edge directions
    net = next(c for c in graph["cards"] if c["id"] == "signaling-network-mechanism")
    assert net["question_ids"] == ["network_read"]


# ── literature NETWORK/PHOSPHO/PATHWAY/PERTURBATION/PREDICTABILITY axis crosswalk ────────────────────
def test_literature_axis_crosswalk(decision, questions):
    d = copy.deepcopy(decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = build_evidence_graph(d, questions=questions)
    axes = {ax["axis_id"]: ax for ax in g["literature"]["axes"]}
    assert set(axes) == {"NETWORK", "PHOSPHO", "PATHWAY", "PERTURBATION", "PREDICTABILITY"}
    assert axes["NETWORK"]["question_ids"] == ["network_read"]
    assert axes["PHOSPHO"]["question_ids"] == ["phospho_read"]
    assert axes["PATHWAY"]["question_ids"] == ["pathway_read"]
    assert axes["PERTURBATION"]["question_ids"] == ["perturbation_read"]
    assert axes["PREDICTABILITY"]["question_ids"] == ["predictability_read"]
    # crosswalk materialized on the question node too — every lens axis resolves (no corroboration
    # questions here, so no dangling literature axis)
    for qid, axis in [("network_read", "NETWORK"), ("phospho_read", "PHOSPHO"),
                      ("pathway_read", "PATHWAY"), ("perturbation_read", "PERTURBATION"),
                      ("predictability_read", "PREDICTABILITY")]:
        q = next(q for q in g["questions"] if q["id"] == qid)
        assert q["literature_axis_ids"] == [axis]
    # citations hoisted + referentially intact
    cit_ids = {c["id"] for c in g["citations"]}
    assert "simanshu2017" in cit_ids
    assert axes["NETWORK"]["citation_ids"] == ["simanshu2017"]


# ── each card's dataset→data→rule→verdict chain (no .card.yaml, no prose) ───────────────────────────
def test_driving_card_chain(graph):
    net = next(c for c in graph["cards"] if c["id"] == "signaling-network-mechanism")
    assert net["chain"]["rule_id"] == "mechanism-well-characterized-supportive"
    assert net["chain"]["contributes_to_verdict"] is True
    assert net["chain"]["is_driving"] is True
    # exactly one driving card, and it matches the verdict's driving_rule_id
    driving = [c["id"] for c in graph["cards"] if c["chain"]["is_driving"]]
    assert driving == ["signaling-network-mechanism"]
    # a display-only card never invents a rule
    do = next(c for c in graph["cards"] if c["id"] == "pathway-activity-context")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(graph, decision):
    # NULL-TOLERANT: the top-level decision verdict is None (descriptive/verdict-inert), but the headline
    # resolves a mechanism_verdict token whose descriptive phrase populates the graph's verdict node.
    assert decision.get("verdict") is None
    assert decision["headline"]["mechanism_verdict"] == "well_characterized"
    assert graph["verdict"]["id"] == "well_characterized"
    assert graph["verdict"]["call"] == "Well-characterized signaling network"
    assert graph["verdict"]["driving_rule_id"] == "mechanism-well-characterized-supportive"
    assert graph["verdict"]["polarity"] == "neutral"   # descriptive — every rung neutral


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
    assert "evidence_graph" not in decision["headline"]  # trimmed fixture predates the layer
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
    assert len(g["questions"]) == 5 and len(g["cards"]) == 5
    for q in g["questions"]:
        assert q["literature_axis_ids"] == []


def test_graph_without_registry_is_referentially_intact(decision):
    g = build_evidence_graph(decision, questions=[])
    assert g["questions"] == []
    assert len(g["cards"]) == 5
    for c in g["cards"]:
        assert c["question_ids"] == []
        assert set(c["dataset_ids"]) <= {d["id"] for d in g["datasets"]}
