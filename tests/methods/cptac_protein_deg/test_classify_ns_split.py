"""classify() ns-split (2026-08-14 multi-pair review, finding #5).

The former single `ns` conflated "not statistically significant" (q>=0.05) with "significant but
biologically small" (q<0.05, |logfc|<=0.5). classify() now returns not_significant vs small_effect.
VERDICT-SAFE invariant pinned here: the UNION of the two new labels == the old `ns` set, and neither
is an elevated class — so the breadth/coverage rollups (which key on {strong_up, modest_up} /
data_unavailable, never on the literal `ns`) are unchanged.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

pytest.importorskip("pandas")
import numpy as np  # noqa: E402

_STEP = (Path(__file__).resolve().parents[3]
         / "methods" / "cptac_protein_deg" / "steps" / "03_pool_and_write.py")


def _load():
    spec = importlib.util.spec_from_file_location("cptac_pool_write", _STEP)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_m = _load()


def test_not_significant_when_q_high():
    assert _m.classify(0.1, 0.9) == "not_significant"
    assert _m.classify(3.0, 0.20) == "not_significant"   # large fc but q>=0.05 → still not significant


def test_not_significant_when_stats_missing():
    assert _m.classify(np.nan, 0.01) == "not_significant"
    assert _m.classify(0.8, np.nan) == "not_significant"


def test_small_effect_when_significant_but_small():
    assert _m.classify(0.5, 1e-4) == "small_effect"      # q<0.05, |logfc|<=0.5
    assert _m.classify(-0.5, 1e-3) == "small_effect"
    assert _m.classify(0.0, 1e-6) == "small_effect"


def test_up_down_bands_unchanged():
    assert _m.classify(2.0, 1e-4) == "strong_up"
    assert _m.classify(0.8, 1e-3) == "modest_up"
    assert _m.classify(-2.0, 1e-4) == "strong_down"
    assert _m.classify(-0.8, 1e-3) == "modest_down"


def test_old_ns_union_preserved_and_not_elevated():
    """Everything that used to be `ns` is now not_significant OR small_effect, and NEITHER is an
    elevated class — the verdict-safety invariant for breadth/coverage rollups."""
    old_ns_cases = [(0.1, 0.9), (3.0, 0.20), (np.nan, 0.01), (0.5, 1e-4), (0.0, 1e-6)]
    labels = {_m.classify(fc, q) for fc, q in old_ns_cases}
    assert labels <= {"not_significant", "small_effect"}
    assert labels.isdisjoint({"strong_up", "modest_up"})   # never elevated
