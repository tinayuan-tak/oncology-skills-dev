"""Synthetic-data test for the driver-recurrence percentile (Axis-1 analog, 2026-08-05).

read_hotspot_summary now contextualizes overall_mutation_frequency: it ranks the
target gene's recurrence against ALL mutated genes in the SAME indication aggregate,
emitting driver_recurrence_percentile + driver_recurrence_class + a context string.

These tests build a synthetic MC3-aggregate parquet (matching cli._output_schema) with
a KNOWN frequency distribution, so no S3 / real MC3 is needed. They pin:
  - the null uses GENE-SUMMARY rows only (a gene with many hotspots isn't over-counted);
  - a high-recurrence gene lands top_1pct/top_decile, a rare gene lands bottom/mid;
  - a target ABSENT from the aggregate (real biological zero) ranks at the bottom
    (a genuine negative), distinct from data_unavailable when the aggregate is missing;
  - the display fields never claim to be a verdict (they are additive/inert).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from methods.gdc_somatic_hotspot import read as r


def _agg_row(indication, gene, freq, n_samples=100, hotspot=None, hs_n=None):
    """One aggregate row. Gene-summary row => hotspot_protein_change is None."""
    return {
        "indication": indication,
        "gene_symbol": gene,
        "n_samples_in_indication": n_samples,
        "n_samples_mutated": int(round(freq * n_samples)),
        "overall_mutation_frequency": freq,
        "hotspot_protein_change": hotspot,
        "hotspot_n_samples": hs_n,
        "hotspot_frequency": (hs_n / n_samples) if hs_n is not None else None,
    }


def _build_aggregate(path: Path, indication: str = "COADREAD") -> None:
    """101 genes: 1 high-recurrence driver (0.45) + 100 background genes ramped
    0.001..0.10. The driver also carries TWO hotspot rows to prove the null uses
    only the gene-summary row (else the driver's frequency would be triple-counted)."""
    rows = []
    # High-recurrence driver at 0.45 with two hotspot codons.
    rows.append(_agg_row(indication, "DRIVER_HI", 0.45))
    rows.append(_agg_row(indication, "DRIVER_HI", 0.45, hotspot="p.G12D", hs_n=30))
    rows.append(_agg_row(indication, "DRIVER_HI", 0.45, hotspot="p.G12C", hs_n=15))
    # 100 background genes with a gentle frequency ramp (0.001 .. 0.10).
    for i in range(100):
        freq = round(0.001 + i * (0.099 / 99), 6)
        rows.append(_agg_row(indication, f"BG{i:03d}", freq))
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_parquet(path)


@pytest.fixture()
def aggregate(tmp_path):
    p = tmp_path / "coadread_mc3_hotspots.parquet"
    _build_aggregate(p)
    # lru_cache on the null is keyed by path string; tmp_path is unique per test → no bleed.
    r._allgene_mutation_frequency_null.cache_clear()
    return p


def test_null_uses_gene_summary_rows_only(aggregate):
    """101 genes total (1 driver + 100 background), NOT 103 — the driver's two
    hotspot rows must be excluded from the reference population."""
    null = r._allgene_mutation_frequency_null(str(aggregate))
    assert len(null) == 101, f"expected 101 gene-summary rows, got {len(null)}"


def test_high_recurrence_gene_is_top_percentile(aggregate):
    s = r.read_hotspot_summary("DRIVER_HI", "COADREAD", aggregate_path=aggregate)
    assert s["overall_mutation_frequency"] == 0.45
    # 0.45 is above all 100 background genes (max 0.10) → ~top of the distribution.
    assert s["driver_recurrence_percentile"] >= 99.0
    assert s["driver_recurrence_class"] == "top_1pct"
    assert "COADREAD" in s["driver_recurrence_context"]
    assert "n_genes=101" in s["driver_recurrence_context"]


def test_low_recurrence_gene_is_not_top(aggregate):
    # BG005 sits near the bottom of the ramp → bottom_decile, definitely not top.
    s = r.read_hotspot_summary("BG005", "COADREAD", aggregate_path=aggregate)
    assert s["driver_recurrence_class"] in ("bottom_decile", "mid")
    assert s["driver_recurrence_percentile"] < 90.0


def test_absent_target_is_real_negative_not_unavailable(aggregate):
    """A target with NO rows (zero non-synonymous mutations) is a real biological
    zero — it ranks below every mutated gene, NOT data_unavailable."""
    s = r.read_hotspot_summary("NEVER_MUTATED", "COADREAD", aggregate_path=aggregate)
    assert s["overall_mutation_frequency"] == 0.0
    assert s["driver_recurrence_class"] == "bottom_decile"
    assert s["driver_recurrence_percentile"] is not None
    assert s["driver_recurrence_percentile"] < 10.0


def test_missing_aggregate_is_data_unavailable(tmp_path, monkeypatch):
    """When the aggregate is resolvable via NEITHER the local cache NOR the registered S3
    product, the recurrence axis is unknowable — data_unavailable, distinct from the real-zero
    case above. Post-manifest-migration: an absent LOCAL path alone is no longer enough (the
    reader falls back to the tcga-mc3-hotspot-frequency-v1 S3 product), so this test also points
    DATA_CATALOG at an empty dir → the manifest can't resolve → no S3 fallback → data_unavailable.
    (This is the migration working as designed: S3 fallback is a feature; data_unavailable now
    means genuinely-nowhere-to-read.)"""
    monkeypatch.setattr(r, "DATA_CATALOG", tmp_path / "empty_catalog")   # manifest glob → [] → no S3
    r._allgene_mutation_frequency_null.cache_clear()
    missing = tmp_path / "does_not_exist.parquet"
    s = r.read_hotspot_summary("DRIVER_HI", "COADREAD", aggregate_path=missing)
    assert s["driver_recurrence_class"] == "data_unavailable"
    assert s["driver_recurrence_percentile"] is None
    assert s["driver_recurrence_context"] is None


# --- GENIE recurrence fields on the card (Phase 1e tail) ---------------------

def test_genie_recurrence_fields_graceful_when_module_absent(monkeypatch):
    """read_hotspot_summary always carries the 4 genie_driver_recurrence_* keys; if the GENIE
    reader raises/absent, they degrade to data_unavailable rather than breaking the MC3 card."""
    from methods.gdc_somatic_hotspot import read as r
    def _boom(*a, **k):
        raise RuntimeError("genie module unavailable")
    # patch the lazy import target so the try/except fallback fires
    import methods.genie_panel_recurrence.read as gr
    monkeypatch.setattr(gr, "genie_recurrence_for_gene", _boom)
    fields = r._genie_recurrence_fields("KRAS", "NSCLC")
    assert fields["genie_driver_recurrence_class"] == "data_unavailable"
    assert fields["genie_driver_recurrence_percentile"] is None
    assert set(fields) == {"genie_driver_recurrence_percentile", "genie_driver_recurrence_class",
                           "genie_mutation_frequency", "genie_recurrence_context"}
