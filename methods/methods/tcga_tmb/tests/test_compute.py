"""Unit tests for tcga_tmb.compute — synthetic MAF, no file I/O."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tcga_tmb.compute import (  # noqa: E402
    NONSYNONYMOUS_CLASSES,
    compute_tmb,
    patient_key,
)


@pytest.mark.parametrize(
    "barcode, expected",
    [
        ("TCGA-05-4244-01A-11R-2326-07", "TCGA-05-4244"),
        ("TCGA-05-4244-01", "TCGA-05-4244"),
        ("TCGA-ZZ-1234", "TCGA-ZZ-1234"),
        ("not-a-barcode", None),
        (None, None),
        (42, None),
    ],
)
def test_patient_key(barcode, expected):
    assert patient_key(barcode) == expected


def _maf(rows):
    return pd.DataFrame(rows, columns=["Variant_Classification", "Tumor_Sample_Barcode"])


def test_counts_only_nonsynonymous():
    """Silent / UTR / Intron must NOT count toward TMB; coding classes do."""
    maf = _maf(
        [
            ("Missense_Mutation", "TCGA-AA-0001-01"),
            ("Nonsense_Mutation", "TCGA-AA-0001-01"),
            ("Silent", "TCGA-AA-0001-01"),  # excluded
            ("3'UTR", "TCGA-AA-0001-01"),  # excluded
            ("Intron", "TCGA-AA-0001-01"),  # excluded
        ]
    )
    tmb = compute_tmb(maf, exome_mb=1.0, high_threshold=10.0)
    row = tmb[tmb["patient_key"] == "TCGA-AA-0001"].iloc[0]
    assert row["n_nonsyn"] == 2  # only the 2 coding-altering variants


def test_bucket_threshold():
    """tmb_bucket flips at the threshold; per-Mb divides by exome size."""
    # 20 missense in a 2 Mb exome → 10 mut/Mb → exactly high at threshold 10.
    maf = _maf([("Missense_Mutation", "TCGA-BB-0002-01")] * 20)
    tmb = compute_tmb(maf, exome_mb=2.0, high_threshold=10.0)
    row = tmb.iloc[0]
    assert row["tmb_mut_per_mb"] == 10.0
    assert row["tmb_bucket"] == "high"  # >= threshold
    # 19 → 9.5 mut/Mb → low
    maf2 = _maf([("Missense_Mutation", "TCGA-BB-0002-01")] * 19)
    assert compute_tmb(maf2, exome_mb=2.0, high_threshold=10.0).iloc[0]["tmb_bucket"] == "low"


def test_zero_mutation_sample_is_low_not_missing():
    """A sample with only silent variants → n_nonsyn=0, bucket=low (assayed negative)."""
    maf = _maf(
        [
            ("Silent", "TCGA-CC-0003-01"),
            ("Missense_Mutation", "TCGA-DD-0004-01"),
        ]
    )
    tmb = compute_tmb(maf, exome_mb=1.0)
    c3 = tmb[tmb["patient_key"] == "TCGA-CC-0003"].iloc[0]
    assert c3["n_nonsyn"] == 0
    assert c3["tmb_bucket"] == "low"
    # both samples present (silent-only sample is not dropped)
    assert set(tmb["patient_key"]) == {"TCGA-CC-0003", "TCGA-DD-0004"}


def test_aggregates_aliquots_to_patient():
    """Multiple aliquots of one patient collapse to a single patient_key row."""
    maf = _maf(
        [
            ("Missense_Mutation", "TCGA-EE-0005-01A-11D-1234-01"),
            ("Missense_Mutation", "TCGA-EE-0005-01A-21D-5678-02"),
        ]
    )
    tmb = compute_tmb(maf, exome_mb=1.0)
    assert len(tmb) == 1
    assert tmb.iloc[0]["patient_key"] == "TCGA-EE-0005"
    assert tmb.iloc[0]["n_nonsyn"] == 2


def test_nonsynonymous_set_is_coding():
    """Guardrail: the nonsynonymous set excludes non-coding classes."""
    for excluded in ["Silent", "Intron", "3'UTR", "5'UTR", "RNA", "3'Flank", "5'Flank"]:
        assert excluded not in NONSYNONYMOUS_CLASSES
    for included in ["Missense_Mutation", "Nonsense_Mutation", "Splice_Site", "Frame_Shift_Del", "Frame_Shift_Ins"]:
        assert included in NONSYNONYMOUS_CLASSES
