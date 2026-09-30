"""Regression (burndown P1): phospho_pathway_activity._read_gene_sites must distinguish a GENUINE
missing product (NoSuchKey/404, or FileNotFoundError for a missing object -> None -> caller emits
data_unavailable, unchanged) from a transient/broken-env failure (-> re-raise, surfaced as
_live_read_error by the live-read seam). The caller no longer double-tags _live_read_error on None
(that path is now genuine-absence only).
"""

from __future__ import annotations

import pytest

from onc_methods.phospho_pathway_activity import read as phospho


def test_missing_local_product_is_genuine_absence(tmp_path):
    # pyarrow raises FileNotFoundError on a missing local path -> None (genuine absence).
    missing = tmp_path / "nope.parquet"
    assert phospho._read_gene_sites("EGFR", "coad", product_path=str(missing)) is None


def test_caller_genuine_absence_is_data_unavailable_no_live_read_error(tmp_path):
    missing = tmp_path / "nope.parquet"
    r = phospho.read_phospho_pathway_activity("EGFR", "COADREAD", product_path=str(missing))
    assert r["phospho_activity_class"] == "data_unavailable"
    assert "_live_read_error" not in r  # no double-handling: absence != read error


def test_transient_reraises(monkeypatch, tmp_path):
    import pyarrow.parquet as pq

    monkeypatch.setattr(pq, "read_table", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("throttle")))
    with pytest.raises(RuntimeError):
        phospho._read_gene_sites("EGFR", "coad", product_path=str(tmp_path / "x.parquet"))
    # and the raise propagates through the public entrypoint (no swallow -> live-read seam):
    with pytest.raises(RuntimeError):
        phospho.read_phospho_pathway_activity("EGFR", "COADREAD", product_path=str(tmp_path / "x.parquet"))
