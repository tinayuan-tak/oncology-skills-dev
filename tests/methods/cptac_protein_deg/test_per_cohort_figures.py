"""Per-cohort CPTAC protein tumor-vs-normal DISTRIBUTION figures.

Upgraded 2026-07-22: the per-SAMPLE product (cptac-protein-tumor-vs-normal-per-sample-v1) persists
the per-aliquot log-ratios, so the figure is now a true grouped tumor-vs-normal BOXPLOT per cohort
with per-cohort statistics (Welch + Mann-Whitney) recomputed FROM THE SAMPLES — not a median-only
dumbbell. Tests (no S3 — read_per_sample monkeypatched to synthetic per-aliquot rows) pin:
per_cohort_distribution_stats computes quartiles + p-values + delta and sorts by delta desc; the SVG
+ plot_data + plotly emit; the plotly box traces carry the SAME per-aliquot values (no drift); a
target absent from every cohort degrades gracefully; a cohort with <3 samples/side keeps its box but
reports p=None.
"""
from __future__ import annotations

import importlib
import json
import sys
import tempfile
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

r = importlib.import_module("methods.cptac_protein_deg.read")


def _per_sample_df(spec):
    """spec: {cohort: (tumor_values, normal_values)} -> long per-aliquot DataFrame."""
    recs = []
    for cohort, (tvals, nvals) in spec.items():
        for j, v in enumerate(tvals):
            recs.append({"gene_symbol": "EGFR", "cohort": cohort,
                         "aliquot_submitter_id": f"{cohort}-T{j}", "sample_type": "Primary Tumor",
                         "condition": "Tumor", "log2_ratio": float(v)})
        for j, v in enumerate(nvals):
            recs.append({"gene_symbol": "EGFR", "cohort": cohort,
                         "aliquot_submitter_id": f"{cohort}-N{j}", "sample_type": "Solid Tissue Normal",
                         "condition": "Normal", "log2_ratio": float(v)})
    return pd.DataFrame(recs)


# BRCA: tumor clearly elevated (delta ~ +2). COAD: essentially flat (delta ~ 0).
_SPEC = {
    "BRCA": ([5.0, 5.2, 5.4, 5.1, 5.3, 4.9], [3.2, 3.4, 3.1, 3.5, 3.3, 3.6]),
    "COAD": ([4.0, 4.1, 3.9, 4.2, 4.0, 3.8], [4.0, 3.9, 4.1, 4.0, 3.8, 4.2]),
}


def _patch(monkeypatch, spec):
    df = _per_sample_df(spec)
    monkeypatch.setattr(r, "read_per_sample",
                        lambda target: df[df["gene_symbol"] == target.upper()].copy())
    # per_cohort_distribution_stats is @lru_cache'd (retrieval-opt #5) — clear it between tests so a
    # prior test's patched data doesn't return a stale cached result for the same target.
    r.per_cohort_distribution_stats.cache_clear()


def test_distribution_stats_sorted_by_delta_desc(monkeypatch):
    _patch(monkeypatch, _SPEC)
    stats = r.per_cohort_distribution_stats("EGFR")
    assert [s["cohort"] for s in stats] == ["BRCA", "COAD"]      # delta desc: +2 before ~0
    brca = stats[0]
    assert brca["n_tumor"] == 6 and brca["n_normal"] == 6
    assert brca["delta_median"] > 1.5                            # clearly elevated
    assert brca["mwu_p"] is not None and brca["mwu_p"] < 0.05    # significant
    assert brca["welch_p"] is not None
    # COAD flat → not significant
    assert stats[1]["mwu_p"] is None or stats[1]["mwu_p"] > 0.05


def test_boxplot_svg_and_plot_data_emitted(monkeypatch):
    _patch(monkeypatch, _SPEC)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        p = r.emit_per_cohort_panel("EGFR", out)
        assert p.name == "figure_protein_per_cohort_tumor_vs_normal.svg" and p.exists()
        pd_path = r.emit_plot_data("EGFR", out)
        df = pd.read_parquet(pd_path)
        assert len(df) == 2 and "delta_median" in df.columns and "mwu_p" in df.columns
        # raw per-aliquot arrays are NOT persisted in plot_data (source-of-record is the product)
        assert not any(c.startswith("_") for c in df.columns)


def test_plotly_box_traces_no_drift(monkeypatch):
    pytest.importorskip("plotly")
    _patch(monkeypatch, _SPEC)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        specs = r.emit_plotly_specs("EGFR", out)
        assert [s["id"] for s in specs] == ["protein_per_cohort_tumor_vs_normal"]
        obj = json.loads((out / specs[0]["path"]).read_text())
        names = {t.get("name") for t in obj["data"]}
        assert names == {"tumor", "normal"} and all(t["type"] == "box" for t in obj["data"])
        # tumor trace carries EACH per-aliquot BRCA value (no reduction to a median)
        tumor = [t for t in obj["data"] if t["name"] == "tumor"][0]
        brca_tumor_xs = [x for x, y in zip(tumor["x"], tumor["y"]) if "BRCA" in y]
        assert sorted(brca_tumor_xs) == sorted(_SPEC["BRCA"][0])


def test_absent_target_degrades(monkeypatch):
    _patch(monkeypatch, _SPEC)
    assert r.per_cohort_distribution_stats("GHOST") == []
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        p = r.emit_per_cohort_panel("GHOST", out)      # placeholder SVG, no crash
        assert p.exists()
        assert r.emit_plotly_specs("GHOST", out) == []


def test_low_n_cohort_keeps_box_but_no_pvalue(monkeypatch):
    # 2 tumor vs 5 normal → below the 3-per-side threshold on the tumor side → p None, box still drawn
    _patch(monkeypatch, {"GBM": ([6.0, 6.1], [3.0, 3.1, 3.2, 3.3, 3.4])})
    stats = r.per_cohort_distribution_stats("EGFR")
    assert len(stats) == 1
    s = stats[0]
    assert s["n_tumor"] == 2 and s["welch_p"] is None and s["mwu_p"] is None
    assert s["tumor_median"] is not None and s["delta_median"] is not None
