"""Slice 4 link 3: comparator_concordance is surfaced to the human render + the LLM prompt.

The reader (analysis-methods) computes it and the card (target-contracts) declares it; this pins that
target-profile actually SURFACES it — it's in the selectivity curated PHASE_METRIC_FIELDS (which feeds
BOTH the 'Evidence by question' render and the 'Per-phase evidence' prompt section), and a synthetic
selectivity summary carrying the field renders its value. Bedrock-free.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run_cc", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()


def test_comparator_concordance_in_selectivity_curated_metrics():
    fields = dict(tp.PHASE_METRIC_FIELDS["selectivity"])
    assert "comparator_concordance" in fields
    assert fields["comparator_concordance"] == "comparator agreement"


def test_comparator_concordance_renders_in_evidence_section():
    sub_results = {
        "selectivity": {
            "skill_dir": "tumor-selectivity",
            "cards": [{"card_id": "tumor-vs-normal-selectivity",
                       "summary": {"cells_supporting": 3, "cells_ran": 3,
                                   "comparator_concordance": "concordant",
                                   "dominant_direction": "up", "max_abs_log2fc": 2.1}}],
            "verdict": ("strong_tumor_selective", "r"), "fired": [],
        },
    }
    html, _n = tp._render_card_data_html(sub_results)
    joined = "".join(html)
    assert "comparator agreement" in joined       # the curated label
    assert "concordant" in joined                  # the value


def test_single_comparator_value_is_readable():
    """single_comparator renders as-is (no crash / no truncation); the underscore reads clearly."""
    sub_results = {
        "selectivity": {"skill_dir": "tumor-selectivity",
                        "cards": [{"card_id": "tumor-vs-normal-selectivity",
                                   "summary": {"comparator_concordance": "single_comparator"}}],
                        "verdict": ("modest_tumor_selective", "r"), "fired": []},
    }
    html, _ = tp._render_card_data_html(sub_results)
    assert "single_comparator" in "".join(html)
