"""evidence_graph layer — translational-readiness's bespoke DATA assertions for its additive claim graph.

Ground truth is a committed KRAS·COADREAD decision.json fixture (a real translational-readiness run,
trimmed to only the fields build_evidence_graph reads). The shared decision/questions/graph fixtures + the
structural invariants (referential integrity, additivity, determinism, fail-soft, no-orphans) live in
skills/conftest.py and skills/tests/test_evidence_graph_invariants.py; this file keeps ONLY what is
specific to translational-readiness's graph.

translational-readiness is GATELESS / DESCRIPTIVE (verdict_fn=None): the skill emits NO nomination
verdict, so the graph's verdict node carries id=None (verdict.call is null) and polarity `neutral`, while
the display `call` falls back to the deterministic descriptive phrase — the dashboard's Summary + header
still render. NB the ONE borrowed functional-requirement dependency rule that the organoid-crispr-
dependency card fires means that ONE card projects as a `verdict_bearing` CARD (a fired-rule fact) even
though the SKILL bears no verdict; the other three legs are display_only. VERDICT-INERT: nothing here
touches a spine (there is none).
"""

from __future__ import annotations

import copy

# In a standalone run the ONLY card that fires a rule is organoid-crispr-dependency (its BORROWED
# functional-requirement dependency rule) — so it is the sole verdict_bearing CARD; the other three
# translational legs fire no rule (the skill is gateless) and are display_only.
VERDICT_BEARING = {"organoid-crispr-dependency"}
DISPLAY_ONLY = {
    "target-model-availability",
    "target-genotype-matched-model",
    "target-pdx-drug-response",
}

# a synthetic literature_synthesis keyed by the translational-readiness lens axis LETTERS
# (narrator_lenses.TRANSLATIONAL_READINESS.axis_labels keys — what make_literature_fn emits)
_SYNTH_LIT = {
    "axes": [
        {
            "axis_key": "MODEL",
            "literature_read": "supports",
            "assertion": "HCMI patient-derived colorectal models are available.",
            "agreement_vs_omics": "agree",
            "confidence": "high",
            "citations": [{"label": "Vlachogiannis 2018", "pmid": "29472484", "verified": True}],
        },
        {
            "axis_key": "GENOTYPE",
            "literature_read": "supports",
            "assertion": "KRAS-mutant colorectal organoids exist.",
            "agreement_vs_omics": "agree",
            "confidence": "moderate",
            "citations": [],
        },
        {
            "axis_key": "ORGANOID",
            "literature_read": "mixed",
            "assertion": "Organoid dependency partially reproduces.",
            "agreement_vs_omics": "omics_blind",
            "confidence": "low",
            "citations": [],
        },
        {
            "axis_key": "PDX",
            "literature_read": "supports",
            "assertion": "PDXE regressions reported for KRAS-directed agents.",
            "agreement_vs_omics": "agree",
            "confidence": "high",
            "citations": [],
        },
    ],
    "blind_spots": [],
    "overall_consistency": "consistent",
    "key_divergence": None,
}


# ── Phase 0 registry sanity ──────────────────────────────────────────────────────────────────────
def test_questions_registry_loads_four(eg_questions):
    ids = [q["id"] for q in eg_questions]
    assert ids == [
        "models_available",
        "genotype_matched_model_carries_alteration",
        "organoid_ex_vivo_dependency",
        "pdx_in_vivo_response",
    ]
    # unified axis vocabulary shared with the translational-readiness narrator lens
    axes = {q["axis_id"] for q in eg_questions if q.get("axis_id")}
    assert axes == {"MODEL", "GENOTYPE", "ORGANOID", "PDX"}
    # legacy_id join keys mirror the emitted translational_readiness_question_table (Q1..Q4)
    assert [q["legacy_id"] for q in eg_questions] == [f"Q{i}" for i in range(1, 5)]
    # descriptive skill → every question is a non-corroboration `context` read (owns its axis)
    assert {q["role"] for q in eg_questions} == {"context"}


# ── role partition (CARD roles, derived by the builder from fired rules) ─────────────────────────────
def test_card_role_partition_one_verdict_bearing_three_display_only(eg_graph):
    vb = {c["id"] for c in eg_graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in eg_graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 1 and len(do) == 3 and len(eg_graph["cards"]) == 4


# ── reconstruction: each question anchors exactly its one card; no orphans ──────────────────────────
def test_reconstruct_questions_and_cards(eg_graph):
    qs = {q["id"]: q for q in eg_graph["questions"]}
    assert len(qs) == 4
    # the many-to-many card join (measurement_type membership) — here strictly 1:1 per leg
    assert set(qs["models_available"]["card_ids"]) == {"target-model-availability"}
    assert set(qs["genotype_matched_model_carries_alteration"]["card_ids"]) == {"target-genotype-matched-model"}
    assert set(qs["organoid_ex_vivo_dependency"]["card_ids"]) == {"organoid-crispr-dependency"}
    assert set(qs["pdx_in_vivo_response"]["card_ids"]) == {"target-pdx-drug-response"}
    # the descriptive question signal is `informs` (never supports/opposes) — canonical pass-through
    assert qs["models_available"]["signal"]["polarity"] == "informs"
    # every card joins at least one question (nothing collapses into the "Other" layer)
    assert all(c["question_ids"] for c in eg_graph["cards"])
    # each card's inverse edge names exactly its owning question
    by_card = {c["id"]: c for c in eg_graph["cards"]}
    assert by_card["organoid-crispr-dependency"]["question_ids"] == ["organoid_ex_vivo_dependency"]
    assert by_card["target-pdx-drug-response"]["question_ids"] == ["pdx_in_vivo_response"]
    # the card axis_id is projected from its owning question's axis
    assert by_card["target-model-availability"]["axis_id"] == "MODEL"


# ── literature MODEL/GENOTYPE/ORGANOID/PDX axis crosswalk ────────────────────────────────────────────
def test_literature_axis_crosswalk(eg_decision, eg_questions, eg_build):
    d = copy.deepcopy(eg_decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = eg_build(d, questions=eg_questions)
    axes = {ax["axis_id"]: ax for ax in g["literature"]["axes"]}
    assert set(axes) == {"MODEL", "GENOTYPE", "ORGANOID", "PDX"}
    assert axes["MODEL"]["question_ids"] == ["models_available"]
    assert axes["GENOTYPE"]["question_ids"] == ["genotype_matched_model_carries_alteration"]
    assert axes["ORGANOID"]["question_ids"] == ["organoid_ex_vivo_dependency"]
    assert axes["PDX"]["question_ids"] == ["pdx_in_vivo_response"]
    # crosswalk materialized on the question node too — all four `context` questions own their axis
    for qid, axis in (
        ("models_available", "MODEL"),
        ("genotype_matched_model_carries_alteration", "GENOTYPE"),
        ("organoid_ex_vivo_dependency", "ORGANOID"),
        ("pdx_in_vivo_response", "PDX"),
    ):
        q = next(q for q in g["questions"] if q["id"] == qid)
        assert q["literature_axis_ids"] == [axis]
    # citations hoisted + referentially intact
    cit_ids = {c["id"] for c in g["citations"]}
    assert "vlachogiannis2018" in cit_ids
    assert axes["MODEL"]["citation_ids"] == ["vlachogiannis2018"]


# ── each card's dataset→data→rule→verdict chain (no .card.yaml, no prose) ───────────────────────────
def test_card_chains(eg_graph):
    by_card = {c["id"]: c for c in eg_graph["cards"]}
    # the ONE card that fired a (borrowed) rule contributes but is NOT driving (no skill verdict / driver)
    org = by_card["organoid-crispr-dependency"]
    assert org["chain"]["rule_id"] == "organoid-broad-dependency-supportive"
    assert org["chain"]["contributes_to_verdict"] is True
    assert org["chain"]["is_driving"] is False  # gateless — there is no driving card
    assert org["rule_ids"] == ["organoid-broad-dependency-supportive"]
    # a display-only leg never invents a rule
    pdx = by_card["target-pdx-drug-response"]
    assert pdx["role"] == "display_only"
    assert pdx["rule_ids"] == []
    assert pdx["chain"]["rule_id"] is None
    assert pdx["chain"]["is_driving"] is False


def test_verdict_node_is_null_safe_descriptive(eg_graph):
    v = eg_graph["verdict"]
    # GATELESS skill: no verdict id / no driving rule; polarity defaults neutral (null-safe)
    assert v["id"] is None
    assert v["driving_rule_id"] is None
    assert v["polarity"] == "neutral"
    # the DISPLAY call still resolves to the deterministic descriptive phrase (Summary/header render)
    assert v["call"] and "validatable" in v["call"].lower()
