"""sweep2 Fix 5: kinome_atlas_prediction.derive writes the product sorted by percentile DESC.

The runtime reader loads with filters=[('percentile','>=',95)]. If the product is written unsorted,
every parquet row-group spans the full [90,100] range and pyarrow can prune NONE of them. Sorting
percentile descending before write clusters the high-percentile edges into the leading row-groups so
the >=95 predicate skips the tail. This test drives derive_kinome_atlas_long with synthetic melted
frames (no Excel), writes a real parquet, and asserts the on-disk percentile column is non-increasing.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

derive = importlib.import_module("methods.kinome_atlas_prediction.derive")


def _synth_frame(kinome_label, percentiles):
    n = len(percentiles)
    return pd.DataFrame({
        "kinase_symbol": pd.Series([f"K{i}" for i in range(n)], dtype="string"),
        "substrate_gene": pd.Series([f"G{i}" for i in range(n)], dtype="string"),
        "substrate_ac": pd.Series([f"P{i}" for i in range(n)], dtype="string"),
        "phosphosite": pd.Series([f"S{i}" for i in range(n)], dtype="string"),
        "phos_res": pd.Series(["S"] * n, dtype="string"),
        "motif_15mer": pd.Series(["AAAAAAA"] * n, dtype="string"),
        "kinome": kinome_label,
        "percentile": pd.to_numeric(percentiles),
        "rank": pd.Series([1] * n, dtype="Int64"),
    })


def test_product_written_percentile_descending(monkeypatch, tmp_path):
    # unsorted, interleaved percentiles across the two atlases
    frames = {
        "ser_thr": _synth_frame("ser_thr", [90.1, 99.5, 93.0, 97.2]),
        "tyr": _synth_frame("tyr", [95.5, 91.0, 98.8, 90.0]),
    }

    def _fake_melt(xlsx_path, sheet_name, kinome_label, percentile_threshold):
        return frames[kinome_label]

    monkeypatch.setattr(derive, "_melt_wide_atlas", _fake_melt)

    out = tmp_path / "kinome_atlas_long_edges.parquet"
    derive.derive_kinome_atlas_long(
        johnson_xlsx=Path("/dev/null/johnson.xlsx"),
        yaron_xlsx=Path("/dev/null/yaron.xlsx"),
        out_parquet=out,
        percentile_threshold=90.0,
    )
    got = pd.read_parquet(out)["percentile"].tolist()
    assert got == sorted(got, reverse=True), f"percentile not descending on disk: {got}"
    # all 8 rows retained (nothing dropped by the sort)
    assert len(got) == 8
