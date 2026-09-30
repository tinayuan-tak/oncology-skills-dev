"""Credential-less tests for the ProCan cell-line protein-abundance reader.

No S3: a synthetic local long/tidy parquet (the derived product's schema) is read via the
`product_path`/`null_path` offline seams, and the symbol->UniProt map is monkeypatched. Pins:
  * the emitted summary carries EVERY field the cellline-protein-abundance card declares (the
    reader-real-field-names drift class the tumor-presence replay exists to catch);
  * the distribution class + all-gene percentile are computed against the on-read all-protein null;
  * broadly_high is REACHABLE (proves the null wiring — the H3 fix the Gygi sibling carries);
  * absence discipline: unresolved symbol / accession-absent → data_unavailable (a coverage gap);
  * absence discipline (#832): read_target_summary degrades to data_unavailable on GENUINE absence
    (NoSuchKey/404/FileNotFound) but a TRANSIENT/creds fault PROPAGATES (never masked as data_unavailable);
  * per-lineage stratification is empty (SIDM ids have no OncotreeLineage crosswalk yet).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest

cli = importlib.import_module("onc_methods.procan_protein_abundance.cli")
read = importlib.import_module("onc_methods.procan_protein_abundance.read")

# The fields the cellline-protein-abundance card declares in outputs.summary_fields — the reader MUST
# emit all of them (the drift guard). Kept explicit so a card/reader divergence fails HERE.
_CARD_SUMMARY_FIELDS = {
    "n_cell_lines_evaluated",
    "n_cell_lines_in_panel",
    "fraction_detected",
    "median_log2_abundance_panel",
    "p25_log2_abundance_panel",
    "p75_log2_abundance_panel",
    "p5_log2_abundance_panel",
    "p95_log2_abundance_panel",
    "log2_abundance_iqr",
    "protein_expression_class",
    "n_lineages_evaluated",
    "per_lineage_stats",
    "n_lineage_restricted_lineages",
    "method_version",
    "allgene_percentile",
    "allgene_percentile_class",
    "allgene_percentile_context",
}
# Local mirror of cellline-protein-abundance-procan.card.yaml
# summary_fields_vocabulary.protein_expression_class, which the shared classifier in
# methods/depmap_protein_abundance/cli.py emits. sub_broad_detection is the middle-band label THIS
# reader actually produces — SIDM model ids have no OncotreeLineage crosswalk, so per_lineage_stats is
# always empty (asserted below) and no lineage token is reachable here. lineage_restricted is retained
# only because the vocabulary is shared with the Gygi sibling, where it IS reachable.
_CLASS_VOCAB = {
    "broadly_high",
    "broadly_moderate",
    "lineage_restricted",
    "sub_broad_detection",
    "broadly_low",
    "data_unavailable",
}


def _write_product(tmp_path, rows) -> Path:
    """rows: list of (uniprot_base, uniprot_id, model_id, log_abundance)."""
    df = pd.DataFrame(rows, columns=["uniprot_base", "uniprot_id", "model_id", "log_abundance"])
    p = tmp_path / "procan.parquet"
    df.to_parquet(p, index=False)
    return p


def _mk_null_background(tmp_path, target_rows) -> Path:
    """A product with the target protein PLUS many background proteins spanning a low-abundance null,
    so the target's median lands high in the all-protein null (broadly_high reachable + real percentile)."""
    rows = list(target_rows)
    for gi in range(60):
        acc = f"BG{gi:04d}"
        for j in range(5):
            rows.append((acc, f"{acc}_HUMAN", f"SIDM{gi:03d}{j}", 0.2 + 0.01 * gi))  # low background medians
    return _write_product(tmp_path, rows)


@pytest.fixture(autouse=True)
def _reset_caches():
    cli._load_abundance_pushdown_live.cache_clear()
    cli._reset_allprotein_null_cache()  # F1: success-only memo replaced the old @lru_cache
    cli._panel_size.cache_clear()
    yield


def _patch_map(monkeypatch, mapping):
    monkeypatch.setattr(cli, "_symbol_to_uniprot_map", lambda: mapping)


def _patch_panel(monkeypatch, n):
    monkeypatch.setattr(cli, "_panel_size", lambda: n)


def test_summary_shape_matches_card_and_percentile_computed(tmp_path, monkeypatch):
    _patch_map(monkeypatch, {"EGFR": ["P00533"]})
    _patch_panel(monkeypatch, 100)
    # EGFR detected in 50 of 100 lines, high median (5.0) vs a low-abundance background null.
    tgt = [("P00533", "EGFR_HUMAN", f"SIDM{i:04d}", 5.0) for i in range(50)]
    prod = _mk_null_background(tmp_path, tgt)
    out = cli.load_and_classify("EGFR", product_path=prod, null_path=prod)

    missing = _CARD_SUMMARY_FIELDS - set(out)
    assert not missing, f"reader is missing card-declared summary_fields: {sorted(missing)}"
    assert out["protein_abundance_source"] == "procan_dia_swath"
    assert out["protein_expression_class"] in _CLASS_VOCAB
    assert out["n_cell_lines_evaluated"] == 50
    assert out["n_cell_lines_in_panel"] == 100
    assert out["fraction_detected"] == 0.5
    assert out["median_log2_abundance_panel"] == 5.0
    assert out["method_version"] == cli.METHOD_VERSION
    assert isinstance(out["allgene_percentile"], float) and out["allgene_percentile"] > 90.0
    assert out["allgene_percentile_class"] in {"top_1pct", "top_decile"}
    assert cli.DERIVED_PRODUCT_MANIFEST_ID in out["allgene_percentile_context"]
    # SIDM cell-line ids carry no OncotreeLineage crosswalk → per-lineage stratification is empty.
    assert out["per_lineage_stats"] == []
    assert out["n_lineages_evaluated"] == 0


def test_broadly_high_reachable_with_null(tmp_path, monkeypatch):
    """Detected in >70% of the panel AND median above the all-protein panel-high cutoff → broadly_high
    (proves the on-read null feeds the panel-relative high cutoff — the Gygi H3 discipline)."""
    _patch_map(monkeypatch, {"EGFR": ["P00533"]})
    _patch_panel(monkeypatch, 100)
    tgt = [("P00533", "EGFR_HUMAN", f"SIDM{i:04d}", 6.0) for i in range(80)]  # 80% detected, high median
    prod = _mk_null_background(tmp_path, tgt)
    out = cli.load_and_classify("EGFR", product_path=prod, null_path=prod)
    assert out["protein_expression_class"] == "broadly_high"


def test_unresolved_symbol_is_data_unavailable(tmp_path, monkeypatch):
    _patch_map(monkeypatch, {})  # symbol not in the map
    _patch_panel(monkeypatch, 100)
    prod = _mk_null_background(tmp_path, [])
    out = cli.load_and_classify("GHOST", product_path=prod, null_path=prod)
    assert out["protein_expression_class"] == "data_unavailable"
    assert out["protein_abundance_source"] == "data_unavailable"
    assert out["allgene_percentile"] is None
    assert out["allgene_percentile_class"] == "data_unavailable"
    # The gap path emits the core fields (parity with the Gygi sibling's compute_summary None-branch,
    # which omits the p*/iqr detail — headline/rules read those via get_card_field → None, safely).
    _GAP_CORE = {
        "protein_expression_class",
        "n_cell_lines_evaluated",
        "n_cell_lines_in_panel",
        "fraction_detected",
        "median_log2_abundance_panel",
        "per_lineage_stats",
        "method_version",
        "protein_abundance_source",
        "allgene_percentile",
        "allgene_percentile_class",
        "allgene_percentile_context",
    }
    assert set(out) >= _GAP_CORE


def test_accession_absent_from_panel_is_data_unavailable(tmp_path, monkeypatch):
    _patch_map(monkeypatch, {"EGFR": ["Q99999"]})  # resolves, but not in the product
    _patch_panel(monkeypatch, 100)
    tgt = [("P00533", "EGFR_HUMAN", f"SIDM{i:04d}", 5.0) for i in range(10)]
    prod = _mk_null_background(tmp_path, tgt)
    out = cli.load_and_classify("EGFR", product_path=prod, null_path=prod)
    assert out["protein_expression_class"] == "data_unavailable"


def test_read_target_summary_genuine_absence_is_data_unavailable(monkeypatch):
    """Absence discipline (#832): a GENUINE absence (missing product/object → ClientError NoSuchKey/404
    or FileNotFoundError) degrades to a graceful data_unavailable summary (never crashes the compose
    path). This is the FIRE-ABLE half of the narrowing — the absence branch must still be reachable."""
    from botocore.exceptions import ClientError

    def _absent(*a, **k):
        raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")

    monkeypatch.setattr(cli, "load_and_classify", _absent)
    out = read.read_target_summary("EGFR", indication="COADREAD")
    assert out["_live_read_error"] == "procan_protein_abundance_read_failed"
    assert out["protein_expression_class"] == "data_unavailable"
    assert out["protein_abundance_source"] == "data_unavailable"
    assert out["allgene_percentile"] is None and out["median_log2_abundance_panel"] is None
    assert out["per_lineage_stats"] == [] and out["method_version"] == cli.METHOD_VERSION

    def _missing(*a, **k):
        raise FileNotFoundError("product gone")

    monkeypatch.setattr(cli, "load_and_classify", _missing)
    assert read.read_target_summary("EGFR", indication="COADREAD")["protein_expression_class"] == "data_unavailable"


def test_read_target_summary_transient_fault_propagates(monkeypatch):
    """Absence discipline (#832): the OTHER side of the narrowing — a TRANSIENT / creds / broken-env
    fault must PROPAGATE (an honest _live_read_error at the compose seam), NOT be masked as
    protein_expression_class=data_unavailable (the RD-class silent-dead-axis bug). Before this pass the
    reader swallowed ANY exception into data_unavailable; that breadth is exactly what is removed here."""

    def _boom(*a, **k):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(cli, "load_and_classify", _boom)
    with pytest.raises(RuntimeError, match="s3 down"):
        read.read_target_summary("EGFR", indication="COADREAD")


def test_transient_null_scan_failure_not_memoized(monkeypatch):
    """F1: a transient failure of the all-protein null scan must NOT stick session-wide. The old
    @lru_cache(maxsize=1) memoized the except-branch empty tuple, poisoning allgene_percentile +
    broadly_high for every target for the process lifetime. The success-only memo lets a later call
    retry: first call degrades to (), the second succeeds and is cached."""
    monkeypatch.setattr(cli, "ensure_aws_profile", lambda: None)
    monkeypatch.setattr(cli, "_derived_bucket_key", lambda: ("bucket", "key"))
    monkeypatch.setattr(cli, "_get_s3fs", lambda: object())
    calls = {"n": 0}

    def _flaky(path, filesystem=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient s3 throttle")
        return (1.0, 2.0, 3.0)

    monkeypatch.setattr(cli, "_compute_null_from_table", _flaky)
    cli._reset_allprotein_null_cache()

    assert cli._allprotein_median_null_live() == tuple()  # transient failure → graceful empty
    assert cli._allprotein_median_null_live() == (1.0, 2.0, 3.0)  # NOT poisoned — retried, succeeded
    assert cli._allprotein_median_null_live() == (1.0, 2.0, 3.0)  # success now memoized
    assert calls["n"] == 2  # third call served from cache, no re-scan


def test_missing_panel_size_is_data_unavailable_not_full_panel(tmp_path, monkeypatch):
    """F7: when panel_size_n_cell_lines is absent from manifest params, compute_summary would fall back
    to denom=n_eval → a fabricated fraction_detected=1.0. Instead emit data_unavailable (never a false
    '100% of panel')."""
    _patch_map(monkeypatch, {"EGFR": ["P00533"]})
    _patch_panel(monkeypatch, None)  # manifest genuinely missing the panel-size constant
    tgt = [("P00533", "EGFR_HUMAN", f"SIDM{i:04d}", 5.0) for i in range(50)]
    prod = _mk_null_background(tmp_path, tgt)
    out = cli.load_and_classify("EGFR", product_path=prod, null_path=prod)
    assert out["protein_expression_class"] == "data_unavailable"
    assert out["protein_abundance_source"] == "data_unavailable"
    assert out["fraction_detected"] != 1.0  # the fabricated full-panel value is NOT emitted
    assert out["fraction_detected"] == 0.0
    assert out["n_cell_lines_in_panel"] is None
    assert out["allgene_percentile_class"] == "data_unavailable"


def test_pct_cutoffs_track_default_cutoffs(monkeypatch):
    """F6: the percentile cutoffs derive from onc_methods.percentile_null.DEFAULT_CUTOFFS (no hard-copied
    literals that could silently drift)."""
    from onc_methods.percentile_null import DEFAULT_CUTOFFS

    assert cli._PCT_CUTOFFS == DEFAULT_CUTOFFS


def test_s3fs_singleton_is_shared(monkeypatch):
    """F5: _get_s3fs returns one process-wide instance (the shared hardening point)."""
    cli._S3FS = None
    built = {"n": 0}

    class _FakeFS:
        pass

    def _fake_ctor():
        built["n"] += 1
        return _FakeFS()

    import pyarrow.fs as pafs

    monkeypatch.setattr(pafs, "S3FileSystem", _fake_ctor)
    a = cli._get_s3fs()
    b = cli._get_s3fs()
    assert a is b and built["n"] == 1
    cli._S3FS = None  # don't leak the fake into other tests


def test_isoform_tiebreak_picks_min_uniprot_id(tmp_path, monkeypatch):
    """Two uniprot_id share the base accession → deterministically pick the min (parity with Gygi)."""
    _patch_map(monkeypatch, {"EGFR": ["P00533"]})
    _patch_panel(monkeypatch, 100)
    tgt = [("P00533", "EGFR_HUMAN", f"SIDM{i:04d}", 5.0) for i in range(20)] + [
        ("P00533", "AAAA_HUMAN", f"SIDM{i:04d}", 1.0) for i in range(20)
    ]  # min uid = AAAA_HUMAN
    prod = _mk_null_background(tmp_path, tgt)
    out = cli.load_and_classify("EGFR", product_path=prod, null_path=prod)
    assert out["median_log2_abundance_panel"] == 1.0  # AAAA_HUMAN rows chosen
