"""read_tumor_elevation_breadth (Slice B1, 2026-07-21).

A TARGET-GRAIN roll-up over CPTAC cohorts: "elevated in K of N cancers." Built on
read_all_cohorts (per-cohort summary). Breadth over INDICATIONS for ONE target (allowed),
NOT a ranking over targets. "Elevated" = protein_expression_class in {strong_up, modest_up}.

Tests (no S3 — _load_indexed monkeypatched to synthetic multi-cohort rows) pin:
  - the count (n_tested / n_elevated / fraction) over the existing per-cohort classes;
  - median effect is over ELEVATED cohorts only;
  - the breadth_class ladder (broadly / multi / single / not / data_unavailable);
  - most_elevated_cohorts is effect-sorted and elevated-only;
  - a target absent from all cohorts degrades to data_unavailable (never a fabricated negative).
"""
from __future__ import annotations

import importlib
import sys
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


def _row(cohort, gene, cls, effect, q=1e-6):
    return {"cohort": cohort, "gene_symbol": gene, "protein_effect_size": effect,
            "protein_bh_q_value": q, "protein_p_value": q, "protein_median_log2_tumor": 5.0,
            "protein_median_log2_normal": 3.0, "n_tumor_samples": 100, "n_normal_samples": 20,
            "protein_expression_class": cls,
            "stat_test_used": "msstatstmt_limma_ebayes_moderated", "method_version": "1.0.0"}


# 4 cohorts: 3 elevated (2 strong + 1 modest), 1 ns → broadly (frac 3/4 >= .5, n_elev 3)
_BROAD = [
    _row("BRCA", "EGFR", "strong_up", 2.0),
    _row("LUAD", "EGFR", "strong_up", 1.6),
    _row("COAD", "EGFR", "modest_up", 0.8),
    _row("OV", "EGFR", "ns", 0.1, q=0.3),
]


def test_broadly_tumor_elevated(monkeypatch):
    _patch(monkeypatch, _BROAD)
    b = r.read_tumor_elevation_breadth("EGFR")
    assert b["tumor_elevation_breadth_class"] == "broadly_tumor_elevated"
    assert b["n_cohorts_tested"] == 4
    assert b["n_cohorts_elevated"] == 3
    assert b["fraction_elevated"] == 0.75
    # median effect over ELEVATED only (2.0, 1.6, 0.8) → 1.6, not dragged by the ns cohort
    assert b["median_effect_across_elevated"] == 1.6
    # most_elevated is effect-sorted + elevated-only (ns cohort excluded)
    assert [c["cohort"] for c in b["most_elevated_cohorts"]] == ["BRCA", "LUAD", "COAD"]
    assert b["cohorts_tested"] == ["BRCA", "COAD", "LUAD", "OV"]


def test_multi_tumor_elevated(monkeypatch):
    # 2 elevated of 5 → n_elev 2 (>=2) but fraction 0.4 (<0.5) → multi, not broadly
    rows = [_row("BRCA", "MET", "strong_up", 2.0), _row("LUAD", "MET", "modest_up", 0.7),
            _row("COAD", "MET", "ns", 0.1, q=0.4), _row("OV", "MET", "ns", 0.0, q=0.9),
            _row("GBM", "MET", "strong_down", -1.7)]
    _patch(monkeypatch, rows)
    b = r.read_tumor_elevation_breadth("MET")
    assert b["tumor_elevation_breadth_class"] == "multi_tumor_elevated"
    assert b["n_cohorts_elevated"] == 2 and b["n_cohorts_tested"] == 5
    assert b["fraction_elevated"] == 0.4


def test_single_tumor_elevated(monkeypatch):
    rows = [_row("BRCA", "X", "strong_up", 2.0), _row("LUAD", "X", "ns", 0.1, q=0.4)]
    _patch(monkeypatch, rows)
    b = r.read_tumor_elevation_breadth("X")
    assert b["tumor_elevation_breadth_class"] == "single_tumor_elevated"
    assert b["n_cohorts_elevated"] == 1
    assert b["median_effect_across_elevated"] == 2.0


def test_not_tumor_elevated_when_tested_but_none_elevated(monkeypatch):
    rows = [_row("BRCA", "Y", "ns", 0.1, q=0.5), _row("LUAD", "Y", "strong_down", -2.0)]
    _patch(monkeypatch, rows)
    b = r.read_tumor_elevation_breadth("Y")
    assert b["tumor_elevation_breadth_class"] == "not_tumor_elevated"
    assert b["n_cohorts_elevated"] == 0
    assert b["fraction_elevated"] == 0.0
    assert b["median_effect_across_elevated"] is None
    assert b["most_elevated_cohorts"] == []


def test_absent_target_is_data_unavailable(monkeypatch):
    _patch(monkeypatch, _BROAD)
    b = r.read_tumor_elevation_breadth("GHOST")
    assert b["tumor_elevation_breadth_class"] == "data_unavailable"
    assert b["n_cohorts_tested"] == 0
    assert b["fraction_elevated"] is None
    assert b["most_elevated_cohorts"] == []
    assert b["cohorts_tested"] == []


def test_median_effect_even_count(monkeypatch):
    # 2 elevated → even count → average of the two effects
    rows = [_row("BRCA", "Z", "strong_up", 2.0), _row("LUAD", "Z", "modest_up", 1.0),
            _row("COAD", "Z", "ns", 0.1, q=0.4)]
    _patch(monkeypatch, rows)
    b = r.read_tumor_elevation_breadth("Z")
    assert b["n_cohorts_elevated"] == 2
    assert b["median_effect_across_elevated"] == 1.5   # (1.0 + 2.0)/2
