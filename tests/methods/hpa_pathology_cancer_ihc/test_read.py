"""hpa_pathology_cancer_ihc.read — mapping + absence discipline (hermetic; no S3 for the guards)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.hpa_pathology_cancer_ihc import read as ihc_read  # noqa: E402
from methods.hpa_pathology_cancer_ihc.read import (  # noqa: E402
    _READ_COLUMNS,
    _SUMMARY_FIELDS,
    INDICATION_TO_HPA_CANCER,
    _resolve_s3fs_credentials,
    read_target_summary,
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


def test_read_columns_projection_covers_consumed_fields():
    """The S3 column projection must include every summary field returned to the caller plus the
    in-Python row selector `cancer_type` — a missing projected column would KeyError/None-out."""
    for field in _SUMMARY_FIELDS:
        assert field in _READ_COLUMNS
    assert "cancer_type" in _READ_COLUMNS


def test_missing_default_profile_falls_back_to_ambient(monkeypatch):
    """cbg is a dev SSO profile absent in CI/prod/instance-role hosts. With no AWS_PROFILE set and the
    default profile unconfigured, credential resolution must fall back to the ambient chain — never
    raise ProfileNotFound (which would leave the pyarrow read path dead in a non-cbg env)."""
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    monkeypatch.setattr(ihc_read, "DEFAULT_AWS_PROFILE", "definitely-not-a-real-profile-xyz")
    # Must NOT raise: returns S3FileSystem cred kwargs (or {} when no ambient creds resolve here).
    creds = _resolve_s3fs_credentials()
    assert isinstance(creds, dict)
    assert set(creds).issubset({"access_key", "secret_key", "session_token"})


def test_missing_env_profile_falls_back_to_ambient(monkeypatch):
    """AWS_PROFILE pointing at an unconfigured profile must fall back, not crash."""
    monkeypatch.setenv("AWS_PROFILE", "definitely-not-a-real-profile-xyz")
    creds = _resolve_s3fs_credentials()
    assert isinstance(creds, dict)
    assert set(creds).issubset({"access_key", "secret_key", "session_token"})
