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
