"""The middle gnomAD constraint band is no longer decision-inert.

Before 2026-07-17 `moderately_constrained` had no rule → safety _verdict returned
`insufficient` for every mid-band gene, and the 6-category risk table's safety row
was insufficient_evidence. Now moderately-constrained-safety-neutral fires → verdict
`moderately_constrained_safety` → risk table MEDIUM (equivocal). NOT a hold (only
highly_constrained gates a safety hold).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

SAFETY_RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"
TP_RUN = SAFETY_RUN.parent.parent.parent / "target-profile" / "scripts" / "run.py"


def _load(p, name):
    spec = importlib.util.spec_from_file_location(name, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_safety_verdict_maps_moderate_band():
    sf = _load(SAFETY_RUN, "sf_run")
    v = sf._verdict([{"rule_id": "moderately-constrained-safety-neutral"}])
    assert v == ("moderately_constrained_safety", "moderately-constrained-safety-neutral")


def test_risk_table_moderate_is_medium_not_insufficient():
    tp = _load(TP_RUN, "tp_run_c2c")
    sr = {"safety": {"verdict": ("moderately_constrained_safety", "r")}}
    row = next((lvl, drv) for c, lvl, drv in tp._risk_by_category_from_sub_verdicts(sr)
               if c == "safety")
    assert row[0] == "MEDIUM"


def test_moderate_band_does_not_gate_a_hold():
    """Neutral middle band must NOT force a nomination hold (only highly_constrained does)."""
    tp = _load(TP_RUN, "tp_run_c2c2")
    sr = {"safety": {"verdict": ("moderately_constrained_safety", "r")}}
    forced, _, _sup = tp._gate_recommendation(sr)
    assert forced is None
