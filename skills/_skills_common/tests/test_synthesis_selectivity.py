"""Two-slot LLM synthesis for the SELECTIVITY lens: prompt grounding + schema discipline.

Mirrors test_synthesis.py (presence). The load-bearing guarantee — that --synthesize adds
ONLY the llm_synthesis sibling key — is covered generically by the dispatcher byte-stability
test (test_synthesis_dispatch.py); here we pin the selectivity-specific prompt + schema.
Bedrock is fully mocked (no network).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

COMMON_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(COMMON_DIR.parent))  # skills/

from _skills_common import synthesis_selectivity as SS  # noqa: E402


def _decision_fixture():
    return {
        "skill": "tumor-selectivity", "target": "MSLN", "indication": "PAAD",
        "headline": {
            "selectivity_class": "strong_tumor_selective",
            "cells_supporting": 3, "cells_ran": 3, "dominant_direction": "up",
            "discordant": False, "sig_all_cells": True, "max_abs_log2fc": 2.4,
            "percentile_crossing_class": "high",
            "fraction_tumor_above_normal_p95": 0.82,
            "distribution_overlap_tumor_normal": 0.11},
        "cards": [
            {"card_id": "tumor-vs-normal-selectivity", "summary": {
                "selectivity_class": "strong_tumor_selective",
                "selectivity_allgene_percentile": 98.5,
                "selectivity_allgene_percentile_class": "top_decile",
                "selectivity_allgene_percentile_context": "tcga_vs_adjacent:PAAD (dge)"},
             "_missing": False},
            {"card_id": "tumor-vs-normal-percentile-crossing", "summary": {
                "selectivity_class": "high", "fraction_tumor_above_normal_p95": 0.82},
             "_missing": False},
        ],
        "fired_rules": [],
    }


def test_prompt_grounds_verdict_comparators_and_axes():
    p = SS.build_user_prompt(_decision_fixture())
    assert "strong_tumor_selective" in p                      # verdict
    assert "3 / 3" in p                                        # comparator robustness
    assert "98.5" in p and "top_decile" in p                  # Axis-1 selectivity percentile
    assert "0.82" in p                                         # per-sample crossing
    # system prompt forbids changing the verdict + scopes modality out
    assert "never change" in SS._SYSTEM.lower() and "narrate" in SS._SYSTEM.lower()


def test_prompt_handles_missing_selectivity_card_gracefully():
    d = {"target": "X", "indication": "BRCA",
         "headline": {"selectivity_class": None},
         "cards": [{"card_id": "tumor-vs-normal-selectivity", "summary": {},
                    "_missing": True, "_missing_reason": "no_dge_product"}]}
    p = SS.build_user_prompt(d)
    assert "DATA_UNAVAILABLE" in p and "n/a" in p              # must not raise


def test_tool_schema_is_relevance_read_never_a_verdict():
    props = SS.SYNTHESIS_TOOL_SCHEMA["properties"]
    assert props["selectivity_relevance_for_target"]["enum"] == [
        "strongly_supports", "supports_with_caveats", "neutral_uninformative", "argues_against"]
    assert props["confidence_qualifier"]["enum"] == [
        "well_supported", "supported_with_caveats", "weakly_supported", "insufficient_evidence"]
    # the LLM cannot emit or restate the deterministic verdict class
    assert "selectivity_class" not in props
    assert SS.SYNTHESIS_TOOL_SCHEMA["additionalProperties"] is False


def test_schema_and_system_are_modality_and_abundance_free():
    schema_txt = json.dumps(SS.SYNTHESIS_TOOL_SCHEMA).lower()
    for tok in ["adc", "t-cell-engager", "tce", "bite", "car ", "small_molecule", "degrader"]:
        assert tok not in schema_txt, f"selectivity schema should not mention modality token {tok!r}"
    sys_l = SS._SYSTEM.lower()
    assert "do not discuss therapeutic modality" in sys_l
    assert "window" in sys_l                                   # selectivity == therapeutic window


def test_synthesize_selectivity_returns_stamped_block():
    fake = {"selectivity_relevance_for_target": {"value": "strongly_supports",
            "_source": "llm_synthesized", "_model_id": "opus", "_prompt_hash": "abc"}}
    with patch("_skills_common.llm.synthesize_structured", return_value=fake) as m:
        out = SS.synthesize_selectivity(_decision_fixture())
    assert m.called
    assert out["selectivity_relevance_for_target"]["_source"] == "llm_synthesized"
