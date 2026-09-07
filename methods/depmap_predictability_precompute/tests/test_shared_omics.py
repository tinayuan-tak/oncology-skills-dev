"""Tests for the shared-memory omics transport (fix for the 2026-07-02 OOM).

Verifies the round-trip publish → attach reconstruction gives DataFrames
that are numerically equivalent to the input, that Model.csv metadata goes
through the extras pickle path, and that unlink cleans up all SHM segments.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from depmap_predictability_precompute import shared_omics as _shm  # noqa: E402


def _make_test_omics():
    """Small synthetic omics bundle mimicking the real structure."""
    rng = np.random.default_rng(42)
    mids = [f"ACH-{i:06d}" for i in range(20)]
    genes = [f"GENE_{i}" for i in range(15)]
    return {
        "chronos": pd.DataFrame(
            rng.normal(0, 1, (20, 15)).astype(np.float32),
            index=mids, columns=genes),
        "expression": pd.DataFrame(
            rng.normal(3, 1, (20, 15)).astype(np.float32),
            index=mids, columns=genes),
        "mut_hotspot": pd.DataFrame(
            rng.integers(0, 2, (20, 15)).astype(np.int8),
            index=mids, columns=genes),
        "lineage_one_hot": pd.DataFrame(
            rng.integers(0, 2, (20, 5)).astype(np.int8),
            index=mids, columns=[f"lineage_{n}" for n in "ABCDE"]),
        "model_df": pd.DataFrame({
            "ModelID": mids,
            "OncotreeLineage": ["A"] * 10 + ["B"] * 10,
        }),
    }


def test_publish_then_attach_roundtrip_preserves_values():
    """Values through the SHM round-trip must be numerically identical."""
    omics = _make_test_omics()
    handle = _shm.publish_omics_to_shm(omics)
    try:
        attached = _shm.attach_omics_from_shm(handle)
        # Numeric frames: SHM-backed, must equal originals
        for key in ("chronos", "expression", "mut_hotspot", "lineage_one_hot"):
            pd.testing.assert_frame_equal(attached[key], omics[key])
        # model_df: extras path, must equal too
        pd.testing.assert_frame_equal(
            attached["model_df"].reset_index(drop=True),
            omics["model_df"].reset_index(drop=True),
        )
    finally:
        handle.unlink_all()
        _shm.detach_all()


def test_handle_size_is_small():
    """The handle must be << omics itself (that's the whole point)."""
    omics = _make_test_omics()
    handle = _shm.publish_omics_to_shm(omics)
    try:
        # Handle should be a few KB (index/column labels + Model.csv), NOT
        # containing the numeric data. Enforce < 100 KB for this tiny test set.
        total_bytes = (len(handle.extras_pickle)
                        + sum(len(f.index_pickle) + len(f.columns_pickle)
                              for f in handle.frames.values()))
        assert total_bytes < 100_000
    finally:
        handle.unlink_all()
        _shm.detach_all()


def test_unlink_is_idempotent():
    """Calling unlink twice must not raise (crash-recovery friendliness)."""
    omics = _make_test_omics()
    handle = _shm.publish_omics_to_shm(omics)
    handle.unlink_all()
    handle.unlink_all()  # second call: must be a no-op
    _shm.detach_all()


def test_attach_returns_dataframes_with_correct_indices():
    omics = _make_test_omics()
    handle = _shm.publish_omics_to_shm(omics)
    try:
        attached = _shm.attach_omics_from_shm(handle)
        assert list(attached["chronos"].index) == list(omics["chronos"].index)
        assert list(attached["chronos"].columns) == list(omics["chronos"].columns)
    finally:
        handle.unlink_all()
        _shm.detach_all()


def test_worker_side_read_after_coordinator_edit_isolated():
    """After publish, edits to the coordinator's local `omics` must NOT affect
    the attached view (verifies we made a copy into SHM, not a shared view
    over the coordinator's arrays)."""
    omics = _make_test_omics()
    handle = _shm.publish_omics_to_shm(omics)
    try:
        # Mutate coordinator's original DataFrame after publish
        omics["chronos"].iloc[0, 0] = 999.0
        attached = _shm.attach_omics_from_shm(handle)
        # The SHM copy should retain the original value, not the mutation
        assert attached["chronos"].iloc[0, 0] != 999.0
    finally:
        handle.unlink_all()
        _shm.detach_all()
