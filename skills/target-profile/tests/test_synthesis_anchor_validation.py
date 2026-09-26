"""Tier-3 synthesis — post-hoc anchor validation (verdict-INERT audit).

The prompt tells the model to cite ONLY [rule_id]/[card_id] anchors present in the narrative block;
validate_synthesis_anchors flags any bracketed kebab-case anchor absent from the deterministic set
(narrative_by_axis + fired rules + card_ids). Fail-visible; never edits prose or the verdict.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SKILLS = Path(__file__).resolve().parents[2]
for _p in (str(SKILLS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import tp_synthesis_prompt as tp  # noqa: E402

_NBA = {
    "dependency": {
        "verdict": "lineage_selective",
        "driving_rule_id": "lineage-selective-supportive",
        "movers": [{"rule_id": "lineage-selective-supportive", "card_id": "dependency-lineage-selectivity"}],
        "dissenters": [{"rule_id": "rnai-discordant-neutral", "card_id": "crispr-rnai-dependency-concordance"}],
        "flip_conditions": [{"rule_id": "pan-essential-killer"}],
        "rule_sentences": {"lineage-selective-supportive": {"card_id": "dependency-lineage-selectivity"}},
    },
}
_SUB = {
    "dependency": {
        "fired": [{"rule_id": "lineage-selective-supportive", "card_id": "dependency-lineage-selectivity"}],
        "cards": [{"card_id": "pan-cancer-crispr-dependency-distribution"}],
    }
}


def _wrap(v):
    return {"value": v, "_source": "llm_synthesized"}


def test_flags_invented_anchor_and_passes_legal_one():
    out = {
        # legal (in narrative) + invented (hallucinated kebab id) cited inline
        "executive_summary": _wrap("Selective dependency [lineage-selective-supportive] but note [made-up-rule-id]."),
        "tension_analysis": _wrap("RNAi discordant [crispr-rnai-dependency-concordance]."),
        "top_arguments_for": _wrap(["strong [pan-cancer-crispr-dependency-distribution]"]),
        "top_arguments_against": _wrap(["risk [another-invented-card]"]),
    }
    audit = tp.validate_synthesis_anchors(out, _NBA, _SUB)
    assert set(audit["invented_anchors"]) == {"made-up-rule-id", "another-invented-card"}
    assert audit["n_invented"] == 2
    assert "made-up-rule-id" in audit["invented_by_field"]["executive_summary"]
    assert "another-invented-card" in audit["invented_by_field"]["top_arguments_against"]
    # legal anchors are NOT flagged
    assert "lineage-selective-supportive" not in audit["invented_anchors"]
    assert "crispr-rnai-dependency-concordance" not in audit["invented_anchors"]


def test_clean_synthesis_has_no_invented_anchors():
    out = {
        "executive_summary": _wrap("Selective [lineage-selective-supportive] via [dependency-lineage-selectivity]."),
        "tension_analysis": _wrap("flip on [pan-essential-killer]."),
        "top_arguments_for": _wrap([]),
        "top_arguments_against": _wrap([]),
    }
    audit = tp.validate_synthesis_anchors(out, _NBA, _SUB)
    assert audit["invented_anchors"] == [] and audit["n_invented"] == 0
    assert audit["allowed_anchor_count"] > 0


def test_non_id_brackets_are_not_flagged():
    # numeric refs, UPPER_SNAKE strata, and prose asides in brackets are NOT rule/card anchors
    out = {
        "executive_summary": _wrap("dependent in [MSI_H] subtype [see ref 1] value [1]"),
        "tension_analysis": _wrap(""),
        "top_arguments_for": _wrap([]),
        "top_arguments_against": _wrap([]),
    }
    audit = tp.validate_synthesis_anchors(out, _NBA, _SUB)
    assert audit["invented_anchors"] == []


def test_structured_citations_anchors_validated():
    out = {
        "executive_summary": _wrap("x"),
        "tension_analysis": _wrap("x"),
        "top_arguments_for": _wrap([]),
        "top_arguments_against": _wrap([]),
        "citations": _wrap([{"claim": "c", "anchors": ["lineage-selective-supportive", "phantom-rule-xyz"]}]),
    }
    audit = tp.validate_synthesis_anchors(out, _NBA, _SUB)
    assert audit["invented_by_field"]["citations"] == ["phantom-rule-xyz"]


def test_groundedness_summary_forwards_invented_tokens_and_fields():
    """The renderer summary must forward invented_anchors/invented_by_field to the reader (not just the
    aggregate count) so the offending token + field is locatable. Verdict-inert display telemetry."""
    from _skills_common.report_render import ir  # noqa: PLC0415

    out = {
        "executive_summary": _wrap("Selective [lineage-selective-supportive] but note [made-up-rule-id]."),
        "tension_analysis": _wrap("RNAi discordant [crispr-rnai-dependency-concordance]."),
        "top_arguments_for": _wrap([]),
        "top_arguments_against": _wrap([]),
    }
    audit = tp.validate_synthesis_anchors(out, _NBA, _SUB)
    nomination = {"llm_synthesis": {"_anchor_validation": audit}}
    gr = ir._groundedness_summary(nomination)
    assert gr is not None
    assert gr["n_invented"] == 1
    assert gr["invented_anchors"] == ["made-up-rule-id"]
    assert gr["invented_by_field"]["executive_summary"] == ["made-up-rule-id"]


def test_groundedness_summary_clean_run_forwards_empty_collections():
    from _skills_common.report_render import ir  # noqa: PLC0415

    out = {
        "executive_summary": _wrap("Selective [lineage-selective-supportive]."),
        "tension_analysis": _wrap(""),
        "top_arguments_for": _wrap([]),
        "top_arguments_against": _wrap([]),
    }
    audit = tp.validate_synthesis_anchors(out, _NBA, _SUB)
    gr = ir._groundedness_summary({"llm_synthesis": {"_anchor_validation": audit}})
    assert gr is not None
    assert gr["n_invented"] == 0
    assert gr["invented_anchors"] == []
    assert gr["invented_by_field"] == {}
