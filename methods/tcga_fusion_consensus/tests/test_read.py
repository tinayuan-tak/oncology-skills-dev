"""Tests for tcga_fusion_consensus.read — no file I/O required.

Uses synthetic DataFrames injected directly into the normalization logic
to verify: barcode normalization, each loader's canonical schema, and the
assayed-samples denominator helpers.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tcga_fusion_consensus.read import (  # noqa: E402
    sample_key,
    load_tumorfusions,
    load_gao_2018,
    load_cbioportal_sv,
    tumorfusions_assayed_samples,
    gao_2018_assayed_samples,
)


# ---------- sample_key normalization --------------------------------------

CANONICAL_SCHEMA = [
    "sample_key",
    "gene_symbol",
    "partner_gene",
    "partner_side",
    "tissue",
    "frame_pred",
    "caller",
    "event_id",
]


@pytest.mark.parametrize(
    "barcode, expected",
    [
        # TumorFusions/Gao: sample + vial
        ("TCGA-05-4244-01A", "TCGA-05-4244-01"),
        # Gao: full aliquot
        ("TCGA-05-4244-01A-11R-A29S-07", "TCGA-05-4244-01"),
        # TumorFusions: full aliquot
        ("TCGA-50-8460-01A-11R-2326-07", "TCGA-50-8460-01"),
        # cBioPortal: already sample-level (no vial)
        ("TCGA-05-4244-01", "TCGA-05-4244-01"),
        # Numeric sample type 11 (normal)
        ("TCGA-ZZ-1234-11A", "TCGA-ZZ-1234-11"),
        # Garbage
        ("not-a-tcga-barcode", None),
        ("", None),
        (None, None),
        (123, None),
    ],
)
def test_sample_key(barcode, expected):
    assert sample_key(barcode) == expected


# ---------- load_tumorfusions (mock pd.read_excel) ------------------------


def _make_tumorfusions_df():
    """Minimal File007 'Cancer fusions' content (3 rows)."""
    return pd.DataFrame(
        {
            "Tissue": ["LUAD", "LUAD", "LUSC"],
            "Sample": ["TCGA-50-8460-01A-11R-2326-07", "TCGA-05-4244-01A", "TCGA-66-2756-01A"],
            "Gene_A": ["EML4", "KIF5B", "FGFR3"],
            "Gene_B": ["ALK", "RET", "TACC3"],
            "Frame Prediction": ["In-frame", "In-frame", "In-frame"],
        }
    )


def test_load_tumorfusions_schema():
    with patch("tcga_fusion_consensus.read.pd.read_excel", return_value=_make_tumorfusions_df()):
        df = load_tumorfusions("fake.xlsx")
    assert list(df.columns) == CANONICAL_SCHEMA
    assert df["caller"].unique().tolist() == ["tumorfusions"]
    # 3 events × 2 sides = 6 rows
    assert len(df) == 6


def test_load_tumorfusions_sample_key_normalization():
    with patch("tcga_fusion_consensus.read.pd.read_excel", return_value=_make_tumorfusions_df()):
        df = load_tumorfusions("fake.xlsx")
    assert (df["sample_key"] == df["sample_key"].str.extract(r"^(TCGA-[A-Z0-9]+-[A-Z0-9]+-\d{2})$")[0]).all()


def test_load_tumorfusions_drops_null_sample_key():
    bad = _make_tumorfusions_df().copy()
    bad.loc[0, "Sample"] = "NOT_A_TCGA_BARCODE"
    with patch("tcga_fusion_consensus.read.pd.read_excel", return_value=bad):
        df = load_tumorfusions("fake.xlsx")
    # Row 0 dropped (both sides), so 2 events × 2 = 4 rows
    assert len(df) == 4


def test_load_tumorfusions_drops_null_gene():
    bad = _make_tumorfusions_df().copy()
    bad.loc[1, "Gene_A"] = None
    with patch("tcga_fusion_consensus.read.pd.read_excel", return_value=bad):
        df = load_tumorfusions("fake.xlsx")
    # Row 1 has no Gene_A; the 5prime copy for row 1 should be dropped
    # (3prime copy still has gene_symbol=Gene_B=RET which is non-null)
    five_prime = df[df["partner_side"] == "5prime"]
    assert "KIF5B" not in five_prime["gene_symbol"].values


# ---------- load_gao_2018 (mock pd.read_excel) ----------------------------


def _make_gao_df():
    """Minimal 'Final fusion call set' content (2 rows, after skiprows=1)."""
    return pd.DataFrame(
        {
            "Cancer": ["LUAD", "LUSC"],
            "Sample": ["TCGA-05-4244-01A-11R-A29S-07", "TCGA-66-2756-01A-11R-2235-07"],
            "Fusion": ["EML4--ALK", "FGFR3--TACC3"],
            "Junction": [10, 20],
            "Spanning": [5, 8],
            "Breakpoint1": ["chr2:29", "chr4:1"],
            "Breakpoint2": ["chr2:42", "chr4:1"],
        }
    )


def test_load_gao_schema():
    with patch("tcga_fusion_consensus.read.pd.read_excel", return_value=_make_gao_df()):
        df = load_gao_2018("fake.xlsx")
    assert list(df.columns) == CANONICAL_SCHEMA
    assert df["caller"].unique().tolist() == ["gao_2018"]
    assert df["frame_pred"].isna().all()  # Gao doesn't publish frame predictions
    # 2 events × 2 sides = 4 rows
    assert len(df) == 4


def test_load_gao_fusion_parse():
    """EML4--ALK should produce gene_symbol=EML4 partner=ALK (5prime) and vice-versa (3prime)."""
    with patch("tcga_fusion_consensus.read.pd.read_excel", return_value=_make_gao_df()):
        df = load_gao_2018("fake.xlsx")
    five_prime = df[(df["partner_side"] == "5prime") & (df["tissue"] == "LUAD")]
    assert five_prime["gene_symbol"].iloc[0] == "EML4"
    assert five_prime["partner_gene"].iloc[0] == "ALK"


def test_load_gao_drops_nan_gene():
    """Rows where the Fusion string parse produces 'nan' should be dropped."""
    bad = _make_gao_df().copy()
    bad.loc[0, "Fusion"] = "nan--ALK"
    with patch("tcga_fusion_consensus.read.pd.read_excel", return_value=bad):
        df = load_gao_2018("fake.xlsx")
    # The 5prime gene_symbol='nan' should be filtered; 3prime gene_symbol='ALK' survives
    five_prime_eml4 = df[(df["partner_side"] == "5prime") & (df["gene_symbol"] == "nan")]
    assert len(five_prime_eml4) == 0


# ---------- load_cbioportal_sv (in-memory, no gzip mock) ------------------


def _cbio_rows():
    return [
        {
            "sampleId": "TCGA-50-8460-01",
            "site1HugoSymbol": "EML4",
            "site2HugoSymbol": "ALK",
            "site2EffectOnFrame": "In_frame",
        },
        {
            "sampleId": "TCGA-XX-0001-01",
            "site1HugoSymbol": "ROS1",
            "site2HugoSymbol": "CD74",
            "site2EffectOnFrame": None,
        },
        {
            "sampleId": None,
            "site1HugoSymbol": "FGFR3",
            "site2HugoSymbol": "TACC3",
            "site2EffectOnFrame": "In_frame",
        },  # null sampleId → should be dropped
    ]


def test_load_cbioportal_sv_schema(tmp_path):
    import gzip, json

    sv_file = tmp_path / "structural_variants.jsonl.gz"
    with gzip.open(sv_file, "wt") as f:
        for r in _cbio_rows():
            f.write(json.dumps(r) + "\n")
    df = load_cbioportal_sv(sv_file, "luad_tcga_pan_can_atlas_2018")
    assert list(df.columns) == CANONICAL_SCHEMA
    assert df["caller"].unique().tolist() == ["cbioportal"]
    assert df["tissue"].unique().tolist() == ["LUAD"]
    # 2 valid events × 2 sides = 4 rows (null sampleId row dropped)
    assert len(df) == 4


def test_load_cbioportal_sv_frame_replicated(tmp_path):
    """site2EffectOnFrame should appear on BOTH the 5prime and 3prime rows."""
    import gzip, json

    sv_file = tmp_path / "structural_variants.jsonl.gz"
    with gzip.open(sv_file, "wt") as f:
        f.write(json.dumps(_cbio_rows()[0]) + "\n")
    df = load_cbioportal_sv(sv_file, "luad_tcga_pan_can_atlas_2018")
    assert (df["frame_pred"] == "In_frame").all()


# ---------- assayed-samples denominators ----------------------------------


def _make_file006_df():
    return pd.DataFrame(
        {
            "Disease": ["LUAD", "LUAD", "LUSC"],
            "barcode": ["TCGA-50-8460-01A-11R-2326-07", "TCGA-05-4244-01A-11R-A29S-07", "TCGA-66-2756-01A"],
        }
    )


def test_tumorfusions_assayed_samples_schema():
    with patch("tcga_fusion_consensus.read.pd.read_excel", return_value=_make_file006_df()):
        df = tumorfusions_assayed_samples("fake.xlsx")
    assert set(df.columns) == {"sample_key", "tissue", "caller"}
    assert (df["caller"] == "tumorfusions").all()
    assert len(df) == 3


def _make_gao_samples_df():
    return pd.DataFrame(
        {
            "Sample": ["TCGA-05-4244-01A-11R-A29S-07", "TCGA-66-2756-01A"],
            "Cancer": ["LUAD", "LUSC"],
        }
    )


def test_gao_assayed_samples_schema():
    with patch("tcga_fusion_consensus.read.pd.read_excel", return_value=_make_gao_samples_df()):
        df = gao_2018_assayed_samples("fake.xlsx")
    assert set(df.columns) == {"sample_key", "tissue", "caller"}
    assert (df["caller"] == "gao_2018").all()
    assert len(df) == 2
