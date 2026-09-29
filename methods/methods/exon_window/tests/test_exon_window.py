"""Tests for the per-exon tumor-vs-normal window classifier (E5). Pure — synthetic exon frames.

Pins the classifier bands + the live-smoke-driven design fixes: (1) best exon = TUMOR-DOMINANT
(not max-window), so heterogeneity is >= 0 by construction (the CLDN18-negative-heterogeneity bug);
(2) exon_heterogeneity_flag is the HYPOTHESIS band; (3) essential_exon_liability / uniform /
cohort-honesty / not_in_product coverage-gap."""

from __future__ import annotations

import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))
import pandas as pd  # noqa: E402

from methods.exon_window import classify as c  # noqa: E402


def _log2(tpm):
    return math.log2(tpm + 1.0)


def _rows(exon_tumor_tpm: dict, ess_tpm: dict, study="COAD", ess_tissue="LIVER"):
    r = []
    for e, t in exon_tumor_tpm.items():
        r.append(
            {
                "exon_id": e,
                "gene_symbol": "TESTG",
                "gene_id": "ENSG1",
                "source": "tcga_tumor",
                "group": study,
                "median": _log2(t),
            }
        )
    for e, v in ess_tpm.items():
        r.append(
            {
                "exon_id": e,
                "gene_symbol": "TESTG",
                "gene_id": "ENSG1",
                "source": "gtex_normal",
                "group": ess_tissue,
                "median": _log2(v),
            }
        )
    return pd.DataFrame(r)


def test_exon_heterogeneity_flag_is_the_marquee_band():
    """One exon high in tumor + LOW essential-normal + far above the gene's other exons →
    the hypothesis flag (candidate for isoform-resolved follow-up)."""
    tumor = {"E1": 0.2, "E2": 0.3, "E3": 200.0, "E4": 0.4}  # E3 dominant + stands out
    ess = {"E1": 0.1, "E2": 0.1, "E3": 0.2, "E4": 0.1}
    out = c.compute_exon_window_from_rows(
        _rows(tumor, ess), "COADREAD", tier_threshold_tpm=c.MODALITY_TIER_THRESHOLD["bite_tce"]
    )
    assert out["exon_window_class"] == "exon_heterogeneity_flag"
    assert out["best_exon_id"] == "E3"
    assert out["best_exon_window_ratio"] >= c.CLEAN_WINDOW_RATIO
    assert out["exon_heterogeneity_log2"] >= c.EXON_HETEROGENEITY_LOG2


def test_best_exon_is_tumor_dominant_heterogeneity_never_negative():
    """The live-smoke bug: best exon must be the MAX-TUMOR exon (so heterogeneity >= 0), NOT the
    max-window exon (which could be a low-tumor exon → negative heterogeneity)."""
    # E_low has a huge window (normal~0) but tiny tumor; E_hi is the tumor-dominant exon.
    tumor = {"E_hi": 300.0, "E_mid": 50.0, "E_low": 0.5}
    ess = {"E_hi": 0.2, "E_mid": 0.2, "E_low": 0.0001}  # E_low window enormous but must NOT be chosen
    out = c.compute_exon_window_from_rows(_rows(tumor, ess), "COADREAD")
    assert out["best_exon_id"] == "E_hi"  # tumor-dominant, not max-window E_low
    assert out["exon_heterogeneity_log2"] >= 0.0  # never negative


def test_uniform_gene_window_when_exons_behave_the_same():
    tumor = {"E1": 50.0, "E2": 55.0, "E3": 48.0}
    ess = {"E1": 0.2, "E2": 0.2, "E3": 0.2}
    out = c.compute_exon_window_from_rows(_rows(tumor, ess), "COADREAD")
    assert out["exon_window_class"] == "uniform_gene_window"
    assert out["exon_heterogeneity_log2"] < c.EXON_HETEROGENEITY_LOG2


def test_essential_exon_liability_when_dominant_exon_dirty():
    tumor = {"E1": 100.0, "E2": 0.3}
    ess = {"E1": 5.0, "E2": 0.1}  # dominant E1 essential-normal 5.0 >= bite_tce 1.0
    out = c.compute_exon_window_from_rows(
        _rows(tumor, ess), "COADREAD", tier_threshold_tpm=c.MODALITY_TIER_THRESHOLD["bite_tce"]
    )
    assert out["exon_window_class"] == "essential_exon_liability"


def test_not_expressed_in_cohort_is_honest():
    out = c.compute_exon_window_from_rows(_rows({"E1": 0.2, "E2": 0.1}, {"E1": 0.05, "E2": 0.05}), "COADREAD")
    assert out["exon_window_class"] == "not_expressed_in_cohort"


def test_absent_gene_is_not_in_product_not_a_negative():
    out = c.compute_exon_window_from_rows(pd.DataFrame(), "COADREAD")
    assert out["exon_window_class"] == "not_in_product"


def test_unmapped_indication_is_data_unavailable():
    out = c.compute_exon_window_from_rows(_rows({"E1": 100.0}, {"E1": 0.1}), "NOTREAL")
    assert out["exon_window_class"] == "data_unavailable"


def test_adc_tier_more_permissive_than_bite():
    tumor = {"E1": 200.0, "E2": 0.3}
    ess = {"E1": 3.0, "E2": 0.1}
    bite = c.compute_exon_window_from_rows(
        _rows(tumor, ess), "COADREAD", tier_threshold_tpm=c.MODALITY_TIER_THRESHOLD["bite_tce"]
    )
    adc = c.compute_exon_window_from_rows(
        _rows(tumor, ess), "COADREAD", tier_threshold_tpm=c.MODALITY_TIER_THRESHOLD["adc"]
    )
    assert bite["exon_window_class"] == "essential_exon_liability"
    assert adc["exon_window_class"] in ("exon_heterogeneity_flag", "uniform_gene_window")


def test_contract_fields_present():
    out = c.compute_exon_window_from_rows(_rows({"E1": 200.0, "E2": 0.3}, {"E1": 0.1, "E2": 0.1}), "COADREAD")
    for f in (
        "exon_window_class",
        "n_exons",
        "best_exon_id",
        "best_exon_tumor_tpm",
        "best_exon_max_essential_tpm",
        "best_exon_window_ratio",
        "exon_heterogeneity_log2",
        "modality_tier_threshold_tpm",
        "tumor_studies",
    ):
        assert f in out
