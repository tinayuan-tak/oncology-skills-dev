"""depmap_methylation_silencing.compute_methylation_silencing — hermetic (synthetic methylation + TPM).

Pins the silencing classifier: high promoter methylation → LOW expression = NEGATIVE correlation →
silencing_coupled_* (MLH1/CDKN2A epigenetic-silencing archetype); methylation varies but expression
independent → methylation_uncoupled; uniformly (un)methylated panel → methylation_invariant_panel
(untestable, distinct from uncoupled); too few jointly-measured lines → data_unavailable.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_methylation_silencing.cli import (  # noqa: E402
    compute_methylation_silencing, HYPERMETHYLATION_THRESHOLD,
)


def _silencing_panel(n=120, *, slope=8.0, noise=0.4, seed=0):
    """Methylation fraction spread 0..1; TPM = high - slope*methyl + noise → strong NEGATIVE coupling."""
    import random
    rng = random.Random(seed)
    meth, tpm = {}, {}
    for i in range(n):
        f = i / (n - 1)                          # methylation fraction 0..1
        m = f"ACH-{i:05d}"
        meth[m] = f
        tpm[m] = 9.0 - slope * f + rng.uniform(-noise, noise)
    return meth, tpm


def test_silencing_coupled_strong():
    meth, tpm = _silencing_panel(noise=0.4)
    s = compute_methylation_silencing(meth, tpm)
    assert s["methylation_silencing_class"] == "silencing_coupled_strong"
    assert s["methyl_expr_spearman_r"] <= -0.4
    assert s["methyl_expr_spearman_p"] <= 0.01
    assert s["n_hypermethylated"] > 0
    assert s["delta_log2tpm_hyper_vs_unmethylated"] < 0    # hypermethylated lines UNDER-express
    assert s["hypermethylation_threshold"] == HYPERMETHYLATION_THRESHOLD


def test_uncoupled_when_expression_independent_of_methylation():
    import random
    rng = random.Random(3)
    meth, tpm = {}, {}
    for i in range(120):
        m = f"ACH-{i:05d}"
        meth[m] = i / 119                        # real methylation spread
        tpm[m] = 6.0 + rng.uniform(-1.0, 1.0)    # expression independent of methylation
    s = compute_methylation_silencing(meth, tpm)
    assert s["methylation_silencing_class"] == "methylation_uncoupled"
    assert s["methylation_p10_p90_spread"] >= 0.1


def test_methylation_invariant_panel_is_not_uncoupled():
    """Uniformly unmethylated panel (no methylation variation) → methylation_invariant_panel
    (untestable), NOT methylation_uncoupled."""
    import random
    rng = random.Random(5)
    meth, tpm = {}, {}
    for i in range(120):
        m = f"ACH-{i:05d}"
        meth[m] = 0.02 + rng.uniform(-0.01, 0.01)   # essentially unmethylated everywhere (spread << 0.1)
        tpm[m] = 6.0 + rng.uniform(-1.0, 1.0)
    s = compute_methylation_silencing(meth, tpm)
    assert s["methylation_silencing_class"] == "methylation_invariant_panel"
    assert s["methylation_p10_p90_spread"] < 0.1
    assert s["methyl_expr_spearman_r"] is None


def test_data_unavailable_when_too_few_lines():
    meth, tpm = _silencing_panel(n=20)
    s = compute_methylation_silencing(meth, tpm)
    assert s["methylation_silencing_class"] == "data_unavailable"


def test_positive_correlation_not_mislabeled_silencing():
    """A POSITIVE methylation↔expression correlation (anomalous) must NOT read as silencing."""
    import random
    rng = random.Random(8)
    meth, tpm = {}, {}
    for i in range(120):
        f = i / 119
        m = f"ACH-{i:05d}"
        meth[m] = f
        tpm[m] = 2.0 + 6.0 * f + rng.uniform(-0.4, 0.4)   # methylation UP → expression UP (positive)
    s = compute_methylation_silencing(meth, tpm)
    assert s["methylation_silencing_class"] == "methylation_uncoupled"   # not silencing_coupled_*
    assert s["methyl_expr_spearman_r"] > 0
