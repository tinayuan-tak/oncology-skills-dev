"""allgene_percentile_precompute.lookup — a rank-product READ FAILURE must not masquerade as the
gene being genuinely ABSENT from the product.

Regression for the CEACAM5/COADREAD stale-run diagnosis: the accessors' bare `except: return None`
reported a transient S3/auth/parse failure identically to a true coverage gap ("target absent"),
which reads downstream as "not measured". The read now raises the typed `_RankReadError`, and the
public accessors emit a distinct "rank read failed" context (still `data_unavailable`, so behaviour
is unchanged — only the AUDIT context becomes honest).

Hermetic: `pyarrow.parquet.read_table` and the S3 filesystem are monkeypatched — no S3, no creds.
"""
from __future__ import annotations

import pandas as pd
import pyarrow.parquet as pq
import pytest

from methods.allgene_percentile_precompute import lookup as L


def _patch(monkeypatch, read_table_behavior):
    monkeypatch.setattr(L, "_s3fs", lambda: None)           # never build a real S3FileSystem
    monkeypatch.setattr(pq, "read_table", read_table_behavior)
    L._depmap_row.cache_clear()
    L._tumor_rows.cache_clear()


class _FakeTable:
    def __init__(self, df):
        self._df = df

    def to_pandas(self):
        return self._df


# ── DepMap (gene_symbol-keyed) ─────────────────────────────────────────────────────────────────
def test_depmap_read_failure_is_not_reported_as_absent(monkeypatch):
    def boom(*a, **k):
        raise OSError("simulated S3 auth denied")
    _patch(monkeypatch, boom)
    out = L.depmap_allgene_percentile("CEACAM5")
    assert out["allgene_percentile"] is None
    assert out["allgene_percentile_class"] == "data_unavailable"
    assert "rank read failed" in out["allgene_percentile_context"]
    assert "target absent" not in out["allgene_percentile_context"]


def test_depmap_genuine_absence_still_reported_as_absent(monkeypatch):
    empty = pd.DataFrame(columns=["allgene_percentile", "allgene_rank", "n_genes", "panel_median_log2tpm"])
    _patch(monkeypatch, lambda *a, **k: _FakeTable(empty))
    out = L.depmap_allgene_percentile("NOT_A_REAL_GENE")
    assert out["allgene_percentile"] is None
    assert out["allgene_percentile_class"] == "data_unavailable"
    assert "target absent" in out["allgene_percentile_context"]
    assert "rank read failed" not in out["allgene_percentile_context"]


def test_depmap_hit_returns_percentile(monkeypatch):
    hit = pd.DataFrame([{"allgene_percentile": 29.57, "allgene_rank": 13535,
                         "n_genes": 19215, "panel_median_log2tpm": 0.141}])
    _patch(monkeypatch, lambda *a, **k: _FakeTable(hit))
    out = L.depmap_allgene_percentile("CEACAM5")
    assert out["allgene_percentile"] == pytest.approx(29.57, abs=0.01)
    assert out["allgene_percentile_class"] == "mid"
    assert "rank 13535/19215" in out["allgene_percentile_context"]


# ── Tumor (ensembl-keyed, per-study) ───────────────────────────────────────────────────────────
def test_tumor_read_failure_is_not_reported_as_absent(monkeypatch):
    def boom(*a, **k):
        raise OSError("simulated S3 timeout")
    _patch(monkeypatch, boom)
    out = L.tumor_allgene_percentile(["ENSG00000105388"], ["COAD", "READ"])
    assert out["allgene_percentile"] is None
    assert out["allgene_percentile_class"] == "data_unavailable"
    assert "rank read failed" in out["allgene_percentile_context"]
    assert "target absent" not in out["allgene_percentile_context"]


def test_tumor_genuine_absence_still_reported_as_absent(monkeypatch):
    empty = pd.DataFrame(columns=["group", "allgene_percentile", "allgene_rank",
                                  "n_genes_in_group", "median"])
    _patch(monkeypatch, lambda *a, **k: _FakeTable(empty))
    out = L.tumor_allgene_percentile(["ENSG00000105388"], ["COAD", "READ"])
    assert out["allgene_percentile"] is None
    assert "target absent" in out["allgene_percentile_context"]
    assert "rank read failed" not in out["allgene_percentile_context"]
