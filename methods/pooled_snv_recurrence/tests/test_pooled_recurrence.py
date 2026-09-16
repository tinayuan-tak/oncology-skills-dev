"""Offline synthetic tests for the pooled multi-cohort SNV recurrence core (scope-coherence Phase 2).

No S3: the three per-cohort count readers are monkeypatched with in-memory {gene: (n_mut, n_cov)} dicts,
so the summed-counts/summed-coverage pooling + percentile ranking + cohort provenance are exercised
entirely on fixtures."""

from __future__ import annotations

import methods.pooled_snv_recurrence.read as pr


# ── pure pooling core ─────────────────────────────────────────────────────────────────────────────
def test_pool_sums_counts_and_tracks_cohorts():
    per_cohort = {
        "TCGA-MC3": {"KRAS": (100, 500), "TP53": (200, 500)},
        "GENIE": {"KRAS": (300, 1000), "APC": (40, 900)},
        "MSK-CHORD": {"KRAS": (150, 600)},
    }
    pooled = pr.pool_gene_counts(per_cohort)
    # KRAS pooled across all three: n_mut 100+300+150=550, n_cov 500+1000+600=2100
    assert pooled["KRAS"]["n_mut"] == 550 and pooled["KRAS"]["n_cov"] == 2100
    assert pooled["KRAS"]["cohorts"] == ["GENIE", "MSK-CHORD", "TCGA-MC3"]
    # APC only in GENIE
    assert pooled["APC"]["cohorts"] == ["GENIE"]


def test_pool_ignores_zero_coverage():
    pooled = pr.pool_gene_counts({"GENIE": {"X": (5, 0)}, "TCGA-MC3": {"X": (3, 100)}})
    assert pooled["X"]["n_cov"] == 100 and pooled["X"]["cohorts"] == ["TCGA-MC3"]  # zero-cov cohort dropped


# ── per-gene recurrence over monkeypatched cohorts ─────────────────────────────────────────────────
def _install(monkeypatch, mc3=None, genie=None, msk=None):
    # Force the LIVE pooled computation over the monkeypatched cohorts: pooled_recurrence_for_gene tries
    # the precomputed product first, so stub it absent (else this offline test would attempt a real S3
    # read of pooled-snv-recurrence-v2).
    monkeypatch.setattr(pr, "_pooled_from_product", lambda *a, **k: None)
    monkeypatch.setattr(pr, "_mc3_gene_counts", lambda ind: mc3 or {})
    monkeypatch.setattr(pr, "_genie_gene_counts", lambda ind: genie or {})
    monkeypatch.setattr(pr, "_msk_gene_counts", lambda ind: msk or {})
    pr._pooled_for_indication.cache_clear()


def test_top_recurrent_gene_ranks_high(monkeypatch):
    # KRAS very frequent; a spread of low-frequency genes forms the null (all with n_cov >= 20).
    mc3 = {"KRAS": (250, 500)}  # 50%
    mc3.update({f"G{i}": (1, 500) for i in range(200)})  # 0.2% background (>=100 genes → top_1pct reachable)
    _install(monkeypatch, mc3=mc3, genie={"KRAS": (300, 700)}, msk={"KRAS": (120, 300)})
    r = pr.pooled_recurrence_for_gene("KRAS", "COADREAD")
    assert r["cohorts_contributing"] == ["GENIE", "MSK-CHORD", "TCGA-MC3"]
    assert r["n_mutated_pooled"] == 670 and r["n_covered_pooled"] == 1500
    assert r["pooled_driver_recurrence_class"] == "top_1pct"
    assert r["pooled_driver_recurrence_percentile"] >= 99.0


def test_uncovered_gene_is_data_unavailable(monkeypatch):
    _install(monkeypatch, mc3={"KRAS": (10, 500)})
    r = pr.pooled_recurrence_for_gene("BRAF", "COADREAD")
    assert r["pooled_driver_recurrence_class"] == "data_unavailable" and r["n_covered_pooled"] == 0


def test_thin_coverage_not_ranked(monkeypatch):
    # target covered on < _MIN_COVERED pooled samples → freq emitted, percentile withheld
    _install(monkeypatch, msk={"RARE1": (2, 5)})
    r = pr.pooled_recurrence_for_gene("RARE1", "COADREAD")
    assert r["n_covered_pooled"] == 5 and r["pooled_driver_recurrence_class"] == "data_unavailable"
    assert r["pooled_mutation_frequency"] == 2 / 5


def test_no_cohorts_is_data_unavailable(monkeypatch):
    _install(monkeypatch)  # all empty
    r = pr.pooled_recurrence_for_gene("KRAS", "GC")
    assert r["pooled_driver_recurrence_class"] == "data_unavailable" and r["cohorts_contributing"] == []
