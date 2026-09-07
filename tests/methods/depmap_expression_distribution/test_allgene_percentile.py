"""Phase 1C: allgene percentile merged into the cellline-rna-distribution read layer.

Offline — monkeypatches load_expression_files (so no DepMap matrix read) + the
depmap_allgene_percentile accessor (so no S3), and asserts read_expression_distribution
merges the allgene_* fields WITHOUT disturbing expression_class (one-directional).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_expression_distribution import read as R  # noqa: E402
from methods.depmap_expression_distribution import cli as C  # noqa: E402


def _fake_load(release_pin, target_symbol):
    # (tpm_by_model, model_metadata, load_errors) — a small in-panel gene.
    tpm = {f"ACH-{i:03d}": v for i, v in enumerate([6.0, 6.5, 7.0, 5.8, 6.1] * 4)}
    meta = {m: {"OncotreeLineage": "Bowel"} for m in tpm}
    return tpm, meta, []


def test_read_merges_allgene_percentile(monkeypatch):
    monkeypatch.setattr(C, "load_expression_files", _fake_load)
    import methods.allgene_percentile_precompute.lookup as _lk

    monkeypatch.setattr(_lk, "_depmap_row", lambda sym: (99.9, 17, 19215, 11.9))
    out = R.read_expression_distribution("GAPDH")
    assert out["allgene_percentile"] == pytest.approx(99.9)
    assert out["allgene_percentile_class"] == "top_1pct"
    assert "allgene-depmap-rank-26q1-v1" in out["allgene_percentile_context"]
    # core panel summary still present + unperturbed
    assert out["expression_class"] in {"broadly_high", "broadly_moderate", "lineage_restricted", "broadly_low"}
    assert "median_log2tpm_panel" in out


def test_read_allgene_absent_gene_data_unavailable(monkeypatch):
    monkeypatch.setattr(C, "load_expression_files", _fake_load)
    import methods.allgene_percentile_precompute.lookup as _lk

    monkeypatch.setattr(_lk, "_depmap_row", lambda sym: None)
    out = R.read_expression_distribution("MADE_UP")
    assert out["allgene_percentile"] is None
    assert out["allgene_percentile_class"] == "data_unavailable"


def test_read_lookup_failure_is_nonfatal(monkeypatch):
    """If the lookup raises (e.g. S3 down), the core summary must still return with
    null allgene fields — the enrichment is best-effort, never fatal to the read."""
    monkeypatch.setattr(C, "load_expression_files", _fake_load)
    import methods.allgene_percentile_precompute.lookup as _lk

    def _boom(sym):
        raise RuntimeError("s3 unreachable")

    monkeypatch.setattr(_lk, "_depmap_row", _boom)
    out = R.read_expression_distribution("GAPDH")
    assert out["allgene_percentile"] is None
    assert out["allgene_percentile_class"] == "data_unavailable"
    assert "expression_class" in out  # core summary intact
