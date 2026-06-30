"""Synthetic tests for depmap_expression_distribution.

Verify the four expression_class branches + per-lineage breakdown logic.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

METHODS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(METHODS_ROOT))

from methods.depmap_expression_distribution import cli as c


def _panel(lineage_to_log2tpm: dict) -> tuple[dict, dict]:
    tpm, meta = {}, {}
    i = 1
    for lin, scores in lineage_to_log2tpm.items():
        for s in scores:
            mid = f"ACH-{i:06d}"
            tpm[mid] = float(s)
            meta[mid] = {"ModelID": mid, "OncotreeLineage": lin, "CCLEName": f"CL{i}_{lin}"}
            i += 1
    return tpm, meta


def test_broadly_high():
    """All lines highly expressed -> broadly_high."""
    tpm, meta = _panel({"Lung": [6.0] * 20, "Breast": [6.5] * 20, "Bowel": [7.0] * 20})
    s = c.compute_summary_stats(tpm, meta)
    assert s["expression_class"] == "broadly_high"
    assert s["fraction_highly_expressed"] >= 0.30


def test_broadly_moderate():
    """All lines expressed but few highly -> broadly_moderate."""
    tpm, meta = _panel({"Lung": [3.0] * 20, "Breast": [2.5] * 20, "Bowel": [3.5] * 20})
    s = c.compute_summary_stats(tpm, meta)
    assert s["expression_class"] == "broadly_moderate"
    assert s["fraction_expressed"] >= 0.70


def test_lineage_restricted():
    """One lineage expressed, two not -> lineage_restricted."""
    tpm, meta = _panel({
        "Lung": [5.0] * 20,   # expressed
        "Breast": [0.2] * 20, # not expressed
        "Bowel": [0.1] * 20,  # not expressed
    })
    s = c.compute_summary_stats(tpm, meta)
    assert s["expression_class"] == "lineage_restricted"
    assert s["fraction_expressed"] >= 0.10
    assert s["fraction_expressed"] <= 0.70
    assert s["n_lineage_restricted_lineages"] >= 1


def test_broadly_low():
    """No lines expressed -> broadly_low."""
    tpm, meta = _panel({"Lung": [0.1] * 20, "Breast": [0.2] * 20, "Bowel": [0.0] * 20})
    s = c.compute_summary_stats(tpm, meta)
    assert s["expression_class"] == "broadly_low"
    assert s["fraction_expressed"] < 0.10


def test_per_lineage_stats_present():
    """per_lineage_stats includes only lineages with n>=5."""
    tpm, meta = _panel({"Lung": [3.0] * 10, "Breast": [3.0] * 3, "Bowel": [3.0] * 10})
    s = c.compute_summary_stats(tpm, meta)
    lineages = {row["lineage"] for row in s["per_lineage_stats"]}
    assert "Lung" in lineages
    assert "Bowel" in lineages
    assert "Breast" not in lineages   # only n=3, below min_lineage_size
