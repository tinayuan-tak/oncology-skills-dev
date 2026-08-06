"""immune_context.classify — per-indication T-cell-infiltration classifier (pure, no S3).

Pins the immune-hot/intermediate/cold ladder (anchored to pan-cancer CD8-fraction quartiles) + the
summarize reduction + the data_unavailable-abstains discipline.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.immune_context.classify import (  # noqa: E402
    classify_immune_context, summarize_immune_context,
    CD8_FRACTION_HOT_MIN, CD8_FRACTION_COLD_MAX, T_CELL_COLUMNS,
)


# ── the hot/intermediate/cold ladder ─────────────────────────────────────────
def test_immune_hot_at_or_above_q3():
    assert classify_immune_context(CD8_FRACTION_HOT_MIN) == "immune_hot"
    assert classify_immune_context(0.154) == "immune_hot"        # SKCM-like


def test_immune_cold_at_or_below_q1():
    assert classify_immune_context(CD8_FRACTION_COLD_MAX) == "immune_cold"
    assert classify_immune_context(0.022) == "immune_cold"       # LAML-like desert


def test_immune_intermediate_between():
    assert classify_immune_context(0.097) == "immune_intermediate"   # pan-cancer median


def test_none_cd8_is_data_unavailable_not_cold():
    # absence must ABSTAIN, never default to a (dangerous) false 'cold' call
    assert classify_immune_context(None) == "data_unavailable"


# ── summarize reduction ──────────────────────────────────────────────────────
def _row(cd8, others=0.0):
    r = {c: others for c in T_CELL_COLUMNS}
    r["T.cells.CD8"] = cd8
    return r


def test_summarize_medians_and_class():
    df = pd.DataFrame([_row(0.15), _row(0.13), _row(0.20)])   # median CD8 = 0.15 → hot
    s = summarize_immune_context(df)
    assert s["immune_context_class"] == "immune_hot"
    assert s["median_cd8_fraction"] == 0.15
    assert s["n_samples"] == 3
    assert s["median_total_t_cell_fraction"] >= 0.15   # CD8 + other T subsets


def test_summarize_empty_is_data_unavailable():
    s = summarize_immune_context(pd.DataFrame())
    assert s["immune_context_class"] == "data_unavailable"
    assert s["n_samples"] == 0
    assert s["median_cd8_fraction"] is None


def test_summarize_missing_cd8_column_is_data_unavailable():
    s = summarize_immune_context(pd.DataFrame([{"B.cells.naive": 0.1}]))
    assert s["immune_context_class"] == "data_unavailable"


def test_cold_indication_summarizes_cold():
    df = pd.DataFrame([_row(0.05), _row(0.07), _row(0.06)])   # median 0.06 → cold
    assert summarize_immune_context(df)["immune_context_class"] == "immune_cold"
