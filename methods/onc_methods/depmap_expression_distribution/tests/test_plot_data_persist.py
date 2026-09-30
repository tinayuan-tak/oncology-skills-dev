"""Stage-1 (figure consolidation): read_expression_distribution persists plot_data on the verdict
path when asked, and is a byte-identical no-op otherwise.

Offline/deterministic — monkeypatch load_expression_files with a synthetic panel; no S3 / cbg.
Proves the plot_data becomes an artifact of card RESOLUTION (not a figure re-read side effect),
which is what lets render_from_plot_data (Stage 2) draw without a second live read.
"""

from __future__ import annotations

import pytest

from onc_methods.depmap_expression_distribution import read as r


def _panel() -> tuple[dict, dict]:
    tpm, meta = {}, {}
    for i, (lin, val) in enumerate([("Lung", 6.0), ("Breast", 5.5), ("Bowel", 0.2)], start=1):
        mid = f"ACH-{i:06d}"
        tpm[mid] = float(val)
        meta[mid] = {"ModelID": mid, "OncotreeLineage": lin, "CCLEName": f"CL{i}_{lin}"}
    return tpm, meta


@pytest.fixture
def offline_panel(monkeypatch):
    tpm, meta = _panel()
    monkeypatch.setattr(r._cli, "load_expression_files", lambda release_pin, target_symbol: (tpm, meta, []))
    return tpm, meta


def test_plot_data_written_when_requested(offline_panel, tmp_path):
    import pandas as pd

    tpm, _ = offline_panel
    summary = r.read_expression_distribution("MYGENE", plot_data_out=tmp_path)
    assert summary["expression_class"]  # core summary still produced

    pq = tmp_path / "plot_data_expression.parquet"
    assert pq.exists(), "plot_data_out must persist plot_data_expression.parquet"
    df = pd.read_parquet(pq)
    assert len(df) == len(tpm)  # one row per model
    assert set(df["model_id"]) == set(tpm)
    assert {"model_id", "lineage", "log2tpm", "is_expressed"} <= set(df.columns)


def test_summary_byte_identical_regardless_of_plot_data(offline_panel, tmp_path):
    """plot_data persistence is verdict-inert: the returned summary is unchanged by plot_data_out."""
    s_without = r.read_expression_distribution("MYGENE")
    s_with = r.read_expression_distribution("MYGENE", plot_data_out=tmp_path)
    assert s_without == s_with


def test_no_write_without_plot_data_out(offline_panel, tmp_path):
    r.read_expression_distribution("MYGENE")  # default plot_data_out=None
    assert not (tmp_path / "plot_data_expression.parquet").exists()
    assert list(tmp_path.iterdir()) == []
