"""Hermetic (credential-less) tests for the ici_response per-gene reader.

Monkeypatches the S3 read (`_read_gene_rows`) so the summariser + absence discipline + melanoma-scope
guard run offline. VERDICT-INERT display reader; pins the per-gene ICI-association shape, the
rollup-direction class, the significance flag, the melanoma-scope ceiling, and data_unavailable paths.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from methods.ici_response import read as R  # noqa: E402


_COLS = ["gene_symbol", "cohort", "indication", "ici_agent",
         "log2fc_resp_vs_nonresp", "mannwhitney_p", "higher_in",
         "stouffer_z", "stouffer_p", "n_cohorts_concordant"]


def _df(rows):
    return pd.DataFrame(rows, columns=_COLS)


def _cd8_like():
    # two per-cohort rows + the pan-melanoma-rollup meta-row (CD8A-like: higher in responders)
    return _df([
        ["CD8A", "riaz-gse91061", "SKCM", "nivolumab",     1.26, 0.09, "responder",
         np.nan, np.nan, np.nan],
        ["CD8A", "hugo-gse78220", "SKCM", "pembrolizumab", 1.01, 0.20, "responder",
         np.nan, np.nan, np.nan],
        ["CD8A", "pan-melanoma-rollup", "SKCM", "anti-PD-1", 1.14, 0.04, "responder",
         2.10, 0.036, 2],
    ])


def test_summary_shape_and_rollup_direction(monkeypatch):
    monkeypatch.setattr(R, "_read_gene_rows", lambda target: _cd8_like())
    out = R.read_target_summary("CD8A", indication="SKCM")
    assert out["ici_response_class"] == "higher_in_responders"
    assert out["direction_higher_in"] == "responder"
    assert out["median_log2fc_resp_vs_nonresp"] == 1.14   # rollup log2fc
    assert out["rollup_stouffer_p"] == 0.036
    assert out["rollup_stouffer_z"] == 2.10
    assert out["n_cohorts_concordant"] == 2
    assert out["n_cohorts"] == 2
    assert out["cohorts"] == ["hugo-gse78220", "riaz-gse91061"]
    assert out["ici_agents"] == ["nivolumab", "pembrolizumab"]
    # per-cohort min p is 0.09 (rollup row excluded from the per-cohort significance scan) → not sig
    assert out["any_cohort_significant"] is False
    assert out["min_mannwhitney_p"] == 0.09
    assert out["indication"] == "SKCM"
    assert out["product_id"] == R.MANIFEST_ID
    assert {k for k in out if not k.startswith("_")} == {
        "ici_response_class", "direction_higher_in", "median_log2fc_resp_vs_nonresp",
        "rollup_stouffer_z", "rollup_stouffer_p", "n_cohorts_concordant", "n_cohorts",
        "any_cohort_significant", "min_mannwhitney_p", "cohorts", "ici_agents",
        "indication", "product_id"}


def test_higher_in_nonresponders_and_significance_flag(monkeypatch):
    df = _df([
        ["VEGFA", "riaz-gse91061", "SKCM", "nivolumab", -0.80, 0.01, "non_responder",
         np.nan, np.nan, np.nan],
        ["VEGFA", "pan-melanoma-rollup", "SKCM", "anti-PD-1", -0.60, 0.03, "non_responder",
         -1.9, 0.05, 1],
    ])
    monkeypatch.setattr(R, "_read_gene_rows", lambda target: df)
    out = R.read_target_summary("VEGFA", indication="SKCM")
    assert out["ici_response_class"] == "higher_in_nonresponders"
    assert out["any_cohort_significant"] is True     # riaz p=0.01 < 0.05
    assert out["min_mannwhitney_p"] == 0.01


def test_no_rollup_uses_single_cohort(monkeypatch):
    df = _df([["GENE", "riaz-gse91061", "SKCM", "nivolumab", 0.0, 0.9, "tie",
               np.nan, np.nan, np.nan]])
    monkeypatch.setattr(R, "_read_gene_rows", lambda target: df)
    out = R.read_target_summary("GENE", indication="SKCM")
    assert out["ici_response_class"] == "no_ici_association"
    assert out["rollup_stouffer_p"] is None
    assert out["n_cohorts_concordant"] is None


def test_non_melanoma_indication_out_of_scope(monkeypatch):
    # scope guard fires BEFORE any read → melanoma-only product
    called = {"n": 0}
    def _boom(target):  # noqa: ANN001
        called["n"] += 1
        return _cd8_like()
    monkeypatch.setattr(R, "_read_gene_rows", _boom)
    out = R.read_target_summary("CD8A", indication="COADREAD")
    assert out["ici_response_class"] == "data_unavailable"
    assert "out of scope" in out["_data_note"]
    assert called["n"] == 0


def test_gene_absent_and_no_product(monkeypatch):
    monkeypatch.setattr(R, "_read_gene_rows", lambda target: _df([]))
    assert R.read_target_summary("ZZZ", indication="SKCM")["ici_response_class"] == "data_unavailable"
    monkeypatch.setattr(R, "_read_gene_rows", lambda target: None)
    assert R.read_target_summary("CD8A", indication="SKCM")["ici_response_class"] == "data_unavailable"
