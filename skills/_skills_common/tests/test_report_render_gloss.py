"""report_render card-chain plain-language layer (interpretation-encoding Stage 1).

The RICH embedded card view now leads class-first: a plain card DESCRIPTION (from the contract `question:`,
{target.symbol}/{indication.label} filled), a class-led 'Reads: <class>' line, and a GLOSSED key-evidence
reading ('median CRISPR gene-effect (CHRONOS) = -1.18 (CHRONOS; lower = stronger)') instead of a bare
`median_chronos=-1.18`. Graph builder + graph goldens are UNCHANGED (this is a render-side join).
"""

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render import build_ir_for_skill, resolve_spec
from _skills_common.report_render import backends as be


def _graph_with_gauged_card() -> dict:
    # a real card_id (so the description join can resolve) carrying the FR key_evidence shape
    return {
        "schema_version": "1.0",
        "skill": "functional-requirement",
        "target": "KRAS",
        "indication": "COADREAD",
        "verdict": {"id": "dependency", "call": "Selective dependency", "polarity": "supportive"},
        "questions": [
            {
                "id": "is_dependency",
                "seq": 1,
                "text": "Genetic dependency?",
                "axis_id": "DEP",
                "role": "verdict_bearing",
                "signal": {"tier": "strong", "polarity": "supportive", "label": "strong"},
                "confidence": {"level": "high", "dots": 3},
                "card_ids": ["dependency-lineage-selectivity"],
                "rule_ids": ["lineage-selective-supportive"],
                "literature_axis_ids": [],
            },
        ],
        "cards": [
            {
                "id": "dependency-lineage-selectivity",
                "measurement_type": "crispr_lof_dependency",
                "role": "verdict_bearing",
                "question_ids": ["is_dependency"],
                "signal": {
                    "tier": "strong",
                    "polarity": "supportive",
                    "label": "lineage_selective",
                    "liability": False,
                },
                "confidence": {"level": "high", "dots": 3, "n": 1538},
                "class": {"field": "dependency_lineage_selectivity_class", "value": "lineage_selective"},
                "dataset_ids": ["depmap-crispr-v1"],
                "rule_ids": ["lineage-selective-supportive"],
                "chain": {
                    "dataset_ids": ["depmap-crispr-v1"],
                    "data": [{"field": "median_chronos", "value": -1.1771}],
                    "rule_id": "lineage-selective-supportive",
                    "contributes_to_verdict": True,
                    "is_driving": True,
                },
                "key_evidence": {
                    "effect": {"metric": "median_chronos", "value": -1.1771, "direction": "lower_is_stronger"},
                    "n": 1538,
                    "significance": {"stat": "q_value", "value": 3.8079e-16},
                    "omnibus": {"stat": "lineage_omnibus_p", "value": 7.1383e-50},
                    "top_strata": [
                        {"label": "Bowel", "role": "indication", "value": -1.1771, "n": 88, "q": 3.8079e-16}
                    ],
                    "categorical": [{"field": "dep_control_position_class", "value": "between_controls"}],
                },
            },
        ],
        "rules": [{"id": "lineage-selective-supportive", "card_id": "dependency-lineage-selectivity"}],
        "datasets": [{"id": "depmap-crispr-v1"}],
        "literature": {},
        "citations": [],
        "narrative": {},
    }


def _skill_report(graph) -> dict:
    return {
        "role": "gating",
        "call": "dependency",
        "polarity": "supportive",
        "honest_phrase": "dep",
        "confidence": {"level": "high"},
        "question_table": [{"id": "Q1", "question": "x", "signal": {}, "confidence": {}}],
        "provenance": {
            "driving_rule_id": "lineage-selective-supportive",
            "fired_rule_ids": ["lineage-selective-supportive"],
            "cards_used": ["dependency-lineage-selectivity"],
        },
        "evidence_graph": graph,
    }


def _ir(graph):
    return build_ir_for_skill(
        _skill_report(graph), resolve_spec("full"), short="dependency", target="KRAS", indication="COADREAD"
    )


def test_html_card_view_leads_with_reads_and_glossed_metric():
    h = be.render(_ir(_graph_with_gauged_card()), "html")
    assert "class='cread'>Reads:" in h  # class-led plain reading
    assert "Lineage selective" in h  # humanized class value
    # the KEY line reads the metric as gauged plain language (the raw field survives only in the
    # low-level dataset→data drill, which is intended provenance, not the headline reading)
    assert "median CRISPR gene-effect (CHRONOS)" in h  # glossed metric label (not bare median_chronos)
    assert "lower = stronger" in h  # direction phrase consumed
    assert "cross-lineage omnibus p-value" in h  # omnibus stat glossed
    assert "Between controls" in h  # categorical humanized


def test_text_card_view_glosses_the_metric_and_humanizes_class():
    t = be.render(_ir(_graph_with_gauged_card()), "text")
    assert "median CRISPR gene-effect (CHRONOS)" in t
    assert "lower = stronger" in t
    assert "Lineage selective" in t  # humanized class in the class column


def test_json_backend_carries_reads_and_glossed_key():
    import json

    obj = json.loads(be.render(_ir(_graph_with_gauged_card()), "json"))
    cc = [b for s in obj["sections"] for b in s["blocks"] if b["kind"] == "card_chain"]
    assert cc, "card_chain block present"
    card = cc[0]["layers"][0]["cards"][0]
    assert card["reads"] == "Lineage selective"
    assert "key_evidence_summary" in card and "CHRONOS" in card["key_evidence_summary"]


def _graph_with_ruler() -> dict:
    g = _graph_with_gauged_card()
    g["cards"][0]["key_evidence"]["interpretation"] = [
        {
            "metric": "median_chronos_panel",
            "value": -0.4574,
            "scale": "chronos",
            "direction": "lower_is_stronger",
            "position": "between_controls",
            "position_source": "dep_control_position_class",
            "frame": {
                "kind": "floor_cut_ceiling",
                "anchors": [
                    {"role": "floor", "label": "non_essential_floor", "value": -0.038},
                    {"role": "ceiling", "label": "pan_essential_ceiling", "value": -1.499},
                    {"role": "cut", "label": "dependency_cut", "value": -0.5},
                ],
            },
        }
    ]
    return g


def test_html_draws_the_gauge_ruler():
    h = be.render(_ir(_graph_with_ruler()), "html")
    assert "class='gtrack'" in h and "gmark" in h  # visual ruler track + value marker
    assert "gtick gcut" in h  # the cut tick
    assert "between controls —" in h  # gauge words caption
    assert "short of the -0.5 cut" in h


def test_text_surfaces_the_gauge_words():
    t = be.render(_ir(_graph_with_ruler()), "text")
    assert "between non essential floor -0.038 and pan essential ceiling -1.499" in t
    assert "short of the -0.5 cut" in t


def test_json_carries_interpretation_and_gauge():
    import json

    obj = json.loads(be.render(_ir(_graph_with_ruler()), "json"))
    card = [b for s in obj["sections"] for b in s["blocks"] if b["kind"] == "card_chain"][0]["layers"][0]["cards"][0]
    assert card["interpretation"] and card["interpretation"][0]["frame"]["kind"] == "floor_cut_ceiling"
    assert "between controls —" in (card.get("gauge") or "")


def test_description_interpolates_target_when_contracts_available():
    # fail-soft: only assert when the real card contract resolves (isolated CI may lack it)
    h = be.render(_ir(_graph_with_gauged_card()), "html")
    if "class='cdesc'>" in h:
        # the card's question: carries {target.symbol} -> must be KRAS, never a raw placeholder
        import re

        seg = re.search(r"class='cdesc'>(.*?)</div>", h)
        assert seg and "{target" not in seg.group(1)
        assert "KRAS" in seg.group(1)
