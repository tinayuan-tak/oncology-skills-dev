"""allgene_percentile_precompute.lookup — a rank-product READ FAILURE must not masquerade as the
gene being genuinely ABSENT from the product.

Regression for the CEACAM5/COADREAD stale-run diagnosis: the accessors' bare `except: return None`
reported a transient S3/auth/parse failure identically to a true coverage gap ("target absent"),
which reads downstream as "not measured". The read now raises the typed `_RankReadError`, and the
public accessors emit a distinct "rank read failed" context (still `data_unavailable`, so behaviour
is unchanged — only the AUDIT context becomes honest).

Hermetic: the cached rank Dataset (`_rank_dataset`) and the S3 filesystem are monkeypatched — no
S3, no creds.
"""

from __future__ import annotations

import pandas as pd
import pytest

from methods.allgene_percentile_precompute import lookup as L


def _patch(monkeypatch, to_table_behavior):
    monkeypatch.setattr(L, "_s3fs", lambda: None)  # never build a real S3FileSystem
    # The accessors now read via a process-cached pyarrow Dataset — `_rank_dataset(key).to_table(
    # filter=..., columns=...)` — not `pq.read_table`, so THAT is the seam to mock. A fake Dataset
    # whose `.to_table` runs the supplied behavior lets a test simulate a read failure (raise), a
    # genuine absence (empty frame), or a hit — exercising the real _RankReadError-vs-absent split.
    monkeypatch.setattr(L, "_rank_dataset", lambda key: _FakeDataset(to_table_behavior))
    L._DATASETS.clear()  # drop any real cached Dataset
    L._depmap_row.cache_clear()
    L._tumor_rows.cache_clear()


class _FakeTable:
    def __init__(self, df):
        self._df = df

    def to_pandas(self):
        return self._df


class _FakeDataset:
    """Stands in for the cached pyarrow Dataset. `.to_table(...)` delegates to the behavior the test
    supplied (raise → read failure; return a _FakeTable → hit/absence)."""

    def __init__(self, to_table_behavior):
        self._behavior = to_table_behavior

    def to_table(self, *a, **k):
        return self._behavior(*a, **k)


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
    hit = pd.DataFrame(
        [{"allgene_percentile": 29.57, "allgene_rank": 13535, "n_genes": 19215, "panel_median_log2tpm": 0.141}]
    )
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
    empty = pd.DataFrame(columns=["group", "allgene_percentile", "allgene_rank", "n_genes_in_group", "median"])
    _patch(monkeypatch, lambda *a, **k: _FakeTable(empty))
    out = L.tumor_allgene_percentile(["ENSG00000105388"], ["COAD", "READ"])
    assert out["allgene_percentile"] is None
    assert "target absent" in out["allgene_percentile_context"]
    assert "rank read failed" not in out["allgene_percentile_context"]
