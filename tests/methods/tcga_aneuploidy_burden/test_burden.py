"""tcga_aneuploidy_burden — per-indication genome-instability burden.

Mocks the two S3 loaders (seg scores + barcode→cancer-type) to pin: indication scoping via the
barcode-patient join, the median-based cohort class, and graceful data_unavailable.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.tcga_aneuploidy_burden import read as r  # noqa: E402


def _setup(monkeypatch, seg_rows, cancer_map):
    r._load_seg_scores.cache_clear()
    r._load_sample_cancer_types.cache_clear()
    monkeypatch.setattr(r, "_load_seg_scores", lambda: pd.DataFrame(seg_rows))
    monkeypatch.setattr(r, "_load_sample_cancer_types", lambda: cancer_map)


def test_scopes_to_indication_and_classifies_high(monkeypatch):
    # 3 COAD samples with high frac_altered (median 0.5 → highly_aneuploid) + 1 LUAD (excluded).
    seg = [{"Sample": f"TCGA-A6-000{i}-01", "frac_altered": 0.5, "n_segs": 100, "n_extrema": 50} for i in range(3)]
    seg.append({"Sample": "TCGA-05-9999-01", "frac_altered": 0.05, "n_segs": 10, "n_extrema": 5})  # LUAD
    cancer = {f"TCGA-A6-000{i}": "COAD" for i in range(3)}
    cancer["TCGA-05-9999"] = "LUAD"
    _setup(monkeypatch, seg, cancer)
    out = r.aneuploidy_burden_for_indication("COADREAD")
    assert out["n_samples"] == 3   # LUAD sample excluded
    assert out["median_fraction_genome_altered"] == 0.5
    assert out["aneuploidy_burden_class"] == "highly_aneuploid"


def test_quiet_genome_low_median(monkeypatch):
    seg = [{"Sample": f"TCGA-A6-000{i}-01", "frac_altered": 0.05, "n_segs": 10, "n_extrema": 5} for i in range(4)]
    cancer = {f"TCGA-A6-000{i}": "COAD" for i in range(4)}
    _setup(monkeypatch, seg, cancer)
    out = r.aneuploidy_burden_for_indication("COADREAD")
    assert out["aneuploidy_burden_class"] == "quiet_genome"


def test_barcode_patient_truncation_join(monkeypatch):
    # seg Sample is 4-segment; annotation keys on 3-segment patient — the join must truncate.
    seg = [{"Sample": "TCGA-A6-1111-01A", "frac_altered": 0.3, "n_segs": 50, "n_extrema": 25}]
    cancer = {"TCGA-A6-1111": "COAD"}
    _setup(monkeypatch, seg, cancer)
    out = r.aneuploidy_burden_for_indication("COADREAD")
    assert out["n_samples"] == 1 and out["aneuploidy_burden_class"] == "intermediate_aneuploidy"


def test_unmapped_indication_is_data_unavailable(monkeypatch):
    _setup(monkeypatch, [], {})
    out = r.aneuploidy_burden_for_indication("MADEUP")
    assert out["aneuploidy_burden_class"] == "data_unavailable"


# ---------- WGD summary (v0.2.0, ABSOLUTE abs_tables) ----------

def _setup_wgd(monkeypatch, absolute_rows, cancer_map):
    r._load_absolute.cache_clear()
    r._load_sample_cancer_types.cache_clear()
    monkeypatch.setattr(r, "_load_absolute", lambda: pd.DataFrame(absolute_rows))
    monkeypatch.setattr(r, "_load_sample_cancer_types", lambda: cancer_map)


def _abs_row(array, gd, ploidy=2.0, purity=0.8):
    # ABSOLUTE `array` is the sample-level barcode; join truncates to 3-segment patient.
    return {"array": array, "Genome doublings": gd, "ploidy": ploidy, "purity": purity}


def test_wgd_enriched_high_fraction(monkeypatch):
    # 6 of 8 COAD samples have >=1 genome doubling → 0.75 >= 0.50 → wgd_enriched.
    rows = [_abs_row(f"TCGA-A6-000{i}-01", 1.0, ploidy=3.0) for i in range(6)]
    rows += [_abs_row(f"TCGA-A6-010{i}-01", 0.0, ploidy=2.0) for i in range(2)]
    cancer = {f"TCGA-A6-000{i}": "COAD" for i in range(6)}
    cancer.update({f"TCGA-A6-010{i}": "COAD" for i in range(2)})
    _setup_wgd(monkeypatch, rows, cancer)
    out = r.wgd_summary_for_indication("COADREAD")
    assert out["n_samples"] == 8 and out["n_wgd_samples"] == 6
    assert out["wgd_fraction"] == 0.75
    assert out["wgd_class"] == "wgd_enriched"
    assert out["median_ploidy"] is not None


def test_wgd_rare_low_fraction(monkeypatch):
    # 1 of 10 doubled → 0.1 <= 0.20 → wgd_rare.
    rows = [_abs_row(f"TCGA-A6-000{i}-01", 1.0 if i == 0 else 0.0) for i in range(10)]
    cancer = {f"TCGA-A6-000{i}": "COAD" for i in range(10)}
    _setup_wgd(monkeypatch, rows, cancer)
    out = r.wgd_summary_for_indication("COADREAD")
    assert out["wgd_fraction"] == 0.1 and out["wgd_class"] == "wgd_rare"


def test_wgd_scopes_to_indication(monkeypatch):
    # a LUAD row must not enter the COADREAD WGD fraction.
    rows = [_abs_row("TCGA-A6-0001-01", 1.0), _abs_row("TCGA-05-9999-01", 0.0)]
    cancer = {"TCGA-A6-0001": "COAD", "TCGA-05-9999": "LUAD"}
    _setup_wgd(monkeypatch, rows, cancer)
    out = r.wgd_summary_for_indication("COADREAD")
    assert out["n_samples"] == 1 and out["wgd_fraction"] == 1.0


def test_wgd_double_doubling_counts_as_wgd(monkeypatch):
    # Genome doublings == 2 (double WGD) must count toward the WGD fraction (>=1 threshold).
    rows = [_abs_row("TCGA-A6-0001-01", 2.0), _abs_row("TCGA-A6-0002-01", 0.0)]
    cancer = {"TCGA-A6-0001": "COAD", "TCGA-A6-0002": "COAD"}
    _setup_wgd(monkeypatch, rows, cancer)
    out = r.wgd_summary_for_indication("COADREAD")
    assert out["n_wgd_samples"] == 1 and out["wgd_fraction"] == 0.5


def test_wgd_unmapped_indication_is_data_unavailable(monkeypatch):
    _setup_wgd(monkeypatch, [], {})
    out = r.wgd_summary_for_indication("MADEUP")
    assert out["wgd_class"] == "data_unavailable" and out["wgd_fraction"] is None
