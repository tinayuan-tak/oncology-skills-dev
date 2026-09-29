"""#712 (D1-D): `read_dge_gene_row` must raise loudly on provider schema drift, never
collapse silently to a whole-indication `data_unavailable`.

Pre-fix, `raw.get("log2FoldChange")` / `raw.get("padj")` return `None` for EVERY gene if
the provider parquet renames or drops either column — no `KeyError`, no schema-drift
signal, just a quiet data gap that classifies `data_unavailable` for the whole indication.
This mirrors the loud-schema-drift discipline `target_id_sidecar.read_resolver_sidecar_map`
already uses (raises `ValueError` naming the missing column).

These tests pin BOTH directions so the fix can't over-correct:
  1. a row present but MISSING a required column (schema drift) -> loud ValueError naming
     the missing column, not a silent None-filled row.
  2. the gene genuinely absent from the parquet (0 matching rows) -> still returns `None`
     (clean, honest absence — unchanged behavior).

Builds tiny REAL local parquet files (via pyarrow) and reads them through the actual
`read_dge_gene_row` code path (with `pyarrow.fs.LocalFileSystem` swapped in for the S3
filesystem + a stubbed manifest loader) rather than mocking the column lookups directly,
so a regression in the real column-presence check is caught.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.fs as pafs
import pyarrow.parquet as pq
import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.dge_deseq2 import read as r  # noqa: E402


def _write_local_parquet(tmp_path: Path, columns: dict) -> str:
    path = tmp_path / "t.parquet"
    pq.write_table(pa.table(columns), str(path))
    return str(path)


def _patch_local_read(monkeypatch, s3_uri: str):
    """Route read_dge_gene_row's S3 read at a local file: stub `_load_manifest` to point at
    `s3_uri` (an absolute local path, so `_s3_uri_to_path`'s `s3://` strip is a no-op) and swap
    `_get_s3fs` for a LocalFileSystem so pyarrow reads it directly, with no network/creds."""
    monkeypatch.setattr(r, "_load_manifest", lambda manifest_id: {"id": manifest_id, "s3_uri": s3_uri})
    monkeypatch.setattr(r, "_get_s3fs", lambda: pafs.LocalFileSystem())
    # avoid touching real AWS profile env / allgene-null S3 scan for this unit test
    monkeypatch.setattr(r, "ensure_aws_profile", lambda: None)
    monkeypatch.setattr(r, "_allgene_log2fc_null", lambda manifest_id, column="log2FoldChange": tuple())


def test_missing_padj_column_raises_loud_schema_drift(tmp_path, monkeypatch):
    path = _write_local_parquet(
        tmp_path,
        {"gene_symbol": ["KRAS"], "log2FoldChange": [1.5], "baseMean": [10.0]},  # padj dropped
    )
    _patch_local_read(monkeypatch, path)

    with pytest.raises(ValueError, match="schema drift"):
        r.read_dge_gene_row("KRAS", "fake-manifest")


def test_missing_log2foldchange_column_raises_loud_schema_drift(tmp_path, monkeypatch):
    path = _write_local_parquet(
        tmp_path,
        {"gene_symbol": ["KRAS"], "padj": [0.01], "baseMean": [10.0]},  # log2FoldChange dropped
    )
    _patch_local_read(monkeypatch, path)

    with pytest.raises(ValueError, match="schema drift"):
        r.read_dge_gene_row("KRAS", "fake-manifest")


def test_missing_column_error_names_the_column(tmp_path, monkeypatch):
    path = _write_local_parquet(
        tmp_path,
        {"gene_symbol": ["KRAS"], "log2FoldChange": [1.5]},  # padj dropped
    )
    _patch_local_read(monkeypatch, path)

    with pytest.raises(ValueError, match="padj"):
        r.read_dge_gene_row("KRAS", "fake-manifest")


def test_genuine_absence_still_returns_none_not_an_error(tmp_path, monkeypatch):
    """A gene genuinely absent from the parquet (0 matching rows, full schema intact) must
    stay a clean, honest `None` — this is NOT schema drift and must not raise."""
    path = _write_local_parquet(
        tmp_path,
        {"gene_symbol": ["EGFR"], "log2FoldChange": [1.5], "padj": [0.01]},
    )
    _patch_local_read(monkeypatch, path)

    assert r.read_dge_gene_row("KRAS", "fake-manifest") is None


def test_intact_schema_still_reads_normally(tmp_path, monkeypatch):
    """Sanity: with both required columns present, the read still succeeds and returns the
    normalized field map — the drift guard must not false-positive on a healthy row."""
    path = _write_local_parquet(
        tmp_path,
        {"gene_symbol": ["KRAS"], "log2FoldChange": [1.5], "padj": [0.01], "baseMean": [10.0]},
    )
    _patch_local_read(monkeypatch, path)

    row = r.read_dge_gene_row("KRAS", "fake-manifest")
    assert row is not None
    assert row["log2_fc"] == 1.5
    assert row["q_value"] == 0.01
