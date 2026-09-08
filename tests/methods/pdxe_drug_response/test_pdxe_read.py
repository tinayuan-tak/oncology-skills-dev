"""Hermetic (credential-less) tests for the pdxe_drug_response per-gene reader.

Monkeypatches the S3 read (`_read_gene_row`) so the summariser + absence discipline + response-class
logic run offline. VERDICT-INERT display reader; pins the per-gene PDX-response shape, the
responder-fraction-driven class, the indication-ignored target-grain, and the data_unavailable paths.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from methods.pdxe_drug_response import read as R  # noqa: E402

_COLS = [
    "gene_symbol",
    "n_treatments",
    "n_models_tested",
    "n_response_records",
    "median_best_avg_response",
    "min_best_avg_response",
    "responder_fraction",
    "most_active_treatment",
    "most_active_treatment_median_best_avg_response",
    "treatment_types",
]


def _df(rows):
    return pd.DataFrame(rows, columns=_COLS)


def _braf_like():
    # BRAF-like: an active in-vivo signal (median shrinkage, some objective responders).
    return _df([["BRAF", 6, 40, 88, -11.1, -55.2, 0.34, "LEE011 + encorafenib", -22.4, "single|combo"]])


def test_summary_shape_and_responders_class(monkeypatch):
    monkeypatch.setattr(R, "_read_gene_row", lambda target: _braf_like())
    out = R.read_target_summary("BRAF", indication="SKCM")
    assert out["pdx_drug_response_class"] == "pdx_objective_responders"
    assert out["n_treatments"] == 6
    assert out["n_models_tested"] == 40
    assert out["n_response_records"] == 88
    assert out["median_best_avg_response"] == -11.1
    assert out["min_best_avg_response"] == -55.2
    assert out["responder_fraction"] == 0.34
    assert out["most_active_treatment"] == "LEE011 + encorafenib"
    assert out["most_active_treatment_median_best_avg_response"] == -22.4
    assert out["treatment_types"] == "single|combo"
    assert out["source"] == R.SOURCE
    # the substantive (non-underscore) emit set is EXACTLY the card's summary_fields set
    assert {k for k in out if not k.startswith("_")} == {
        "pdx_drug_response_class",
        "n_treatments",
        "n_models_tested",
        "n_response_records",
        "median_best_avg_response",
        "min_best_avg_response",
        "responder_fraction",
        "most_active_treatment",
        "most_active_treatment_median_best_avg_response",
        "treatment_types",
        "source",
    }


def test_no_objective_response_class(monkeypatch):
    # measured, but zero mRECIST CR/PR responders -> the honest 'measured, no objective response' class.
    df = _df([["MDM2", 2, 20, 30, 28.8, 5.1, 0.0, "HDM201", 24.0, "single"]])
    monkeypatch.setattr(R, "_read_gene_row", lambda target: df)
    out = R.read_target_summary("MDM2")  # indication omitted (target-grain)
    assert out["pdx_drug_response_class"] == "pdx_no_objective_response"
    assert out["responder_fraction"] == 0.0


def test_indication_is_ignored_target_grain(monkeypatch):
    # same gene, different indications -> identical payload (the rollup has no per-indication split).
    monkeypatch.setattr(R, "_read_gene_row", lambda target: _braf_like())
    a = R.read_target_summary("BRAF", indication="SKCM")
    b = R.read_target_summary("BRAF", indication="COADREAD")
    assert a == b


def test_nan_response_fields_round_to_none(monkeypatch):
    df = _df([["EGFR", 1, 5, 5, np.nan, np.nan, np.nan, "erlotinib", np.nan, "single"]])
    monkeypatch.setattr(R, "_read_gene_row", lambda target: df)
    out = R.read_target_summary("EGFR")
    assert out["pdx_drug_response_class"] == "pdx_response_unavailable"
    assert out["median_best_avg_response"] is None
    assert out["responder_fraction"] is None


def test_gene_absent_and_no_product(monkeypatch):
    monkeypatch.setattr(R, "_read_gene_row", lambda target: _df([]))
    absent = R.read_target_summary("ZZZ")
    assert absent["pdx_drug_response_class"] == "data_unavailable"
    assert "not a PDXE" in absent["_data_note"]
    monkeypatch.setattr(R, "_read_gene_row", lambda target: None)
    no_prod = R.read_target_summary("BRAF")
    assert no_prod["pdx_drug_response_class"] == "data_unavailable"
    assert "No landed PDXE" in no_prod["_data_note"]


def test_no_target_supplied():
    assert R.read_target_summary("")["pdx_drug_response_class"] == "data_unavailable"
