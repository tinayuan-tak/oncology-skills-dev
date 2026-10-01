"""evidence_graph layer — tumor-presence's bespoke DATA assertions for the additive claim graph at
decision.headline.evidence_graph (spec §7).

Ground truth is the committed EPCAM·COADREAD decision.json fixture (a real tumor-presence run,
pre-evidence_graph). The shared decision/questions/graph fixtures + the structural invariants
(referential integrity, additivity, determinism, fail-soft, no-orphans) live in skills/conftest.py and
skills/tests/test_evidence_graph_invariants.py; this file keeps ONLY what is specific to tumor-presence's
graph — the 9/8 role partition, reconstructed signal/confidence/cards, the axis-B literature crosswalk,
the driving-card chain, canonical-polarity + liability flags, and schema validation. VERDICT-INERT:
nothing here touches the presence_verdict spine.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from _skills_common.paths import TARGET_CONTRACTS_ROOT_DEFAULT

# ── the 8/9 role partition (spec §7.4 + appendix) ──
# `cellline-rna-protein-concordance` fires `rna-protein-adequate-proxy-supportive` (an `rna_as_biomarker`
# proxy-reliability rule) but its measurement layer (rna_protein_concordance) has no presence-verdict
# ladder in run.py `_MEASUREMENT_RANK`, so `_rank_verdict` can never select it — it moves NO presence
# verdict and is display_only, exactly like its tumor sibling `rna-protein-concordance-tumor` (#1526 F1).
VERDICT_BEARING = {
    "cellline-rna-distribution",
    "tumor-rna-vs-adjacent",
    "tumor-rna-distribution",
    "cellline-protein-abundance",
    "tumor-elevation-breadth",
    "tumor-scrna-celltype-expression",
    "expression-purity-confound",
    "sc-normal-celltype-expression",
}
DISPLAY_ONLY = {
    "tumor-protein-abundance-cptac",
    "cellline-protein-abundance-procan",
    "hpa-pathology-cancer-ihc",
    "cellline-rna-protein-concordance",
    "rna-protein-concordance-tumor",
    "tumor-rna-distribution-by-subtype",
    "cellline-rna-distribution-by-subtype",
    "tumor-protein-distribution-by-subtype",
    "normal-tissue-liability",
}
# ★ SK#1825 scope note — these three numbers describe THE COMMITTED GOLDEN, not run.py CARDS. The golden
# `fixtures/epcam_coadread_decision.json` is a frozen snapshot of a real run that PRE-DATES the 18th card
# (the TPHP DIA-MS tumor arm), so its graph still carries 17 cards and 9 display_only ones. Bumping these
# to 18/10 to "match run.py" is wrong twice over: it would red on a fixture that cannot contain the card,
# and it would hide the fact that the assertion's subject is the snapshot. The new card's display_only-ness
# is asserted where it can actually be measured — against the FRESH replay emit, in
# tests/test_tphp_tumor_presence_arm.py (DATA_PRODUCT.md:16: "the FRESH replay emit is the conformance
# target; the static golden is a secondary check"). These numbers move only when the golden is re-derived
# from a live run, never by hand.


# ── Phase 0 registry sanity ──────────────────────────────────────────────────────────────────────
def test_questions_registry_loads_seven(eg_questions):
    ids = [q["id"] for q in eg_questions]
    assert ids == [
        "expressed_at_all",
        "vs_other_cancers",
        "elevated_vs_normal",
        "subtypes_differ",
        "absolute_abundance",
        "rna_protein_agree",
        "malignant_intrinsic",
    ]
    # unified axis vocabulary present incl. the missing presence axis B (tumor-vs-normal)
    axes = {q["axis_id"] for q in eg_questions if q.get("axis_id")}
    assert axes == {"A", "B", "C", "D"}


# ── §7.4 role partition ──────────────────────────────────────────────────────────────────────────
def test_role_partition_8_verdict_bearing_9_display_only(eg_graph):
    vb = {c["id"] for c in eg_graph["cards"] if c["role"] == "verdict_bearing"}
    do = {c["id"] for c in eg_graph["cards"] if c["role"] == "display_only"}
    assert vb == VERDICT_BEARING
    assert do == DISPLAY_ONLY
    assert len(vb) == 8 and len(do) == 9 and len(eg_graph["cards"]) == 17
    # a fired-but-display_only card (concordance) still declares NO rule contribution to the verdict
    conc = next(c for c in eg_graph["cards"] if c["id"] == "cellline-rna-protein-concordance")
    assert conc["role"] == "display_only"
    assert conc["chain"]["contributes_to_verdict"] is False
    assert conc["chain"]["is_driving"] is False


# ── §7.1 reconstruction: 7 questions with signal+confidence, each question's cards ──────────────────
def test_reconstruct_questions_signal_confidence_and_cards(eg_graph):
    qs = {q["id"]: q for q in eg_graph["questions"]}
    assert len(qs) == 7
    # signal + confidence readable off the graph (no prose parsing)
    assert qs["expressed_at_all"]["signal"]["tier"] == "strong"
    assert qs["expressed_at_all"]["confidence"]["level"] == "moderate"
    assert qs["elevated_vs_normal"]["signal"]["polarity"] == "opposing"  # canonical (was legacy "opposes")
    assert qs["subtypes_differ"]["signal"]["tier"] == "uniform"
    assert qs["malignant_intrinsic"]["confidence"]["level"] == "high"
    # each question's card list (the many-to-many join) matches the curated dashboard exactly
    assert set(qs["expressed_at_all"]["card_ids"]) == {
        "tumor-rna-distribution",
        "hpa-pathology-cancer-ihc",
        "cellline-rna-distribution",
        "cellline-protein-abundance",
        "cellline-protein-abundance-procan",
        "tumor-protein-abundance-cptac",
    }
    assert set(qs["elevated_vs_normal"]["card_ids"]) == {
        "tumor-rna-vs-adjacent",
        "tumor-protein-abundance-cptac",
        "normal-tissue-liability",
        "sc-normal-celltype-expression",
    }
    assert set(qs["subtypes_differ"]["card_ids"]) == {
        "tumor-rna-distribution-by-subtype",
        "cellline-rna-distribution-by-subtype",
        "tumor-protein-distribution-by-subtype",
        "expression-purity-confound",
    }
    # a card appearing in TWO questions (many-to-many) is materialized both directions
    assert set(qs["absolute_abundance"]["card_ids"]) >= {"tumor-rna-distribution"}
    trd = next(c for c in eg_graph["cards"] if c["id"] == "tumor-rna-distribution")
    assert set(trd["question_ids"]) == {"expressed_at_all", "absolute_abundance"}


# ── §7.1/§7.5 each question's literature, incl. axis B → elevated_vs_normal ──────────────────────────
def test_literature_axis_crosswalk_including_axis_B(eg_graph):
    axes = {ax["axis_id"]: ax for ax in eg_graph["literature"]["axes"]}
    assert set(axes) == {"A", "B", "C", "D"}
    assert axes["A"]["question_ids"] == ["expressed_at_all", "absolute_abundance"]
    assert axes["B"]["question_ids"] == ["elevated_vs_normal"]  # the missing link
    assert axes["C"]["question_ids"] == ["malignant_intrinsic"]
    assert axes["D"]["question_ids"] == ["vs_other_cancers"]
    assert axes["B"]["read"] == "mixed" and axes["B"]["agreement_vs_omics"] == "agree"
    assert eg_graph["literature"]["overall_consistency"] == "concordant"
    # the crosswalk is materialized on the question node too
    q3 = next(q for q in eg_graph["questions"] if q["id"] == "elevated_vs_normal")
    assert q3["literature_axis_ids"] == ["B"]
    # corroboration question (rna_protein_agree, axis A) is NOT a literature target
    q6 = next(q for q in eg_graph["questions"] if q["id"] == "rna_protein_agree")
    assert q6["literature_axis_ids"] == []


# ── §7.1 each card's dataset→data→rule→verdict chain (no .card.yaml, no prose) ──────────────────────
def test_driving_card_chain(eg_graph):
    trd = next(c for c in eg_graph["cards"] if c["id"] == "tumor-rna-distribution")
    assert trd["class"] == {"field": "tumor_expression_class", "value": "broadly_high"}
    assert "tcga-tumor-tpm-recount3-long-v1" in trd["chain"]["dataset_ids"]
    assert trd["chain"]["rule_id"] == "tumor-expression-broadly-high-supportive"
    assert trd["chain"]["contributes_to_verdict"] is True
    assert trd["chain"]["is_driving"] is True
    assert trd["key_fields"].get("allgene_percentile") == pytest.approx(99.74, abs=0.1)
    # a display-only card never invents a rule (spec §6)
    do = next(c for c in eg_graph["cards"] if c["id"] == "hpa-pathology-cancer-ihc")
    assert do["role"] == "display_only"
    assert do["rule_ids"] == []
    assert do["chain"]["rule_id"] is None
    assert do["chain"]["is_driving"] is False


def test_verdict_node_matches_spine(eg_graph, eg_decision):
    assert eg_graph["verdict"]["id"] == eg_decision["headline"]["presence_verdict"] == "tumor_broadly_expressed"
    assert eg_graph["verdict"]["driving_rule_id"] == "tumor-expression-broadly-high-supportive"
    assert eg_graph["verdict"]["polarity"] == "supportive"  # canonical (was legacy "positive")


# ── P1: one canonical polarity vocabulary + orthogonal liability flag (docs/COMPOSED_EVIDENCE_GRAPH_ROLLUP.md §6)
_CANONICAL_POLARITIES = {"supportive", "neutral", "opposing", "killer", "not_applicable", None}


def test_card_polarity_is_canonical_and_liability_flagged(eg_graph):
    cards = {c["id"]: c for c in eg_graph["cards"]}
    # a fired/verdict-bearing card → supportive; the driving card is fired
    assert cards["tumor-rna-distribution"]["signal"]["polarity"] == "supportive"
    assert cards["tumor-rna-distribution"]["signal"]["liability"] is False
    # the normal single-cell liability card → killer polarity + the orthogonal flag set
    sc = cards["sc-normal-celltype-expression"]
    assert sc["signal"]["polarity"] == "killer"
    assert sc["signal"]["liability"] is True
    # a display-only, non-liability card → neutral
    assert cards["hpa-pathology-cancer-ihc"]["signal"]["polarity"] == "neutral"
    # NO card carries a legacy token — the whole graph speaks one vocabulary
    for c in eg_graph["cards"]:
        assert c["signal"]["polarity"] in _CANONICAL_POLARITIES
        assert c["signal"]["polarity"] not in {"supports", "opposes", "positive", "negative"}
    for q in eg_graph["questions"]:
        assert q["signal"]["polarity"] in _CANONICAL_POLARITIES


# ── §7.5 schema validation ─────────────────────────────────────────────────────────────────────────
def _contracts_schema_path() -> Path | None:
    root = os.environ.get("TARGET_CONTRACTS_ROOT")
    candidates = []
    if root:
        candidates.append(Path(root) / "schemas" / "evidence_graph.schema.json")
    candidates.append(Path(TARGET_CONTRACTS_ROOT_DEFAULT) / "schemas" / "evidence_graph.schema.json")
    for c in candidates:
        if c.exists():
            return c
    return None


def test_graph_validates_against_schema(eg_graph):
    schema_path = _contracts_schema_path()
    if schema_path is None:
        pytest.skip("evidence_graph.schema.json not found (set TARGET_CONTRACTS_ROOT)")
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(eg_graph, json.loads(schema_path.read_text()))


def test_narrative_fail_soft_on_error_stub(eg_graph):
    # the committed fixture carries an llm_synthesis error stub → narrative must be empty, not error
    assert eg_graph["narrative"] == {}
