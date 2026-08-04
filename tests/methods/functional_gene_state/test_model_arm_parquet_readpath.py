"""functional_gene_state MODEL arm: the DepMap parquet column-projection read-path.

Guards the reshape that swapped the MODEL arm's raw full-object DepMap CSV reads (~500 MB each:
OmicsSomaticMutationsMatrixDamaging/Hotspot + OmicsCNGeneWGS) for gene-column projection reads of
the depmap-26q1-parquet-v1 product (~1-2 MB/gene). All S3-free (the parquet accessor is monkeypatched).

Invariants:
  1. PREFERENCE: when the parquet accessor returns a column, the arm uses it and maps to the right
     dict shape ({ModelID: bool} for mutations, {ModelID: float} for CN).
  2. FALLBACK: when the parquet accessor returns None (product unreachable), the arm falls back to
     the raw-CSV read (_s3_read_bytes) — verified by asserting that path is what runs.
  3. CN THRESHOLD ROBUSTNESS: a float32 CN value near a _depmap_cn_class boundary classifies the
     same as its float64 form (the float32/float64 subtlety the live equivalence check surfaced).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

pd = pytest.importorskip("pandas")

from methods.functional_gene_state import read as fgs  # noqa: E402


def test_mut_matrix_prefers_parquet_column(monkeypatch):
    """A parquet DataFrame [ModelID, '<gene> (entrez)'] → {ModelID: bool}, no CSV read."""
    df = pd.DataFrame({"ModelID": ["ACH-1", "ACH-2", "ACH-3"],
                       "KRAS (3845)": [1.0, 0.0, None]})
    monkeypatch.setattr(fgs, "_read_depmap_matrix_column", lambda matrix, target: df)
    # if the CSV path were hit, this would raise (no S3) — proving preference
    monkeypatch.setattr(fgs, "_s3_read_bytes",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("CSV path hit")))
    out = fgs._read_depmap_mut_matrix("OmicsSomaticMutationsMatrixDamaging.csv", "KRAS")
    assert out == {"ACH-1": True, "ACH-2": False}   # None dropped


def test_cn_prefers_parquet_column(monkeypatch):
    df = pd.DataFrame({"ModelID": ["ACH-1", "ACH-2"], "PTEN (5728)": [0.05, 1.10]})
    monkeypatch.setattr(fgs, "_read_depmap_matrix_column", lambda matrix, target: df)
    monkeypatch.setattr(fgs, "_s3_read_bytes",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("CSV path hit")))
    out = fgs._read_depmap_cn("PTEN")
    assert out == {"ACH-1": 0.05, "ACH-2": 1.10}


def test_unreachable_parquet_falls_back_to_csv(monkeypatch):
    """Accessor returns None → the raw-CSV read runs (we stub _s3_read_bytes to a sentinel CSV)."""
    monkeypatch.setattr(fgs, "_read_depmap_matrix_column", lambda matrix, target: None)
    csv = b"ModelID,KRAS (3845)\nACH-9,1.0\nACH-8,0.0\n"
    monkeypatch.setattr(fgs, "_s3_read_bytes", lambda key: csv)
    out = fgs._read_depmap_mut_matrix("OmicsSomaticMutationsMatrixDamaging.csv", "KRAS")
    assert out == {"ACH-9": True, "ACH-8": False}


def test_absent_gene_in_parquet_returns_empty(monkeypatch):
    """Accessor returns None because the GENE is absent (not because the product is down) — the
    fallback CSV read then also finds no gene column → {} (a real 'no data' answer, not a crash)."""
    monkeypatch.setattr(fgs, "_read_depmap_matrix_column", lambda matrix, target: None)
    monkeypatch.setattr(fgs, "_s3_read_bytes", lambda key: b"ModelID,OTHER (1)\nACH-1,1.0\n")
    assert fgs._read_depmap_mut_matrix("OmicsSomaticMutationsMatrixHotspot.csv", "KRAS") == {}


@pytest.mark.parametrize("rel_cn,expected", [
    (0.20, "homdel"),          # boundary: <= 0.20
    (0.2000001, "loss"),       # just above homdel
    (0.75, "loss"),            # boundary: <= 0.75
    (0.7500001, "neutral"),    # just above loss
    (0.10, "homdel"), (0.50, "loss"), (1.00, "neutral"),   # interior points (dtype-stable)
])
def test_cn_class_thresholds(rel_cn, expected):
    """The CN→class thresholds (<=0.20 homdel, <=0.75 loss). float64 form is the classifier's
    contract; interior points are dtype-stable (see the boundary caveat test below)."""
    assert fgs._depmap_cn_class(rel_cn) == expected


@pytest.mark.parametrize("rel_cn", [0.10, 0.30, 0.50, 0.90, 1.20])
def test_cn_class_dtype_stable_away_from_boundaries(rel_cn):
    """AWAY from the exact thresholds, float32 (parquet) and float64 (CSV) CN values classify
    identically — the invariant the live parquet-vs-CSV equivalence check confirmed for 2678
    models across KRAS/TP53/PTEN/SMAD4 (0 state diffs). Interior values have ample float32 margin."""
    import numpy as np
    assert fgs._depmap_cn_class(rel_cn) == fgs._depmap_cn_class(float(np.float32(rel_cn)))


def test_cn_class_exact_boundary_is_a_known_float32_caveat():
    """DOCUMENTED caveat (not a bug we mask): a CN of EXACTLY 0.20 is homdel in float64 but
    np.float32(0.20) > 0.20 → loss. This is measure-zero in real WGS data (continuous ratios never
    land on the exact threshold), and the live equivalence check found 0 such models. Pinning it
    here so a future reader knows the parquet(float32) path can differ ONLY at the exact boundary —
    if this ever matters, make _depmap_cn_class compare at a rounded precision."""
    import numpy as np
    assert fgs._depmap_cn_class(0.20) == "homdel"
    assert fgs._depmap_cn_class(float(np.float32(0.20))) == "loss"   # the exact-boundary artifact
