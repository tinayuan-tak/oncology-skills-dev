"""AM-3 primary read path: read_target_summary reads the DERIVED product (real ohnolog).

The reader now PREFERS the gene-sorted derived product depmap-paralog-buffering-per-gene-v1
(cheap predicate-pushdown), which carries the Ensembl-Compara ohnolog_flag the card declares —
falling back to the raw-CSV recompute only when the product is unreachable. These tests mock the
per-gene product row (no S3) and pin: (1) product columns map to the card fields, (2)
strongest_paralog_ohnolog is POPULATED from the product's ohnolog_flag, (3) an unreachable
product falls back to the raw-CSV path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

import methods.depmap_paralog_aggregator.read as R  # noqa: E402


def _product_row(symbol="VPS4A", partner="VPS4B", delta=1.55, ohnolog=True, buffering_class="strong"):
    """A synthetic derived-product row (matches the emitted parquet schema)."""
    top_partners = [
        {
            "partner_symbol": partner,
            "dep_delta_paired_vs_max_single": delta,
            "median_dual_ko_effect": -1.6,
            "single_ko_target": -0.05,
            "single_ko_partner": -0.02,
            "buffering_class": buffering_class,
            "ohnolog_flag": ohnolog,
            "ensembl_lca": None,
        },
        {
            "partner_symbol": "OTHER",
            "dep_delta_paired_vs_max_single": 0.1,
            "median_dual_ko_effect": -0.2,
            "single_ko_target": -0.1,
            "single_ko_partner": 0.0,
            "buffering_class": "none",
            "ohnolog_flag": False,
            "ensembl_lca": None,
        },
    ]
    return {
        "target_gene_symbol": symbol,
        "paralog_buffering_class": buffering_class,
        "n_paralogs_annotated": 2,
        "n_paralogs_buffering": 1,
        "strongest_partner": partner,
        "strongest_delta": delta,
        "top_partners": json.dumps(top_partners),
        "sanger_screen_included": False,
        "method_version": "1.0.0",
    }


def test_primary_path_populates_real_ohnolog(monkeypatch):
    """The product read maps columns → card fields AND populates strongest_paralog_ohnolog
    from the strongest partner's ohnolog_flag (the whole point of materializing the product)."""
    monkeypatch.setattr(R, "_derived_parquet_uri", lambda: "s3://fake/paralog.parquet")
    monkeypatch.setattr(R, "_fetch_derived_row", lambda uri, gene: _product_row())
    res = R.read_target_summary("VPS4A")
    assert res["paralog_buffering_class"] == "strong"
    assert res["strongest_paralog_symbol"] == "VPS4B"
    assert res["strongest_paralog_delta"] == 1.55
    assert res["strongest_paralog_ohnolog"] is True  # POPULATED (not None)
    assert res["_data_source"] == "depmap-paralog-buffering-per-gene-v1"
    # functional_paralogs carry the per-partner ohnolog too
    fp = res["functional_paralogs"][0]
    assert fp["partner_gene_symbol"] == "VPS4B"
    assert fp["ohnolog"] is True


def test_primary_path_non_ohnolog(monkeypatch):
    monkeypatch.setattr(R, "_derived_parquet_uri", lambda: "s3://fake/paralog.parquet")
    monkeypatch.setattr(R, "_fetch_derived_row", lambda uri, gene: _product_row(ohnolog=False))
    res = R.read_target_summary("VPS4A")
    assert res["strongest_paralog_ohnolog"] is False


def test_absent_gene_in_product_is_data_unavailable(monkeypatch):
    """Gene not in the product → data_unavailable (NOT a fallback to raw CSV — the product IS
    reachable, the gene just isn't in it)."""
    monkeypatch.setattr(R, "_derived_parquet_uri", lambda: "s3://fake/paralog.parquet")
    monkeypatch.setattr(R, "_fetch_derived_row", lambda uri, gene: None)
    res = R.read_target_summary("GHOST")
    assert res["paralog_buffering_class"] == "data_unavailable"
    assert res["_data_note"] == "target_not_in_paralog_screens"
    assert res["strongest_paralog_ohnolog"] is None


def test_unreachable_product_falls_back_to_raw_csv(monkeypatch, tmp_path):
    """When the product URI is unresolvable, the reader must FALL BACK to the raw-CSV recompute
    (not crash, not silently return empty). The fallback stamps the raw CSV + ohnolog None."""
    # product unreachable: _derived_parquet_uri returns None
    monkeypatch.setattr(R, "_derived_parquet_uri", lambda: None)
    # provide a synthetic raw CSV for the fallback path
    import csv

    p = tmp_path / "ParalogGeneEffect.csv"
    with p.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ModelID", "GA", "GB", "GA_GB"])
        w.writerow(["ACH-1", 0.0, 0.05, -1.20])
        w.writerow(["ACH-2", 0.02, 0.0, -1.25])
    monkeypatch.setattr(R, "_ensure_paralog_cached", lambda: p)
    R._load_paralog_indexed.cache_clear()
    res = R.read_target_summary("GA")
    assert res["paralog_buffering_class"] == "strong"
    assert "ParalogGeneEffect.csv" in res["_data_source"]  # raw-CSV fallback stamp
    assert res["strongest_paralog_ohnolog"] is None  # no ohnolog on fallback
    R._load_paralog_indexed.cache_clear()


def test_fetch_derived_row_parses_s3_uri(monkeypatch):
    """_fetch_derived_row must split an s3:// URI into (bucket, key) for pyarrow.fs — guard the
    parsing so a URI-format regression is caught without a live read.

    ISOLATION FIX (2026-08-11): `_fetch_derived_row` does `import pyarrow.parquet as pq`, which binds
    `pq = pyarrow.parquet` — an ATTRIBUTE lookup on the pyarrow module, NOT a sys.modules["pyarrow.parquet"]
    lookup. The old test faked only sys.modules, so once ANY earlier test in the session imported real
    pyarrow (setting pyarrow.parquet/pyarrow.fs attributes), the fake was bypassed → real S3 read →
    order-dependent failure. Patch BOTH the attribute and sys.modules, via monkeypatch (auto-reverts)."""
    import methods.depmap_paralog_aggregator.read as RR

    captured = {}

    class _FakeTable:
        num_rows = 0
        column_names: list = []

    import sys
    import types

    fake_pq = types.SimpleNamespace(
        read_table=lambda path, filesystem=None, filters=None: (
            captured.update(path=path, filters=filters) or _FakeTable()
        )
    )
    fake_fs = types.SimpleNamespace(S3FileSystem=lambda: object())
    import pyarrow  # real top-level module; we override its .parquet/.fs submodule attributes

    monkeypatch.setattr(pyarrow, "parquet", fake_pq, raising=False)
    monkeypatch.setattr(pyarrow, "fs", fake_fs, raising=False)
    monkeypatch.setitem(sys.modules, "pyarrow.parquet", fake_pq)
    monkeypatch.setitem(sys.modules, "pyarrow.fs", fake_fs)

    out = RR._fetch_derived_row("s3://onc-compbio/data-catalog/derived/x/p.parquet", "kras")
    assert out is None  # num_rows == 0
    assert captured["path"] == "onc-compbio/data-catalog/derived/x/p.parquet"
    assert captured["filters"] == [("target_gene_symbol", "=", "KRAS")]  # upper-cased
