"""Absence discipline (#832 second pass) for expression_purity_confound.read.

read_tumor_samples_with_case already applies the absence discipline internally (genuine absence -> an
EMPTY frame; transient/creds re-raised), so genuine absence arrives as an empty frame and the reader's
len(expr)==0 guard yields purity_confound_class=data_unavailable (the fire-able absence branch). The
broad masking except was removed, so a transient fault now PROPAGATES.
"""

from __future__ import annotations

import pandas as pd
import pytest
from botocore.exceptions import ClientError

import onc_methods.tcga_gtex_expression_distribution.read as tg
from onc_methods.expression_purity_confound import read as R


def test_genuine_absence_empty_frame_is_data_unavailable(monkeypatch):
    monkeypatch.setattr(tg, "read_tumor_samples_with_case", lambda s, i: pd.DataFrame(columns=["case", "log2_tpm"]))
    out = R.read_expression_purity_confound("EGFR", "COADREAD")
    assert out["purity_confound_class"] == "data_unavailable"


def test_transient_fault_propagates(monkeypatch):
    def _boom(s, i):
        raise ClientError({"Error": {"Code": "SlowDown"}}, "GetObject")

    monkeypatch.setattr(tg, "read_tumor_samples_with_case", _boom)
    with pytest.raises(ClientError):
        R.read_expression_purity_confound("EGFR", "COADREAD")
