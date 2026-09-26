"""Unit tests for methods/depmap_coessentiality/read.py.

S3-free: writes a small fixture parquet and passes it via the `parquet_path`
override. The real predicate-pushdown read + dict-shaping logic runs; the live
S3 read is exercised by the PR-description smoke, not here.
"""

from __future__ import annotations

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
    schema = pa.schema(
        [
            pa.field("gene_symbol", pa.string()),
            pa.field("partner_symbol", pa.string()),
            pa.field("pearson_r", pa.float32()),
            pa.field("abs_rank", pa.int32()),
            pa.field("n_cell_lines", pa.int32()),
        ]
    )
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
        out = read_mod.read_coessential_partners("ZZZ3", top_n=10, min_abs_r=0.25, parquet_path=fixture_parquet)
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


@pytest.fixture
def module_fixture(tmp_path) -> str:
    """A co-essentiality fixture with a COHERENT-module gene (>=3 strong partners), a SPARSE gene
    (1 strong), and an ISOLATED gene (only weak edges) — for read_coessential_module_summary."""
    rows = [
        # HUBGENE: 3 strong (|r|>=0.4) partners → in_coherent_module
        ("HUBGENE", "PART1", 0.71, 1, 1538),
        ("HUBGENE", "PART2", 0.55, 2, 1538),
        ("HUBGENE", "PART3", -0.44, 3, 1538),
        ("HUBGENE", "PART4", 0.22, 4, 1538),
        # SPARSEGENE: 1 strong partner → sparse_module
        ("SPARSEGENE", "S1", 0.48, 1, 1538),
        ("SPARSEGENE", "S2", 0.25, 2, 1538),
        # LONEGENE: only weak edges (< 0.4), < 5 partners → isolated_dependency
        ("LONEGENE", "L1", 0.23, 1, 1538),
    ]
    df = pd.DataFrame(rows, columns=["gene_symbol", "partner_symbol", "pearson_r", "abs_rank", "n_cell_lines"])
    df = df.sort_values("gene_symbol").reset_index(drop=True)
    schema = pa.schema(
        [
            pa.field("gene_symbol", pa.string()),
            pa.field("partner_symbol", pa.string()),
            pa.field("pearson_r", pa.float32()),
            pa.field("abs_rank", pa.int32()),
            pa.field("n_cell_lines", pa.int32()),
        ]
    )
    path = tmp_path / "coessentiality_edges.parquet"
    pq.write_table(pa.Table.from_pandas(df, schema=schema, preserve_index=False), path)
    return str(path)


class TestCoessentialModuleSummary:
    def test_coherent_module(self, module_fixture):
        out = read_mod.read_coessential_module_summary("HUBGENE", parquet_path=module_fixture)
        assert out["coessential_module_class"] == "in_coherent_module"
        assert out["n_partners"] == 4 and out["n_strong_partners"] == 3
        assert out["n_coessential"] == 3 and out["n_anti_correlated"] == 1  # PART3 is negative
        assert out["strongest_partner_symbol"] == "PART1" and out["strongest_partner_r"] == pytest.approx(
            0.71, abs=1e-3
        )
        assert len(out["top_partners"]) == 4

    def test_sparse_module(self, module_fixture):
        out = read_mod.read_coessential_module_summary("SPARSEGENE", parquet_path=module_fixture)
        assert out["coessential_module_class"] == "sparse_module"
        assert out["n_strong_partners"] == 1

    def test_isolated_dependency(self, module_fixture):
        out = read_mod.read_coessential_module_summary("LONEGENE", parquet_path=module_fixture)
        assert out["coessential_module_class"] == "isolated_dependency"
        assert out["n_strong_partners"] == 0

    def test_absent_gene_is_data_unavailable(self, module_fixture):
        out = read_mod.read_coessential_module_summary("NOTAGENE", parquet_path=module_fixture)
        assert out["coessential_module_class"] == "data_unavailable"
        assert out.get("_data_unavailable") is True

    def test_indication_accepted_not_consumed(self, module_fixture):
        # target-grain: passing an indication must not change the result (generic-dispatch contract)
        a = read_mod.read_coessential_module_summary("HUBGENE", parquet_path=module_fixture)
        b = read_mod.read_coessential_module_summary("HUBGENE", indication="COADREAD", parquet_path=module_fixture)
        assert a["coessential_module_class"] == b["coessential_module_class"] == "in_coherent_module"

    def test_data_source_and_version(self, module_fixture):
        out = read_mod.read_coessential_module_summary("HUBGENE", parquet_path=module_fixture)
        assert out["_data_source"] == "depmap-coessentiality-26q3-v1"
        assert out["method_version"] == read_mod.METHOD_VERSION
