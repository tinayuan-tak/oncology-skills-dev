"""report_render P3 — the RICH embedded sub-skill view rendered from a carried skill_report.evidence_graph
(docs/COMPOSED_EVIDENCE_GRAPH_ROLLUP.md §4): EVIDENCE_FINGERPRINT + CARD_CHAIN + LITERATURE_AXES.

Asserts the three new blocks emit + render (html/text/json) when the skill_report carries an
evidence_graph, that they SUPERSEDE the lean sub-group bands/scatter, and that a skill_report WITHOUT a
graph still falls back to the bands/scatter path (byte-stable for the existing composed report).
"""

import json
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render import backends as be
from _skills_common.report_render import build_ir_for_skill, resolve_spec, vocab


def _graph() -> dict:
    return {
        "schema_version": "1.0",
        "skill": "tumor-presence",
        "target": "EPCAM",
        "indication": "COADREAD",
        "verdict": {"id": "tumor_broadly_expressed", "call": "Abundantly present", "polarity": "supportive"},
        "questions": [
            {
                "id": "expressed_at_all",
                "seq": 1,
                "text": "Expressed at all?",
                "axis_id": "A",
                "role": "verdict_bearing",
                "signal": {"tier": "strong", "polarity": "supportive", "label": "strong"},
                "confidence": {"level": "moderate", "dots": 2},
                "card_ids": ["tumor-rna", "hpa-ihc"],
                "rule_ids": ["r1"],
                "literature_axis_ids": ["A"],
            },
            {
                "id": "elevated_vs_normal",
                "seq": 3,
                "text": "Elevated vs normal?",
                "axis_id": "B",
                "role": "verdict_bearing",
                "signal": {"tier": "weak", "polarity": "opposing", "label": "flat"},
                "confidence": {"level": "moderate", "dots": 2},
                "card_ids": ["sc-normal"],
                "rule_ids": [],
                "literature_axis_ids": ["B"],
            },
        ],
        "cards": [
            {
                "id": "tumor-rna",
                "measurement_type": "tumor_expression_distribution",
                "role": "verdict_bearing",
                "question_ids": ["expressed_at_all"],
                "signal": {"tier": "strong", "polarity": "supportive", "label": "broadly_high", "liability": False},
                "confidence": {"level": "high", "dots": 3, "n": 669},
                "class": {"field": "c", "value": "broadly_high"},
                "dataset_ids": ["tcga-v1"],
                "rule_ids": ["r1"],
                "chain": {
                    "dataset_ids": ["tcga-v1"],
                    "data": [{"field": "pctile", "value": 99.7}],
                    "rule_id": "r1",
                    "contributes_to_verdict": True,
                    "is_driving": True,
                },
            },
            {
                "id": "hpa-ihc",
                "measurement_type": "tumor_protein_ihc_presence",
                "role": "display_only",
                "question_ids": ["expressed_at_all"],
                "signal": {"tier": None, "polarity": "neutral", "label": "ihc_detected", "liability": False},
                "confidence": {"level": "moderate", "dots": 2, "n": None},
                "class": {"field": "c", "value": "ihc_detected"},
                "dataset_ids": ["hpa-v1"],
                "rule_ids": [],
                "chain": {
                    "dataset_ids": ["hpa-v1"],
                    "data": [],
                    "rule_id": None,
                    "contributes_to_verdict": False,
                    "is_driving": False,
                },
            },
            {
                "id": "sc-normal",
                "measurement_type": "sc_normal_celltype_expression",
                "role": "verdict_bearing",
                "question_ids": ["elevated_vs_normal"],
                "signal": {"tier": "strong", "polarity": "killer", "label": "HIGH_LIABILITY", "liability": True},
                "confidence": {"level": "high", "dots": 3, "n": 361},
                "class": {"field": "c", "value": "HIGH_LIABILITY"},
                "dataset_ids": ["scn-v1"],
                "rule_ids": ["veto"],
                "chain": {
                    "dataset_ids": ["scn-v1"],
                    "data": [],
                    "rule_id": "veto",
                    "contributes_to_verdict": True,
                    "is_driving": False,
                },
            },
        ],
        "rules": [{"id": "r1", "card_id": "tumor-rna"}],
        "datasets": [{"id": "tcga-v1"}],
        "literature": {
            "axes": [
                {
                    "axis_id": "A",
                    "question_ids": ["expressed_at_all"],
                    "read": "strongly_supports",
                    "agreement_vs_omics": "agree",
                    "confidence": "high",
                    "assertion": "Abundant antigen.",
                    "citation_ids": ["went2006"],
                },
                {
                    "axis_id": "B",
                    "question_ids": ["elevated_vs_normal"],
                    "read": "mixed",
                    "agreement_vs_omics": "mixed",
                    "confidence": "moderate",
                    "assertion": "High in normal epithelium.",
                    "citation_ids": ["went2006"],
                },
            ],
            "blind_spots": [{"text": "localization", "why_omics_blind": "MS/RNA cannot resolve", "citation_ids": []}],
            "overall_consistency": "concordant",
            "key_divergence": None,
        },
        "citations": [{"id": "went2006", "label": "Went 2006", "pmid": "16404434", "doi": None, "verified": True}],
        "narrative": {},
    }


def _skill_report(**extra) -> dict:
    sr = {
        "role": "gating",
        "call": "tumor_broadly_expressed",
        "polarity": "supportive",
        "honest_phrase": "Abundantly present",
        "confidence": {"level": "moderate"},
        "question_table": [{"id": "Q1", "question": "x", "signal": {}, "confidence": {}}],
        "provenance": {"driving_rule_id": "r1", "fired_rule_ids": ["r1"], "cards_used": ["tumor-rna"]},
    }
    sr.update(extra)
    return sr


def _ir(sr):
    return build_ir_for_skill(sr, resolve_spec("full"), short="expression", target="EPCAM", indication="COADREAD")


def test_graph_emits_the_three_rich_blocks():
    present = _ir(_skill_report(evidence_graph=_graph())).present_kinds()
    assert vocab.EVIDENCE_FINGERPRINT in present
    assert vocab.CARD_CHAIN in present
    assert vocab.LITERATURE_AXES in present


def test_html_renders_fingerprint_chain_and_literature():
    h = be.render(_ir(_skill_report(evidence_graph=_graph())), "html")
    assert "hmcell" in h and "Evidence fingerprint" in h  # per-question heatmap
    assert "DRIVING" in h and "chainline" in h  # dataset→data→rule→verdict chain
    assert "cite-pill" in h and "16404434" in h  # literature axis + verified PMID
    assert "var(--killer)" in h  # liability card rendered as killer


def test_fingerprint_cell_carries_glyph_ring_and_table_twin():
    """Tier-2 hmcell rebuild: each heatmap cell is neither colour-only nor hover-only — it stamps a
    filled signal mark inside (secondary encoding), encodes confidence as a RING-weight class (not
    opacity, which desaturated a status hue toward neutral so a low-confidence supportive cell read
    neutral), and the strip ships an accessible <table> twin (keyboard / print / screen-reader path)."""
    h = be.render(_ir(_skill_report(evidence_graph=_graph())), "html")
    assert "hmcell hm-c" in h  # confidence is a ring-weight class ON the cell, not opacity
    assert any(g in h for g in ("▲", "▼", "•", "✕"))  # filled signal mark stamped in-cell
    assert "Table view" in h and "<th>Confidence</th>" in h  # accessible table twin


def test_card_chain_regroups_by_question_with_badges_and_lit_treatment():
    """Tier-4 subskill regroup: the card drill groups by the QUESTION each card answers (aligned with
    the question-anchored fingerprint) rather than one-card measurement-type accordions; each card
    carries a role badge (drives-verdict / contributes / context); the litdot shows an agreement glyph
    (✓/✗/≈); and literature axis cards read as literature via a --lit left border (litaxis)."""
    ir = _ir(_skill_report(evidence_graph=_graph()))
    obj = json.loads(be.render(ir, "json"))
    ccb = [b for s in obj["sections"] for b in s["blocks"] if b["kind"] == "card_chain"][0]
    assert ccb["grouped_by"] == "question"  # question-grouped, not measurement_type
    assert len(ccb["layers"]) == 2  # fixture: expressed_at_all + elevated_vs_normal
    h = be.render(ir, "html")
    assert "rbadge" in h and ("drives verdict" in h or "context" in h)  # role badges
    assert "litaxis" in h and "border-left:3px solid var(--lit)" in h  # literature two-tone
    assert "✓" in h or "≈" in h  # litdot agreement glyph (fixture has agree + mixed)


def test_text_and_json_backends_cover_the_blocks():
    ir = _ir(_skill_report(evidence_graph=_graph()))
    t = be.render(ir, "text")
    assert "Evidence fingerprint" in t and "dataset → data → rule" in t and "per-axis agreement" in t
    obj = json.loads(be.render(ir, "json"))
    kinds = {b["kind"] for s in obj["sections"] for b in s["blocks"]}
    assert {vocab.EVIDENCE_FINGERPRINT, vocab.CARD_CHAIN, vocab.LITERATURE_AXES} <= kinds


def test_fingerprint_supersedes_bands_when_graph_present():
    # a graph-bearing skill_report shows the fingerprint, NOT the lean sub-group bands/scatter
    h = be.render(
        _ir(
            _skill_report(
                evidence_graph=_graph(), subgroup_signals={"primary": {"signal": "strong", "confidence": "high"}}
            )
        ),
        "html",
    )
    assert "Evidence fingerprint" in h
    assert "Sub-group bands" not in h


def test_falls_back_to_bands_without_a_graph():
    # no evidence_graph → the existing lean bands/scatter path (byte-stable for legacy composed reports)
    h = be.render(_ir(_skill_report(subgroup_signals={"primary": {"signal": "strong", "confidence": "high"}})), "html")
    assert "Sub-group bands" in h
    assert "Evidence fingerprint" not in h


def test_no_payload_shadows_kind_for_new_blocks():
    ir = _ir(_skill_report(evidence_graph=_graph()))
    for sec in ir.sections:
        for b in sec.blocks:
            assert "kind" not in b.payload, f"{b.kind} payload shadows 'kind'"
