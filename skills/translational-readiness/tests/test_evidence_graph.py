"""evidence_graph layer — acceptance tests for translational-readiness's additive claim graph at
decision.headline.evidence_graph, plus a standalone-dashboard render smoke test.

Ground truth is a committed KRAS·COADREAD decision.json fixture (a real translational-readiness run,
trimmed to only the fields build_evidence_graph reads — verified to yield a byte-identical graph vs the
full decision AND vs the graph the dispatcher attaches). The graph is BUILT from that fixture + the
canonical questions.yaml registry, so these tests prove the projection reconstructs the dashboard with
zero .card.yaml reads / zero free-text parsing, is referentially intact, byte-stable (purely additive),
anchors every card to exactly one question (no orphans), and resolves the MODEL/GENOTYPE/ORGANOID/PDX
literature axis→question crosswalk.

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
from _skills_common.evidence_graph_dashboard import render_dashboard  # noqa: E402

# In a standalone run the ONLY card that fires a rule is organoid-crispr-dependency (its BORROWED
# functional-requirement dependency rule) — so it is the sole verdict_bearing CARD; the other three
# translational legs fire no rule (the skill is gateless) and are display_only.
VERDICT_BEARING = {"organoid-crispr-dependency"}
DISPLAY_ONLY = {
    "target-model-availability", "target-genotype-matched-model", "target-pdx-drug-response",
}

# a synthetic literature_synthesis keyed by the translational-readiness lens axis LETTERS
# (narrator_lenses.TRANSLATIONAL_READINESS.axis_labels keys — what make_literature_fn emits)
_SYNTH_LIT = {
    "axes": [
        {"axis_key": "MODEL", "literature_read": "supports",
         "assertion": "HCMI patient-derived colorectal models are available.",
         "agreement_vs_omics": "agree", "confidence": "high",
         "citations": [{"label": "Vlachogiannis 2018", "pmid": "29472484", "verified": True}]},
        {"axis_key": "GENOTYPE", "literature_read": "supports",
         "assertion": "KRAS-mutant colorectal organoids exist.",
         "agreement_vs_omics": "agree", "confidence": "moderate", "citations": []},
        {"axis_key": "ORGANOID", "literature_read": "mixed",
         "assertion": "Organoid dependency partially reproduces.",
         "agreement_vs_omics": "omics_blind", "confidence": "low", "citations": []},
        {"axis_key": "PDX", "literature_read": "supports",
         "assertion": "PDXE regressions reported for KRAS-directed agents.",
         "agreement_vs_omics": "agree", "confidence": "high", "citations": []},
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
def test_questions_registry_loads_four(questions):
    ids = [q["id"] for q in questions]
    assert ids == ["models_available", "genotype_matched_model_carries_alteration",
                   "organoid_ex_vivo_dependency", "pdx_in_vivo_response"]
    # unified axis vocabulary shared with the translational-readiness narrator lens
    axes = {q["axis_id"] for q in questions if q.get("axis_id")}
    assert axes == {"MODEL", "GENOTYPE", "ORGANOID", "PDX"}
    # legacy_id join keys mirror the emitted translational_readiness_question_table (Q1..Q4)
    assert [q["legacy_id"] for q in questions] == [f"Q{i}" for i in range(1, 5)]
    # descriptive skill → every question is a non-corroboration `context` read (owns its axis)
    assert {q["role"] for q in questions} == {"context"}


# ── role partition (CARD roles, derived by the builder from fired rules) ─────────────────────────────
def test_card_role_partition_one_verdict_bearing_three_display_only(graph):
    vb = {c["id"] for c in graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 1 and len(do) == 3 and len(graph["cards"]) == 4


# ── reconstruction: each question anchors exactly its one card; no orphans ──────────────────────────
def test_reconstruct_questions_and_cards(graph):
    qs = {q["id"]: q for q in graph["questions"]}
    assert len(qs) == 4
    # the many-to-many card join (measurement_type membership) — here strictly 1:1 per leg
    assert set(qs["models_available"]["card_ids"]) == {"target-model-availability"}
    assert set(qs["genotype_matched_model_carries_alteration"]["card_ids"]) == {"target-genotype-matched-model"}
    assert set(qs["organoid_ex_vivo_dependency"]["card_ids"]) == {"organoid-crispr-dependency"}
    assert set(qs["pdx_in_vivo_response"]["card_ids"]) == {"target-pdx-drug-response"}
    # the descriptive question signal is `informs` (never supports/opposes) — canonical pass-through
    assert qs["models_available"]["signal"]["polarity"] == "informs"
    # every card joins at least one question (nothing collapses into the "Other" layer)
    assert all(c["question_ids"] for c in graph["cards"])
    # each card's inverse edge names exactly its owning question
    by_card = {c["id"]: c for c in graph["cards"]}
    assert by_card["organoid-crispr-dependency"]["question_ids"] == ["organoid_ex_vivo_dependency"]
    assert by_card["target-pdx-drug-response"]["question_ids"] == ["pdx_in_vivo_response"]
    # the card axis_id is projected from its owning question's axis
    assert by_card["target-model-availability"]["axis_id"] == "MODEL"


# ── literature MODEL/GENOTYPE/ORGANOID/PDX axis crosswalk ────────────────────────────────────────────
def test_literature_axis_crosswalk(decision, questions):
    d = copy.deepcopy(decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = build_evidence_graph(d, questions=questions)
    axes = {ax["axis_id"]: ax for ax in g["literature"]["axes"]}
    assert set(axes) == {"MODEL", "GENOTYPE", "ORGANOID", "PDX"}
    assert axes["MODEL"]["question_ids"] == ["models_available"]
    assert axes["GENOTYPE"]["question_ids"] == ["genotype_matched_model_carries_alteration"]
    assert axes["ORGANOID"]["question_ids"] == ["organoid_ex_vivo_dependency"]
    assert axes["PDX"]["question_ids"] == ["pdx_in_vivo_response"]
    # crosswalk materialized on the question node too — all four `context` questions own their axis
    for qid, axis in (("models_available", "MODEL"),
                      ("genotype_matched_model_carries_alteration", "GENOTYPE"),
                      ("organoid_ex_vivo_dependency", "ORGANOID"),
                      ("pdx_in_vivo_response", "PDX")):
        q = next(q for q in g["questions"] if q["id"] == qid)
        assert q["literature_axis_ids"] == [axis]
    # citations hoisted + referentially intact
    cit_ids = {c["id"] for c in g["citations"]}
    assert "vlachogiannis2018" in cit_ids
    assert axes["MODEL"]["citation_ids"] == ["vlachogiannis2018"]


# ── each card's dataset→data→rule→verdict chain (no .card.yaml, no prose) ───────────────────────────
def test_card_chains(graph):
    by_card = {c["id"]: c for c in graph["cards"]}
    # the ONE card that fired a (borrowed) rule contributes but is NOT driving (no skill verdict / driver)
    org = by_card["organoid-crispr-dependency"]
    assert org["chain"]["rule_id"] == "organoid-broad-dependency-supportive"
    assert org["chain"]["contributes_to_verdict"] is True
    assert org["chain"]["is_driving"] is False        # gateless — there is no driving card
    assert org["rule_ids"] == ["organoid-broad-dependency-supportive"]
    # a display-only leg never invents a rule
    pdx = by_card["target-pdx-drug-response"]
    assert pdx["role"] == "display_only"
    assert pdx["rule_ids"] == []
    assert pdx["chain"]["rule_id"] is None
    assert pdx["chain"]["is_driving"] is False


def test_verdict_node_is_null_safe_descriptive(graph):
    v = graph["verdict"]
    # GATELESS skill: no verdict id / no driving rule; polarity defaults neutral (null-safe)
    assert v["id"] is None
    assert v["driving_rule_id"] is None
    assert v["polarity"] == "neutral"
    # the DISPLAY call still resolves to the deterministic descriptive phrase (Summary/header render)
    assert v["call"] and "validatable" in v["call"].lower()


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
    # the trimmed fixture is a verified stand-in for the full decision (byte-identical graph); the
    # projection is a pure function, so two builds are byte-identical.
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
    assert len(g["questions"]) == 4 and len(g["cards"]) == 4
    for q in g["questions"]:
        assert q["literature_axis_ids"] == []


def test_graph_without_registry_is_referentially_intact(decision):
    g = build_evidence_graph(decision, questions=[])
    assert g["questions"] == []
    assert len(g["cards"]) == 4
    for c in g["cards"]:
        assert c["question_ids"] == []
        assert set(c["dataset_ids"]) <= {d["id"] for d in g["datasets"]}


# ── standalone dashboard render smoke test (evidence_graph_dashboard consumes the graph ONLY) ────────
def test_dashboard_renders_summary_and_questions_with_null_verdict(decision, questions):
    d = copy.deepcopy(decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = build_evidence_graph(d, questions=questions)
    html = render_dashboard(g)
    assert "<!doctype html>" in html
    # the DETERMINISTIC Summary block renders even with a null verdict (descriptive skill)
    assert '<div class="card summ"><h2>Summary</h2>' in html
    # header verdict chip falls back to NEUTRAL (gateless — no polarity)
    assert "NEUTRAL" in html
    # the descriptive phrase renders as the verdict call
    assert "validatable" in html.lower()
    # all 4 question slugs render (fingerprint label + question-table row)
    for qid in ("models_available", "genotype_matched_model_carries_alteration",
                "organoid_ex_vivo_dependency", "pdx_in_vivo_response"):
        assert qid in html
    # the borrowed-rule card + literature crosswalk render
    assert "organoid-crispr-dependency" in html
    assert "HCMI patient-derived colorectal models are available" in html
