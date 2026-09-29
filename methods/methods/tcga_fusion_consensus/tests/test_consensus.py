"""Tests for build_consensus() in tcga_fusion_consensus.cli.

Uses synthetic long-form DataFrames — no file I/O, no S3.
Exercises: caller aggregation, outer-join merge, n_events NaN→0 fill,
callers_supporting list, caller_count, tissue majority-vote.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from tcga_fusion_consensus.cli import build_consensus  # noqa: E402

CANONICAL_COLS = [
    "sample_key",
    "gene_symbol",
    "tissue",
    "caller_count",
    "callers_supporting",
    "partners_tumorfusions",
    "partners_gao_2018",
    "partners_cbioportal",
    "frame_preds_tumorfusions",
    "frame_preds_gao_2018",
    "frame_preds_cbioportal",
    "n_events_tumorfusions",
    "n_events_gao_2018",
    "n_events_cbioportal",
]


def _long_row(sample_key, gene, partner, side, tissue, frame, caller, eid):
    return {
        "sample_key": sample_key,
        "gene_symbol": gene,
        "partner_gene": partner,
        "partner_side": side,
        "tissue": tissue,
        "frame_pred": frame,
        "caller": caller,
        "event_id": eid,
    }


def _mk(*rows):
    return pd.DataFrame(rows)


# ---------- three-caller unanimous case -----------------------------------


def test_three_caller_alk():
    """ALK in sample S1: all three callers agree → caller_count == 3."""
    rows = [
        _long_row("TCGA-50-8460-01", "ALK", "EML4", "3prime", "LUAD", "In-frame", "tumorfusions", "e1"),
        _long_row("TCGA-50-8460-01", "ALK", "EML4", "3prime", "LUAD", None, "gao_2018", "e2"),
        _long_row("TCGA-50-8460-01", "ALK", "EML4", "3prime", "LUAD", "In_frame", "cbioportal", "e3"),
    ]
    df = build_consensus(_mk(*rows))
    assert list(df.columns) == CANONICAL_COLS
    assert len(df) == 1
    row = df.iloc[0]
    assert row["caller_count"] == 3
    assert set(row["callers_supporting"]) == {"tumorfusions", "gao_2018", "cbioportal"}
    assert row["n_events_tumorfusions"] == 1
    assert row["n_events_gao_2018"] == 1
    assert row["n_events_cbioportal"] == 1
    assert "EML4" in row["partners_tumorfusions"]
    assert row["tissue"] == "LUAD"


# ---------- single-caller case (caller_count == 1) ------------------------


def test_single_caller_fills_zeros():
    """A (sample, gene) seen only in tumorfusions: other callers get n_events==0,
    partners/frame_preds == [], callers_supporting length == 1."""
    rows = [
        _long_row("TCGA-AA-0001-01", "NTRK1", "TPM3", "3prime", "LUAD", "In-frame", "tumorfusions", "x1"),
    ]
    df = build_consensus(_mk(*rows))
    assert len(df) == 1
    row = df.iloc[0]
    assert row["caller_count"] == 1
    assert row["callers_supporting"] == ["tumorfusions"]
    assert row["n_events_tumorfusions"] == 1
    assert row["n_events_gao_2018"] == 0
    assert row["n_events_cbioportal"] == 0
    assert row["partners_gao_2018"] == []
    assert row["partners_cbioportal"] == []
    assert row["frame_preds_gao_2018"] == []
    assert row["frame_preds_cbioportal"] == []


# ---------- two-caller case (caller_count == 2) ---------------------------


def test_two_caller_ros1():
    rows = [
        _long_row("TCGA-BB-0002-01", "ROS1", "CD74", "3prime", "LUAD", "In-frame", "tumorfusions", "r1"),
        _long_row("TCGA-BB-0002-01", "ROS1", "CD74", "3prime", "LUAD", "In_frame", "cbioportal", "r2"),
    ]
    df = build_consensus(_mk(*rows))
    row = df.iloc[0]
    assert row["caller_count"] == 2
    assert "tumorfusions" in row["callers_supporting"]
    assert "cbioportal" in row["callers_supporting"]
    assert "gao_2018" not in row["callers_supporting"]
    assert row["n_events_gao_2018"] == 0


# ---------- multiple events, distinct partners deduplication ---------------


def test_distinct_partners_deduplicated():
    """Two rows from the same caller with SAME partner → partners list has length 1."""
    rows = [
        _long_row("TCGA-CC-0003-01", "ALK", "EML4", "3prime", "LUAD", "In-frame", "tumorfusions", "t1"),
        _long_row("TCGA-CC-0003-01", "ALK", "EML4", "3prime", "LUAD", "In-frame", "tumorfusions", "t2"),
        _long_row("TCGA-CC-0003-01", "ALK", "EML4", "3prime", "LUAD", None, "gao_2018", "g1"),
    ]
    df = build_consensus(_mk(*rows))
    row = df.iloc[0]
    assert row["n_events_tumorfusions"] == 2  # two raw rows
    assert row["partners_tumorfusions"] == ["EML4"]  # deduped to 1


def test_multiple_distinct_partners():
    """Two different partners from the same caller → partners list has length 2."""
    rows = [
        _long_row("TCGA-DD-0004-01", "ALK", "EML4", "3prime", "LUAD", "In-frame", "tumorfusions", "t1"),
        _long_row("TCGA-DD-0004-01", "ALK", "NPM1", "3prime", "LUAD", "In-frame", "tumorfusions", "t2"),
    ]
    df = build_consensus(_mk(*rows))
    row = df.iloc[0]
    assert len(row["partners_tumorfusions"]) == 2
    assert set(row["partners_tumorfusions"]) == {"EML4", "NPM1"}


# ---------- tissue majority-vote ------------------------------------------


def test_tissue_majority_vote():
    """Two callers say LUAD, one says None → majority is LUAD."""
    rows = [
        _long_row("TCGA-EE-0005-01", "ALK", "EML4", "3prime", "LUAD", None, "tumorfusions", "t1"),
        _long_row("TCGA-EE-0005-01", "ALK", "EML4", "3prime", None, None, "gao_2018", "g1"),
        _long_row("TCGA-EE-0005-01", "ALK", "EML4", "3prime", "LUAD", None, "cbioportal", "c1"),
    ]
    df = build_consensus(_mk(*rows))
    assert df.iloc[0]["tissue"] == "LUAD"


# ---------- multiple samples, multiple genes --------------------------------


def test_multiple_samples_sorted():
    rows = [
        _long_row("TCGA-ZZ-9999-01", "FGFR3", "TACC3", "5prime", "LUSC", "In-frame", "tumorfusions", "t1"),
        _long_row("TCGA-AA-0001-01", "RET", "KIF5B", "3prime", "LUAD", "In-frame", "gao_2018", "g1"),
    ]
    df = build_consensus(_mk(*rows))
    assert len(df) == 2
    # sorted by sample_key then gene_symbol
    assert df.iloc[0]["sample_key"] == "TCGA-AA-0001-01"
    assert df.iloc[1]["sample_key"] == "TCGA-ZZ-9999-01"


# ---------- empty input edge case -----------------------------------------


def test_empty_input():
    empty = pd.DataFrame(
        columns=[
            "sample_key",
            "gene_symbol",
            "partner_gene",
            "partner_side",
            "tissue",
            "frame_pred",
            "caller",
            "event_id",
        ]
    )
    df = build_consensus(empty)
    assert list(df.columns) == CANONICAL_COLS
    assert len(df) == 0


# ---------- frame_preds deduplication -------------------------------------


def test_frame_preds_deduplicated():
    rows = [
        _long_row("TCGA-FF-0006-01", "ALK", "EML4", "3prime", "LUAD", "In-frame", "tumorfusions", "t1"),
        _long_row("TCGA-FF-0006-01", "ALK", "EML4", "3prime", "LUAD", "In-frame", "tumorfusions", "t2"),
        _long_row("TCGA-FF-0006-01", "ALK", "EML4", "3prime", "LUAD", "Frame-shift", "tumorfusions", "t3"),
    ]
    df = build_consensus(_mk(*rows))
    fps = df.iloc[0]["frame_preds_tumorfusions"]
    assert len(fps) == 2
    assert "In-frame" in fps
    assert "Frame-shift" in fps
