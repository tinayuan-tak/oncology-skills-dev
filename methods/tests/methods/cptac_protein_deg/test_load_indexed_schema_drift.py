"""#715 (D): `_load_indexed` must raise loudly on provider schema drift, never collapse
silently to a whole-product `data_unavailable`.

Pre-fix, `_row_to_summary`'s `row.get("protein_expression_class", "not_significant")` and the bare
`row.get("protein_effect_size")` return a fabricated/missing value for EVERY gene if the provider
parquet renames or drops any of the three verdict-bearing columns — no `KeyError`, no schema-drift
signal, just a quiet "tested, no difference" call (or a silent data_unavailable collapse). This
mirrors the loud-schema-drift discipline `target_id_sidecar.read_resolver_sidecar_map` /
`dge_deseq2.read_dge_gene_row` (#712) already use (raise `ValueError` naming the missing column).

These tests pin BOTH directions so the fix can't over-correct:
  1. the parquet present but MISSING a required column (schema drift) -> loud ValueError naming
     the missing column, not a silent fabricated/None-filled row.
  2. a genuinely EMPTY product (0 rows, intact schema) -> still degrades cleanly to
     data_unavailable (unchanged behavior).

Builds a tiny REAL local parquet (via pyarrow) and reads it through the actual `_load_indexed`
code path (`_ensure_derived_cached` stubbed to point at the local file) rather than mocking the
column lookups directly, so a regression in the real column-presence check is caught.
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

from methods.cptac_protein_deg import read as cptac  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_lru():
    cptac._load_indexed.cache_clear()
    yield
    cptac._load_indexed.cache_clear()


def _write_local_parquet(tmp_path: Path, columns: dict) -> Path:
    path = tmp_path / "cptac.parquet"
    pq.write_table(pa.table(columns), str(path))
    return path


def _patch_local_read(monkeypatch, path: Path):
    """Route `_load_indexed`'s S3 read at a local file: `_ensure_derived_cached` returns the local
    path (its S3-existence-probe logic is out of scope here) and `_get_s3fs` is swapped for a
    LocalFileSystem so pyarrow/pandas read it directly, with no network/creds — mirrors
    dge_deseq2/tests/test_gene_row_schema_drift.py::_patch_local_read (#712)."""
    monkeypatch.setattr(cptac, "_ensure_derived_cached", lambda: str(path))
    monkeypatch.setattr(cptac, "_get_s3fs", lambda: pafs.LocalFileSystem())


_FULL_ROW = {
    "cohort": ["BRCA"],
    "gene_symbol": ["EGFR"],
    "protein_expression_class": ["strong_up"],
    "protein_effect_size": [1.5],
    "protein_effect_size_se": [0.1],
}


def test_missing_protein_expression_class_raises_loud_schema_drift(tmp_path, monkeypatch):
    cols = {k: v for k, v in _FULL_ROW.items() if k != "protein_expression_class"}
    path = _write_local_parquet(tmp_path, cols)
    _patch_local_read(monkeypatch, path)

    with pytest.raises(ValueError, match="schema drift"):
        cptac._load_indexed()


def test_missing_protein_effect_size_raises_loud_schema_drift(tmp_path, monkeypatch):
    cols = {k: v for k, v in _FULL_ROW.items() if k != "protein_effect_size"}
    path = _write_local_parquet(tmp_path, cols)
    _patch_local_read(monkeypatch, path)

    with pytest.raises(ValueError, match="schema drift"):
        cptac._load_indexed()


def test_missing_protein_effect_size_se_raises_loud_schema_drift(tmp_path, monkeypatch):
    cols = {k: v for k, v in _FULL_ROW.items() if k != "protein_effect_size_se"}
    path = _write_local_parquet(tmp_path, cols)
    _patch_local_read(monkeypatch, path)

    with pytest.raises(ValueError, match="schema drift"):
        cptac._load_indexed()


def test_missing_column_error_names_the_column(tmp_path, monkeypatch):
    cols = {k: v for k, v in _FULL_ROW.items() if k != "protein_effect_size_se"}
    path = _write_local_parquet(tmp_path, cols)
    _patch_local_read(monkeypatch, path)

    with pytest.raises(ValueError, match="protein_effect_size_se"):
        cptac._load_indexed()


def test_schema_drift_propagates_through_read_target_summary(tmp_path, monkeypatch):
    """The raise must reach the public read entrypoints too, not be re-swallowed to data_unavailable."""
    cols = {k: v for k, v in _FULL_ROW.items() if k != "protein_expression_class"}
    path = _write_local_parquet(tmp_path, cols)
    _patch_local_read(monkeypatch, path)

    with pytest.raises(ValueError, match="schema drift"):
        cptac.read_target_summary("EGFR", "BRCA")


def test_genuinely_empty_product_still_returns_data_unavailable_not_an_error(tmp_path, monkeypatch):
    """A genuinely EMPTY product (0 rows, intact schema) is NOT schema drift and must not raise."""
    cols = {k: [] for k in _FULL_ROW}
    path = _write_local_parquet(tmp_path, cols)
    _patch_local_read(monkeypatch, path)

    out = cptac.read_target_summary("EGFR", "BRCA")
    assert out["protein_expression_class"] == "data_unavailable"


def test_intact_schema_still_reads_normally(tmp_path, monkeypatch):
    """Sanity: with all three required columns present, the read still succeeds normally — the
    drift guard must not false-positive on a healthy row."""
    path = _write_local_parquet(tmp_path, dict(_FULL_ROW))
    _patch_local_read(monkeypatch, path)

    out = cptac.read_target_summary("EGFR", "BRCA")
    assert out["protein_expression_class"] == "strong_up"
    assert out["protein_effect_size"] == 1.5
