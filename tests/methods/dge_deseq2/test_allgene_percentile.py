"""Phase 1B: all-gene percentile over DGE products (fixture-only, no S3).

Loads read.py by file path (repo convention) + monkeypatches the cached-null loaders,
so the test is deterministic and offline.
"""

import importlib.util
from pathlib import Path

import pytest

READ = Path(__file__).resolve().parents[3] / "methods" / "dge_deseq2" / "read" / "__init__.py"


def _load():
    spec = importlib.util.spec_from_file_location("dge_read_pct", READ)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_dge_allgene_percentile_uses_manifest_null(monkeypatch):
    read = _load()
    monkeypatch.setattr(read, "_allgene_log2fc_null", lambda manifest_id, column="log2FoldChange": tuple(range(10)))
    pct, klass = read._dge_allgene_percentile("some-manifest", 9)
    assert pct == pytest.approx(95.0) and klass == "top_decile"
    pct, klass = read._dge_allgene_percentile("some-manifest", 0)
    assert pct == pytest.approx(5.0) and klass == "bottom_decile"


def test_dge_percentile_none_on_empty_null(monkeypatch):
    read = _load()
    monkeypatch.setattr(read, "_allgene_log2fc_null", lambda manifest_id, column="log2FoldChange": tuple())
    pct, klass = read._dge_allgene_percentile("empty", 1.5)
    assert pct is None and klass == "data_unavailable"


def test_sensitivity_cell_percentile_uses_cell_null(monkeypatch):
    # read.py generalized _sensitivity_cellA_null -> _sensitivity_cell_null(…, column) and
    # _dge_sensitivity_cellA_percentile -> _dge_sensitivity_cell_percentile(…, column, …) (per-cell
    # comparator columns log2fc_A/B/C). This test was stale against the pre-generalization names.
    read = _load()
    monkeypatch.setattr(read, "_sensitivity_cell_null", lambda manifest_id, s3_uri, column: tuple(range(100)))
    pct, klass = read._dge_sensitivity_cell_percentile("m", "s3://x", "log2fc_A", 99)
    assert pct == pytest.approx(99.5) and klass == "top_1pct"
