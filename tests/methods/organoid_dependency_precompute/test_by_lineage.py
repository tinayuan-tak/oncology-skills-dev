"""Per-lineage organoid dependency: producer compute on a synthetic matrix + reader enrichment
(indication → organoid lineage). No S3 — the reader's _lineage_rows is monkeypatched."""
import importlib.util
from pathlib import Path

import pandas as pd
import pytest

_MOD = Path(__file__).resolve().parents[3] / "methods" / "organoid_dependency_precompute"


def _load(name):
    spec = importlib.util.spec_from_file_location(f"organoid_{name}", _MOD / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---- producer: per-lineage rollup + cohort-floor gating ----
def _matrix_and_model(tmp_path):
    # 6 models across 2 big lineages (Bowel x3, Pancreas x3) + 1 tiny (Lung x1, below floor=... use 5)
    idx = ["ACH-1", "ACH-2", "ACH-3", "ACH-4", "ACH-5", "ACH-6", "ACH-7"]
    df = pd.DataFrame({
        # KRASlike: dependent in Bowel (all < -0.5), not in Pancreas
        "KRASlike (1)": [-1.2, -0.9, -0.8, -0.1, 0.0, -0.2, -1.5],
        "ESS (2)":      [-1.5, -1.6, -1.2, -1.1, -1.3, -1.4, -2.0],
    }, index=idx)
    p = tmp_path / "OrganoidGeneEffect.csv"; df.to_csv(p)
    model = pd.DataFrame({
        "ModelID": idx,
        "OncotreeLineage": ["Bowel", "Bowel", "Bowel", "Pancreas", "Pancreas", "Pancreas", "Lung"],
    })
    mp = tmp_path / "Model.csv"; model.to_csv(mp, index=False)
    return str(p), str(mp)


def test_by_lineage_gates_small_cohorts_and_counts(tmp_path, monkeypatch):
    b = _load("build_by_lineage")
    monkeypatch.setattr(b, "MIN_LINEAGE_COHORT", 3)  # admit Bowel(3)+Pancreas(3), drop Lung(1)
    mtx, mdl = _matrix_and_model(tmp_path)
    out = b.build(mtx, mdl)
    assert set(out["lineage"].unique()) == {"Bowel", "Pancreas"}  # Lung (n=1) dropped
    bowel_kras = out[(out.gene_symbol == "KRASlike") & (out.lineage == "Bowel")].iloc[0]
    panc_kras = out[(out.gene_symbol == "KRASlike") & (out.lineage == "Pancreas")].iloc[0]
    assert bowel_kras["frac_dependent"] == pytest.approx(1.0)   # 3/3 < -0.5
    assert panc_kras["frac_dependent"] == pytest.approx(0.0)    # 0/3 < -0.5
    assert bowel_kras["n_lineage_cohort"] == 3


# ---- reader: indication → lineage enrichment ----
def _lin_rows():
    return (
        {"lineage": "Bowel", "n_lineage_cohort": 22, "n_models_screened": 22, "n_dependent": 21,
         "frac_dependent": 0.955, "n_strongly_dependent": 15, "median_gene_effect": -1.1},
        {"lineage": "Pancreas", "n_lineage_cohort": 23, "n_models_screened": 23, "n_dependent": 19,
         "frac_dependent": 0.826, "n_strongly_dependent": 12, "median_gene_effect": -0.9},
    )


def _summary_row():
    # matches _organoid_row tuple order in lookup.py
    return ("3845", 114, 85, 51, 0.746, 0.447, -0.85, -0.87, -2.6, 94.4, 114, 18159)


def test_reader_surfaces_indication_lineage(monkeypatch):
    lk = _load("lookup")
    monkeypatch.setattr(lk, "_organoid_row", lambda s: _summary_row())
    monkeypatch.setattr(lk, "_lineage_rows", lambda s: _lin_rows())
    out = lk.build_summary("KRAS", "COADREAD")   # COADREAD → Bowel
    assert out["organoid_lineage"] == "Bowel"
    assert out["organoid_lineage_frac_dependent"] == pytest.approx(0.955)
    assert out["organoid_lineage_class"] == "pan_organoid_essential"  # 0.955 >= 0.90
    assert out["organoid_lineage_n_screened"] == 22
    # per_lineage_stats present + sorted by frac_dependent desc
    assert [r["lineage"] for r in out["per_lineage_stats"]] == ["Bowel", "Pancreas"]
    assert out["n_lineages_evaluated"] == 2
    # pan-organoid class unchanged (additive)
    assert out["organoid_dependency_class"] == "broad_organoid_dependency"


def test_reader_unmapped_indication_leaves_lineage_null(monkeypatch):
    lk = _load("lookup")
    monkeypatch.setattr(lk, "_organoid_row", lambda s: _summary_row())
    monkeypatch.setattr(lk, "_lineage_rows", lambda s: _lin_rows())
    out = lk.build_summary("KRAS", "SKCM")   # melanoma → no organoid lineage
    assert out["organoid_lineage"] is None
    assert out["organoid_lineage_frac_dependent"] is None
    assert out["per_lineage_stats"]  # per_lineage_stats still populated (target-only view)


def test_reader_gc_maps_to_esophagus_stomach_lineage(monkeypatch):
    # 'GC' (HCMI gastric code) must map to the Esophagus/Stomach organoid lineage — previously
    # omitted, so GC silently returned None lineage fields though the cohort exists. (TR-01 fix)
    lk = _load("lookup")
    gc_rows = (
        {"lineage": "Esophagus/Stomach", "n_lineage_cohort": 18, "n_models_screened": 18,
         "n_dependent": 10, "frac_dependent": 0.556, "n_strongly_dependent": 6,
         "median_gene_effect": -0.6},
    )
    monkeypatch.setattr(lk, "_organoid_row", lambda s: _summary_row())
    monkeypatch.setattr(lk, "_lineage_rows", lambda s: gc_rows)
    out = lk.build_summary("KRAS", "GC")
    assert out["organoid_lineage"] == "Esophagus/Stomach"
    assert out["organoid_lineage_frac_dependent"] == pytest.approx(0.556)
    assert out["organoid_lineage_class"] == "broad_organoid_dependency"  # 0.556 >= 0.50
    assert out["organoid_lineage_n_screened"] == 18


def test_reader_no_lineage_product_still_returns_summary(monkeypatch):
    lk = _load("lookup")
    monkeypatch.setattr(lk, "_organoid_row", lambda s: _summary_row())
    monkeypatch.setattr(lk, "_lineage_rows", lambda s: ())   # by-lineage product unavailable
    out = lk.build_summary("KRAS", "PAAD")
    assert out["organoid_dependency_class"] == "broad_organoid_dependency"  # pan-organoid intact
    assert out["per_lineage_stats"] == [] and out["organoid_lineage"] is None
