"""P5 — the standalone sub-skill dashboard is produced by report_render (one renderer), retiring the
bespoke evidence_graph_dashboard.py (docs/COMPOSED_EVIDENCE_GRAPH_ROLLUP.md §4, decision R1).

A standalone decision.json carries the claim graph at headline.evidence_graph, a SIBLING of
headline.skill_report. `_extract_skill` merges it onto the skill_report so render_skill_report /
build_ir_auto / the `python -m _skills_common.report_render <decision.json>` CLI draw the RICH view
(fingerprint + chains + literature) — the same P3 blocks the composed embedded view renders, from the
same graph. These tests replace the retired test_evidence_graph_dashboard.py.
"""

from _skills_common.report_render import backends as be
from _skills_common.report_render import build_ir_auto, render_skill_report, resolve_spec, vocab

# reuse the P3 sample graph builder
from _skills_common.tests.test_report_render_evidence_graph_blocks import _graph


def _skill_report_lean() -> dict:
    return {
        "role": "gating",
        "call": "tumor_broadly_expressed",
        "polarity": "supportive",
        "honest_phrase": "Abundantly present",
        "confidence": {"level": "moderate"},
        "question_table": [{"id": "Q1", "question": "x", "signal": {}, "confidence": {}}],
        "provenance": {"driving_rule_id": "r1", "fired_rule_ids": ["r1"], "cards_used": ["tumor-rna"]},
    }


def _decision(with_graph: bool) -> dict:
    """A standalone sub-skill decision.json: the graph is a SIBLING of skill_report under headline."""
    hl = {"skill_report": _skill_report_lean()}
    if with_graph:
        hl["evidence_graph"] = _graph()
    return {"skill": "tumor-presence", "target": "EPCAM", "indication": "COADREAD", "headline": hl}


def test_standalone_decision_renders_rich_view_via_report_render():
    html = render_skill_report(_decision(with_graph=True), backend="html", preset="full")
    assert "<!doctype html>" in html
    assert "Evidence fingerprint" in html and "hmcell" in html  # per-question heatmap
    assert "DRIVING" in html and "chainline" in html  # dataset→data→rule→verdict chain
    assert "cite-pill" in html and "16404434" in html  # literature axis + verified PMID
    assert "var(--killer)" in html  # liability card as killer


def test_extract_skill_merges_sibling_graph_onto_skill_report():
    ir = build_ir_auto(_decision(with_graph=True), resolve_spec("full"))
    present = ir.present_kinds()
    assert vocab.EVIDENCE_FINGERPRINT in present
    assert vocab.CARD_CHAIN in present
    assert vocab.LITERATURE_AXES in present


def test_decision_without_graph_is_lean_not_broken():
    # no headline.evidence_graph → the lean single-skill view (no fingerprint), never an error
    html = render_skill_report(_decision(with_graph=False), backend="html", preset="full")
    assert "<!doctype html>" in html
    assert "Evidence fingerprint" not in html


def test_text_and_json_standalone_paths_cover_the_blocks():
    ir = build_ir_auto(_decision(with_graph=True), resolve_spec("full"))
    t = be.render(ir, "text")
    assert "Evidence fingerprint" in t and "dataset → data → rule" in t
    j = be.render(ir, "json")
    assert "evidence_fingerprint" in j and "card_chain" in j and "literature_axes" in j


def test_bespoke_dashboard_module_is_retired():
    import importlib

    try:
        importlib.import_module("_skills_common.evidence_graph_dashboard")
    except ImportError:
        return
    raise AssertionError("evidence_graph_dashboard was retired in P5; import should fail")
