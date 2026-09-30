"""genie_panel_recurrence — coverage-correct GENIE recurrence.

The load-bearing property: per-gene frequency divides by the PANEL-COVERAGE denominator
(samples whose panel covers the gene), never the raw sample count. Tests inject a synthetic
GENIE MAF + coverage maps (no S3) and pin: coverage-correct frequency, the coverage-gap path
(gene on no panel → data_unavailable not 0), and the too-thin-to-rank path.
"""

from __future__ import annotations

import pandas as pd

from onc_methods.genie_panel_coverage import read as COV
from onc_methods.genie_panel_recurrence import read as R

# 3 panels: BIG covers KRAS+TP53+EGFR (many samples), SMALL covers only TP53.
_PANEL_GENES = {"BIG": frozenset({"KRAS", "TP53", "EGFR"}), "SMALL": frozenset({"TP53"})}


def _setup(monkeypatch, maf_rows, sample_panel, cohort=None):
    # cohort = the FULL indication sample set (mutated + wild-type). Defaults to all samples in
    # sample_panel (i.e. every assayed sample), which is the realistic denominator universe.
    R._covered_gene_frequencies.cache_clear()
    R._indication_cohort.cache_clear()
    monkeypatch.setattr(COV, "load_panel_gene_sets", lambda *a, **k: _PANEL_GENES)
    monkeypatch.setattr(COV, "load_sample_panel_map", lambda *a, **k: sample_panel)
    monkeypatch.setattr(R, "_load_genie_maf", lambda ind: pd.DataFrame(maf_rows))
    monkeypatch.setattr(
        R, "_indication_cohort", lambda ind: tuple(cohort if cohort is not None else sample_panel.keys())
    )


def test_frequency_uses_coverage_denominator(monkeypatch):
    # 30 samples on BIG (all cover KRAS), 30 on SMALL (cover only TP53). KRAS mutated in 15 BIG samples.
    sp = {f"b{i}": "BIG" for i in range(30)}
    sp.update({f"s{i}": "SMALL" for i in range(30)})
    maf = [{"sample_id": f"b{i}", "gene_symbol": "KRAS"} for i in range(15)]
    _setup(monkeypatch, maf, sp)
    out = R.genie_recurrence_for_gene("KRAS", "NSCLC")
    # KRAS covered on the 30 BIG samples only (NOT all 60) → 15/30 = 0.5, not 15/60 = 0.25
    assert out["n_covered"] == 30 and out["n_mutated"] == 15
    assert out["genie_mutation_frequency"] == 0.5
    assert out["coverage_gap"] is False


def test_coverage_gap_is_data_unavailable_not_zero(monkeypatch):
    # MYC on no panel → n_covered 0 → data_unavailable, coverage_gap True, NOT frequency 0.
    sp = {f"b{i}": "BIG" for i in range(30)}
    _setup(monkeypatch, [{"sample_id": "b0", "gene_symbol": "KRAS"}], sp)
    out = R.genie_recurrence_for_gene("MYC", "NSCLC")
    assert out["coverage_gap"] is True
    assert out["genie_driver_recurrence_class"] == "data_unavailable"
    assert out["genie_mutation_frequency"] is None
    assert "coverage gap" in out["genie_recurrence_context"]


def test_too_thin_coverage_emits_no_percentile(monkeypatch):
    # EGFR covered on only 5 BIG samples (< _MIN_COVERED=20) → freq emitted, percentile None.
    sp = {f"b{i}": "BIG" for i in range(5)}
    maf = [{"sample_id": "b0", "gene_symbol": "EGFR"}]
    _setup(monkeypatch, maf, sp)
    out = R.genie_recurrence_for_gene("EGFR", "NSCLC")
    assert out["n_covered"] == 5
    assert out["genie_mutation_frequency"] == 0.2  # 1/5 still reported
    assert out["genie_driver_recurrence_percentile"] is None
    assert out["genie_driver_recurrence_class"] == "data_unavailable"
    assert "too thin" in out["genie_recurrence_context"]


def test_percentile_ranks_among_covered_genes(monkeypatch):
    # KRAS mutated in ALL 30 BIG samples (freq 1.0) → should top the recurrence percentile.
    sp = {f"b{i}": "BIG" for i in range(30)}
    maf = (
        [{"sample_id": f"b{i}", "gene_symbol": "KRAS"} for i in range(30)]
        + [{"sample_id": "b0", "gene_symbol": "TP53"}]  # TP53 rare (1/30)
        + [{"sample_id": "b1", "gene_symbol": "EGFR"}]
    )  # EGFR rare (1/30)
    _setup(monkeypatch, maf, sp)
    out = R.genie_recurrence_for_gene("KRAS", "NSCLC")
    assert out["genie_mutation_frequency"] == 1.0
    # KRAS is the single highest-frequency gene in the 3-gene null → top by mid-rank
    # ((2 + 0.5)/3 = 83.3 for n=3; the exact value depends on ties, but it must exceed the
    # other two genes and be the max percentile in the set).
    assert out["genie_driver_recurrence_percentile"] == max(
        R.genie_recurrence_for_gene(g, "NSCLC")["genie_driver_recurrence_percentile"] for g in ("KRAS", "TP53", "EGFR")
    )
    assert out["genie_driver_recurrence_percentile"] > 50.0
