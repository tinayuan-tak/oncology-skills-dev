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

import pytest

import onc_methods.depmap_paralog_aggregator.read as R


@pytest.fixture
def certified_product(monkeypatch):
    """Certify the derived product as built under the CURRENT delta definition.

    _read_from_derived_product gates on _product_delta_definition_matches() before anything else
    (2026-09-12): a product built under the superseded max()-baseline delta must not be preferred
    over the corrected live recompute. Without this stub these product-MAPPING tests silently fall
    through to the raw-CSV path — and because that path reads the real ~/.cache, they were passing
    or failing on LIVE DepMap numbers rather than on the synthetic row they set up.
    """
    monkeypatch.setattr(R, "_product_delta_definition_matches", lambda: True)


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


def test_primary_path_populates_real_ohnolog(monkeypatch, certified_product):
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
    # single_ko_effect = the STRONGEST single of the PAIR (min on the Chronos scale), i.e. the
    # baseline the product's delta was measured against — was single_ko_target (-0.05), which
    # disagreed with the raw-CSV path and left the delta unverifiable from the record.
    assert fp["single_ko_effect"] == -0.05  # min(-0.05 target, -0.02 partner)


def test_primary_path_non_ohnolog(monkeypatch, certified_product):
    monkeypatch.setattr(R, "_derived_parquet_uri", lambda: "s3://fake/paralog.parquet")
    monkeypatch.setattr(R, "_fetch_derived_row", lambda uri, gene: _product_row(ohnolog=False))
    res = R.read_target_summary("VPS4A")
    assert res["strongest_paralog_ohnolog"] is False


def test_absent_gene_in_product_is_data_unavailable(monkeypatch, certified_product):
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


# --- The staleness gate (2026-09-12) -----------------------------------------------------------


def test_stale_product_definition_forces_the_live_recompute(monkeypatch, tmp_path):
    """A product whose manifest still declares the SUPERSEDED max()-baseline delta must NOT be
    served: the reader falls back to the corrected live recompute instead.

    Without this gate, fixing the arithmetic would have been cosmetic — the PREFERRED path serves
    `dep_delta_paired_vs_max_single` PRE-COMPUTED from the parquet, so the inflated v1 deltas would
    have kept flowing while only the (rarely-taken) fallback was corrected.
    """
    monkeypatch.setattr(R, "_product_delta_definition_matches", lambda: False)
    monkeypatch.setattr(R, "_derived_parquet_uri", lambda: "s3://fake/paralog.parquet")
    monkeypatch.setattr(R, "_fetch_derived_row", lambda uri, gene: pytest.fail("stale product must not be fetched"))
    import csv

    csv_path = tmp_path / "ParalogGeneEffect.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ModelID", "GA", "GB", "GA_GB"])
        w.writerow(["ACH-1", 0.0, 0.05, -1.20])
        w.writerow(["ACH-2", 0.02, 0.0, -1.25])
    monkeypatch.setattr(R, "_ensure_paralog_cached", lambda: csv_path)
    R._load_paralog_indexed.cache_clear()
    res = R.read_target_summary("GA")
    assert "ParalogGeneEffect.csv" in res["_data_source"]  # the live recompute, not the product
    R._load_paralog_indexed.cache_clear()


def test_delta_definition_gate_matches_on_the_token_and_fails_closed(monkeypatch):
    """The gate is a substring check on the manifest's parameters.delta_definition, and ANY read
    failure fails CLOSED (unreadable manifest → cannot certify → treat as stale)."""
    import onc_methods.catalog_query.read as CQ

    monkeypatch.setattr(
        CQ, "load_manifest", lambda mid: {"parameters": {"delta_definition": R._DELTA_DEFINITION_TOKEN + " (x)"}}
    )
    assert R._product_delta_definition_matches() is True
    # the SUPERSEDED v1 string must not certify
    monkeypatch.setattr(
        CQ,
        "load_manifest",
        lambda mid: {
            "parameters": {"delta_definition": "max(single_a, single_b) - median_dual_ko (positive = buffering)"}
        },
    )
    assert R._product_delta_definition_matches() is False
    monkeypatch.setattr(CQ, "load_manifest", lambda mid: {})  # no parameters block
    assert R._product_delta_definition_matches() is False

    def _boom(mid):
        raise RuntimeError("manifest unreadable")

    monkeypatch.setattr(CQ, "load_manifest", _boom)
    assert R._product_delta_definition_matches() is False  # fail-closed


def test_fetch_derived_row_parses_s3_uri(monkeypatch):
    """_fetch_derived_row must split an s3:// URI into (bucket, key) for pyarrow.fs — guard the
    parsing so a URI-format regression is caught without a live read.

    ISOLATION FIX (2026-08-11): `_fetch_derived_row` does `import pyarrow.parquet as pq`, which binds
    `pq = pyarrow.parquet` — an ATTRIBUTE lookup on the pyarrow module, NOT a sys.modules["pyarrow.parquet"]
    lookup. The old test faked only sys.modules, so once ANY earlier test in the session imported real
    pyarrow (setting pyarrow.parquet/pyarrow.fs attributes), the fake was bypassed → real S3 read →
    order-dependent failure. Patch BOTH the attribute and sys.modules, via monkeypatch (auto-reverts)."""
    import onc_methods.depmap_paralog_aggregator.read as RR

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
