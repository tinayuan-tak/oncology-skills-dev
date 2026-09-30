"""Distribution-shape metrics for cellline-rna-distribution (Audit-B D1: bimodality + CoV).

The spec asks "is the distribution continuous or bimodal? are there target-high and target-low
populations? is expression consistent or highly variable?" These were computable from the in-memory
per-cell-line array but never emitted (only median/percentiles/fractions were). Tests pin the
dependency-light gap heuristic (mirrors the dependency side, no KDE/dip test) + the CoV-on-linear-TPM.
"""

from __future__ import annotations

import pytest

np = pytest.importorskip("numpy")


cli = __import__("onc_methods.depmap_expression_distribution.cli", fromlist=["cli"])


def test_distribution_pattern_bimodal():
    # a clear target-high subset (~7) AND a clear off subset (~0), sparse middle
    scores = [0.1] * 10 + [7.0] * 10
    assert cli._distribution_pattern(scores, 1.0, 5.0) == "bimodal"


def test_distribution_pattern_long_tail():
    # mostly off with a rare high tail
    scores = [0.1] * 16 + [6.5] * 2
    assert cli._distribution_pattern(scores, 1.0, 5.0) == "long_tail"


def test_distribution_pattern_continuous():
    # unimodal mid spread, no balanced two-mode split, no rare-tail-on-off shape
    scores = list(np.linspace(2.0, 4.0, 20))
    assert cli._distribution_pattern(scores, 1.0, 5.0) == "continuous"


def test_distribution_pattern_small_panel_is_continuous():
    # n < 8 → too few points to call a shape
    assert cli._distribution_pattern([0.1, 7.0, 0.1, 7.0, 3.0], 1.0, 5.0) == "continuous"


def test_cov_on_linear_tpm_not_log():
    # CoV must be computed on LINEAR TPM (undo log2(TPM+1)); a spread of log values that is tight in
    # linear space should give a modest CoV, and an all-equal array gives 0.
    assert cli._coefficient_of_variation([3.0] * 10) == pytest.approx(0.0, abs=1e-9)
    # bimodal linear spread → CoV around/above 1
    assert cli._coefficient_of_variation([0.1] * 10 + [7.0] * 10) > 0.5


def test_cov_all_off_no_divide_by_zero():
    assert cli._coefficient_of_variation([0.0] * 10) == 0.0


def test_summary_emits_shape_fields():
    """compute_summary_stats now surfaces distribution_pattern + coefficient_of_variation."""
    tpm_by_model = {f"ACH-{i}": v for i, v in enumerate([0.1] * 10 + [7.0] * 10)}
    meta = {m: {"OncotreeLineage": "Bowel"} for m in tpm_by_model}
    s = cli.compute_summary_stats(tpm_by_model, meta)
    assert s["distribution_pattern"] == "bimodal"
    assert "coefficient_of_variation" in s and s["coefficient_of_variation"] > 0.5
