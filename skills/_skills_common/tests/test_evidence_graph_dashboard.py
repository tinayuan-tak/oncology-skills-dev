"""Tests for evidence_graph_dashboard.render_dashboard — proves the renderer draws the whole
dashboard from the evidence_graph ALONE (no .card.yaml reads, no prose parsing, no positional
guessing), and is robust to graphs it did not expect.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SKILLS_ROOT = Path(__file__).resolve().parents[2]  # .../skills
if str(SKILLS_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILLS_ROOT))

from _skills_common.evidence_graph import build_evidence_graph, load_questions  # noqa: E402
from _skills_common.evidence_graph_dashboard import render_dashboard  # noqa: E402

FIXTURE = SKILLS_ROOT / "tumor-presence" / "tests" / "fixtures" / "epcam_coadread_decision.json"
TP_DIR = SKILLS_ROOT / "tumor-presence"

# the 9 verdict-bearing cards → their fired rule_ids (EPCAM·COADREAD real package)
EXPECTED_RULES = [
    "tumor-expression-broadly-high-supportive",          # driving (tumor-rna-distribution)
    "expression-broadly-moderate-neutral",               # cellline-rna-distribution
    "expression-call-not-informative-degrader-killer",   # tumor-rna-vs-adjacent
    "tumor-breadth-multi-supportive",                    # tumor-elevation-breadth
    "protein-abundance-broadly-moderate-neutral",        # cellline-protein-abundance
    "sc-expression-malignant-broadly-detected-supportive",  # tumor-scrna-celltype-expression
    "tvn-sc-normal-critical-organ-veto",                 # sc-normal-celltype-expression
    "rna-protein-adequate-proxy-supportive",             # cellline-rna-protein-concordance
    "purity-independent-neutral",                        # expression-purity-confound
]
QUESTION_SLUGS = ["expressed_at_all", "vs_other_cancers", "elevated_vs_normal", "subtypes_differ",
                  "absolute_abundance", "rna_protein_agree", "malignant_intrinsic"]


@pytest.fixture(scope="module")
def graph() -> dict:
    decision = json.loads(FIXTURE.read_text())
    g = (decision.get("headline") or {}).get("evidence_graph")
    return g or build_evidence_graph(decision, questions=load_questions(TP_DIR))


@pytest.fixture(scope="module")
def html(graph) -> str:
    return render_dashboard(graph)


def test_renders_self_contained_html(html):
    assert html.startswith("<!doctype html>")
    assert "<style>" in html and "</style>" in html
    assert html.rstrip().endswith("</html>")


def test_all_seven_question_slugs_present(html):
    for slug in QUESTION_SLUGS:
        assert slug in html, f"missing question slug {slug}"


def test_nine_verdict_bearing_chains_with_rule_ids(graph, html):
    vb = [c for c in graph["cards"] if c.get("role") == "verdict_bearing"]
    assert len(vb) == 9, f"expected 9 verdict-bearing cards, got {len(vb)}"
    for rid in EXPECTED_RULES:
        assert rid in html, f"missing fired rule_id in render: {rid}"


def test_driving_pill_on_tumor_rna_distribution(graph, html):
    drv = [c for c in graph["cards"] if (c.get("chain") or {}).get("is_driving")]
    assert [c["id"] for c in drv] == ["tumor-rna-distribution"]
    assert "tumor-rna-distribution" in html
    assert "DRIVING" in html


def test_axis_b_literature_inline_under_elevated_vs_normal(graph, html):
    import html as _h
    q = next(q for q in graph["questions"] if q["id"] == "elevated_vs_normal")
    assert "B" in (q.get("literature_axis_ids") or []), "axis B not crosswalked to elevated_vs_normal"
    ax = next(a for a in graph["literature"]["axes"] if a["axis_id"] == "B")
    # literature is labelled by the question it addresses (NOT a bare letter) and woven into the
    # elevated_vs_normal row. Scope to the question-table region (the slug also appears earlier in
    # the fingerprint label), between this question's summary and the next question's summary.
    qtab = html.index('class="qtab"')
    start = html.index("elevated_vs_normal", qtab)
    nxt = html.index("subtypes_differ", start)
    sl = html[start:nxt]
    assert "Literature" in sl, "no literature block under elevated_vs_normal"
    snippet = _h.escape((ax.get("assertion") or "")[:24])
    assert snippet and snippet in sl, "axis-B assertion not inline under elevated_vs_normal"
    assert "axis B" not in sl and "axis {}" not in sl, "bare axis letter should not be shown"


def test_display_only_cards_show_no_rule(graph, html):
    do = [c for c in graph["cards"] if c.get("role") == "display_only"]
    assert len(do) == 8
    assert "display-only · no rule fired" in html


def test_reads_nothing_but_the_graph_bogus_card(graph):
    # a card the renderer has never seen, referenced by no question, must not crash it and must not
    # trigger any .card.yaml read (there is no such path in the module).
    import copy
    g2 = copy.deepcopy(graph)
    g2["cards"].append({
        "id": "totally-made-up-card", "measurement_type": "made_up_mt", "tier": "target",
        "role": "display_only", "question_ids": [], "axis_id": None,
        "signal": {"tier": None, "polarity": "neutral", "label": "x"},
        "confidence": {"level": "moderate", "dots": 2}, "class": {"field": "f", "value": "made_up_class"},
        "dataset_ids": ["made-up-ds"], "rule_ids": [],
        "chain": {"dataset_ids": ["made-up-ds"], "data": [], "rule_id": None,
                  "contributes_to_verdict": False, "is_driving": False},
        "key_fields": {},
    })
    html2 = render_dashboard(g2)
    assert "totally-made-up-card" in html2  # rendered from the graph node, nothing external


def test_deterministic_summary_always_present(graph, html):
    # a deterministic Summary is composed from verdict + question signals even with no LLM lane
    assert not graph["narrative"], "fixture unexpectedly has an AI narrative"
    assert 'class="card summ"' in html and ">Summary<" in html
    assert "Abundantly present" in html                       # the verdict call, in prose
    assert "Supported by:" in html and "Opposing:" in html    # question-signal breakdown


def test_builder_unwraps_provenance_wrapped_narrative():
    # a real focused --synthesize stamps each field as {value,_source:"llm_synthesized",...};
    # the builder must unwrap so the graph carries plain prose (not wrapper dicts) and the renderer
    # shows clean text under 'Narrative (AI gen)'.
    def wrap(v):
        return {"value": v, "_source": "llm_synthesized", "_model_id": "m", "_prompt_hash": "h"}
    decision = json.loads(FIXTURE.read_text())
    decision["llm_synthesis"] = {
        "relevance": wrap("supports_with_caveats"),
        "rationale": wrap("EPCAM broadly-high via tumor-rna-distribution; field-effect risk."),
        "confidence_qualifier": wrap("supported_with_caveats"),
        "key_caveat": wrap("bulk protein not significant"),
    }
    g = build_evidence_graph(decision, questions=load_questions(TP_DIR))
    n = g["narrative"]
    assert isinstance(n["rationale"], str) and n["rationale"].startswith("EPCAM broadly-high")
    assert n["relevance"] == "supports_with_caveats"
    assert "tumor-rna-distribution" in n["cites"]["card_ids"]
    out = render_dashboard(g)
    assert "_source" not in out and "'value'" not in out  # no provenance-wrapper dicts leaked
    assert "EPCAM broadly-high" in out and "Narrative (AI gen)" in out


def test_fail_soft_empty_lanes():
    # minimal graph with empty literature/narrative + a question referencing a missing card id →
    # renders without error, skipping the dangling reference.
    g = {
        "schema_version": "1.0", "skill": "demo", "target": "T", "indication": "I",
        "verdict": {"id": "v", "call": "call", "polarity": "neutral", "driving_rule_id": None,
                    "confidence": {"level": "low", "coverage": {}}, "top_tension": None},
        "questions": [{"id": "q1", "seq": 1, "text": "?", "axis_id": None, "role": "display_only",
                       "signal": {"tier": None, "polarity": "none", "label": None},
                       "confidence": {"level": "low", "dots": 0, "label": None},
                       "card_ids": ["does-not-exist"], "rule_ids": [], "literature_axis_ids": [],
                       "evidence_refs": [], "prose": {"primary": None, "support": None}}],
        "cards": [], "rules": [], "datasets": [], "literature": {}, "citations": [], "narrative": {},
    }
    out = render_dashboard(g)
    assert out.startswith("<!doctype html>") and "q1" in out
