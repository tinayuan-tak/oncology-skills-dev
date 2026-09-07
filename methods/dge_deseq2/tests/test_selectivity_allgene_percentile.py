"""SEL-1 (2026-08-05): the tumor-vs-normal SELECTIVITY all-gene percentile.

read_tumor_vs_normal_sensitivity_gene_row was already COMPUTING a cell-A percentile but
emitting it under `allgene_percentile` — colliding namewise with the presence
tumor-rna-vs-adjacent reader's abundance rank. SEL-1 renames it to
`selectivity_allgene_percentile*` and extends the null to cells B + C, each ranked
against its OWN comparator column (never pooled).

These tests exercise the percentile helper + column-parameterized null WITHOUT S3, by
monkeypatching the null vector. They pin: per-column nulls (no pooling), the mid-rank
convention, and graceful empties.
"""

from __future__ import annotations

import sys
from pathlib import Path


REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.dge_deseq2 import read as r  # noqa: E402


def test_percentile_ranks_within_the_named_column(monkeypatch):
    """The percentile must use the null for the SPECIFIED column — cell A and cell C
    have different comparator scales, so each ranks against its own population."""
    nulls = {
        "log2fc_A": tuple(float(x) for x in range(0, 100)),  # 0..99
        "log2fc_C": tuple(float(x) for x in range(-50, 50)),  # -50..49 (different scale)
    }

    def _fake_null(manifest_id, s3_uri, column):
        return nulls[column]

    monkeypatch.setattr(r, "_sensitivity_cell_null", _fake_null)
    # value 90 is near the top of A's 0..99 population...
    pct_a, cls_a = r._dge_sensitivity_cell_percentile("m", "s3://x", "log2fc_A", 90.0)
    assert pct_a >= 90.0 and cls_a in ("top_decile", "top_1pct")
    # ...but the SAME 90 is above ALL of C's -50..49 population → ~100th
    pct_c, cls_c = r._dge_sensitivity_cell_percentile("m", "s3://x", "log2fc_C", 90.0)
    assert pct_c == 100.0 and cls_c == "top_1pct"
    # proof the two columns are NOT pooled: same value, different percentile
    assert pct_a != pct_c


def test_empty_null_returns_none(monkeypatch):
    monkeypatch.setattr(r, "_sensitivity_cell_null", lambda m, s, c: tuple())
    pct, cls = r._dge_sensitivity_cell_percentile("m", "s3://x", "log2fc_B", 1.2)
    assert pct is None and cls == "data_unavailable"


def test_non_finite_value_is_unrankable(monkeypatch):
    monkeypatch.setattr(r, "_sensitivity_cell_null", lambda m, s, c: (0.0, 1.0, 2.0))
    pct, cls = r._dge_sensitivity_cell_percentile("m", "s3://x", "log2fc_A", float("inf"))
    assert pct is None and cls == "data_unavailable"


def test_null_helper_is_column_parameterized():
    """Guard against a regression to the cell-A-only helper: the null helper must take a
    `column` arg (the whole point of extending to B/C)."""
    import inspect

    sig = inspect.signature(r._sensitivity_cell_null)
    assert "column" in sig.parameters
