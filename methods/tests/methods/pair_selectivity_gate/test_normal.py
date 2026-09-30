"""Tests for pair_selectivity_gate.normal — the normal-tissue selectivity gate + support floor.

Synthetic cube + monkeypatched _read_normal_cube (the repo idiom); no S3."""

import pandas as pd

import onc_methods.pair_selectivity_gate.normal as N


def _cube(rows):
    cols = [
        "gene_a",
        "gene_b",
        "tissue",
        "cell_type",
        "dataset_id",
        "donor_id",
        "n_cells",
        "both_fraction",
        "enrichment_vs_independence",
    ]
    return pd.DataFrame(rows, columns=cols)


def _patch(monkeypatch, cube):
    monkeypatch.setattr(N, "_read_normal_cube", lambda *a, **k: cube)


def _row(ct, ds, donor, n_cells, both, a="FOLR1", b="MSLN", tissue="kidney", enr=1.0):
    return [a, b, tissue, ct, ds, donor, n_cells, both, enr]


def test_floor_excludes_1cell_noise_group(monkeypatch):
    # Well-powered group (3 donors, 75 cells, median both 0.35) + a 1-cell noise group (both=1.0).
    rows = [
        _row("epithelial cell", "D", "d1", 20, 0.30),
        _row("epithelial cell", "D", "d2", 30, 0.35),
        _row("epithelial cell", "D", "d3", 25, 0.40),
        _row("enterocyte", "D", "dx", 1, 1.0),  # mislabel noise — must NOT drive normal_max_both
    ]
    _patch(monkeypatch, _cube(rows))
    r = N.normal_max_both("FOLR1", "MSLN")
    assert r["normal_max_both_fraction"] == 0.35  # NOT 1.0
    assert r["normal_liability_locus"]["cell_type"] == "epithelial cell"
    assert r["n_groups_evaluated"] == 2
    assert r["n_groups_passed_floor"] == 1
    assert r["normal_selectivity_class"] == "normal_liability"  # 0.35 >= 0.10


def test_order_insensitive(monkeypatch):
    rows = [_row("ct", "D", f"d{i}", 15, 0.05) for i in range(3)]
    _patch(monkeypatch, _cube(rows))
    assert N.normal_max_both("MSLN", "FOLR1")["normal_max_both_fraction"] == 0.05  # B:A == A:B


def test_selectivity_clean_low_both(monkeypatch):
    rows = [_row("ct", "D", f"d{i}", 20, 0.01) for i in range(4)]
    _patch(monkeypatch, _cube(rows))
    r = N.normal_max_both("FOLR1", "MSLN")
    assert r["normal_selectivity_class"] == "selectivity_clean"  # <= 0.02
    assert r["normal_max_both_fraction"] == 0.01


def test_under_powered_when_all_groups_thin(monkeypatch):
    # two groups, each only 2 donors -> below the 3-donor floor -> under_powered (NOT clean)
    rows = [
        _row("ct1", "D", "d1", 50, 0.9),
        _row("ct1", "D", "d2", 50, 0.9),
        _row("ct2", "D", "d1", 50, 0.8),
        _row("ct2", "D", "d2", 50, 0.8),
    ]
    _patch(monkeypatch, _cube(rows))
    r = N.normal_max_both("FOLR1", "MSLN")
    assert r["normal_selectivity_class"] == "under_powered"
    assert r["normal_max_both_fraction"] is None
    assert r["n_groups_passed_floor"] == 0
    assert "under-powered" in r["_data_note"].lower()


def test_low_cells_group_excluded(monkeypatch):
    # 3 donors but only 9 cells total -> below the 10-cell floor
    rows = [_row("ct", "D", "d1", 3, 0.9), _row("ct", "D", "d2", 3, 0.9), _row("ct", "D", "d3", 3, 0.9)]
    _patch(monkeypatch, _cube(rows))
    assert N.normal_max_both("FOLR1", "MSLN")["normal_selectivity_class"] == "under_powered"


def test_pair_absent_is_data_unavailable(monkeypatch):
    _patch(monkeypatch, _cube([_row("ct", "D", "d1", 20, 0.3, a="EPCAM", b="CEACAM5")]))
    r = N.normal_max_both("FOLR1", "MSLN")
    assert r["normal_selectivity_class"] == "data_unavailable"
    assert "not scanned" in r["_data_note"]


def test_cube_unreadable_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(N, "_read_normal_cube", lambda *a, **k: None)
    assert N.normal_max_both("FOLR1", "MSLN")["normal_selectivity_class"] == "data_unavailable"


def test_normal_manifest_resolves_in_catalog():
    # wiring smoke (offline — reads local data-catalog YAML): the manifest id resolves to its parquet.
    from onc_methods.catalog_query.read import s3_uri_for

    uri = s3_uri_for(N.NORMAL_SAMECELL_MANIFEST)
    assert uri.startswith("s3://") and uri.endswith("sc_samecell_coexpr.parquet")
    assert "sc-samecell-coexpr-normal-v1" in uri


def test_target_centric_headline_is_worst_partner(monkeypatch):
    # FOLR1 with two partners: MSLN clean (0.01), MUC16 liability (0.4). Headline = worst (MUC16).
    rows = [_row("ct", "D", f"d{i}", 20, 0.01, a="FOLR1", b="MSLN") for i in range(3)] + [
        _row("ct", "D", f"e{i}", 20, 0.40, a="FOLR1", b="MUC16") for i in range(3)
    ]
    _patch(monkeypatch, _cube(rows))
    r = N.read_target_normal_selectivity("FOLR1")
    assert r["n_partners_tested"] == 2
    assert r["worst_partner"] == "MUC16"
    assert r["worst_normal_max_both"] == 0.40
    assert r["normal_selectivity_class"] == "normal_liability"
