"""genie_sv_recurrence — coverage-correct GENIE structural-variant recurrence.

Mirrors the mutation-side property (per-gene frequency divides by the SV-panel-coverage
denominator, never the raw sample count), plus the SV-specific bits: a gene counts at EITHER
breakend, recurrent PARTNER genes are surfaced, and event-type tokens (INTERGENIC/INTRAGENIC)
are not partners. Tests inject a synthetic data_sv + SV-coverage maps (no S3).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.genie_sv_recurrence import read as R  # noqa: E402
from methods.genie_panel_coverage import read as COV  # noqa: E402
from methods.genie_panel_recurrence import read as REC  # noqa: E402


# 2 panels: BIG covers ALK+EML4+TP53 (many samples), SMALL covers only TP53 (no SV-coverage of ALK).
_PANEL_GENES = {"BIG": frozenset({"ALK", "EML4", "TP53"}), "SMALL": frozenset({"TP53"})}


def _setup(monkeypatch, sv_rows, sv_sample_panel, cohort=None):
    """sv_rows = list of (sample_id, site1, site2). sv_sample_panel = {sample_id: panel} keyed on
    the SV assay column. cohort = full indication cohort (defaults to all SV-profiled samples)."""
    R._covered_gene_sv_frequencies.cache_clear()
    R._load_sv.cache_clear()
    REC._indication_cohort.cache_clear()
    monkeypatch.setattr(COV, "load_panel_gene_sets", lambda *a, **k: _PANEL_GENES)
    monkeypatch.setattr(COV, "load_sv_sample_panel_map", lambda *a, **k: sv_sample_panel)
    df = pd.DataFrame(sv_rows, columns=["sample_id", "site1", "site2"])
    monkeypatch.setattr(R, "_load_sv", lambda: df)
    monkeypatch.setattr(REC, "_indication_cohort",
                        lambda ind: tuple(cohort if cohort is not None else sv_sample_panel.keys()))


def test_frequency_uses_sv_coverage_denominator(monkeypatch):
    # 30 samples on BIG (SV-cover ALK), 30 on SMALL (do NOT SV-cover ALK). ALK fused in 15 BIG samples.
    sp = {f"b{i}": "BIG" for i in range(30)}; sp.update({f"s{i}": "SMALL" for i in range(30)})
    sv = [(f"b{i}", "ALK", "EML4") for i in range(15)]
    _setup(monkeypatch, sv, sp)
    out = R.genie_sv_recurrence_for_gene("ALK", "NSCLC")
    # ALK SV-covered on the 30 BIG samples only (NOT all 60) → 15/30 = 0.5, not 15/60 = 0.25.
    assert out["n_sv_covered"] == 30 and out["n_sv_samples"] == 15
    assert out["genie_sv_frequency"] == 0.5
    assert out["coverage_gap"] is False


def test_gene_counts_at_either_breakend(monkeypatch):
    # EML4 appears only as site2 (the 3' partner) — it must still count as SV-bearing.
    sp = {f"b{i}": "BIG" for i in range(30)}
    sv = [(f"b{i}", "ALK", "EML4") for i in range(10)]
    _setup(monkeypatch, sv, sp)
    out = R.genie_sv_recurrence_for_gene("EML4", "NSCLC")
    assert out["n_sv_samples"] == 10           # counted from the site2 slot
    assert out["genie_sv_frequency"] == 10 / 30


def test_recurrent_partners_surface_and_exclude_event_tokens(monkeypatch):
    # ALK fused to EML4 (5 samples) + the event-token INTERGENIC (4 samples). Only EML4 is a partner.
    sp = {f"b{i}": "BIG" for i in range(30)}
    sv = ([(f"b{i}", "ALK", "EML4") for i in range(5)]
          + [(f"b{10+i}", "ALK", "INTERGENIC") for i in range(4)])
    _setup(monkeypatch, sv, sp)
    out = R.genie_sv_recurrence_for_gene("ALK", "NSCLC")
    partners = {p["partner"]: p["n_samples"] for p in out["genie_sv_recurrent_partners"]}
    assert partners == {"EML4": 5}             # INTERGENIC excluded despite clearing the min
    assert out["n_sv_samples"] == 9            # but the SV count includes the intergenic events


def test_coverage_gap_is_data_unavailable_not_zero(monkeypatch):
    # MYC on no SV panel → n_sv_covered 0 → data_unavailable, coverage_gap True, NOT frequency 0.
    sp = {f"b{i}": "BIG" for i in range(30)}
    _setup(monkeypatch, [("b0", "ALK", "EML4")], sp)
    out = R.genie_sv_recurrence_for_gene("MYC", "NSCLC")
    assert out["coverage_gap"] is True
    assert out["genie_sv_recurrence_class"] == "data_unavailable"
    assert out["genie_sv_frequency"] is None
    assert "coverage gap" in out["genie_sv_context"]


def test_too_thin_coverage_emits_no_percentile(monkeypatch):
    # ALK SV-covered on only 5 BIG samples (< _MIN_COVERED=20) → freq emitted, percentile None.
    sp = {f"b{i}": "BIG" for i in range(5)}
    _setup(monkeypatch, [("b0", "ALK", "EML4")], sp)
    out = R.genie_sv_recurrence_for_gene("ALK", "NSCLC")
    assert out["n_sv_covered"] == 5
    assert out["genie_sv_frequency"] == 0.2
    assert out["genie_sv_recurrence_percentile"] is None
    assert out["genie_sv_recurrence_class"] == "data_unavailable"
    assert "too thin" in out["genie_sv_context"]


def test_percentile_ranks_among_covered_genes(monkeypatch):
    # ALK fused in ALL 30 BIG samples (freq 1.0) → tops the recurrence percentile vs rare EML4/TP53.
    sp = {f"b{i}": "BIG" for i in range(30)}
    sv = ([(f"b{i}", "ALK", "PARTNER") for i in range(30)]   # ALK 30/30 (PARTNER not on panel → no self-count)
          + [("b0", "EML4", "X")]                             # EML4 rare (1/30)
          + [("b1", "TP53", "Y")])                            # TP53 rare (1/30)
    _setup(monkeypatch, sv, sp)
    out = R.genie_sv_recurrence_for_gene("ALK", "NSCLC")
    assert out["genie_sv_frequency"] == 1.0
    assert out["genie_sv_recurrence_percentile"] == max(
        R.genie_sv_recurrence_for_gene(g, "NSCLC")["genie_sv_recurrence_percentile"]
        for g in ("ALK", "EML4", "TP53"))
    assert out["genie_sv_recurrence_percentile"] > 50.0


def test_sv_map_is_distinct_from_mutation_map():
    # Guard the column split: the SV sample→panel map keys on `sv`, the mutation map on `mutations`.
    # A sample SNV-profiled but NOT SV-profiled must be absent from the SV map's denominator universe.
    assert COV._SV_PANEL_COLUMN == "sv"
    assert COV._MUTATIONS_PANEL_COLUMN == "mutations"
    assert COV.load_sv_sample_panel_map is not COV.load_sample_panel_map
