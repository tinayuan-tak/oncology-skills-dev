"""Synthesis-substrate fix (Expression-Extraction-Refinement plan, Step 0): the LLM prompt must
PRESERVE load-bearing distribution fields + pass rule COLOR.

The old _build_user_prompt truncation loop dropped `_`-prefixed keys, sampled any list>5 to 3 + a
`_len`, and hard-capped 1200 chars/card — destroying exactly the per-sample distribution stats the
extraction layer produces. And the fired-rules block printed only rule_id/field=value, never the
rationale/signals/killer_message that are computed on every rule. These tests pin the fix.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_prompt", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()


def test_formatter_preserves_scalar_distribution_fields():
    s = {"distribution_pattern": "bimodal", "median_log2tpm_panel": 4.2,
         "coefficient_of_variation": 1.1, "fraction_expressed": 0.62}
    out = tp._format_card_summary_for_prompt(s)
    assert "bimodal" in out and "distribution_pattern" in out
    assert "coefficient_of_variation" in out and "median_log2tpm_panel" in out


def test_formatter_keeps_per_entity_tables_not_dropped_to_len():
    # per_lineage_stats is decision evidence — must survive as top-N rows, NOT collapse to a _len
    s = {"per_lineage_stats": [{"lineage": f"L{i}", "median_log2tpm": float(i)} for i in range(20)]}
    out = tp._format_card_summary_for_prompt(s)
    assert "per_lineage_stats" in out and "per_lineage_stats_len" not in out
    assert "median_log2tpm" in out                         # the rows' content is present


def test_formatter_still_samples_unknown_oversized_lists():
    # a genuinely-noise big list (no load-bearing key) is still summarized, not dumped whole
    s = {"debug_trace": list(range(100))}
    out = tp._format_card_summary_for_prompt(s)
    assert "debug_trace_len" in out and "debug_trace_sample" in out


def test_formatter_drops_underscore_provenance_keys():
    s = {"_data_source": "x", "_prompt_hash": "y", "median_log2tpm_panel": 3.0}
    out = tp._format_card_summary_for_prompt(s)
    assert "_data_source" not in out and "_prompt_hash" not in out
    assert "median_log2tpm_panel" in out


def test_prompt_passes_rule_color():
    sub_results = {
        "expression": {
            "skill_dir": "tumor-presence",
            "verdict": ("broadly_high_expression", "expression-broadly-high-supportive"),
            "cards": [{"card_id": "cellline-rna-distribution",
                       "summary": {"distribution_pattern": "bimodal", "median_log2tpm_panel": 6.1}}],
            "fired": [{"rule_id": "expression-broadly-high-supportive",
                       "card_id": "cellline-rna-distribution", "field": "expression_class",
                       "value": "broadly_high_expression",
                       "signals": {"small_molecule": "supportive", "degrader": "supportive"},
                       "killer_message": None,
                       "rationale": "Broadly high expression across the panel supports presence."}],
        }
    }
    prompt = tp._build_user_prompt("KRAS", "COADREAD", sub_results)
    # rule color present
    assert "signals: small_molecule=supportive" in prompt
    assert "why: Broadly high expression across the panel" in prompt
    # and the distribution field survived into the card-summary block
    assert "bimodal" in prompt


def test_prompt_surfaces_killer_message():
    sub_results = {
        "expression": {
            "skill_dir": "tumor-presence", "verdict": ("data_unavailable", None),
            "cards": [{"card_id": "tumor-protein-abundance-cptac", "summary": {"protein_expression_class": "not_detected"}}],
            "fired": [{"rule_id": "protein-not-detected-degrader-killer",
                       "card_id": "tumor-protein-abundance-cptac", "field": "protein_expression_class",
                       "value": "not_detected", "signals": {"degrader": "killer"},
                       "killer_message": "Protein not detected — hard killer for a degrader.",
                       "rationale": ""}],
        }
    }
    prompt = tp._build_user_prompt("X", "COADREAD", sub_results)
    assert "KILLER: Protein not detected" in prompt
