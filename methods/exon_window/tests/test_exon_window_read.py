"""Tests for the exon_window S3-boundary read layer (read.py).

Pins the two audit fixes:
  T6  — pushdown on gene_id (the product's SORT KEY) when symbol->gene_id resolves, with a
        gene_symbol pushdown FALLBACK (+ breadcrumb) only when resolution is unavailable.
  T3-B — a TRANSIENT read failure is NOT permanently memoized: a call that raises returns
        data_unavailable + _live_read_error, and a SUBSEQUENT call (S3 recovered) returns data
        (the @lru_cache-poisons-None failure class).

The S3 read is monkeypatched — no live creds needed (noted: live S3 not exercised here)."""

from __future__ import annotations

import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
import pandas as pd  # noqa: E402
import pyarrow.fs as fs  # noqa: E402
import pyarrow.parquet as pq  # noqa: E402
import pytest  # noqa: E402

from methods.exon_window import read as r  # noqa: E402


def _log2(tpm):
    return math.log2(tpm + 1.0)


def _exon_frame():
    """A minimal valid exon-quantile frame for ONE gene (E1 tumor-dominant, clean window)."""
    rows = []
    for e, t in {"E1": 200.0, "E2": 0.3}.items():
        rows.append(
            {
                "exon_id": e,
                "gene_symbol": "TESTG",
                "gene_id": "ENSG00000001",
                "source": "tcga_tumor",
                "group": "COAD",
                "median": _log2(t),
            }
        )
    for e, v in {"E1": 0.1, "E2": 0.1}.items():
        rows.append(
            {
                "exon_id": e,
                "gene_symbol": "TESTG",
                "gene_id": "ENSG00000001",
                "source": "gtex_normal",
                "group": "LIVER",
                "median": _log2(v),
            }
        )
    return pd.DataFrame(rows)


class _FakeTable:
    def __init__(self, df):
        self._df = df

    def to_pandas(self):
        return self._df


class _FakeS3FS:
    def __init__(self, *a, **k):
        pass


@pytest.fixture(autouse=True)
def _clear_cache_and_stub_fs(monkeypatch):
    """Isolate each test: clear the success-cache and stub S3FileSystem so no creds are touched."""
    r._ROWS_CACHE.clear()
    monkeypatch.setattr(fs, "S3FileSystem", _FakeS3FS)
    yield
    r._ROWS_CACHE.clear()


def test_t6_pushdown_on_gene_id_when_symbol_resolves(monkeypatch):
    """When symbol->gene_id resolves, the pushdown filter is on gene_id (the SORT KEY), not
    gene_symbol — the row-group-pruning + non-unique-symbol-correctness fix."""
    captured = {}

    def _fake_read_table(path, filesystem=None, filters=None):
        captured["filters"] = filters
        return _FakeTable(_exon_frame())

    monkeypatch.setattr(r, "_symbol_to_gene_ids", lambda sym: ["ENSG00000001"])
    monkeypatch.setattr(pq, "read_table", _fake_read_table)

    out = r.read_exon_window("TESTG", "COADREAD")
    assert captured["filters"] == [("gene_id", "in", ["ENSG00000001"])]
    assert out["exon_window_class"] in ("exon_heterogeneity_flag", "uniform_gene_window", "essential_exon_liability")
    assert "_pushdown_fallback" not in out  # resolution succeeded → no fallback breadcrumb


def test_t6_falls_back_to_gene_symbol_with_breadcrumb(monkeypatch):
    """When symbol->gene_id resolution is unavailable, fall back to a gene_symbol pushdown AND
    surface a breadcrumb (never silently)."""
    captured = {}

    def _fake_read_table(path, filesystem=None, filters=None):
        captured["filters"] = filters
        return _FakeTable(_exon_frame())

    monkeypatch.setattr(r, "_symbol_to_gene_ids", lambda sym: None)  # resolver unavailable
    monkeypatch.setattr(pq, "read_table", _fake_read_table)

    out = r.read_exon_window("TESTG", "COADREAD")
    assert captured["filters"] == [("gene_symbol", "==", "TESTG")]
    assert "_pushdown_fallback" in out


def test_t3b_transient_failure_not_permanently_cached(monkeypatch):
    """A transient read failure must NOT poison the cache: first call (raises) -> data_unavailable
    + _live_read_error; second call (S3 recovered) -> real data. This is the @lru_cache-memoizes-
    None-forever failure class the audit targets."""
    monkeypatch.setattr(r, "_symbol_to_gene_ids", lambda sym: ["ENSG00000001"])

    calls = {"n": 0}

    def _flaky_read_table(path, filesystem=None, filters=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient S3 blip (expired creds)")
        return _FakeTable(_exon_frame())

    monkeypatch.setattr(pq, "read_table", _flaky_read_table)

    first = r.read_exon_window("TESTG", "COADREAD")
    assert first["exon_window_class"] == "data_unavailable"
    assert first.get("_live_read_error") == "exon_tpm_quantiles_read_failed"

    second = r.read_exon_window("TESTG", "COADREAD")  # retry after "recovery" — must NOT be cached
    assert second["exon_window_class"] != "data_unavailable"
    assert second["best_exon_id"] == "E1"
    assert calls["n"] == 2  # the read was genuinely re-attempted


def test_t3b_successful_read_is_cached(monkeypatch):
    """The success path is unchanged: a successful read is cached (only ONE physical read for
    repeated calls on the same target)."""
    monkeypatch.setattr(r, "_symbol_to_gene_ids", lambda sym: ["ENSG00000001"])
    calls = {"n": 0}

    def _counting_read_table(path, filesystem=None, filters=None):
        calls["n"] += 1
        return _FakeTable(_exon_frame())

    monkeypatch.setattr(pq, "read_table", _counting_read_table)

    a = r.read_exon_window("TESTG", "COADREAD")
    b = r.read_exon_window("TESTG", "COADREAD")
    assert a["exon_window_class"] == b["exon_window_class"]
    assert calls["n"] == 1  # second call served from the success-cache
