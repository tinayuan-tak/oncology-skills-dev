"""Guard: read_gene_celltype_rows fans the per-tissue pushdown reads out concurrently, but the
assembled frame is IDENTICAL to the former serial loop — same rows, in tissue (submission) ORDER,
and the None-vs-empty semantics are preserved.

The reader queries one shard per tissue (origin + always-on safety-essential organs — 9 for
COADREAD). Reading them serially paid the sum of the shards' S3 latencies; this parallelizes them
over a bounded ThreadPoolExecutor. This test mocks the S3 layer (no network) so it can pin the
order-preserving concatenation + the found_any_product / gene-absent contract that downstream
classification depends on.
"""

from __future__ import annotations

import pandas as pd
import pytest

from methods.sc_normal_expression import read as r


class _FakeTable:
    def __init__(self, df):
        self._df = df

    def to_pandas(self):
        return self._df.copy()


@pytest.fixture()
def fake_s3(monkeypatch):
    """Stub creds/S3FileSystem so no network/credentials are touched, and route each tissue's
    parquet key to a synthetic one-row frame tagged with the tissue (so order is observable)."""
    monkeypatch.setattr(r.boto3, "Session", lambda *a, **k: _FakeSession())
    monkeypatch.setattr(r.fs, "S3FileSystem", lambda *a, **k: object())

    def fake_read_table(path, filesystem=None, filters=None, columns=None):
        # path == "<bucket>/data-catalog/derived/sc-normal-celltype-expression-<tissue>-v1/..."
        tissue_slug = path.split("sc-normal-celltype-expression-")[1].split("-v1/")[0]
        return _FakeTable(
            pd.DataFrame(
                [{"gene_symbol": "CEACAM5", "tissue": tissue_slug, "cell_type": "epithelial", "median_det": 0.5}]
            )
        )

    monkeypatch.setattr(r.pq, "read_table", fake_read_table)
    return None


class _FakeCreds:
    access_key = "AK"
    secret_key = "SK"
    token = "TK"

    def get_frozen_credentials(self):
        return self


class _FakeSession:
    def get_credentials(self):
        return _FakeCreds()


def test_parallel_read_preserves_tissue_order(fake_s3):
    tissues = ["colon", "heart", "liver", "kidney"]
    df = r.read_gene_celltype_rows("CEACAM5", tissues)
    assert list(df["tissue"]) == tissues  # submission-order, not completion-order
    assert len(df) == len(tissues)


def test_no_product_returns_none(fake_s3, monkeypatch):
    # a tissue with no landed product resolves to no key -> None when NONE of the tissues have one
    monkeypatch.setattr(r, "_s3_key", lambda t: None)
    assert r.read_gene_celltype_rows("CEACAM5", ["colon", "heart"]) is None


def test_gene_absent_returns_empty_frame(fake_s3, monkeypatch):
    # products exist, but the pushdown yields no rows for the gene -> empty DataFrame (not None)
    monkeypatch.setattr(r.pq, "read_table", lambda *a, **k: _FakeTable(pd.DataFrame(columns=["gene_symbol", "tissue"])))
    out = r.read_gene_celltype_rows("NOPE", ["colon", "heart"])
    assert out is not None and out.empty
