"""Unit tests for methods/depmap_coessentiality/read.py.

S3-free: writes a small fixture parquet and passes it via the `parquet_path`
override. The real predicate-pushdown read + dict-shaping logic runs; the live
S3 read is exercised by the PR-description smoke, not here.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

REPO = Path(__file__).resolve().parents[3]
READ_PY = REPO / "methods" / "depmap_coessentiality" / "read.py"


def _load():
    # Load as part of the package so the `from . import METHOD_VERSION` relative
    # import resolves. Insert the repo root and import via the package path.
    sys.path.insert(0, str(REPO))
    import methods.depmap_coessentiality.read as read_mod  # noqa: WPS433
    return read_mod


read_mod = _load()


@pytest.fixture
def fixture_parquet(tmp_path) -> str:
    """A 3-gene co-essentiality fixture, gene-sorted, mirroring the emit schema."""
    rows = [
        # KRAS: 2 partners (one positive, one negative), ranks 1-2
        ("KRAS", "RAF1", 0.42, 1, 1538),
        ("KRAS", "SPRED2", -0.31, 2, 1538),
        # UBA3: 1 partner
        ("UBA3", "NAE1", 0.345, 1, 1538),
        # ZZZ3: partner just above floor
        ("ZZZ3", "FOO", 0.21, 1, 1538),
    ]
    df = pd.DataFrame(rows, columns=["gene_symbol", "partner_symbol", "pearson_r", "abs_rank", "n_cell_lines"])
    df = df.sort_values("gene_symbol").reset_index(drop=True)
    schema = pa.schema([
        pa.field("gene_symbol", pa.string()),
        pa.field("partner_symbol", pa.string()),
        pa.field("pearson_r", pa.float32()),
        pa.field("abs_rank", pa.int32()),
        pa.field("n_cell_lines", pa.int32()),
    ])
    path = tmp_path / "coessentiality_edges.parquet"
    pq.write_table(pa.Table.from_pandas(df, schema=schema, preserve_index=False), path)
    return str(path)


class TestReadCoessentialPartners:
    def test_basic_lookup(self, fixture_parquet):
        out = read_mod.read_coessential_partners("KRAS", top_n=10, parquet_path=fixture_parquet)
        assert out["gene_symbol"] == "KRAS"
        assert out["n_partners"] == 2
        assert out["n_cell_lines"] == 1538
        assert "_data_unavailable" not in out

    def test_partner_shape_and_direction(self, fixture_parquet):
        out = read_mod.read_coessential_partners("KRAS", top_n=10, parquet_path=fixture_parquet)
        by_symbol = {p["symbol"]: p for p in out["partners"]}
        assert by_symbol["RAF1"]["direction"] == "co-essential"
        assert by_symbol["RAF1"]["pearson_r"] == pytest.approx(0.42, abs=1e-4)
        assert by_symbol["SPRED2"]["direction"] == "anti-correlated"
        assert by_symbol["SPRED2"]["pearson_r"] < 0

    def test_top_n_caps_results(self, fixture_parquet):
        out = read_mod.read_coessential_partners("KRAS", top_n=1, parquet_path=fixture_parquet)
        assert out["n_partners"] == 1
        # rank-1 partner is the strongest |r|
        assert out["partners"][0]["abs_rank"] == 1
        assert out["partners"][0]["symbol"] == "RAF1"

    def test_partners_sorted_by_rank(self, fixture_parquet):
        out = read_mod.read_coessential_partners("KRAS", top_n=10, parquet_path=fixture_parquet)
        ranks = [p["abs_rank"] for p in out["partners"]]
        assert ranks == sorted(ranks)

    def test_read_time_min_abs_r_filter(self, fixture_parquet):
        # ZZZ3's only partner is r=0.21; a 0.25 floor should drop it
        out = read_mod.read_coessential_partners(
            "ZZZ3", top_n=10, min_abs_r=0.25, parquet_path=fixture_parquet
        )
        assert out["n_partners"] == 0

    def test_absent_gene_is_data_unavailable(self, fixture_parquet):
        out = read_mod.read_coessential_partners("NOTAGENE", parquet_path=fixture_parquet)
        assert out["_data_unavailable"] is True
        assert out["n_partners"] == 0
        assert "not found" in out["_reason"]

    def test_missing_file_is_data_unavailable(self, tmp_path):
        missing = str(tmp_path / "does_not_exist.parquet")
        out = read_mod.read_coessential_partners("KRAS", parquet_path=missing)
        assert out["_data_unavailable"] is True
        assert "_error" in out

    def test_method_version_carried(self, fixture_parquet):
        out = read_mod.read_coessential_partners("UBA3", parquet_path=fixture_parquet)
        assert out["method_version"] == read_mod.METHOD_VERSION
