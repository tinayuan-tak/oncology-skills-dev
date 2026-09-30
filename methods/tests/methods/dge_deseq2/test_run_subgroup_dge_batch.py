"""Pure planning surface of the multi-axis by-subgroup orchestrator (analysis-methods#738).

The orchestrator's two pure, unit-testable pieces:

* `build_rscript_commands` — one `00_load_recount3.R` load (recount3 cached ONCE per indication) +
  one `07_stratified_four_cell_driver.R` run per axis, each carrying the right
  `--axis/--strata/--assignments/--in/--out-dir` flags;
* `concat_axis_parquets` — UNION columns across per-axis shards (missing -> NA), sorted by
  `[stratum_id, gene_symbol]`.

Hermetic: no Rscript, no subprocess, no S3.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from onc_methods.dge_deseq2 import config as cfg
from onc_methods.dge_deseq2 import run_subgroup_dge_batch as rb

_FIXTURE = {
    "TEST": [
        {"axis": "axis1", "assignments_manifest": "m1", "strata": ["S1", "S2"]},
        {"axis": "axis2", "assignments_manifest": "m2", "strata": ["S3"]},
    ]
}


# ── build_rscript_commands ───────────────────────────────────────────────────
def test_build_rscript_commands_one_load_plus_one_driver_per_axis(monkeypatch):
    monkeypatch.setattr(cfg, "subgroup_axes", lambda: _FIXTURE)
    cmds = rb.build_rscript_commands("TEST", Path("/fake/cfg.yaml"), Path("/out"))

    # 1 recount3 load + 2 axis drivers.
    assert len(cmds) == 3

    rds = "/out/00_recount3.rds"
    assert cmds[0] == ["Rscript", str(rb.R_LOAD_RECOUNT3), "--config=/fake/cfg.yaml", f"--out={rds}"]

    assert cmds[1] == [
        "Rscript",
        str(rb.R_STRATIFIED),
        f"--in={rds}",
        f"--assignments={rb._assignments_parquet('m1')}",
        "--axis=axis1",
        "--strata=S1,S2",
        "--min-subgroup-tumor=10",
        "--out-dir=/out/_axis_axis1",
        "--threads=4",
    ]
    assert cmds[2] == [
        "Rscript",
        str(rb.R_STRATIFIED),
        f"--in={rds}",
        f"--assignments={rb._assignments_parquet('m2')}",
        "--axis=axis2",
        "--strata=S3",
        "--min-subgroup-tumor=10",
        "--out-dir=/out/_axis_axis2",
        "--threads=4",
    ]


def test_build_rscript_commands_threads_and_floor_flow_through(monkeypatch):
    monkeypatch.setattr(cfg, "subgroup_axes", lambda: _FIXTURE)
    cmds = rb.build_rscript_commands("TEST", Path("/fake/cfg.yaml"), Path("/out"), min_subgroup_tumor=30, threads=8)
    for cmd in cmds[1:]:
        assert "--min-subgroup-tumor=30" in cmd
        assert "--threads=8" in cmd


def test_build_rscript_commands_accepts_explicit_axes():
    axes = [{"axis": "solo", "assignments_manifest": "mm", "strata": ["X"]}]
    cmds = rb.build_rscript_commands("ANY", Path("/c.yaml"), Path("/o"), axes=axes)
    assert len(cmds) == 2
    assert "--axis=solo" in cmds[1]
    assert "--strata=X" in cmds[1]


# ── concat_axis_parquets ─────────────────────────────────────────────────────
def test_concat_unions_columns_na_fills_and_sorts():
    df1 = pd.DataFrame(
        {
            "stratum_id": ["B", "A"],
            "gene_symbol": ["g2", "g1"],
            "log2fc_A": [1.0, 2.0],
            "log2fc_C": [0.5, 0.6],
        }
    )
    df2 = pd.DataFrame(  # lacks log2fc_C (its cell C was skipped)
        {"stratum_id": ["A"], "gene_symbol": ["g3"], "log2fc_A": [3.0]}
    )
    combined = rb.concat_axis_parquets([df1, df2])

    assert set(combined.columns) == {"stratum_id", "gene_symbol", "log2fc_A", "log2fc_C"}
    # sorted by [stratum_id, gene_symbol]: (A,g1), (A,g3), (B,g2)
    assert list(combined["stratum_id"]) == ["A", "A", "B"]
    assert list(combined["gene_symbol"]) == ["g1", "g3", "g2"]
    # the missing column is NA-filled for the frame that lacked it (g3 came from df2).
    g3 = combined[combined["gene_symbol"] == "g3"]
    assert g3["log2fc_C"].isna().all()
    # a present value survives unchanged.
    g1 = combined[combined["gene_symbol"] == "g1"]
    assert g1["log2fc_C"].iloc[0] == 0.6


def test_concat_empty_raises():
    with pytest.raises(ValueError, match="no per-axis frames"):
        rb.concat_axis_parquets([])


# ── aggregate_subgroup_provenance ────────────────────────────────────────────
def test_aggregate_single_stratum_axis_is_not_char_exploded():
    """A single-stratum axis serialises as a bare YAML scalar in the per-axis provenance; the
    aggregator must keep it a one-element list, NOT iterate the string into characters
    (regression: ``strata_emitted: HER2_amp`` -> ``['H','E','R','2',...]``)."""
    axes = [
        {"axis": "histology", "assignments_manifest": "m1", "strata": ["ESCC", "EAC"]},
        {"axis": "amplification", "assignments_manifest": "m1", "strata": ["HER2_amp"]},
    ]
    per_axis_provs = [
        {
            "strata_emitted": ["ESCC", "EAC"],  # multi -> list
            "strata_requested": ["ESCC", "EAC"],
            "n_tumor_by_stratum": {"ESCC": 90, "EAC": 79},
            "cells_ran_by_stratum": {"ESCC": ["A", "C"], "EAC": ["A", "C"]},
            "substrate": "recount3",
            "n_gtex": 1577,
        },
        {
            "strata_emitted": "HER2_amp",  # single -> bare scalar (the R-serialiser shape)
            "strata_requested": "HER2_amp",
            "n_tumor_by_stratum": {"HER2_amp": 28},
            "cells_ran_by_stratum": {"HER2_amp": ["A", "C"]},
        },
    ]
    agg = rb.aggregate_subgroup_provenance("ESCA", axes, per_axis_provs)
    assert agg["strata_emitted"]["amplification"] == ["HER2_amp"]
    assert agg["strata_requested"]["amplification"] == ["HER2_amp"]
    assert agg["strata_emitted"]["histology"] == ["ESCC", "EAC"]
    assert agg["n_tumor_by_stratum"]["HER2_amp"] == 28
    assert agg["cells_ran"] == ["A", "C"]


def test_as_stratum_list_coercions():
    assert rb._as_stratum_list(None) == []
    assert rb._as_stratum_list("HER2_amp") == ["HER2_amp"]
    assert rb._as_stratum_list(["A", "B"]) == ["A", "B"]
