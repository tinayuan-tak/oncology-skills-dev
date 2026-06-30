"""Synthetic-data tests for depmap_crispr_rnai_concordance.

Verify:
  1. Partition-preserving union: no imputation of missing values.
  2. 8-bucket per-line classification is exhaustive.
  3. Overall concordance_class transitions at the threshold boundaries.

No S3 access required.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

METHODS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(METHODS_ROOT))

from methods.depmap_crispr_rnai_concordance import cli as c


def _meta_for(model_ids: list, lineages: dict = None) -> dict:
    """Build minimal model_metadata dict for tests."""
    lineages = lineages or {}
    return {
        mid: {"ModelID": mid,
               "OncotreeLineage": lineages.get(mid, "Lung"),
               "CCLEName": f"CL{mid}"}
        for mid in model_ids
    }


def test_classify_cell_line_buckets():
    """Each (has_crispr, has_rnai, crispr_dep, rnai_dep) combo produces the right bucket."""
    # Both, both dependent
    assert c._classify_cell_line("ACH-1", -1.0, -0.6, -0.5, -0.25) == "agree_dependent"
    # Both, both non-dependent
    assert c._classify_cell_line("ACH-2", 0.0, 0.0, -0.5, -0.25) == "agree_non_dependent"
    # Both, CRISPR-only-dep
    assert c._classify_cell_line("ACH-3", -1.0, 0.0, -0.5, -0.25) == "disagree_crispr_dependent"
    # Both, RNAi-only-dep
    assert c._classify_cell_line("ACH-4", 0.0, -0.6, -0.5, -0.25) == "disagree_rnai_dependent"
    # CRISPR only, dependent
    assert c._classify_cell_line("ACH-5", -1.0, None, -0.5, -0.25) == "crispr_only_dependent"
    # CRISPR only, non-dependent
    assert c._classify_cell_line("ACH-6", 0.0, None, -0.5, -0.25) == "crispr_only_non_dependent"
    # RNAi only, dependent
    assert c._classify_cell_line("ACH-7", None, -0.6, -0.5, -0.25) == "rnai_only_dependent"
    # RNAi only, non-dependent
    assert c._classify_cell_line("ACH-8", None, 0.0, -0.5, -0.25) == "rnai_only_non_dependent"


def test_strongly_concordant_dependent():
    """40 lines, all in both, ≥85% agree on dependent."""
    crispr = {f"ACH-{i:03d}": -1.0 for i in range(40)}
    rnai = {f"ACH-{i:03d}": -0.6 for i in range(40)}
    meta = _meta_for(list(crispr.keys()))
    s = c.compute_concordance(crispr, rnai, meta)
    assert s["n_total"] == 40
    assert s["n_in_both"] == 40
    assert s["n_agree_dependent"] == 40
    assert s["concordance_class"] == "strongly_concordant_dependent"
    assert s["fraction_agree"] == 1.0


def test_strongly_concordant_non_dependent():
    """40 lines, all in both, ≥85% agree on NON-dependent."""
    crispr = {f"ACH-{i:03d}": 0.0 for i in range(40)}
    rnai = {f"ACH-{i:03d}": 0.0 for i in range(40)}
    meta = _meta_for(list(crispr.keys()))
    s = c.compute_concordance(crispr, rnai, meta)
    assert s["concordance_class"] == "strongly_concordant_non_dependent"


def test_discordant():
    """50 lines in both, 50% disagree -> discordant."""
    crispr = {f"ACH-{i:03d}": (-1.0 if i < 25 else 0.0) for i in range(50)}
    # Flip RNAi for the dependent CRISPR ones
    rnai = {f"ACH-{i:03d}": (0.0 if i < 25 else -0.6) for i in range(50)}
    meta = _meta_for(list(crispr.keys()))
    s = c.compute_concordance(crispr, rnai, meta)
    assert s["n_disagree_crispr_dependent"] == 25
    assert s["n_disagree_rnai_dependent"] == 25
    assert s["n_agree_dependent"] == 0
    assert s["n_agree_non_dependent"] == 0
    assert s["concordance_class"] == "discordant"


def test_partition_preserving_union_no_imputation():
    """40 lines in both + 20 CRISPR-only + 15 RNAi-only — partition counts are exact."""
    crispr = {}
    rnai = {}
    # 40 in both, dependent
    for i in range(40):
        mid = f"ACH-B-{i:03d}"
        crispr[mid] = -1.0
        rnai[mid] = -0.6
    # 20 CRISPR-only, dependent
    for i in range(20):
        mid = f"ACH-C-{i:03d}"
        crispr[mid] = -1.0
    # 15 RNAi-only, dependent
    for i in range(15):
        mid = f"ACH-R-{i:03d}"
        rnai[mid] = -0.6
    meta = _meta_for(list(set(crispr.keys()) | set(rnai.keys())))
    s = c.compute_concordance(crispr, rnai, meta)
    assert s["n_total"] == 75
    assert s["n_in_both"] == 40
    assert s["n_crispr_only"] == 20
    assert s["n_rnai_only"] == 15
    assert s["n_crispr_only_dependent"] == 20
    assert s["n_rnai_only_dependent"] == 15


def test_partially_assayed_when_overlap_below_threshold():
    """Only 10 lines in both -> partially_assayed (< 30 min_overlap)."""
    crispr = {f"ACH-{i:03d}": -1.0 for i in range(10)}
    rnai = {f"ACH-{i:03d}": -0.6 for i in range(10)}
    # Plus 50 single-assay lines on each side (these don't help the overlap count)
    for i in range(10, 60):
        crispr[f"ACH-CR{i}"] = -1.0
        rnai[f"ACH-RN{i}"] = -0.6
    meta = _meta_for(list(set(crispr.keys()) | set(rnai.keys())))
    s = c.compute_concordance(crispr, rnai, meta)
    assert s["n_in_both"] == 10
    assert s["concordance_class"] == "partially_assayed"
