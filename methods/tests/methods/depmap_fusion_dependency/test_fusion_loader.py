"""depmap_fusion_dependency.read._load_fusion_involvement — hermetic (synthetic CSV via monkeypatched boto3).

Pins the two loader-specific guarantees the compute test can't see:
  1. SYMBOL-UNION: the target counts as fusion-positive whether it is the 5' (LeftGene) OR the 3'
     (RightGene) partner. Both orientations map to True.
  2. PROFILED-UNIVERSE denominator: fusion-negative = every OTHER line PRESENT in the fusion table.
     Lines never fusion-called (absent from the CSV) must NOT appear in fusion_by_model at all
     (they are excluded/abstain, never counted as negatives), and the IsDefaultEntryForModel filter
     is honored.
Also checks '(entrez)' symbol stripping and the read failure → data_unavailable path.
"""

from __future__ import annotations

from io import BytesIO

import pandas as pd

from onc_methods.depmap_fusion_dependency import read as fread


class _FakeS3:
    def __init__(self, df: pd.DataFrame):
        buf = BytesIO()
        df.to_csv(buf, index=False)
        self._bytes = buf.getvalue()

    def get_object(self, Bucket=None, Key=None):  # noqa: N803 — boto3 signature
        return {"Body": BytesIO(self._bytes)}


def _install_fake_s3(monkeypatch, df: pd.DataFrame):
    import boto3

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _FakeS3(df))


def test_symbol_union_both_orientations(monkeypatch):
    """Target as LeftGene (line1) and as RightGene (line2) both → fusion-positive.
    A line whose fusion involves neither → negative. All 3 are in the profiled universe."""
    df = pd.DataFrame(
        {
            "ModelID": ["ACH-1", "ACH-2", "ACH-3"],
            "LeftGene": ["FLI1 (2313)", "EWSR1 (2130)", "BCR (613)"],
            "RightGene": ["EWSR1 (2130)", "FLI1 (2313)", "ABL1 (25)"],
            "IsDefaultEntryForModel": [True, True, True],
        }
    )
    _install_fake_s3(monkeypatch, df)
    fbm, errs = fread._load_fusion_involvement("FLI1")
    assert errs == []
    assert fbm == {"ACH-1": True, "ACH-2": True, "ACH-3": False}


def test_profiled_universe_only(monkeypatch):
    """fusion_by_model keys are exactly the fusion-PROFILED lines. A Chronos-screened line NOT in
    the fusion table simply never appears here (abstain), so the compute-side intersection excludes it."""
    df = pd.DataFrame(
        {
            "ModelID": ["ACH-1", "ACH-2"],
            "LeftGene": ["ALK", "TPM3"],
            "RightGene": ["EML4", "ALK"],
            "IsDefaultEntryForModel": [True, True],
        }
    )
    _install_fake_s3(monkeypatch, df)
    fbm, errs = fread._load_fusion_involvement("ALK")
    assert errs == []
    assert set(fbm.keys()) == {"ACH-1", "ACH-2"}  # profiled universe only
    assert fbm == {"ACH-1": True, "ACH-2": True}  # ALK on both (Left then Right)


def test_default_entry_filter(monkeypatch):
    """Non-default rows are dropped before the universe is built."""
    df = pd.DataFrame(
        {
            "ModelID": ["ACH-1", "ACH-2", "ACH-3"],
            "LeftGene": ["FLI1", "FLI1", "MYC"],
            "RightGene": ["EWSR1", "EWSR1", "PVT1"],
            "IsDefaultEntryForModel": [True, False, True],
        }
    )
    _install_fake_s3(monkeypatch, df)
    fbm, errs = fread._load_fusion_involvement("FLI1")
    assert errs == []
    assert set(fbm.keys()) == {"ACH-1", "ACH-3"}  # ACH-2 non-default → excluded
    assert fbm == {"ACH-1": True, "ACH-3": False}


def test_read_failure_is_data_unavailable(monkeypatch):
    """S3 failure → (empty dict, error), which read_fusion_stratified_dependency turns into
    fusion_stratification_class == data_unavailable (never a raise)."""
    import boto3

    class _Boom:
        def get_object(self, **k):
            raise RuntimeError("no creds")

    monkeypatch.setattr(boto3, "client", lambda *a, **k: _Boom())
    fbm, errs = fread._load_fusion_involvement("FLI1")
    assert fbm == {}
    assert errs and errs[0]["_live_read_error"] == "fusion_read_failed"
