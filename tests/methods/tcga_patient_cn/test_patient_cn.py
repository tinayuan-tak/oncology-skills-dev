"""tcga_patient_cn — per-(gene, indication) PATIENT copy-number prevalence from GISTIC.

Tests mock the GISTIC per-gene reader + the aliquot→cancer-type map (no S3), and force the product
fast-path OFF (→ live-TSV path) to exercise the classification directly. Pin: amp/del classification
mirroring the DepMap vocabulary, the indication scoping, and honest amplification (NOT LoF-collapsed).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.tcga_patient_cn import read as r  # noqa: E402


def _setup(monkeypatch, gistic_by_aliquot, cancer_map):
    """gistic_by_aliquot: {aliquot_barcode: int GISTIC discrete}. cancer_map: {patient_barcode: type}.
    Force the product fast-path to miss so the live-TSV classification path runs."""
    r._read_gistic_gene.cache_clear()
    r._load_sample_cancer_types.cache_clear()
    monkeypatch.setattr(r, "_read_from_product", lambda target, indication: None)  # force live path
    monkeypatch.setattr(r, "_read_gistic_gene", lambda target: tuple(gistic_by_aliquot.items()))
    monkeypatch.setattr(r, "_load_sample_cancer_types", lambda: cancer_map)


def test_recurrently_amplified(monkeypatch):
    # 40 of 100 BRCA samples amplified (>= +1) → 40% >= 20% amp, ~0% del → recurrently_amplified.
    g = {f"TCGA-A1-{i:04d}-01A": (2 if i < 15 else 1 if i < 40 else 0) for i in range(100)}
    cancer = {f"TCGA-A1-{i:04d}": "BRCA" for i in range(100)}
    _setup(monkeypatch, g, cancer)
    out = r.patient_cn_summary_for_gene("ERBB2", "BRCA")
    assert out["n_samples"] == 100
    assert out["patient_amplified_fraction"] == 0.40 and out["patient_high_amp_fraction"] == 0.15
    assert out["patient_copy_number_class"] == "recurrently_amplified"


def test_recurrently_deleted(monkeypatch):
    # 67% deleted (CDKN2A-like), few amp → recurrently_deleted.
    g = {f"TCGA-05-{i:04d}-01A": (-2 if i < 30 else -1 if i < 67 else 0) for i in range(100)}
    cancer = {f"TCGA-05-{i:04d}": "LUAD" for i in range(100)}
    _setup(monkeypatch, g, cancer)
    out = r.patient_cn_summary_for_gene("CDKN2A", "NSCLC")
    assert out["patient_copy_number_class"] == "recurrently_deleted"
    assert out["patient_homdel_fraction"] == 0.30


def test_amplification_not_collapsed_by_loss(monkeypatch):
    # The two-hit product's "min-wins" bug would call this deleted; the raw-GISTIC method must NOT.
    # 45 amplified, 22 deleted — both recurrent, amp dominates by >1.5x (0.45 >= 0.22*1.5) → amplified.
    g = {}
    for i in range(100):
        g[f"TCGA-A1-{i:04d}-01A"] = 2 if i < 45 else (-1 if i < 67 else 0)
    cancer = {f"TCGA-A1-{i:04d}": "BRCA" for i in range(100)}
    _setup(monkeypatch, g, cancer)
    out = r.patient_cn_summary_for_gene("ERBB2", "BRCA")
    assert out["patient_amplified_fraction"] == 0.45 and out["patient_deleted_fraction"] == 0.22
    assert out["patient_copy_number_class"] == "recurrently_amplified"   # NOT deleted (min-wins would)


def test_mixed_when_balanced(monkeypatch):
    # both amp+del recurrent, neither dominates by 1.5x → mixed.
    g = {}
    for i in range(100):
        g[f"TCGA-A1-{i:04d}-01A"] = 1 if i < 30 else (-1 if i < 60 else 0)
    cancer = {f"TCGA-A1-{i:04d}": "BRCA" for i in range(100)}
    _setup(monkeypatch, g, cancer)
    out = r.patient_cn_summary_for_gene("SOMEGENE", "BRCA")
    assert out["patient_copy_number_class"] == "mixed"


def test_broadly_neutral(monkeypatch):
    # <20% amp and <20% del → broadly_neutral (mutation-driven gene like KRAS focal).
    g = {f"TCGA-A6-{i:04d}-01A": (1 if i < 10 else 0) for i in range(100)}
    cancer = {f"TCGA-A6-{i:04d}": "COAD" for i in range(100)}
    _setup(monkeypatch, g, cancer)
    out = r.patient_cn_summary_for_gene("KRAS", "COADREAD")
    assert out["patient_copy_number_class"] == "broadly_neutral"


def test_indication_scoping(monkeypatch):
    # a STAD aliquot must not enter the COADREAD cohort.
    g = {"TCGA-A6-0001-01A": 2, "TCGA-BR-0002-01A": 2}
    cancer = {"TCGA-A6-0001": "COAD", "TCGA-BR-0002": "STAD"}
    _setup(monkeypatch, g, cancer)
    out = r.patient_cn_summary_for_gene("ERBB2", "COADREAD")
    assert out["n_samples"] == 1   # only the COAD aliquot


def test_unmapped_indication_data_unavailable(monkeypatch):
    _setup(monkeypatch, {"TCGA-A1-0001-01A": 2}, {"TCGA-A1-0001": "BRCA"})
    out = r.patient_cn_summary_for_gene("ERBB2", "MADEUP")
    assert out["patient_copy_number_class"] == "data_unavailable"


def test_focal_amplification_gates_on_high_level(monkeypatch):
    # 25% high-level (+2) → recurrent_focal_amplification (>= 10% focal bar). This is the verdict-consensus gate.
    g = {f"TCGA-A1-{i:04d}-01A": (2 if i < 25 else 1 if i < 50 else 0) for i in range(100)}
    cancer = {f"TCGA-A1-{i:04d}": "BRCA" for i in range(100)}
    _setup(monkeypatch, g, cancer)
    out = r.patient_cn_summary_for_gene("ERBB2", "BRCA")
    assert out["patient_focal_cn_class"] == "recurrent_focal_amplification"


def test_arm_level_gain_is_NOT_focal(monkeypatch):
    # 23% any-gain but only 1% high-level (+2) — KRAS-arm-level pattern. patient_copy_number_class is
    # recurrently_amplified (any-gain), but patient_focal_cn_class must be focal_neutral (NOT a focal driver).
    g = {}
    for i in range(100):
        g[f"TCGA-A6-{i:04d}-01A"] = 2 if i < 1 else (1 if i < 23 else 0)
    cancer = {f"TCGA-A6-{i:04d}": "COAD" for i in range(100)}
    _setup(monkeypatch, g, cancer)
    out = r.patient_cn_summary_for_gene("KRAS", "COADREAD")
    assert out["patient_copy_number_class"] == "recurrently_amplified"   # any-gain class
    assert out["patient_focal_cn_class"] == "focal_neutral"              # but NOT focal → verdict-safe


def test_focal_deletion_gates_on_homdel(monkeypatch):
    # 30% homdel (-2) → recurrent_focal_deletion (the TSG analog).
    g = {f"TCGA-05-{i:04d}-01A": (-2 if i < 30 else -1 if i < 60 else 0) for i in range(100)}
    cancer = {f"TCGA-05-{i:04d}": "LUAD" for i in range(100)}
    _setup(monkeypatch, g, cancer)
    out = r.patient_cn_summary_for_gene("CDKN2A", "NSCLC")
    assert out["patient_focal_cn_class"] == "recurrent_focal_deletion"


def test_gene_absent_data_unavailable(monkeypatch):
    monkeypatch.setattr(r, "_read_from_product", lambda t, i: None)
    r._read_gistic_gene.cache_clear()
    monkeypatch.setattr(r, "_read_gistic_gene", lambda target: tuple())  # gene not in GISTIC
    monkeypatch.setattr(r, "_load_sample_cancer_types", lambda: {"TCGA-A1-0001": "BRCA"})
    out = r.patient_cn_summary_for_gene("MADEUPGENE", "BRCA")
    assert out["patient_copy_number_class"] == "data_unavailable"
