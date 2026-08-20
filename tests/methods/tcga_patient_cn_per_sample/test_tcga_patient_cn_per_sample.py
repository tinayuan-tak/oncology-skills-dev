"""Hermetic tests for tcga_patient_cn_per_sample (no S3): barcode-hierarchy helpers +
indication-cohort filtering + absence discipline of the reader."""
from __future__ import annotations

from methods.tcga_patient_cn_per_sample import build, read


def test_barcode_to_case_truncates_to_three_segments():
    # DNA aliquot barcode -> 3-segment CASE barcode (the CN<->expression join key).
    assert build._barcode_to_case("TCGA-OR-A5J1-01A-11D-A29H-01") == "TCGA-OR-A5J1"
    assert build._barcode_to_sample("TCGA-OR-A5J1-01A-11D-A29H-01") == "TCGA-OR-A5J1-01A"


def test_barcode_helpers_degrade_on_short_input():
    assert build._barcode_to_case("TCGA-OR") == "TCGA-OR"
    assert build._barcode_to_sample("TCGA-OR-A5J1") == "TCGA-OR-A5J1"  # only 3 segs -> returned as-is


def _stub_rows():
    # (case_barcode, gistic_call, cancer_type)
    return (
        ("TCGA-A6-0001", 2, "COAD"),
        ("TCGA-A6-0002", -2, "READ"),
        ("TCGA-A6-0003", 0, "BRCA"),
        ("TCGA-A6-0004", 1, "LUAD"),
    )


def test_indication_filter_restricts_to_cohort(monkeypatch):
    monkeypatch.setattr(read, "_read_gene", lambda t: _stub_rows())
    # COADREAD -> COAD + READ only
    out = read.read_patient_cn_per_sample("ERBB2", "COADREAD")
    assert out == {"TCGA-A6-0001": 2, "TCGA-A6-0002": -2}
    # NSCLC -> LUAD + LUSC
    assert read.read_patient_cn_per_sample("ERBB2", "NSCLC") == {"TCGA-A6-0004": 1}


def test_no_indication_returns_pancancer(monkeypatch):
    monkeypatch.setattr(read, "_read_gene", lambda t: _stub_rows())
    out = read.read_patient_cn_per_sample("ERBB2", None)
    assert set(out) == {"TCGA-A6-0001", "TCGA-A6-0002", "TCGA-A6-0003", "TCGA-A6-0004"}


def test_unknown_indication_falls_back_to_pancancer(monkeypatch):
    monkeypatch.setattr(read, "_read_gene", lambda t: _stub_rows())
    out = read.read_patient_cn_per_sample("ERBB2", "NOT_A_REAL_INDICATION")
    assert len(out) == 4


def test_absent_gene_returns_empty(monkeypatch):
    monkeypatch.setattr(read, "_read_gene", lambda t: tuple())
    assert read.read_patient_cn_per_sample("MADEUPGENE", "COADREAD") == {}
