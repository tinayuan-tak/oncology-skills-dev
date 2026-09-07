"""The middle gnomAD constraint band is no longer decision-inert.

Before 2026-07-17 `moderately_constrained` had no rule → safety _verdict returned
`insufficient` for every mid-band gene, and the 6-category risk table's safety row
was insufficient_evidence. Now moderately-constrained-safety-neutral fires → verdict
`moderately_constrained_safety` → risk table MEDIUM (equivocal). NOT a hold (only
highly_constrained gates a safety hold).
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

SAFETY_RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"
TP_RUN = SAFETY_RUN.parent.parent.parent / "target-profile" / "scripts" / "run.py"


def test_safety_verdict_maps_moderate_band():
    sf = load_run_py(SAFETY_RUN.parent.parent, "sf_run")
    v = sf._verdict([{"rule_id": "moderately-constrained-safety-neutral"}])
    assert v == ("moderately_constrained_safety", "moderately-constrained-safety-neutral")


def test_risk_table_moderate_is_medium_not_insufficient():
    # The risk table is now the deterministic risk_6dim projection (re-homed to
    # _skills_common.risk_projection); a moderately-constrained safety verdict → safety bin MED → the
    # md risk row MEDIUM (via tp._risk_rows_from_rollup, the same source md/html/json render).
    tp = load_run_py(TP_RUN.parent.parent, "tp_run_c2c")
    from _skills_common.risk_projection import deterministic_bins

    pkg = {"synthesis": {"sub_verdicts": {"safety": {"verdict": "moderately_constrained_safety"}}}, "cards": []}
    dims = deterministic_bins(pkg, "small_molecule")
    row = next((lvl, drv) for c, lvl, drv in tp._risk_rows_from_rollup(dims) if c == "safety")
    assert row[0] == "MEDIUM"


def test_moderate_band_does_not_gate_a_hold():
    """Neutral middle band must NOT force a nomination hold (only highly_constrained does)."""
    tp = load_run_py(TP_RUN.parent.parent, "tp_run_c2c2")
    sr = {"safety": {"verdict": ("moderately_constrained_safety", "r")}}
    forced, _, _sup = tp._gate_recommendation(sr)
    assert forced is None
