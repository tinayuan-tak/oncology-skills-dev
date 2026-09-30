"""Pure-logic acceptance tests for pathway_node_leverage._classify — no S3 / no live data.

Guards the load-bearing INVARIANTS of the comparative node-leverage verdict (spec §2/§4), at the
LOGIC level rather than tuning to any single live example (the node-set is inherently noisy; the
verdict RULE is what must be pinned):

  1. TRACTABILITY-YIELD (the invariant the reviewer asked to guard): a target dominated on dependency
     by a LESS-tractable node is NOT down-ranked to `dominated_node` — it reads
     `dominated_but_tractability_edge` (the target is the tractable entry point). Only a stronger
     AND >=-as-tractable node yields `dominated_node`.
  2. NOISE-SEPARATION: a nominally-stronger node within MIN_SEP median-Chronos is treated as
     indistinguishable (not counted as stronger).
  3. dominant / weak / not-screenable base cases.

Plus a coverage-regression guard on the INDICATION_LINEAGE map (PAAD must resolve to the Pancreas
DepMap lineage — the confirmed gap that silently forced pancreatic targets to pan-lineage).
"""

from __future__ import annotations

import pandas as pd
import pytest

import onc_methods.pathway_node_leverage.cli as C


def _stats(rows):
    """Build a stats DataFrame matching what _stats() emits, sorted by median_chronos (as _stats does).
    rows: list of (gene, median_chronos, tdl). frac_dependent/n are filled with placeholders; trank is
    derived from tdl exactly as _stats does."""
    df = pd.DataFrame(
        [
            {
                "gene": g,
                "median_chronos": m,
                "frac_dependent": 0.2,
                "n": 100,
                "tdl": tdl,
                "trank": C._TDL_RANK.get(tdl, 9),
            }
            for g, m, tdl in rows
        ]
    )
    return df.sort_values("median_chronos").reset_index(drop=True)


def test_tractability_edge_not_downranked():
    # target dependent (below floor), Tclin; a STRONGER but UNDRUGGABLE (Tdark) competitor exists.
    stats = _stats([("TGT", -0.8, "Tclin"), ("STRONGER_UNDRUGGABLE", -1.2, "Tdark")])
    out = C._classify("TGT", stats)
    assert out["verdict"] == "dominated_but_tractability_edge", out
    assert out["n_stronger"] == 1
    assert out["n_stronger_tractable"] == 0  # the stronger node is LESS tractable -> no edge lost


def test_dominated_node_when_stronger_is_at_least_as_tractable():
    # same, but the stronger competitor is ALSO Tclin (>= as tractable) -> genuinely dominated.
    stats = _stats([("TGT", -0.8, "Tclin"), ("STRONGER_DRUGGABLE", -1.2, "Tclin")])
    out = C._classify("TGT", stats)
    assert out["verdict"] == "dominated_node", out
    assert out["n_stronger_tractable"] == 1
    assert out["dominant_competitors"][0]["gene"] == "STRONGER_DRUGGABLE"


def test_dominant_node_when_target_is_strongest():
    stats = _stats([("TGT", -1.1, "Tchem"), ("WEAKER", -0.3, "Tclin")])
    out = C._classify("TGT", stats)
    assert out["verdict"] == "dominant_node", out
    assert out["n_stronger"] == 0


def test_noise_separation_gate():
    # competitor is nominally more-dependent but WITHIN MIN_SEP -> not counted as stronger.
    stats = _stats([("TGT", -0.8, "Tchem"), ("NEAR", -0.8 - (C.MIN_SEP / 2), "Tclin")])
    out = C._classify("TGT", stats)
    assert out["n_stronger"] == 0
    assert out["verdict"] == "dominant_node", out  # target below floor + nothing separably stronger


def test_weak_and_uncontested_above_floor():
    # target ABOVE the dependency floor and nothing dominates it.
    stats = _stats([("TGT", -0.2, "Tchem"), ("ALSO_WEAK", -0.1, "Tclin")])
    out = C._classify("TGT", stats)
    assert out["verdict"] == "weak_and_uncontested", out


def test_target_not_screenable_when_absent():
    stats = _stats([("OTHER", -1.0, "Tclin")])
    out = C._classify("TGT", stats)
    assert out["verdict"] == "target_not_screenable", out


def test_paad_maps_to_pancreas_lineage():
    from onc_methods.depmap_chronos.cli import INDICATION_LINEAGE

    assert INDICATION_LINEAGE.get("PAAD") == "Pancreas"
    assert INDICATION_LINEAGE.get("PDAC") == "Pancreas"  # disease-abbrev alias still present


# --- PPI lens (BioGRID interactors) + report-only headline exclusion --------------------------------
def test_ppi_node_set_caps_top_n_and_includes_target(monkeypatch):
    # 30 partners with descending publication evidence; the lens keeps the top PPI_TOP_N by n_publications.
    n = 30
    df = pd.DataFrame(
        {
            "gene_symbol": ["TGT"] * n,
            "partner_symbol": [f"P{i:02d}" for i in range(n)],
            "n_publications": list(range(n, 0, -1)),  # P00 highest evidence ... P29 lowest
        }
    )
    monkeypatch.setattr(C, "_get", lambda key: b"")  # bytes unused (read_parquet patched below)
    monkeypatch.setattr(C.pd, "read_parquet", lambda *a, **k: df)
    ns = C._ppi_node_sets("TGT")
    assert len(ns) == 1
    members = ns[0]["members"]
    assert "TGT" in members  # target always retained
    assert len(members) == C.PPI_TOP_N + 1  # top-N partners + the target
    assert "P00" in members and "P29" not in members  # best-evidenced kept, weakest dropped


def test_ppi_lens_fails_soft_on_read_error(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(C, "_get", _boom)
    assert C._ppi_node_sets("TGT") == []  # never propagates → headline lenses survive


def test_headline_excludes_report_only_ppi_lens():
    # complex says dominant_node; ppi (report-only) says dominated_node. Headline must follow the
    # CURATED lenses (dominant_node), NOT be dragged to dominated by the interaction hairball.
    lenses = {
        "complex": [{"verdict": "dominant_node"}],
        "pathway": [],
        "ppi": [{"verdict": "dominated_node"}],
    }
    assert C._headline_class(lenses) == "dominant_node"
    # sanity: without the ppi exclusion the worst-across-all would have been dominated_node
    assert C._HEADLINE_ORDER["dominated_node"] < C._HEADLINE_ORDER["dominant_node"]


# --- paralog / combinatorial correction (single_ko_leverage_understated) ----------------------------
@pytest.mark.parametrize(
    "cls,understated",
    [
        ("strong", True),
        ("partial", True),
        ("none", False),
        ("data_unavailable", False),
    ],
)
def test_buffering_flag_maps_class_to_understated(monkeypatch, cls, understated):
    monkeypatch.setattr(
        C,
        "_read_paralog_buffering",
        lambda target=None: {"paralog_buffering_class": cls, "strongest_paralog_symbol": "PARA1"},
    )
    out = C._paralog_buffering("TGT")
    assert out["paralog_buffering_class"] == cls
    assert out["single_ko_leverage_understated"] is understated
    # strongest paralog is carried through only as context (present regardless of class here)
    assert out["strongest_buffering_paralog"] == "PARA1"


def test_buffering_flag_fails_soft_on_reader_error(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("paralog product unreachable")

    monkeypatch.setattr(C, "_read_paralog_buffering", _boom)
    out = C._paralog_buffering("TGT")  # must NOT propagate
    assert out["paralog_buffering_class"] == "data_unavailable"
    assert out["single_ko_leverage_understated"] is False
    assert out["strongest_buffering_paralog"] == ""


# --- Chronos column-projection (perf: no 563 MB whole-CSV download) ---------------------------------
def _install_fake_chronos_parquet(monkeypatch, values):
    """Install a fake CRISPRGeneEffect.parquet: columns are 'GENE (entrez)', rows are ModelIDs.
    `values`: {bare_symbol: {ModelID: score}}. Returns a list that captures each `columns` projection
    passed to _stream_table, so a test can assert ONLY the requested genes (not the ~18k-col matrix)
    transit the wire."""
    import pyarrow as pa

    entrez = {g: 1000 + i for i, g in enumerate(values)}
    parquet_cols = {f"{g} ({entrez[g]})": col for g, col in values.items()}
    model_ids = sorted({m for col in values.values() for m in col})
    schema = ("ModelID", *parquet_cols.keys())
    requested = []

    def fake_stream_table(uri, columns=None, filters=None):
        requested.append(tuple(columns) if columns else None)
        data = {"ModelID": model_ids}
        for c in columns:
            if c != "ModelID":
                data[c] = [parquet_cols[c].get(m) for m in model_ids]
        return pa.Table.from_pydict(data)

    monkeypatch.setattr(C, "_remote_uri", lambda *a, **k: "onc-compbio/x/CRISPRGeneEffect.parquet")
    monkeypatch.setattr(C, "_remote_schema_names", lambda uri: schema)
    monkeypatch.setattr(C, "_stream_table", fake_stream_table)
    C._chronos_parquet_meta.cache_clear()
    return requested


def test_chronos_subframe_column_projects_and_returns_bare_symbols(monkeypatch):
    requested = _install_fake_chronos_parquet(
        monkeypatch,
        {
            "TGT": {"ACH-1": -1.0, "ACH-2": -0.9},
            "NBR": {"ACH-1": -0.2, "ACH-2": -0.3},
            "OFF": {"ACH-1": 0.1, "ACH-2": 0.0},  # never requested -> must not transit
        },
    )
    sub = C._chronos_subframe({"TGT", "NBR"})
    assert set(sub.columns) == {"TGT", "NBR"}  # bare symbols, only requested genes
    assert sub.index.name == "ModelID"
    assert sub.loc["ACH-1", "TGT"] == -1.0
    cols = requested[0]  # exactly ModelID + the two requested genes
    assert cols is not None and "ModelID" in cols
    assert not any("OFF" in c for c in cols)
    assert len([c for c in cols if c != "ModelID"]) == 2


def test_chronos_subframe_falls_back_to_csv_on_parquet_error(monkeypatch):
    monkeypatch.setattr(C, "_remote_uri", lambda *a, **k: "onc-compbio/x/CRISPRGeneEffect.parquet")
    monkeypatch.setattr(C, "_remote_schema_names", lambda uri: ("ModelID", "TGT (1)", "NBR (2)"))
    C._chronos_parquet_meta.cache_clear()

    def _boom(*a, **k):
        raise RuntimeError("parquet product unreachable")

    monkeypatch.setattr(C, "_stream_table", _boom)
    csv = pd.DataFrame({"TGT": [-1.0, -0.9], "NBR": [-0.2, -0.3]}, index=["ACH-1", "ACH-2"])
    monkeypatch.setattr(C, "_chronos", lambda: csv)
    sub = C._chronos_subframe({"TGT", "NBR"})  # parquet error -> whole-CSV slice
    assert set(sub.columns) == {"TGT", "NBR"}
    assert sub.loc["ACH-2", "NBR"] == -0.3


def test_stats_identical_parquet_vs_csv_fallback(monkeypatch):
    # The pushdown read must produce byte-identical _stats to the whole-CSV slice it replaces.
    models = [f"ACH-{i}" for i in range(8)]
    tgt = {m: -1.0 - 0.01 * i for i, m in enumerate(models)}
    nbr = {m: -0.3 + 0.01 * i for i, m in enumerate(models)}
    monkeypatch.setattr(C, "_tdl", lambda: {})  # deterministic offline (no live TDL/common-ess)
    monkeypatch.setattr(C, "_common_essentials", lambda: frozenset())

    _install_fake_chronos_parquet(monkeypatch, {"TGT": tgt, "NBR": nbr})
    via_parquet = C._stats(["NBR"], "TGT", None).reset_index(drop=True)

    def _boom(*a, **k):
        raise RuntimeError("force CSV path")

    monkeypatch.setattr(C, "_stream_table", _boom)
    C._chronos_parquet_meta.cache_clear()
    csv = pd.DataFrame({"TGT": [tgt[m] for m in models], "NBR": [nbr[m] for m in models]}, index=models)
    monkeypatch.setattr(C, "_chronos", lambda: csv)
    via_csv = C._stats(["NBR"], "TGT", None).reset_index(drop=True)

    pd.testing.assert_frame_equal(via_parquet, via_csv)
