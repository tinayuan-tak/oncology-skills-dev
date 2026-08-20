"""Hermetic tests for the patient cis-coherence arm (no S3): stubs the three case-keyed readers
and verifies (1) the CN->expression join feeds compute_cis_dosage, (2) case-barcode intersection,
(3) the methylation->expression silencing contrast, (4) honest empty/absence propagation."""
from __future__ import annotations

import numpy as np

from methods.tcga_cis_coherence_patient import cli, read


def _stub(monkeypatch, expr, cn, meth):
    monkeypatch.setattr(read, "read_patient_expression_by_case", lambda t, i: expr)
    monkeypatch.setattr(read, "read_patient_cn_by_case", lambda t, i: cn)
    monkeypatch.setattr(read, "read_patient_methylation_by_case", lambda t, i: meth)


def test_cn_expression_coupling_calls_compute_and_intersects_on_case(monkeypatch):
    # Build a coupled signal: higher GISTIC call -> higher expression across 40 cases.
    rng = np.random.default_rng(0)
    n = 60  # >= MIN_CELL_LINES_FOR_CORRELATION (50); patient cohorts easily clear this
    cases = [f"TCGA-XX-{i:04d}" for i in range(n)]
    cn = {c: int(v) for c, v in zip(cases, rng.integers(-2, 3, size=n))}
    expr = {c: 3.0 + 1.5 * cn[c] + rng.normal(0, 0.2) for c in cases}
    # one CN-only + one expr-only case: must be excluded from the intersection (n_patients_cn_expr==n)
    cn["TCGA-XX-9001"] = 2
    expr["TCGA-XX-9002"] = 9.0
    _stub(monkeypatch, expr, cn, {})
    out = cli.compute_patient_cis_coherence("ERBB2", "BRCA")
    assert out["n_patients_cn_expr"] == n                       # intersection only
    assert out["patient_cis_dosage_class"].startswith("cn_dosage_coupled")  # strong positive rank corr
    assert out["cn_expr_spearman_r"] > 0.5


def test_methylation_silencing_negative_delta(monkeypatch):
    # methylated cases express ~2 log2 units lower -> epigenetic_silencing
    meth_cases = {f"TCGA-M-{i:03d}": True for i in range(8)}
    unmeth_cases = {f"TCGA-U-{i:03d}": False for i in range(8)}
    meth = {**meth_cases, **unmeth_cases}
    expr = {**{c: 1.0 for c in meth_cases}, **{c: 5.0 for c in unmeth_cases}}
    _stub(monkeypatch, expr, {}, meth)
    out = cli.compute_patient_cis_coherence("MLH1", "COADREAD")
    assert out["patient_methylation_silencing_class"] == "epigenetic_silencing"
    assert out["delta_log2tpm_methylated_vs_unmethylated"] == -4.0
    assert out["n_methylated"] == 8 and out["n_unmethylated"] == 8


def test_methylation_no_signal_when_expression_unchanged(monkeypatch):
    meth = {**{f"TCGA-M-{i:03d}": True for i in range(6)},
            **{f"TCGA-U-{i:03d}": False for i in range(6)}}
    expr = {c: 5.0 for c in meth}  # identical expression regardless of methylation
    _stub(monkeypatch, expr, {}, meth)
    out = cli.compute_patient_cis_coherence("GENE", "BRCA")
    assert out["patient_methylation_silencing_class"] == "no_silencing_signal"
    assert out["delta_log2tpm_methylated_vs_unmethylated"] == 0.0


def test_methylation_insufficient_when_too_few_methylated(monkeypatch):
    meth = {"TCGA-M-1": True, **{f"TCGA-U-{i}": False for i in range(10)}}  # only 1 methylated
    expr = {c: 5.0 for c in meth}
    _stub(monkeypatch, expr, {}, meth)
    out = cli.compute_patient_cis_coherence("GENE", "BRCA")
    assert out["patient_methylation_silencing_class"] == "insufficient_methylation_data"


def test_all_empty_propagates_honestly(monkeypatch):
    _stub(monkeypatch, {}, {}, {})
    out = cli.compute_patient_cis_coherence("GENE", "BRCA")
    assert out["patient_cis_dosage_class"] == "data_unavailable"
    assert out["patient_methylation_silencing_class"] == "insufficient_methylation_data"
    assert out["n_patients_cn_expr"] == 0


def test_readers_are_thin_case_keyed_wrappers(monkeypatch):
    # read_patient_expression_by_case averages multi-aliquot cases to one value per case.
    import pandas as pd
    fake = pd.DataFrame({"case": ["TCGA-A-1", "TCGA-A-1", "TCGA-B-2"], "log2_tpm": [2.0, 4.0, 7.0]})
    monkeypatch.setattr(
        "methods.tcga_gtex_expression_distribution.read.read_tumor_samples_with_case",
        lambda t, i: fake)
    out = read.read_patient_expression_by_case("GENE", "BRCA")
    assert out == {"TCGA-A-1": 3.0, "TCGA-B-2": 7.0}
