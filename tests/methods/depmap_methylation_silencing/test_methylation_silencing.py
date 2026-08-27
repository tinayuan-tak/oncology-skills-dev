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


# --- per-gene MEAN product read path (perf: pushdown vs whole-gzip stream) ---------------------------
from methods.depmap_methylation_silencing import read as R  # noqa: E402


def _write_product(tmp_path):
    """Synthetic product [gene_symbol, ccle_column, col_index, mean_beta] for two genes."""
    import pandas as pd
    rows = [
        # GENEA: two columns mapping to distinct models
        {"gene_symbol": "GENEA", "ccle_column": "AAA_LUNG", "col_index": 0, "mean_beta": 0.10},
        {"gene_symbol": "GENEA", "ccle_column": "BBB_SKIN", "col_index": 1, "mean_beta": 0.80},
        # GENEA: two columns whose STRIPPED name collides (CCC) → last col_index (3) must win
        {"gene_symbol": "GENEA", "ccle_column": "CCC_LUNG", "col_index": 2, "mean_beta": 0.20},
        {"gene_symbol": "GENEA", "ccle_column": "CCC_BONE", "col_index": 3, "mean_beta": 0.95},
        {"gene_symbol": "GENEB", "ccle_column": "AAA_LUNG", "col_index": 0, "mean_beta": 0.33},
    ]
    p = tmp_path / "prod.parquet"
    pd.DataFrame(rows).to_parquet(p, index=False)
    return str(p)


def test_product_reconstructs_last_column_wins(tmp_path):
    p = _write_product(tmp_path)
    s2m = {"AAA": "ACH-A", "BBB": "ACH-B", "CCC": "ACH-C"}   # stripped -> ModelID
    out = R._load_methylation_from_product("GENEA", s2m, product_path=p)
    assert out is not None
    methyl, err = out
    assert err is None
    assert methyl["ACH-A"] == 0.10 and methyl["ACH-B"] == 0.80
    assert methyl["ACH-C"] == 0.95        # col_index 3 (CCC_BONE) wins over col_index 2 (CCC_LUNG)


def test_product_unmapped_column_skipped(tmp_path):
    p = _write_product(tmp_path)
    s2m = {"AAA": "ACH-A"}                 # BBB / CCC unmapped -> skipped (mirrors live n_unmapped)
    methyl, err = R._load_methylation_from_product("GENEA", s2m, product_path=p)
    assert err is None
    assert set(methyl) == {"ACH-A"} and methyl["ACH-A"] == 0.10


def test_product_absent_gene_returns_gene_not_in_ccle(tmp_path):
    p = _write_product(tmp_path)
    methyl, err = R._load_methylation_from_product("NOSUCHGENE", {"AAA": "ACH-A"}, product_path=p)
    assert methyl == {} and err == "gene_not_in_ccle_rrbs"


def test_product_unreachable_returns_none(tmp_path):
    # nonexistent local path → unreachable → None (caller falls back to the live whole-gzip read)
    assert R._load_methylation_from_product("GENEA", {"AAA": "ACH-A"},
                                            product_path=str(tmp_path / "nope.parquet")) is None


def test_methylation_for_gene_falls_back_to_live_when_product_unreachable(monkeypatch):
    monkeypatch.setattr(R, "_load_methylation_from_product", lambda *a, **k: None)
    calls = {"n": 0}

    def _fake_live(target, s2m):
        calls["n"] += 1
        return {"ACH-X": 0.5}, None
    monkeypatch.setattr(R, "_load_ccle_methylation_for_gene", _fake_live)
    methyl, err = R._methylation_for_gene("GENEA", {"AAA": "ACH-A"})
    assert calls["n"] == 1 and methyl == {"ACH-X": 0.5} and err is None
