"""Synthesis-substrate fix (Expression-Extraction-Refinement plan): the LLM prompt must
PRESERVE load-bearing distribution fields + pass rule COLOR.

The old _build_user_prompt truncation loop dropped `_`-prefixed keys, sampled any list>5 to 3 + a
`_len`, and hard-capped 1200 chars/card — destroying exactly the per-sample distribution stats the
extraction layer produces. And the fired-rules block printed only rule_id/field=value, never the
rationale/signals/killer_message that are computed on every rule. These tests pin the fix.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run_prompt")


def test_formatter_preserves_scalar_distribution_fields():
    s = {
        "distribution_pattern": "bimodal",
        "median_log2tpm_panel": 4.2,
        "coefficient_of_variation": 1.1,
        "fraction_expressed": 0.62,
    }
    out = tp._format_card_summary_for_prompt(s)
    assert "bimodal" in out and "distribution_pattern" in out
    assert "coefficient_of_variation" in out and "median_log2tpm_panel" in out


def test_formatter_keeps_per_entity_tables_not_dropped_to_len():
    # per_lineage_stats is decision evidence — must survive as top-N rows, NOT collapse to a _len
    s = {"per_lineage_stats": [{"lineage": f"L{i}", "median_log2tpm": float(i)} for i in range(20)]}
    out = tp._format_card_summary_for_prompt(s)
    assert "per_lineage_stats" in out and "per_lineage_stats_len" not in out
    assert "median_log2tpm" in out  # the rows' content is present


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


def test_formatter_cap_trims_noise_not_load_bearing_fields():
    """#1632: a large NON-load-bearing early value must not push load-bearing scalars/lists past the
    char cap and sever them. The old `json.dumps(out)[:3000]` sliced in insertion order, so a huge
    early nested dict truncated everything after it (incl. decision fields). The priority-first cap
    keeps every scalar + load-bearing field regardless of where a noise blob sits."""
    import json

    s = {
        # a huge NON-load-bearing nested dict emitted BEFORE the decision fields (mirrors the corpus
        # `kinome_atlas_predictions` case that severed 2,846 truncated cards' load-bearing fields).
        "kinome_atlas_predictions": {f"pred_{i}": {"score": i, "pad": "x" * 40} for i in range(400)},
        "network_class": "actionable_moa",
        "median_log2tpm_panel": 5.5,
        "moa_ontology_unmapped_fraction": 0.12,
        "per_lineage_stats": [{"lineage": f"L{i}", "median_log2tpm": float(i)} for i in range(20)],
    }
    out = tp._format_card_summary_for_prompt(s)
    # the load-bearing / scalar decision fields all survive despite the huge early noise dict
    parsed = json.loads(out)  # output is ALWAYS valid JSON (never truncated mid-token)
    assert parsed["network_class"] == "actionable_moa"
    assert parsed["median_log2tpm_panel"] == 5.5
    assert parsed["moa_ontology_unmapped_fraction"] == 0.12
    assert "per_lineage_stats" in parsed and len(parsed["per_lineage_stats"]) == 8
    # the oversized noise dict is dropped (trimmed by the cap), so the blob stays bounded
    assert "kinome_atlas_predictions" not in parsed
    assert len(out) <= tp._PROMPT_CARD_CHAR_CAP


def test_formatter_output_is_always_valid_json():
    """The cap must never emit JSON truncated mid-token (the old `[:3000]` slice did)."""
    import json

    s = {"blob": "y" * 5000, "median_expr": 3.3, "distribution_pattern": "bimodal"}
    out = tp._format_card_summary_for_prompt(s)
    parsed = json.loads(out)  # would raise if truncated mid-token
    # load-bearing scalars survive even when a single scalar 'blob' is oversized
    assert parsed["median_expr"] == 3.3 and parsed["distribution_pattern"] == "bimodal"


def test_prompt_passes_rule_color():
    sub_results = {
        "expression": {
            "skill_dir": "tumor-presence",
            "verdict": ("broadly_high_expression", "expression-broadly-high-supportive"),
            "cards": [
                {
                    "card_id": "cellline-rna-distribution",
                    "summary": {"distribution_pattern": "bimodal", "median_log2tpm_panel": 6.1},
                }
            ],
            "fired": [
                {
                    "rule_id": "expression-broadly-high-supportive",
                    "card_id": "cellline-rna-distribution",
                    "field": "expression_class",
                    "value": "broadly_high_expression",
                    "signals": {"small_molecule": "supportive", "degrader": "supportive"},
                    "killer_message": None,
                    "rationale": "Broadly high expression across the panel supports presence.",
                }
            ],
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
            "skill_dir": "tumor-presence",
            "verdict": ("data_unavailable", None),
            "cards": [
                {"card_id": "tumor-protein-abundance-cptac", "summary": {"protein_expression_class": "not_detected"}}
            ],
            "fired": [
                {
                    "rule_id": "protein-not-detected-degrader-killer",
                    "card_id": "tumor-protein-abundance-cptac",
                    "field": "protein_expression_class",
                    "value": "not_detected",
                    "signals": {"degrader": "killer"},
                    "killer_message": "Protein not detected — hard killer for a degrader.",
                    "rationale": "",
                }
            ],
        }
    }
    prompt = tp._build_user_prompt("X", "COADREAD", sub_results)
    assert "KILLER: Protein not detected" in prompt
