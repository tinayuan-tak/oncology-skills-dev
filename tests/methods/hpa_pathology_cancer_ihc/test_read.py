"""hpa_pathology_cancer_ihc.read — mapping + absence discipline (hermetic; no S3 for the guards)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.hpa_pathology_cancer_ihc.read import (  # noqa: E402
    read_target_summary,
    INDICATION_TO_HPA_CANCER,
)


def test_no_indication_is_data_unavailable():
    """HPA IHC presence is per cancer type — no indication → honest data_unavailable, never a crash."""
    s = read_target_summary("ERBB2", None)
    assert s["protein_presence_class"] == "data_unavailable"
    assert "indication" in s["_data_note"].lower()


def test_unmapped_indication_is_data_unavailable():
    """An OncoTree code with no HPA cancer-type mapping → data_unavailable (never a wrong-cancer fallback)."""
    s = read_target_summary("ERBB2", "ZZZ_NOT_A_CODE")
    assert s["protein_presence_class"] == "data_unavailable"
    assert s["hpa_cancer_type"] is None


def test_no_target_is_data_unavailable():
    s = read_target_summary("", "BRCA")
    assert s["protein_presence_class"] == "data_unavailable"


def test_key_indications_are_mapped():
    """Pin the crosswalk for the framework's core indications (coarse HPA types)."""
    assert INDICATION_TO_HPA_CANCER["BRCA"] == "breast cancer"
    assert INDICATION_TO_HPA_CANCER["COADREAD"] == "colorectal cancer"
    assert INDICATION_TO_HPA_CANCER["LUAD"] == "lung cancer"  # coarse: no LUAD/LUSC split
    assert INDICATION_TO_HPA_CANCER["LUSC"] == "lung cancer"
    assert INDICATION_TO_HPA_CANCER["PAAD"] == "pancreatic cancer"
    assert INDICATION_TO_HPA_CANCER["GBM"] == "glioma"
