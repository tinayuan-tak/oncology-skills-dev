"""pmhc_presentation.classify — peptide-centric HLA-presentation classifier (pure, no S3).

Pins the inverted safety semantics (broad normal presentation = liability), the atlas-anchored bands,
and the MS-asymmetry rule (absent = weak-negative not_observed, never a confirmed non-presenter).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import pytest  # noqa: E402

from methods.pmhc_presentation.classify import (  # noqa: E402
    classify_pmhc_presentation,
    summarize_pmhc,
    RESTRICTED_MAX_TISSUES,
    BROAD_MIN_TISSUES,
    _ATLAS_N_TISSUES_QUARTILES,
)


# ── the n_tissues bands (inverted: low = clean, high = safety liability) ──────
def test_restricted_is_clean_peptide_target():
    # MAGE-A4 archetype: presented, but on 1 normal tissue (testis) → restricted / TCE-favorable
    assert classify_pmhc_presentation(3, 1) == "restricted_presentation"
    assert classify_pmhc_presentation(3, RESTRICTED_MAX_TISSUES) == "restricted_presentation"


def test_broadly_presented_is_safety_liability():
    # KRAS-like: presented on many normal tissues → broad on-target/off-tumor risk for a pMHC TCE
    assert classify_pmhc_presentation(13, 14) == "intermediate_presentation"  # 14 is between Q1 and Q3
    assert classify_pmhc_presentation(20, BROAD_MIN_TISSUES) == "broadly_presented_normal"
    assert classify_pmhc_presentation(20, 29) == "broadly_presented_normal"


def test_intermediate_band():
    assert classify_pmhc_presentation(6, 12) == "intermediate_presentation"  # PRAME-like


def test_zero_peptides_is_not_observed():
    assert classify_pmhc_presentation(0, 0) == "not_observed"


def test_none_is_data_unavailable():
    assert classify_pmhc_presentation(None, 5) == "data_unavailable"
    assert classify_pmhc_presentation(5, None) == "data_unavailable"


# ── summarize + MS asymmetry (absent protein = weak-negative, not data_unavailable) ──
def test_summarize_row():
    row = {
        "n_peptides": 3,
        "n_tissues": 1,
        "tissues": "testis",
        "hla_class": "HLA-I",
        "n_strong_binder_peptides": 2,
        "n_weak_binder_peptides": 1,
    }
    s = summarize_pmhc(row)
    assert s["pmhc_presentation_class"] == "restricted_presentation"
    assert s["n_normal_tissues_presented"] == 1
    assert s["hla_class"] == "HLA-I"
    assert s["n_strong_binder_peptides"] == 2


def test_summarize_absent_protein_is_weak_negative_not_observed():
    # MS asymmetry: absence from the benign atlas is a WEAK negative (tumor-restricted candidate),
    # never data_unavailable and never a confirmed non-presenter.
    s = summarize_pmhc(None)
    assert s["pmhc_presentation_class"] == "not_observed"
    assert s["n_presented_peptides"] == 0
    assert "WEAK-negative" in s["_note"] and "candidate" in s["_note"].lower()


def test_broadly_presented_summary():
    row = {
        "n_peptides": 13,
        "n_tissues": 22,
        "tissues": "a;b;c",
        "hla_class": "HLA-I+II",
        "n_strong_binder_peptides": 5,
        "n_weak_binder_peptides": 3,
    }
    assert summarize_pmhc(row)["pmhc_presentation_class"] == "broadly_presented_normal"


# ── band constants are single-sourced from the quartile provenance tuple (no dual hardcoding) ──
def test_bands_derive_from_quartile_provenance():
    assert RESTRICTED_MAX_TISSUES == _ATLAS_N_TISSUES_QUARTILES[0]  # Q1
    assert BROAD_MIN_TISSUES == _ATLAS_N_TISSUES_QUARTILES[2]  # Q3


@pytest.mark.requires_data
def test_quartile_provenance_matches_atlas():
    """DRIFT-GUARD: recompute the source-atlas n_tissues quartiles from the LIVE product and assert they
    still equal the pinned _ATLAS_N_TISSUES_QUARTILES the classifier bands derive from. If the atlas is
    ever refreshed and the distribution shifts, this fails and forces a recompute of the constants in
    classify.py — the bands must never silently classify against a stale cutpoint. Credential-less CI
    xfails this (live read degrades); locally with AWS_PROFILE=cbg it validates the provenance claim."""
    import numpy as np
    import pyarrow.parquet as pq
    import pyarrow.fs as pafs
    from methods.pmhc_presentation.read import S3_BUCKET, PAYLOAD_KEY

    s3 = pafs.S3FileSystem(region="us-east-1")
    n = (
        pq.read_table(f"{S3_BUCKET}/{PAYLOAD_KEY}", columns=["n_tissues"], filesystem=s3)
        .to_pandas()["n_tissues"]
        .dropna()
        .astype(int)
    )
    assert len(n) == 15262, (
        f"atlas protein count changed ({len(n)} != 15262) — atlas was refreshed; recompute quartiles"
    )
    q1, med, q3 = (int(round(np.percentile(n, p))) for p in (25, 50, 75))
    assert (q1, med, q3) == _ATLAS_N_TISSUES_QUARTILES, (
        f"atlas n_tissues quartiles drifted to {(q1, med, q3)} != pinned {_ATLAS_N_TISSUES_QUARTILES}; "
        f"update _ATLAS_N_TISSUES_QUARTILES in classify.py"
    )
