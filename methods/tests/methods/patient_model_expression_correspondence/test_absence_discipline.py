"""Absence discipline (#832 second pass) for patient_model_expression_correspondence.read.

Genuine absence is converted by load_depmap_files_for_card4 into its errs channel + empty returns and
handled by the `if errs or not tpm_by_model` guard (covered by
test_recommended_models.py::test_data_unavailable_paths -> correspondence_class=data_unavailable). The
broad masking except was removed, so a transient / creds fault raised by the loader now PROPAGATES (an
honest _live_read_error at the compose seam) instead of being laundered into data_unavailable.
"""

from __future__ import annotations

import pytest

import onc_methods.depmap_expression_dependency.cli as c4
import onc_methods.tcga_gtex_expression_distribution.read as pt
from onc_methods.patient_model_expression_correspondence import read as R


def test_transient_load_fault_propagates(monkeypatch):
    # Patient TPM present so we reach the DepMap load seam.
    monkeypatch.setattr(pt, "read_tumor_samples", lambda t, i: [4.0] * 10)

    def _boom(release_pin, target_symbol):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(c4, "load_depmap_files_for_card4", _boom)
    with pytest.raises(RuntimeError, match="s3 down"):
        R.read_recommended_models("X", "COADREAD")
