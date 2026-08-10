"""pancanatlas_ddr_context — hermetic tests (synthetic per-indication frame, no S3).

Pins the classifier thresholds + the alias-pooling (COADREAD = COAD+READ, sample-weighted) + the
data_unavailable path. The live HRD biology (OV enriched, THCA/GBM low) is verified in the build step,
not here (hermetic = no network)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.pancanatlas_ddr_context.cli import _classify, HRD_ENRICHED_FRAC, HRD_INTERMEDIATE_FRAC, MIN_COHORT_N  # noqa: E402
from methods.pancanatlas_ddr_context import read as ddr_read  # noqa: E402


def test_classify_tiers():
    assert _classify(200, 0.55) == "hrd_enriched"        # OV-like
    assert _classify(200, 0.30) == "hrd_enriched"        # boundary (>=)
    assert _classify(200, 0.20) == "hrd_intermediate"    # BRCA-like
    assert _classify(200, 0.10) == "hrd_intermediate"    # boundary
    assert _classify(200, 0.02) == "hrd_low"             # THCA-like
    assert _classify(200, 0.0) == "hrd_low"


def test_underpowered_cohort_is_data_unavailable():
    assert _classify(MIN_COHORT_N - 1, 0.9) == "data_unavailable"   # tiny cohort, never a high call


def test_alias_pooling_sample_weighted(monkeypatch):
    """COADREAD pools COAD+READ with a sample-weighted HRD fraction, then re-classifies on the pool."""
    import pandas as pd
    fake = pd.DataFrame([
        {"indication": "COAD", "n_samples": 300, "median_hrd_score": 10.0, "frac_hrd_high": 0.02,
         "ddr_context_class": "hrd_low"},
        {"indication": "READ", "n_samples": 100, "median_hrd_score": 15.0, "frac_hrd_high": 0.06,
         "ddr_context_class": "hrd_low"},
    ])
    monkeypatch.setattr(ddr_read, "_load_product", lambda: fake)
    out = ddr_read.read_ddr_deficiency_context(indication="COADREAD")
    assert out["n_samples"] == 400
    # weighted frac = (0.02*300 + 0.06*100)/400 = 0.03
    assert abs(out["frac_hrd_high"] - 0.03) < 1e-6
    assert out["ddr_context_class"] == "hrd_low"
    assert sorted(out["pooled_from"]) == ["COAD", "READ"]


def test_unmapped_indication_is_data_unavailable(monkeypatch):
    import pandas as pd
    monkeypatch.setattr(ddr_read, "_load_product",
                        lambda: pd.DataFrame([{"indication": "OV", "n_samples": 173,
                                               "median_hrd_score": 44.0, "frac_hrd_high": 0.55,
                                               "ddr_context_class": "hrd_enriched"}]))
    out = ddr_read.read_ddr_deficiency_context(indication="ZZZ_NOT_A_CANCER")
    assert out["ddr_context_class"] == "data_unavailable"


def test_missing_indication_arg_is_data_unavailable():
    out = ddr_read.read_ddr_deficiency_context(indication=None)
    assert out["ddr_context_class"] == "data_unavailable"
