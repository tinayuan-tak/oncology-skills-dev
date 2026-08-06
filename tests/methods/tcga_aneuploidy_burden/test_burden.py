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


# ---------- MSI summary (v0.2.0, TCGA marker-paper subtype labels — CRC + STAD only) ----------

def _setup_msi(monkeypatch, labels):
    """labels: tuple of raw MSI-status strings the marker-paper CSV would supply."""
    r._load_msi_labels.cache_clear()
    monkeypatch.setattr(r, "_load_msi_labels", lambda key, column: tuple(labels))


def test_msi_high_enriched(monkeypatch):
    # 22% MSI-H (STAD-like) → >= 0.15 → msi_high_enriched.
    labels = ["MSI-H"] * 22 + ["MSI-L"] * 15 + ["MSS"] * 63   # n=100, 22% H
    _setup_msi(monkeypatch, labels)
    out = r.msi_summary_for_indication("GC")
    assert out["n_samples"] == 100 and out["n_msi_high"] == 22
    assert out["msi_high_fraction"] == 0.22 and out["msi_class"] == "msi_high_enriched"


def test_msi_mss_dominant_low_fraction(monkeypatch):
    # 3% MSI-H → <= 0.05 → mss_dominant.
    labels = ["MSI-H"] * 3 + ["MSS"] * 97
    _setup_msi(monkeypatch, labels)
    out = r.msi_summary_for_indication("COADREAD")
    assert out["msi_high_fraction"] == 0.03 and out["msi_class"] == "mss_dominant"


def test_msi_normalizes_status_spellings(monkeypatch):
    # mixed spellings/casing must normalize; non-evaluable ("Not Evaluable") dropped from denominator.
    # "MSI-H", "msi_h", and "MSI H" all normalize to MSI-H (3); + 1 MSI-L + 1 MSS = 5 evaluable;
    # "Not Evaluable" → None, dropped.
    labels = ["MSI-H", "msi_h", "MSI-L", "MSS", "Not Evaluable", "MSI H"]
    _setup_msi(monkeypatch, labels)
    out = r.msi_summary_for_indication("COADREAD")
    assert out["n_samples"] == 5 and out["n_msi_high"] == 3 and out["n_mss"] == 1


def test_msi_unmapped_indication_is_data_unavailable(monkeypatch):
    # NSCLC / PAAD etc. have NO patient MSI labels → data_unavailable, NOT a fabricated 0% MSI-H.
    _setup_msi(monkeypatch, [])   # loader won't even be called for an unmapped indication
    out = r.msi_summary_for_indication("NSCLC")
    assert out["msi_class"] == "data_unavailable" and out["msi_high_fraction"] is None
    assert "CRC + STAD only" in out["_data_note"]


# ---------- MODEL-side MSI summary (v0.2.0, DepMap OmicsGlobalSignatures MSIScore) ----------

def _setup_model_msi(monkeypatch, by_lineage):
    """by_lineage: {OncotreeLineage: [MSIScore, ...]}."""
    r._load_model_msi_by_lineage.cache_clear()
    monkeypatch.setattr(r, "_load_model_msi_by_lineage", lambda: by_lineage)


def test_model_msi_covers_lung_where_patient_absent(monkeypatch):
    # NSCLC → Lung lineage; the model arm gives a MEASURED value where the patient arm is data_unavailable.
    # 2 of 264 lines MSI-H (score>=20) → 0.8% → mss_dominant (a measured negative, NOT data_unavailable).
    scores = [50.0, 40.0] + [2.0] * 262
    _setup_model_msi(monkeypatch, {"Lung": scores})
    out = r.model_msi_summary_for_indication("NSCLC")
    assert out["n_model_lines"] == 264 and out["n_model_msi_high"] == 2
    assert out["model_msi_class"] == "mss_dominant"
    assert out["model_msi_high_fraction"] < 0.05


def test_model_msi_high_enriched(monkeypatch):
    # UCEC → Uterus; ~49% MSI-H → msi_high_enriched.
    scores = [30.0] * 24 + [1.0] * 25
    _setup_model_msi(monkeypatch, {"Uterus": scores})
    out = r.model_msi_summary_for_indication("UCEC")
    assert out["model_msi_class"] == "msi_high_enriched" and out["n_model_msi_high"] == 24


def test_model_msi_merged_lineage_pools_eso_stomach(monkeypatch):
    # GC/STAD/ESCA all map to the 26q1 merged "Esophagus/Stomach" lineage (broader than gastric).
    _setup_model_msi(monkeypatch, {"Esophagus/Stomach": [25.0] * 10 + [2.0] * 174})
    out = r.model_msi_summary_for_indication("STAD")
    assert out["n_model_lines"] == 184 and out["n_model_msi_high"] == 10


def test_model_msi_score_threshold_at_20(monkeypatch):
    # boundary: exactly 20 counts as MSI-H (>=), 19.9 does not.
    _setup_model_msi(monkeypatch, {"Bowel": [20.0, 19.9, 100.0]})
    out = r.model_msi_summary_for_indication("COADREAD")
    assert out["n_model_msi_high"] == 2 and out["n_model_lines"] == 3


def test_model_msi_unmapped_indication_data_unavailable(monkeypatch):
    _setup_model_msi(monkeypatch, {"Bowel": [50.0]})
    out = r.model_msi_summary_for_indication("MADEUP")
    assert out["model_msi_class"] == "data_unavailable" and out["model_msi_high_fraction"] is None


# ---------- MODEL-side mutational-SIGNATURE arm (DepMap OmicsMolecularSignatureMatrix) ----------

def _setup_model_sig(monkeypatch, by_lineage):
    """by_lineage: {OncotreeLineage: [(mmr_frac, hrd_frac), ...]} — already per-model-normalized."""
    r._load_model_signatures_by_lineage.cache_clear()
    monkeypatch.setattr(r, "_load_model_signatures_by_lineage", lambda: by_lineage)


def test_model_mmr_signature_enriched(monkeypatch):
    # 3 of 10 lines MMR-sig-high (>=0.20) → 0.30 >= 0.15 → mmr_signature_enriched.
    pairs = [(0.5, 0.0), (0.4, 0.01), (0.25, 0.0)] + [(0.01, 0.0)] * 7
    _setup_model_sig(monkeypatch, {"Bowel": pairs})
    out = r.model_signature_summary_for_indication("COADREAD")
    assert out["n_model_signature_lines"] == 10 and out["n_model_mmr_signature_high"] == 3
    assert out["model_mmr_signature_high_fraction"] == 0.3
    assert out["model_mmr_signature_class"] == "mmr_signature_enriched"


def test_model_mmr_signature_rare_lung(monkeypatch):
    # NSCLC → Lung; ~0% MMR-sig-high → mmr_signature_rare (the MSI cross-validation: lung is MMR-clean).
    _setup_model_sig(monkeypatch, {"Lung": [(0.01, 0.02)] * 50})
    out = r.model_signature_summary_for_indication("NSCLC")
    assert out["model_mmr_signature_class"] == "mmr_signature_rare"
    assert out["n_model_mmr_signature_high"] == 0


def test_model_hrd_present_low_threshold(monkeypatch):
    # SBS3 present at the LOW 0.10 threshold — a weak proxy; 2 of 5 lines have SBS3>=0.10.
    pairs = [(0.01, 0.15), (0.01, 0.10), (0.01, 0.05), (0.01, 0.0), (0.01, 0.09)]
    _setup_model_sig(monkeypatch, {"Ovary/Fallopian Tube": pairs})
    out = r.model_signature_summary_for_indication("OV")
    assert out["n_model_hrd_signature_present"] == 2
    assert out["model_hrd_signature_present_fraction"] == 0.4


def test_model_signature_mmr_high_threshold_boundary(monkeypatch):
    # per-model MMR-sig-high requires >= 0.20; exactly 0.20 counts, 0.19 does not.
    _setup_model_sig(monkeypatch, {"Bowel": [(0.20, 0.0), (0.19, 0.0)]})
    out = r.model_signature_summary_for_indication("COADREAD")
    assert out["n_model_mmr_signature_high"] == 1


def test_model_signature_unmapped_data_unavailable(monkeypatch):
    _setup_model_sig(monkeypatch, {"Bowel": [(0.5, 0.0)]})
    out = r.model_signature_summary_for_indication("MADEUP")
    assert out["model_mmr_signature_class"] == "data_unavailable"
    assert out["model_mmr_signature_high_fraction"] is None
