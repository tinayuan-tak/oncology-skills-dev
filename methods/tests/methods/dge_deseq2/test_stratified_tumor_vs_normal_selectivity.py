"""read_stratified_tumor_vs_normal_selectivity — the read side of unblocking the
`tumor-vs-normal-selectivity` card for molecular subgroups (2026-08-18).

Pins three invariants:
  1. _stratum_row_to_card_fields maps the parquet's uppercase cell tags
     (log2fc_A/padj_A) to the lowercase card/classifier names and REUSES the
     whole-cohort classifier + comparator-concordance, so a stratum's
     selectivity_class means exactly what it means whole-cohort.
  2. evidence_state honours the subgroup-n floor (SUBGROUP_N_FLOOR=30):
     a stratum below it reads `underpowered` and is excluded from the
     cross-stratum divergence judgement.
  3. The end-to-end reader projects one record per stratum + the cross-stratum
     reducer scalars, and returns status='data_unavailable' (never raises) when
     the product is genuinely absent.

The end-to-end test writes a synthetic tall parquet and points the reader at it
by monkeypatching s3_uri_for → local path + pyarrow S3FileSystem → LocalFileSystem.
Hermetic: no network, no real S3.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pyarrow as pa
import pyarrow.fs as pafs
import pyarrow.parquet as pq
import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

read = importlib.import_module("methods.dge_deseq2.read")
from methods.subgroup_common.panorama import SUBGROUP_N_FLOOR  # noqa: E402

# ── unit: per-stratum projection reuses the whole-cohort classifier ──────────


def _series(**kw):
    import pandas as pd

    base = dict(
        gene_symbol="FOLR1",
        cells_ran=3,
        cells_supporting=3,
        dominant_direction="up",
        sig_all_cells=True,
        discordant=False,
        log2fc_A=1.8,
        padj_A=1e-8,
        log2fc_C=2.0,
        padj_C=1e-9,
        max_abs_log2fc=2.0,
        stratum_id="MSI_H",
        subgroup_axis="msi_status",
        subgroup_n_tumor=38,
        n_adjacent=41,
        n_gtex=308,
    )
    base.update(kw)
    return pd.Series(base)


def test_projection_maps_cells_and_reuses_strong_classifier():
    rec = read._stratum_row_to_card_fields(_series())
    # uppercase → lowercase mapping
    assert rec["log2fc_cell_a"] == 1.8
    assert rec["q_value_cell_c"] == 1e-9
    # classifier reuse: 3/3 up, raw A & C >= 1.5 → strong
    assert rec["selectivity_class"] == "strong_tumor_selective"
    # both families significant same direction → concordant
    assert rec["comparator_concordance"] == "concordant"
    assert rec["stratum"] == "MSI_H"


def test_evidence_state_respects_subgroup_floor():
    above = read._stratum_row_to_card_fields(_series(subgroup_n_tumor=SUBGROUP_N_FLOOR))
    below = read._stratum_row_to_card_fields(_series(subgroup_n_tumor=SUBGROUP_N_FLOOR - 1))
    absent = read._stratum_row_to_card_fields(_series(subgroup_n_tumor=0))
    assert above["evidence_state"] == "measured"
    assert below["evidence_state"] == "underpowered"
    assert absent["evidence_state"] == "absent"


def test_projection_handles_skipped_cell_nan():
    # A stratum where cell C was skipped (NaN) must not crash and must not count C. (Cell B was
    # removed in analysis-methods#727 and is no longer mapped at all.)
    rec = read._stratum_row_to_card_fields(_series(log2fc_C=float("nan"), padj_C=float("nan")))
    assert rec["log2fc_cell_c"] is None
    # cell A alone still carries it: A=1.8 sig-up, adjacent-only → strong
    assert rec["selectivity_class"] == "strong_tumor_selective"


# ── end-to-end: synthetic parquet through the S3-shaped reader ───────────────


def _write_synthetic_product(tmp_path: Path) -> Path:
    """Two strata for FOLR1: MSI_H strong (n=38), MSS modest (n=193)."""
    rows = {
        "gene_symbol": ["FOLR1", "FOLR1"],
        "cells_ran": [3, 3],
        "cells_supporting": [3, 2],
        "dominant_direction": ["up", "up"],
        "sig_all_cells": [True, False],
        "discordant": [False, False],
        "log2fc_A": [1.8, 0.6],
        "padj_A": [1e-8, 1e-3],
        "log2fc_C": [2.0, 0.7],
        "padj_C": [1e-9, 1e-3],
        "max_abs_log2fc": [2.0, 0.7],
        "stratum_id": ["MSI_H", "MSS"],
        "subgroup_axis": ["msi_status", "msi_status"],
        "subgroup_n_tumor": [38, 193],
        "n_adjacent": [41, 41],
        "n_gtex": [308, 308],
    }
    p = tmp_path / "sensitivity_by_subgroup.parquet"
    pq.write_table(pa.table(rows), p)
    return p


def test_reader_projects_strata_and_reduces(tmp_path, monkeypatch):
    p = _write_synthetic_product(tmp_path)
    monkeypatch.setattr(read, "s3_uri_for", lambda mid: str(p))
    # Reader uses the process-wide _get_s3fs() singleton; point it at the local FS.
    monkeypatch.setattr(read, "_get_s3fs", lambda: pafs.LocalFileSystem())

    out = read.read_stratified_tumor_vs_normal_selectivity("FOLR1", "COADREAD")
    assert out["status"] == "live"
    assert out["subgroup_axis"] == "msi_status"
    assert len(out["per_subgroup_metrics"]) == 2
    classes = out["selectivity_class_by_subgroup"]
    assert classes["MSI_H"] == "strong_tumor_selective"
    assert classes["MSS"] == "modest_tumor_selective"
    # reducer: max/min/delta of max_abs_log2fc across measured strata
    assert out["max_subgroup_log2fc"] == 2.0
    assert out["min_subgroup_log2fc"] == 0.7
    assert out["cross_subgroup_delta_log2fc"] == pytest.approx(1.3)
    # both strata clear the n=30 floor → measured; classes differ → divergence
    assert out["cross_subgroup_selectivity_divergence"] is True
    assert out["any_subgroup_strong_selective"] is True


def test_reader_absent_product_returns_data_unavailable(monkeypatch):
    def _raise(mid):
        raise FileNotFoundError(mid)

    monkeypatch.setattr(read, "s3_uri_for", _raise)
    out = read.read_stratified_tumor_vs_normal_selectivity("FOLR1", "NOPE")
    assert out["status"] == "data_unavailable"
    assert out["per_subgroup_metrics"] == []
    assert out["n_subgroups_with_data"] == 0
