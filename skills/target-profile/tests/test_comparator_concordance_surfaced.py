"""comparator_concordance is surfaced to the human render + the LLM prompt.

The reader (analysis-methods) computes it and the card (target-contracts) declares it; this pins that
target-profile actually SURFACES it — it's in the selectivity curated PHASE_METRIC_FIELDS (which feeds
BOTH the 'Evidence by question' render and the 'Per-phase evidence' prompt section), and a synthetic
selectivity summary carrying the field renders its value. Bedrock-free.
"""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run_cc")


def test_comparator_concordance_in_selectivity_curated_metrics():
    fields = dict(tp.PHASE_METRIC_FIELDS["selectivity"])
    assert "comparator_concordance" in fields
    assert fields["comparator_concordance"] == "comparator agreement"
