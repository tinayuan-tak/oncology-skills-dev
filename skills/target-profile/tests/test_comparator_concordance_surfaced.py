"""comparator_concordance is surfaced to the human render + the LLM prompt.

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
