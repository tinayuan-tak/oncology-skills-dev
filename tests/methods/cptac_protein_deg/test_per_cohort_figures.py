"""Per-cohort CPTAC protein tumor-vs-normal figures (Slice 7 CPTAC protein viz).

The derived product (cptac-protein-tumor-vs-normal-per-cohort-v1) is per-cohort SUMMARY statistics —
NOT per-sample — so the honest figure is a per-cohort tumor-vs-normal panel (dumbbell), NOT a
sample-level boxplot. Tests (no S3 — _load_indexed monkeypatched to synthetic multi-cohort rows)
pin: read_all_cohorts returns all cohort rows effect-sorted; the panel SVG + plot_data + plotly
emit; the plotly medians equal the input (no-drift); a target absent from all cohorts degrades.
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


def _patch(monkeypatch, rows):
    df = pd.DataFrame(rows)
    gi = {}
    for i, row in enumerate(rows):
        gi.setdefault(str(row["gene_symbol"]).upper(), []).append(i)
    monkeypatch.setattr(r, "_load_indexed", lambda: (df, {}, gi))


_ROWS = [
    {"cohort": "BRCA", "gene_symbol": "EGFR", "protein_effect_size": 1.8, "protein_bh_q_value": 1e-6,
     "protein_p_value": 1e-7, "protein_median_log2_tumor": 5.2, "protein_median_log2_normal": 3.4,
     "n_tumor_samples": 120, "n_normal_samples": 20, "protein_expression_class": "strong_up",
     "stat_test_used": "msstatstmt_limma_ebayes_moderated", "method_version": "1.0.0"},
    {"cohort": "COAD", "gene_symbol": "EGFR", "protein_effect_size": 0.4, "protein_bh_q_value": 0.2,
     "protein_p_value": 0.1, "protein_median_log2_tumor": 4.1, "protein_median_log2_normal": 3.7,
     "n_tumor_samples": 90, "n_normal_samples": 8, "protein_expression_class": "ns",
     "stat_test_used": "msstatstmt_limma_ebayes_moderated", "method_version": "1.0.0"},
]


def test_read_all_cohorts_returns_effect_sorted(monkeypatch):
    _patch(monkeypatch, _ROWS)
    rows = r.read_all_cohorts("EGFR")
    assert [x["cohort"] for x in rows] == ["BRCA", "COAD"]      # |effect| desc: 1.8 before 0.4
    assert rows[0]["protein_median_log2_tumor"] == 5.2


def test_panel_svg_and_plot_data_emitted(monkeypatch):
    _patch(monkeypatch, _ROWS)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        p = r.emit_per_cohort_panel("EGFR", out)
        assert p.name == "figure_protein_per_cohort_tumor_vs_normal.svg" and p.exists()
        pd_path = r.emit_plot_data("EGFR", out)
        df = pd.read_parquet(pd_path)
        assert len(df) == 2 and "cohort" in df.columns


def test_plotly_no_drift(monkeypatch):
    pytest.importorskip("plotly")
    _patch(monkeypatch, _ROWS)
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        specs = r.emit_plotly_specs("EGFR", out)
        assert [s["id"] for s in specs] == ["protein_per_cohort_tumor_vs_normal"]
        obj = json.loads((out / specs[0]["path"]).read_text())
        # tumor trace medians equal the input (effect-ascending order: COAD 4.1 then BRCA 5.2)
        tumor_trace = [t for t in obj["data"] if t.get("name") == "tumor"][0]
        assert list(tumor_trace["x"]) == [4.1, 5.2]


def test_absent_target_degrades(monkeypatch):
    _patch(monkeypatch, _ROWS)
    assert r.read_all_cohorts("GHOST") == []
    with tempfile.TemporaryDirectory() as d:
        out = Path(d)
        p = r.emit_per_cohort_panel("GHOST", out)     # placeholder SVG, no crash
        assert p.exists()
        assert r.emit_plotly_specs("GHOST", out) == []
