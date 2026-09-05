"""evidence_graph layer — acceptance tests for surface-modality-fit's additive claim graph at
decision.headline.evidence_graph, plus a standalone-dashboard render smoke test.

Ground truth is a committed EPCAM·COADREAD decision.json fixture (a real surface-modality-fit run,
trimmed to only the fields build_evidence_graph reads — verified to yield a byte-identical graph vs the
full decision before committing). The graph is BUILT from that fixture + the canonical questions.yaml
registry, so these tests prove the projection reconstructs the dashboard with zero .card.yaml reads /
zero free-text parsing, is referentially intact, byte-stable (purely additive), partitions cards 16
verdict-bearing / 8 display-only, and resolves the FIT/TOPOLOGY/DENSITY/SAFETY/SHED literature
axis->question crosswalk. VERDICT-INERT: nothing here touches the fit_class / surface_modality_verdict
spine.

The verdict spine here is a DOWNGRADE: fit_class=both_viable but a normal-tissue-surface liability
(sc-normal-celltype-expression HIGH_LIABILITY) drives surface_modality_verdict=adc_preferred_tce_unsafe,
so the driving card is the SAFETY card (sc-normal-celltype-expression) — it must still join a question
(SAFETY), while the verdict-defining fit_class card (adc-tce-modality-fit) joins FIT.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
FIXTURE = SKILL_DIR / "tests" / "fixtures" / "epcam_coadread_decision.json"
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common.evidence_graph import build_evidence_graph, load_questions  # noqa: E402

# cards that fire a rule in the EPCAM/COADREAD fixture (verdict-bearing) vs the pure display-only facets
VERDICT_BEARING = {
    "surface-topology-and-ptm", "surfaceome-family-classification", "surfaceome-cohort-ranking",
    "adc-tce-modality-fit", "surface-abundance-density", "normal-tissue-liability",
    "copy-number-distribution", "protein-surface-evidence", "surface-colocalization-avidity",
    "surface-bulk-pair-selectivity", "tumor-scrna-celltype-expression", "modality-therapeutic-window",
    "modality-exon-window", "pmhc-epitope-evidence-iedb", "sc-normal-celltype-expression",
    "cd-antigen-backbone",
}
DISPLAY_ONLY = {
    "structure-features-static", "mutation-stratified-surface", "pathway-stratified-surface",
    "pmhc-presentation", "rna-protein-concordance-tumor", "sc-surface-normal-safety",
    "sc-surface-rna-protein-concordance", "shed-ectodomain-liability",
}

# surfaceome-cohort-ranking declares NO measurement_type in its card contract, so its capsule
# measurement_type is null and it cannot join any question via the measurement_type membership key. It is
# the ONE standard-run card that lands un-anchored (a card-contract gap in target-contracts, out of scope
# for this display-only registry). Pinned so a future contract fix that adds a measurement_type surfaces.
ORPHAN_NO_MEASUREMENT_TYPE = {"surfaceome-cohort-ranking"}

# a synthetic literature_synthesis keyed by the SURFACE_MODALITY_FIT lens axis LETTERS (make_literature_fn
# emits FIT/TOPOLOGY/DENSITY/SAFETY/SHED — the SAME axis_labels keys the narrator lens uses)
_SYNTH_LIT = {
    "axes": [
        {"axis_key": "FIT", "literature_read": "supports", "assertion": "EPCAM is a clinical ADC/TCE antigen.",
         "agreement_vs_omics": "agree", "confidence": "high",
         "citations": [{"label": "Smith 2019", "pmid": "31000000", "verified": True}]},
        {"axis_key": "TOPOLOGY", "literature_read": "supports", "assertion": "Single-pass type I surface protein.",
         "agreement_vs_omics": "agree", "confidence": "moderate", "citations": []},
        {"axis_key": "DENSITY", "literature_read": "mixed", "assertion": "Antigen density reports vary.",
         "agreement_vs_omics": "omics_blind", "confidence": "low", "citations": []},
        {"axis_key": "SAFETY", "literature_read": "opposes", "assertion": "Normal epithelium expresses EPCAM.",
         "agreement_vs_omics": "agree", "confidence": "high", "citations": []},
        {"axis_key": "SHED", "literature_read": "supports", "assertion": "EpEX shedding reported.",
         "agreement_vs_omics": "agree", "confidence": "moderate", "citations": []},
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
def test_questions_registry_loads_eight(questions):
    ids = [q["id"] for q in questions]
    assert ids == ["modality_fit_call", "topology_read", "density_read", "safety_read", "shed_read",
                   "pmhc_tce_route", "bispecific_pair", "tce_homogeneity"]
    # unified axis vocabulary shared with the SURFACE_MODALITY_FIT narrator lens (axis_labels keys)
    axes = {q["axis_id"] for q in questions if q.get("axis_id")}
    assert axes == {"FIT", "TOPOLOGY", "DENSITY", "SAFETY", "SHED"}
    # the 4 questions with an emitted question_table counterpart carry its legacy_id join key
    legacy = {q["id"]: q.get("legacy_id") for q in questions}
    assert legacy["topology_read"] == "Surface"
    assert legacy["density_read"] == "Density"
    assert legacy["shed_read"] == "ADC"
    assert legacy["tce_homogeneity"] == "TCE"
    # the FIT-axis questions (no emitted row) carry no legacy_id
    assert legacy["modality_fit_call"] is None
    assert legacy["safety_read"] is None


# ── role partition ─────────────────────────────────────────────────────────────────────────────────
def test_role_partition_16_verdict_bearing_8_display_only(graph):
    vb = {c["id"] for c in graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 16 and len(do) == 8 and len(graph["cards"]) == 24


# ── reconstruction: each question's cards, no orphans (except the mt-less contract gap) ─────────────
def test_reconstruct_questions_and_cards(graph):
    qs = {q["id"]: q for q in graph["questions"]}
    assert len(qs) == 8
    # the many-to-many card join (measurement_type membership) — the FIT core call anchors the composed
    # fit_class card + its family/backbone/window siblings + the stratified surface CONTEXT cards
    assert set(qs["modality_fit_call"]["card_ids"]) == {
        "adc-tce-modality-fit", "surfaceome-family-classification", "cd-antigen-backbone",
        "modality-therapeutic-window", "modality-exon-window", "copy-number-distribution",
        "mutation-stratified-surface", "pathway-stratified-surface"}
    assert set(qs["topology_read"]["card_ids"]) == {
        "surface-topology-and-ptm", "structure-features-static"}
    assert set(qs["density_read"]["card_ids"]) == {
        "surface-abundance-density", "protein-surface-evidence", "rna-protein-concordance-tumor",
        "sc-surface-rna-protein-concordance", "tumor-scrna-celltype-expression"}
    assert set(qs["safety_read"]["card_ids"]) == {
        "normal-tissue-liability", "sc-normal-celltype-expression", "sc-surface-normal-safety"}
    assert set(qs["shed_read"]["card_ids"]) == {"shed-ectodomain-liability"}
    assert set(qs["pmhc_tce_route"]["card_ids"]) == {"pmhc-presentation", "pmhc-epitope-evidence-iedb"}
    assert set(qs["bispecific_pair"]["card_ids"]) == {
        "surface-colocalization-avidity", "surface-bulk-pair-selectivity"}
    assert set(qs["tce_homogeneity"]["card_ids"]) == {"tumor-scrna-celltype-expression"}
    # a shared measurement_type materializes both edge directions (rna_protein_concordance on 2 cards)
    for cid in ("rna-protein-concordance-tumor", "sc-surface-rna-protein-concordance"):
        c = next(cc for cc in graph["cards"] if cc["id"] == cid)
        assert "density_read" in c["question_ids"]
    # sc_tumor_celltype_expression joins BOTH the density read and the (corroboration) homogeneity read
    tsc = next(c for c in graph["cards"] if c["id"] == "tumor-scrna-celltype-expression")
    assert set(tsc["question_ids"]) == {"density_read", "tce_homogeneity"}


def test_only_orphan_is_the_measurement_type_less_card(graph):
    orphans = {c["id"] for c in graph["cards"] if not c["question_ids"]}
    assert orphans == ORPHAN_NO_MEASUREMENT_TYPE
    # and the reason is a null capsule measurement_type (a card-contract gap), nothing else
    for c in graph["cards"]:
        if c["id"] in ORPHAN_NO_MEASUREMENT_TYPE:
            assert c["measurement_type"] is None
        else:
            assert c["measurement_type"] is not None
            assert c["question_ids"], c["id"]


# ── literature FIT/TOPOLOGY/DENSITY/SAFETY/SHED axis crosswalk ───────────────────────────────────────
def test_literature_axis_crosswalk(decision, questions):
    d = copy.deepcopy(decision)
    d["literature_synthesis"] = _SYNTH_LIT
    g = build_evidence_graph(d, questions=questions)
    axes = {ax["axis_id"]: ax for ax in g["literature"]["axes"]}
    assert set(axes) == {"FIT", "TOPOLOGY", "DENSITY", "SAFETY", "SHED"}
    # FIT owns the 3 non-corroboration FIT questions (in seq order); the others own one each
    assert axes["FIT"]["question_ids"] == ["modality_fit_call", "pmhc_tce_route", "bispecific_pair"]
    assert axes["TOPOLOGY"]["question_ids"] == ["topology_read"]
    assert axes["DENSITY"]["question_ids"] == ["density_read"]
    assert axes["SAFETY"]["question_ids"] == ["safety_read"]
    assert axes["SHED"]["question_ids"] == ["shed_read"]
    # crosswalk materialized on the question node too
    q1 = next(q for q in g["questions"] if q["id"] == "modality_fit_call")
    assert q1["literature_axis_ids"] == ["FIT"]
    # the corroboration question (tce_homogeneity) is NOT a literature target
    tce = next(q for q in g["questions"] if q["id"] == "tce_homogeneity")
    assert tce["literature_axis_ids"] == []
    # citations hoisted + referentially intact
    cit_ids = {c["id"] for c in g["citations"]}
    assert "smith2019" in cit_ids
    assert axes["FIT"]["citation_ids"] == ["smith2019"]


# ── each card's dataset→data→rule→verdict chain (no .card.yaml, no prose) ───────────────────────────
def test_driving_card_chain_is_the_safety_downgrade(graph):
    # the DRIVING card here is the SAFETY card (a normal-tissue-surface liability downgrades TCE), NOT
    # the fit_class card — it must still join a question (SAFETY).
    drv = next(c for c in graph["cards"] if c["chain"]["is_driving"])
    assert drv["id"] == "sc-normal-celltype-expression"
    assert drv["chain"]["rule_id"] == "sc-normal-high-liability-bite-killer"
    assert drv["chain"]["contributes_to_verdict"] is True
    assert "safety_read" in drv["question_ids"]
    # the verdict-DEFINING fit_class card anchors the FIT question with the composed both_viable call
    fit = next(c for c in graph["cards"] if c["id"] == "adc-tce-modality-fit")
    assert fit["question_ids"] == ["modality_fit_call"]
    assert fit["class"] == {"field": "fit_class", "value": "both_viable"}
    assert fit["chain"]["is_driving"] is False
    # a display-only card never invents a rule
    do = next(c for c in graph["cards"] if c["id"] == "shed-ectodomain-liability")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(graph, decision):
    # the verdict node id is the composed fit_class (the canonical call), NOT the downgraded token
    assert graph["verdict"]["id"] == decision["headline"]["fit_class"] == "both_viable"
    assert graph["verdict"]["driving_rule_id"] == "sc-normal-high-liability-bite-killer"
    assert graph["verdict"]["polarity"] == "supportive"   # canonical (positive → supportive)


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
    assert "evidence_graph" not in decision["headline"]  # fixture predates the layer
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
    assert len(g["questions"]) == 8 and len(g["cards"]) == 24
    for q in g["questions"]:
        assert q["literature_axis_ids"] == []


def test_graph_without_registry_is_referentially_intact(decision):
    g = build_evidence_graph(decision, questions=[])
    assert g["questions"] == []
    assert len(g["cards"]) == 24
    for c in g["cards"]:
        assert c["question_ids"] == []
        assert set(c["dataset_ids"]) <= {d["id"] for d in g["datasets"]}
