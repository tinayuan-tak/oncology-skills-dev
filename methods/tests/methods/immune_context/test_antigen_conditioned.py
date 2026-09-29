"""immune_context.antigen_conditioned — antigen-conditioned effector stat (pure, no S3).

Pins the antigen-tertile split, the antigen-high-vs-low CD8 comparison, the antigen_high_is_colder
escape flag, and the small-n / empty guards. The S3 barcode↔UUID join is live-smoked separately.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pytest.importorskip("pandas")
import pandas as pd

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.immune_context.antigen_conditioned import (  # noqa: E402
    COLD_IN_HIGH_DELTA,
    antigen_conditioned_summary,
)


def _pts(pairs):
    """pairs: list of (antigen_tpm, cd8_fraction)."""
    return pd.DataFrame([{"antigen_tpm": a, "cd8_fraction": c} for a, c in pairs])


def test_antigen_high_immune_hot_when_high_subset_inflamed():
    # antigen-high tertile (top ~third by tpm) has high CD8 → hot + not colder than low
    pts = _pts(
        [
            (1, 0.05),
            (2, 0.05),
            (3, 0.05),
            (4, 0.06),
            (5, 0.06),
            (6, 0.06),
            (7, 0.05),
            (8, 0.06),
            (100, 0.16),
            (110, 0.17),
            (120, 0.18),
            (130, 0.17),
        ]
    )  # top tertile tpm→ high cd8 ~0.17
    r = antigen_conditioned_summary(pts)
    assert r["antigen_high_immune_context_class"] == "immune_hot"
    assert r["antigen_conditioned_call"] == "antigen_high_immune_hot"
    assert r["cd8_high_minus_low"] > 0


def test_antigen_high_is_colder_flag():
    # the failure mode: antigen-HIGH patients are T-cell POORER than antigen-low (effector escape)
    pts = _pts(
        [
            (1, 0.16),
            (2, 0.15),
            (3, 0.17),
            (4, 0.16),
            (5, 0.15),
            (6, 0.16),
            (7, 0.16),
            (8, 0.15),
            (100, 0.05),
            (110, 0.04),
            (120, 0.05),
            (130, 0.05),
        ]
    )  # high tpm → LOW cd8
    r = antigen_conditioned_summary(pts)
    assert r["cd8_high_minus_low"] <= -COLD_IN_HIGH_DELTA
    assert r["antigen_conditioned_call"] == "antigen_high_is_colder"


def test_empty_is_data_unavailable():
    r = antigen_conditioned_summary(pd.DataFrame())
    assert r["antigen_conditioned_call"] == "data_unavailable"
    assert r["n_patients_joined"] == 0


def test_too_few_patients_is_data_unavailable():
    r = antigen_conditioned_summary(_pts([(1, 0.1), (2, 0.2)]))  # n<10 → cannot tertile-split
    assert r["antigen_conditioned_call"] == "data_unavailable"
    assert r["n_patients_joined"] == 2


def test_missing_columns_is_data_unavailable():
    assert antigen_conditioned_summary(pd.DataFrame([{"foo": 1}]))["antigen_conditioned_call"] == "data_unavailable"


def test_nan_rows_dropped():
    import numpy as np

    pts = _pts([(1, 0.05)] * 5 + [(100, 0.16)] * 5)
    pts.loc[0, "cd8_fraction"] = np.nan  # one NaN dropped, still >=10? 9 left → data_unavailable
    r = antigen_conditioned_summary(pts)
    assert r["n_patients_joined"] == 9  # NaN row dropped
