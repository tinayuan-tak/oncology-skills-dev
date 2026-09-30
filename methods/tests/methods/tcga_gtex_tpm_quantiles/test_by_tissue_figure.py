"""tcga_gtex_tpm_quantiles.read — by-tissue tumor-vs-normal distribution figure emitters.

The figure co-plots TCGA tumor (per study) + GTEx normal (per tissue) on ONE log2(TPM+1) axis,
drawn from the precomputed five-number-summary product via ax.bxp / plotly precomputed boxes (no
per-sample scan). Tests (no S3 — read_pan_cancer_by_tissue monkeypatched to synthetic quantile
rows) pin: the whisker fence clamps to [min,max]; both sources co-plot; SVG + plot_data + plotly
emit; the plotly box uses precomputed q1/median/q3 (no drift, no raw samples); absent gene degrades.
"""

from __future__ import annotations

import importlib
import json
import tempfile
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")


r = importlib.import_module("onc_methods.tcga_gtex_tpm_quantiles.read")


def _rows(recs):
    return pd.DataFrame(recs)


# GENEA: tumor high in GBM (median 11), lower in COAD (6); normal moderate in BRAIN (8), low COLON (2)
_RECS = [
    {
        "gene_symbol": "GENEA",
        "ensembl_gene_id": "ENSG1",
        "source": "tcga_tumor",
        "group": "GBM",
        "n": 157,
        "min": 8.0,
        "q1": 10.3,
        "median": 11.0,
        "q3": 11.8,
        "max": 13.0,
        "mean": 11.0,
    },
    {
        "gene_symbol": "GENEA",
        "ensembl_gene_id": "ENSG1",
        "source": "tcga_tumor",
        "group": "COAD",
        "n": 503,
        "min": 2.0,
        "q1": 5.0,
        "median": 6.0,
        "q3": 7.0,
        "max": 9.0,
        "mean": 6.0,
    },
    {
        "gene_symbol": "GENEA",
        "ensembl_gene_id": "ENSG1",
        "source": "gtex_normal",
        "group": "BRAIN",
        "n": 2931,
        "min": 5.0,
        "q1": 7.0,
        "median": 8.0,
        "q3": 9.0,
        "max": 11.0,
        "mean": 8.0,
    },
    {
        "gene_symbol": "GENEA",
        "ensembl_gene_id": "ENSG1",
        "source": "gtex_normal",
        "group": "COLON",
        "n": 300,
        "min": 0.0,
        "q1": 1.0,
        "median": 2.0,
        "q3": 3.0,
        "max": 4.0,
        "mean": 2.0,
    },
]


def _patch(monkeypatch, recs):
    monkeypatch.setattr(r, "read_pan_cancer_by_tissue", lambda target: _rows(recs) if recs else _rows([]))


def test_bxp_stat_fence_clamps_to_min_max():
    # IQR = q3-q1 = 4; 1.5*IQR fence = q1-6 .. q3+6 = well beyond [min,max] → clamp to min,max
    row = {"q1": 5.0, "median": 6.0, "q3": 9.0, "min": 2.0, "max": 10.0}
    st = r._bxp_stat(row, "COAD")
    assert st["whislo"] == 2.0 and st["whishi"] == 10.0  # clamped to observed extremes
    # a tight-IQR case where the fence is INSIDE [min,max] → fence wins
    row2 = {"q1": 5.0, "median": 6.0, "q3": 5.5, "min": -100.0, "max": 100.0}
    st2 = r._bxp_stat(row2, "X")
    assert st2["whislo"] > -100.0 and st2["whishi"] < 100.0


def test_ordered_rows_sorted_by_median_desc(monkeypatch):
    _patch(monkeypatch, _RECS)
    df = r.read_pan_cancer_by_tissue("GENEA")
    tumor, normal = r._ordered_rows(df)
    assert [t["group"] for t in tumor] == ["GBM", "COAD"]  # 11 before 6
    assert [n["group"] for n in normal] == ["BRAIN", "COLON"]  # 8 before 2


def test_svg_and_plot_data_emitted(monkeypatch):
    _patch(monkeypatch, _RECS)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        p = r.emit_by_tissue_distribution("GENEA", out)
        assert p.name == "figure_pan_cancer_by_tissue_distribution.svg" and p.exists()
        pdp = r.emit_plot_data("GENEA", out)
        got = pd.read_parquet(pdp)
        assert len(got) == 4 and set(got["source"]) == {"tcga_tumor", "gtex_normal"}


def test_plotly_precomputed_boxes_no_raw_samples(monkeypatch):
    pytest.importorskip("plotly")
    _patch(monkeypatch, _RECS)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        specs = r.emit_plotly_specs("GENEA", out)
        assert [s["id"] for s in specs] == ["pan_cancer_by_tissue_distribution"]
        obj = json.loads((out / specs[0]["path"]).read_text())
        names = {t.get("name") for t in obj["data"]}
        assert names == {"TCGA tumor", "GTEx normal"}
        for t in obj["data"]:
            assert t["type"] == "box"
            # precomputed-box fields present; NO raw per-sample x/y values
            assert "median" in t and "q1" in t and "q3" in t
            assert "x" not in t or not t.get("x")
        tumor = [t for t in obj["data"] if t["name"] == "TCGA tumor"][0]
        assert 11.0 in list(tumor["median"])  # GBM median carried through


def test_absent_gene_degrades(monkeypatch):
    _patch(monkeypatch, [])
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        p = r.emit_by_tissue_distribution("GHOST", out)  # placeholder SVG, no crash
        assert p.exists()
        assert r.emit_plotly_specs("GHOST", out) == []
