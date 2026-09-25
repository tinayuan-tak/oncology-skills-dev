"""Q5 RNA↔protein concordance — correlation, rna_as_biomarker classification, gap safety.

No S3: the two per-model readers (RNA card4 loader, protein Gygi loader) are monkeypatched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_rna_protein_concordance import read as R  # noqa: E402


def _wire(monkeypatch, rna_by_model, prot_by_model, accession="P00000", errs=None):
    import methods.depmap_expression_dependency.cli as rna_cli

    monkeypatch.setattr(
        rna_cli, "load_depmap_files_for_card4", lambda release_pin, target_symbol: ({}, rna_by_model, {}, errs or [])
    )
    import methods.depmap_protein_abundance.cli as prot_cli

    monkeypatch.setattr(prot_cli, "resolve_accession", lambda t, sidecar_path=None: accession)
    monkeypatch.setattr(
        prot_cli, "load_abundance_column", lambda acc, matrix_path=None: (prot_by_model, len(prot_by_model))
    )


def test_adequate_proxy_high_correlation(monkeypatch):
    # RNA ≈ protein (tight linear) → adequate_proxy
    ids = [f"ACH-{i:04d}" for i in range(40)]
    rna = {m: float(i % 8) for i, m in enumerate(ids)}
    prot = {m: rna[m] + 0.1 for m in ids}  # near-perfect
    _wire(monkeypatch, rna, prot)
    out = R.read_rna_protein_concordance("EGFR")
    assert out["rna_as_biomarker"] == "adequate_proxy"
    assert out["rna_protein_r"] > 0.7 and out["n_paired_models"] == 40


def test_poor_proxy_decoupled(monkeypatch):
    ids = [f"ACH-{i:04d}" for i in range(40)]
    rna = {m: float(i % 8) for i, m in enumerate(ids)}
    prot = {m: float((i * 37) % 5) for i, m in enumerate(ids)}  # scrambled → low r
    _wire(monkeypatch, rna, prot)
    out = R.read_rna_protein_concordance("X")
    assert out["rna_as_biomarker"] in ("poor_proxy", "partial_proxy")
    assert out["rna_protein_r"] < 0.7


def test_classifies_on_spearman_not_pearson_outlier_inflated(monkeypatch):
    """G10 regression: rna_as_biomarker classifies on SPEARMAN, not Pearson. A single extreme concordant
    outlier over an otherwise-uncorrelated cluster inflates PEARSON above the adequate bar (0.7) while the
    rank (Spearman) correlation is low — the classic Pearson-misleads case. The verdict must follow the
    rank metric (NOT adequate), and rna_protein_r (Pearson, retained) must still read high, proving the
    two metrics diverge and the class tracks Spearman."""
    ids = [f"ACH-{i:04d}" for i in range(40)]
    # 39-point cluster with uncorrelated small jitter + one far concordant outlier at (20, 20)
    rna = {m: (2.0 + (i % 5) * 0.01 if i < 39 else 20.0) for i, m in enumerate(ids)}
    prot = {m: (5.0 + (i % 3) * 0.017 if i < 39 else 20.0) for i, m in enumerate(ids)}
    _wire(monkeypatch, rna, prot)
    out = R.read_rna_protein_concordance("X")
    assert out["rna_protein_r"] > 0.7  # Pearson inflated by the outlier
    assert out["rna_protein_spearman"] < 0.7  # rank correlation is not adequate
    assert out["rna_as_biomarker"] != "adequate_proxy"  # class follows Spearman, not Pearson
    assert out["rna_proxy_classified_on"] == "spearman"


def test_boundary_ci_fragility_flag_G10():
    """G10 refinement: the Fisher-z 95% CI of the classifying r + a verdict-inert boundary-fragility flag.
    A near-boundary r at small n straddles a class boundary (fragile=True); a value far from any boundary
    is not; a wider n narrows the CI. The flag never changes the class (rna_as_biomarker unaffected)."""
    from methods.depmap_rna_protein_concordance import read as R

    # r=0.45 at n=20: sits just above the 0.4 partial/poor boundary, wide CI → straddles 0.4 → fragile
    near = R._proxy_boundary_ci(0.45, 20)
    assert near["rna_protein_r_ci95_low"] < 0.4 < near["rna_protein_r_ci95_high"]
    assert near["rna_proxy_class_boundary_fragile"] is True
    # r=0.95 at n=60: far above 0.7, tight CI → no boundary in range → not fragile
    strong = R._proxy_boundary_ci(0.95, 60)
    assert strong["rna_proxy_class_boundary_fragile"] is False
    # more samples narrow the CI (higher lower-bound) for the same r
    assert R._proxy_boundary_ci(0.45, 200)["rna_protein_r_ci95_low"] > near["rna_protein_r_ci95_low"]
    # under-powered / undefined inputs → None (never a fabricated CI)
    assert R._proxy_boundary_ci(None, 40)["rna_proxy_class_boundary_fragile"] is None
    assert R._proxy_boundary_ci(0.5, 3)["rna_protein_r_ci95_low"] is None


def test_spearman_ci_wider_than_pearson_F3():
    """F3: the classifying r is Spearman, whose Fisher-z SE is ~6% larger than Pearson's, so the CI
    built for a Spearman-classified r must be WIDER than the Pearson-coefficient band at the same r/n
    (default spearman=True); the widened band is what stops fragility being under-reported."""
    r, n = 0.55, 40
    spear = R._proxy_boundary_ci(r, n)  # default: classifying metric (Spearman)
    pear = R._proxy_boundary_ci(r, n, spearman=False)
    assert spear["rna_protein_r_ci95_low"] < pear["rna_protein_r_ci95_low"]
    assert spear["rna_protein_r_ci95_high"] > pear["rna_protein_r_ci95_high"]
    # boundary test-vector unchanged: r=0.45 @ n=20 still straddles 0.4 and stays fragile
    assert R._proxy_boundary_ci(0.45, 20)["rna_proxy_class_boundary_fragile"] is True


def test_detection_limited_qualifier_F1(monkeypatch):
    """F1: a poor/partial class where protein coverage is low (< DETECTION_LIMITED_FRACTION) is flagged
    rna_proxy_detection_limited — the discordance may be an MS detection-floor artifact. Verdict-INERT:
    rna_as_biomarker is unchanged. A high-coverage poor/partial call is NOT flagged."""
    ids = [f"ACH-{i:04d}" for i in range(50)]
    rna = {m: float(i % 8) for i, m in enumerate(ids)}
    prot = {m: float((i * 37) % 5) for i, m in enumerate(ids)}  # scrambled → poor/partial
    # low protein coverage: protein quantified in 22/50 models → detection_fraction 0.44 < 0.5, but
    # still >= MIN_PAIRED_MODELS paired so a class is emitted
    prot_sparse = {m: prot[m] for m in ids[:22]}
    _wire(monkeypatch, rna, prot_sparse)
    out = R.read_rna_protein_concordance("X")
    assert out["rna_as_biomarker"] in ("poor_proxy", "partial_proxy")
    assert out["protein_detection_fraction"] < R.DETECTION_LIMITED_FRACTION
    assert out["rna_proxy_detection_limited"] is True
    # full coverage → same discordant class, but NOT detection-limited
    _wire(monkeypatch, rna, prot)
    out2 = R.read_rna_protein_concordance("X")
    assert out2["protein_detection_fraction"] >= R.DETECTION_LIMITED_FRACTION
    assert out2["rna_proxy_detection_limited"] is False


def test_underpowered_qualifier_near_floor_F2(monkeypatch):
    """F2: a class emitted between MIN_PAIRED_MODELS (20) and the ≥30 confident bar is flagged
    rna_proxy_underpowered (verdict-INERT — the class still emits); at n≥30 it is not."""
    ids = [f"ACH-{i:04d}" for i in range(25)]  # 20 <= n < 30
    rna = {m: float(i % 8) for i, m in enumerate(ids)}
    _wire(monkeypatch, rna, {m: rna[m] + 0.1 for m in ids})
    out = R.read_rna_protein_concordance("EGFR")
    assert out["n_paired_models"] == 25 and out["rna_as_biomarker"] != "insufficient_paired_models"
    assert out["rna_proxy_underpowered"] is True
    ids2 = [f"ACH-{i:04d}" for i in range(35)]  # n >= 30
    rna2 = {m: float(i % 8) for i, m in enumerate(ids2)}
    _wire(monkeypatch, rna2, {m: rna2[m] + 0.1 for m in ids2})
    assert R.read_rna_protein_concordance("EGFR")["rna_proxy_underpowered"] is False


def test_underpowered_paired_models(monkeypatch):
    # fewer than MIN_PAIRED_MODELS with BOTH → insufficient, not a fabricated r
    ids = [f"ACH-{i:04d}" for i in range(10)]
    _wire(monkeypatch, {m: 4.0 for m in ids}, {m: 4.0 for m in ids})
    out = R.read_rna_protein_concordance("X")
    assert out["rna_as_biomarker"] == "insufficient_paired_models"
    assert out["rna_protein_r"] is None and out["n_paired_models"] == 10


def test_data_unavailable_paths(monkeypatch):
    # no RNA
    _wire(monkeypatch, {}, {"ACH-0001": 4.0})
    assert R.read_rna_protein_concordance("X")["rna_as_biomarker"] == "data_unavailable"
    # RNA present but no protein accession
    _wire(monkeypatch, {"ACH-0001": 4.0}, {}, accession=None)
    out = R.read_rna_protein_concordance("X")
    assert out["rna_as_biomarker"] == "data_unavailable"


def test_rna_high_protein_low_population(monkeypatch):
    # all RNA-expressed (but VARIED, so correlation is defined); a subset protein-bottom-decile
    # → nonzero rna_high_protein_low_fraction
    ids = [f"ACH-{i:04d}" for i in range(40)]
    rna = {m: 3.0 + (i % 5) * 0.5 for i, m in enumerate(ids)}  # all >= detectable, varied
    prot = {m: (0.0 if i < 5 else 5.0) for i, m in enumerate(ids)}  # 5 protein-low
    _wire(monkeypatch, rna, prot)
    out = R.read_rna_protein_concordance("X")
    assert out["rna_high_protein_low_fraction"] is not None
    assert out["rna_high_protein_low_fraction"] > 0.0


def test_zero_variance_guard(monkeypatch):
    # a constant arm → undefined correlation → honest gap, not a NaN r
    ids = [f"ACH-{i:04d}" for i in range(40)]
    _wire(monkeypatch, {m: 5.0 for m in ids}, {m: float(i % 7) for i, m in enumerate(ids)})
    out = R.read_rna_protein_concordance("X")
    assert out["rna_as_biomarker"] == "insufficient_paired_models"
    assert out["rna_protein_r"] is None


def test_tumor_arm_concordance(monkeypatch):
    import pandas as pd

    # a COAD cohort matched frame with a clean linear KRAS relationship
    n = 40
    rows = [
        {
            "patient_id": f"01CO{i:03d}",
            "gene": "KRAS",
            "rna_log2tpm": 3.0 + (i % 8) * 0.3,
            "protein_log2abundance": 3.0 + (i % 8) * 0.3 + 0.1,
        }
        for i in range(n)
    ]
    monkeypatch.setattr(R, "_read_matched_cohort", lambda cohort, target=None: pd.DataFrame(rows))
    out = R.read_tumor_rna_protein_concordance("KRAS", "COADREAD")
    assert out["cptac_cohort"] == "coad" and out["substrate"] == "cptac_tumor"
    assert out["rna_as_biomarker"] == "adequate_proxy" and out["n_paired_tumors"] == n
    # unmapped indication → data_unavailable (no CPTAC cohort)
    assert R.read_tumor_rna_protein_concordance("KRAS", "SKCM")["rna_as_biomarker"] == "data_unavailable"


def test_tumor_gene_pushdown_and_projection(monkeypatch):
    """OPT-1: _read_matched_cohort pushes the gene predicate down and projects only the consumed
    columns to the parquet reader, instead of materializing the whole cohort matrix."""
    import pandas as pd
    import pyarrow.parquet as pq

    captured = {}

    def _fake_read_table(path, filesystem=None, columns=None, filters=None):
        captured["columns"] = columns
        captured["filters"] = filters
        return pytest.importorskip("pyarrow").Table.from_pandas(
            pd.DataFrame(columns=["patient_id", "gene", "rna_log2tpm", "protein_log2abundance"])
        )

    monkeypatch.setattr(pq, "read_table", _fake_read_table)
    R._read_matched_cohort("coad", target="kras")
    assert captured["columns"] == ["patient_id", "gene", "rna_log2tpm", "protein_log2abundance"]
    assert ("cohort", "==", "coad") in captured["filters"]
    assert ("gene", "==", "KRAS") in captured["filters"]  # upper()/strip() normalized


def test_tumor_emitter(tmp_path, monkeypatch):
    import importlib

    import pandas as pd

    pytest.importorskip("matplotlib")
    cli = importlib.import_module("methods.depmap_rna_protein_concordance.cli")
    n = 40
    rows = [
        {
            "patient_id": f"01CO{i:03d}",
            "gene": "CDX2",
            "rna_log2tpm": 3.0 + (i % 8) * 0.3,
            "protein_log2abundance": 3.0 + (i % 8) * 0.3 + 0.1,
        }
        for i in range(n)
    ]
    monkeypatch.setattr(R, "_read_matched_cohort", lambda cohort, target=None: pd.DataFrame(rows))
    svg = cli.emit_tumor_svg("CDX2", "COADREAD", tmp_path)
    assert svg is not None and svg.exists()
    specs = cli.emit_tumor_plotly_specs("CDX2", "COADREAD", tmp_path)
    assert [s["id"] for s in specs] == ["rna_protein_concordance_tumor_scatter"]
    # no CPTAC cohort → no figure
    assert cli.emit_tumor_svg("CDX2", "SKCM", tmp_path) is None


def test_tumor_arm_underpowered_and_gap(monkeypatch):
    import pandas as pd

    # fewer than the floor → insufficient_paired_tumors
    rows = [
        {"patient_id": f"p{i}", "gene": "X", "rna_log2tpm": float(i), "protein_log2abundance": float(i)}
        for i in range(5)
    ]
    monkeypatch.setattr(R, "_read_matched_cohort", lambda cohort, target=None: pd.DataFrame(rows))
    assert R.read_tumor_rna_protein_concordance("X", "COADREAD")["rna_as_biomarker"] == "insufficient_paired_tumors"
    # target absent from the cohort → data_unavailable (n==0)
    monkeypatch.setattr(
        R,
        "_read_matched_cohort",
        lambda cohort, target=None: pd.DataFrame(
            columns=["patient_id", "gene", "rna_log2tpm", "protein_log2abundance"]
        ),
    )
    assert R.read_tumor_rna_protein_concordance("GHOST", "COADREAD")["rna_as_biomarker"] == "data_unavailable"


def test_cli_build_and_figure(tmp_path, monkeypatch):
    import importlib

    pytest.importorskip("matplotlib")
    cli = importlib.import_module("methods.depmap_rna_protein_concordance.cli")
    ids = [f"ACH-{i:04d}" for i in range(40)]
    rna = {m: float(i % 8) for i, m in enumerate(ids)}
    _wire(monkeypatch, rna, {m: rna[m] + 0.1 for m in ids})
    s = cli.build_summary("EGFR")
    assert s["rna_as_biomarker"] == "adequate_proxy" and "method_version" in s
    svg = cli.emit_svg("EGFR", None, s, tmp_path)
    assert svg is not None and svg.exists()
    assert [x["id"] for x in cli.emit_plotly_specs("EGFR", None, tmp_path)] == ["rna_protein_concordance_scatter"]
