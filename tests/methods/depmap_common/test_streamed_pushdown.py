"""Streamed-pushdown refactor (2026-08-21 data-layer hardening): the per-target readers project a
single gene column over an S3 filesystem with NO whole-file download; the whole-matrix batch path
(`get_full_matrix_path`) still downloads-and-caches. These tests use the `source_path` offline seam
(a tiny local parquet) — no S3 — to prove the projection logic, and assert the streaming infra +
the release-pin guard are intact.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_common import parquet as P  # noqa: E402


def _tiny_wide(tmp_path):
    """A 3-row × (ModelID, IsDefaultEntryForModel, 2 gene cols) wide matrix, entrez-suffixed cols."""
    import pandas as pd

    p = tmp_path / "wide.parquet"
    pd.DataFrame(
        {
            "ModelID": ["ACH-0001", "ACH-0002", "ACH-0003"],
            "IsDefaultEntryForModel": [True, True, False],
            "EPCAM (4072)": [1.5, 0.0, 3.2],
            "KRAS (3845)": [4.1, 2.2, 1.0],
        }
    ).to_parquet(p, index=False)
    return str(p)


def test_read_wide_target_column_projects_via_source_path(tmp_path):
    src = _tiny_wide(tmp_path)
    df = P._read_wide_target_column("ignored.parquet", "EPCAM", id_col_hints=("ModelID",), source_path=src)
    assert set(df.columns) == {"EPCAM (4072)", "ModelID", "IsDefaultEntryForModel"}
    assert len(df) == 3
    assert df.loc[df["ModelID"] == "ACH-0003", "EPCAM (4072)"].iloc[0] == 3.2
    # gene absent from the matrix → None (a data condition, not an error)
    assert P._read_wide_target_column("ignored.parquet", "NOPE", source_path=src) is None


def test_get_matrix_column_by_model_id_via_source_path(tmp_path):
    src = _tiny_wide(tmp_path)
    df = P.get_matrix_column_by_model_id("ignored.parquet", "KRAS", source_path=src)
    assert list(df.columns) == ["ModelID", "KRAS (3845)"]  # exactly ModelID + target, no default-entry col
    assert len(df) == 3
    assert P.get_matrix_column_by_model_id("ignored.parquet", "NOPE", source_path=src) is None


def test_streaming_infra_present_and_uri_resolves():
    # singleton + helpers exist (the streamed read path)
    assert callable(P._get_s3fs) and callable(P._stream_table) and callable(P._remote_uri)
    P._release_prefix.cache_clear()
    uri = P._remote_uri("OmicsExpressionTPMLogp1HumanProteinCodingGenes.parquet", "26q1")
    assert uri == (
        "onc-compbio/data-catalog/derived/depmap-26q1-parquet-v1/OmicsExpressionTPMLogp1HumanProteinCodingGenes.parquet"
    )


def test_remote_uri_raises_on_unregistered_release_before_s3():
    import pytest

    P._release_prefix.cache_clear()
    with pytest.raises(FileNotFoundError):
        P._remote_uri("anything.parquet", "26q99")
