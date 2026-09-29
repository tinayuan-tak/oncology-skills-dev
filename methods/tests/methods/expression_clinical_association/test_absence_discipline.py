"""Absence discipline (#832 second pass) for expression_clinical_association.read.

read_tumor_samples_with_case already applies the absence discipline internally (genuine absence -> an
EMPTY frame; transient/creds re-raised), so genuine absence arrives as an empty frame and the reader's
len(expr)==0 guard yields survival_association_class=data_unavailable (the fire-able absence branch).
The broad masking except was removed, so a transient fault now PROPAGATES.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest
from botocore.exceptions import ClientError

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import methods.tcga_gtex_expression_distribution.read as tg  # noqa: E402
from methods.expression_clinical_association import read as R  # noqa: E402


def test_genuine_absence_empty_frame_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(tg, "read_tumor_samples_with_case", lambda s, i: pd.DataFrame(columns=["case", "log2_tpm"]))
    out = R.read_expression_clinical_association("EGFR", "COADREAD")
    assert out["survival_association_class"] == "data_unavailable"


def test_transient_fault_propagates(monkeypatch):
    def _boom(s, i):
        raise ClientError({"Error": {"Code": "SlowDown"}}, "GetObject")

    monkeypatch.setattr(tg, "read_tumor_samples_with_case", _boom)
    with pytest.raises(ClientError):
        R.read_expression_clinical_association("EGFR", "COADREAD")
