"""Cross-indication QC index (S3b, github analysis-methods#702).

``build_qc_index`` concatenates per-run ``qc_summary.csv`` files into one index
table. The anti-"green-on-empty" discipline is enforced here too: the index
REFUSES to build from nothing, REFUSES a header-only (zero-row) summary, and
REJECTS a summary missing the enumerated columns — so a silently-empty run
surfaces instead of being absorbed. The count is reconciled (index rows ==
sum of per-run rows), not merely "a parquet was written".
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from onc_methods.dge_deseq2.build_qc_index import (
    EXPECTED_COLUMNS,
    build_qc_index,
    find_qc_summaries,
    main,
)


def _row(indication: str, cell: str, substrate: str = "recount3", **over) -> dict:
    base = {
        "indication": indication,
        "substrate": substrate,
        "cell": cell,
        "n_tumor": 100,
        "n_normal": 50,
        "genes_pre_filter": 60000,
        "genes_post_filter": 25000,
        "n_filtered_indep": 1200,
        "n_filtered_cooks": 30,
        "n_sig_fdr05": 8000,
        "n_sig_fdr10": 9000,
        "median_abs_lfc_sig": 1.4,
        "size_factor_min": 0.7,
        "size_factor_max": 1.5,
        "size_factor_ratio": 2.14,
        "n_tested": 24000,
        "n_figures": 9,
        "figures": "ma_plot.png;volcano.png",
    }
    base.update(over)
    return base


def _write_summary(path: Path, rows: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=list(EXPECTED_COLUMNS)).to_csv(path, index=False)
    return path


def test_find_qc_summaries_covers_both_driver_layouts(tmp_path):
    # 06 whole-cohort layout: <run>/qc/qc_summary.csv
    _write_summary(tmp_path / "coadread" / "qc" / "qc_summary.csv", [_row("COADREAD", "A"), _row("COADREAD", "C")])
    # 07 stratified layout: <run>/_strat_<s>/qc/qc_summary.csv
    _write_summary(tmp_path / "coadread" / "_strat_MSI_H" / "qc" / "qc_summary.csv", [_row("COADREAD:MSI_H", "A")])
    found = find_qc_summaries([tmp_path])
    assert len(found) == 2, f"recursive search should find both layouts, got {found}"


def test_build_qc_index_reconciles_row_count(tmp_path):
    s1 = _write_summary(tmp_path / "coadread" / "qc" / "qc_summary.csv", [_row("COADREAD", "A"), _row("COADREAD", "C")])
    s2 = _write_summary(
        tmp_path / "luad" / "qc" / "qc_summary.csv", [_row("LUAD", "A"), _row("LUAD", "B"), _row("LUAD", "C")]
    )
    index = build_qc_index([s1, s2])
    # Count reconciliation: index rows == sum of per-run rows (2 + 3).
    assert len(index) == 5
    assert "source_summary" in index.columns
    assert set(index["indication"]) == {"COADREAD", "LUAD"}
    # Sorted by (indication, substrate, cell).
    assert list(index["indication"]) == ["COADREAD", "COADREAD", "LUAD", "LUAD", "LUAD"]


def test_build_qc_index_refuses_empty_input():
    with pytest.raises(ValueError, match="no qc_summary.csv"):
        build_qc_index([])


def test_build_qc_index_rejects_header_only_summary(tmp_path):
    s = _write_summary(tmp_path / "empty" / "qc" / "qc_summary.csv", [])
    with pytest.raises(ValueError, match="zero rows"):
        build_qc_index([s])


def test_build_qc_index_rejects_missing_columns(tmp_path):
    path = tmp_path / "bad" / "qc" / "qc_summary.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    # Drop an enumerated column.
    pd.DataFrame([{"indication": "X", "cell": "A"}]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="missing required column"):
        build_qc_index([path])


def test_main_writes_parquet_and_reconciles(tmp_path):
    _write_summary(tmp_path / "coadread" / "qc" / "qc_summary.csv", [_row("COADREAD", "A"), _row("COADREAD", "C")])
    _write_summary(tmp_path / "luad" / "qc" / "qc_summary.csv", [_row("LUAD", "A")])
    out = tmp_path / "index" / "qc_index.parquet"
    rc = main([str(tmp_path), "--out", str(out)])
    assert rc == 0
    assert out.is_file()
    df = pd.read_parquet(out)
    assert len(df) == 3


def test_main_returns_nonzero_when_no_summaries(tmp_path):
    out = tmp_path / "qc_index.parquet"
    rc = main([str(tmp_path), "--out", str(out)])
    assert rc == 1
    assert not out.exists()


def test_cli_module_runs_as_subprocess(tmp_path):
    _write_summary(tmp_path / "coadread" / "qc" / "qc_summary.csv", [_row("COADREAD", "A")])
    out = tmp_path / "qc_index.parquet"
    proc = subprocess.run(
        [sys.executable, "-m", "onc_methods.dge_deseq2.build_qc_index", str(tmp_path), "--out", str(out)],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[3]),
    )
    assert proc.returncode == 0, proc.stderr
    assert out.is_file()
