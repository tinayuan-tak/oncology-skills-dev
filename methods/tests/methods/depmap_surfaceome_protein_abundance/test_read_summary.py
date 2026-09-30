"""Credential-less tests for the DepMap Surfaceome 26Q3 surface protein-abundance reader.

No S3: a synthetic local long/tidy parquet (the derived product's schema) is read via the
`product_path`/`null_path` offline seams, and the symbol->UniProt map is monkeypatched. Pins:
  * the emitted summary carries EVERY field the cellline-protein-abundance card declares PLUS the
    paired-assay enrichment block (the reader-real-field-names drift class);
  * the distribution class + all-gene percentile are computed against the on-read all-protein null
    over the SURFACE layer; broadly_high is REACHABLE (proves the null wiring — the H3 fix);
  * the surface-vs-wholecell enrichment rollup: median_enrichment_log2ratio /
    fraction_lines_predicted_enriched / median_pr_auc + the surface_localization_class classes
    (surface_confirmed / intracellular_contaminant / mixed / insufficient);
  * a surface-UNDETECTED line (surface_log2 null) is not counted in the abundance summary;
  * absence discipline: unresolved symbol / accession-absent → data_unavailable (a coverage gap);
  * read_target_summary degrades to _live_read_error on a load fault (never crashes the compose path);
  * per-lineage stratification is empty (no OncotreeLineage crosswalk in this product).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest

cli = importlib.import_module("onc_methods.depmap_surfaceome_protein_abundance.cli")
read = importlib.import_module("onc_methods.depmap_surfaceome_protein_abundance.read")

# The fields the cellline-protein-abundance card declares — the reader MUST emit all of them.
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
# The genuinely-new paired-assay block (surface-vs-wholecell enrichment rollup).
_ENRICHMENT_FIELDS = {
    "n_lines_enrichment_evaluated",
    "median_enrichment_log2ratio",
    "fraction_lines_predicted_enriched",
    "median_pr_auc",
    "surface_localization_class",
}
_CLASS_VOCAB = {
    "broadly_high",
    "broadly_moderate",
    "lineage_restricted",
    "sub_broad_detection",
    "broadly_low",
    "data_unavailable",
}
_LOCALIZATION_VOCAB = {"surface_confirmed", "mixed", "intracellular_contaminant", "insufficient"}

_COLS = [
    "uniprot_base",
    "uniprot_id",
    "model_id",
    "surface_log2",
    "wholecell_log2",
    "enrichment_log2ratio",
    "proteomics_predicted_enriched",
    "proteomics_pr_auc",
    "proteomics_enrichment_filter_status",
    "proteomics_wholecell_filter_status",
]


def _row(base, uid, model, surface, whole=None, enrich=None, pred=None, auc=None):
    return (base, uid, model, surface, whole, enrich, pred, auc, "not_filtered_out", "not_filtered_out")


def _write_product(tmp_path, rows) -> Path:
    df = pd.DataFrame(rows, columns=_COLS)
    p = tmp_path / "surfaceome.parquet"
    df.to_parquet(p, index=False)
    return p


def _mk_null_background(tmp_path, target_rows) -> Path:
    """Target protein PLUS many low-abundance background proteins spanning the surface null, so the
    target's median lands high in the all-protein null (broadly_high reachable + real percentile)."""
    rows = list(target_rows)
    for gi in range(60):
        acc = f"BG{gi:04d}"
        for j in range(5):
            rows.append(_row(acc, f"{acc}_HUMAN", f"ACH{gi:03d}{j}", 0.2 + 0.01 * gi))
    return _write_product(tmp_path, rows)


@pytest.fixture(autouse=True)
def _reset_caches():
    cli._load_pushdown_live.cache_clear()
    cli._reset_allprotein_null_cache()
    cli._panel_size.cache_clear()
    yield


def _patch_map(monkeypatch, mapping):
    monkeypatch.setattr(cli, "_symbol_to_uniprot_map", lambda: mapping)


def _patch_panel(monkeypatch, n):
    monkeypatch.setattr(cli, "_panel_size", lambda: n)


def test_summary_shape_matches_card_and_percentile_computed(tmp_path, monkeypatch):
    _patch_map(monkeypatch, {"EGFR": ["P00533"]})
    _patch_panel(monkeypatch, 64)
    # EGFR detected in 32 of 64 lines, high surface median (5.0) vs a low-abundance background null,
    # each with a positive enrichment ratio and a predicted-enriched classifier call.
    tgt = [
        _row("P00533", "EGFR_HUMAN", f"ACH{i:04d}", 5.0, whole=3.0, enrich=2.0, pred=True, auc=0.9) for i in range(32)
    ]
    prod = _mk_null_background(tmp_path, tgt)
    out = cli.load_and_classify("EGFR", product_path=prod, null_path=prod)

    missing = (_CARD_SUMMARY_FIELDS | _ENRICHMENT_FIELDS) - set(out)
    assert not missing, f"reader is missing declared fields: {sorted(missing)}"
    assert out["protein_abundance_source"] == "depmap_surfaceome_dia_ms"
    assert out["protein_expression_class"] in _CLASS_VOCAB
    assert out["n_cell_lines_evaluated"] == 32
    assert out["n_cell_lines_in_panel"] == 64
    assert out["fraction_detected"] == 0.5
    assert out["median_log2_abundance_panel"] == 5.0
    assert out["method_version"] == cli.METHOD_VERSION
    assert isinstance(out["allgene_percentile"], float) and out["allgene_percentile"] > 90.0
    assert out["allgene_percentile_class"] in {"top_1pct", "top_decile"}
    assert cli.DERIVED_PRODUCT_MANIFEST_ID in out["allgene_percentile_context"]
    assert out["per_lineage_stats"] == [] and out["n_lineages_evaluated"] == 0
    # enrichment rollup
    assert out["n_lines_enrichment_evaluated"] == 32
    assert out["median_enrichment_log2ratio"] == 2.0
    assert out["fraction_lines_predicted_enriched"] == 1.0
    assert out["median_pr_auc"] == 0.9
    assert out["surface_localization_class"] == "surface_confirmed"
    assert out["surface_localization_class"] in _LOCALIZATION_VOCAB


def test_broadly_high_reachable_with_null(tmp_path, monkeypatch):
    """Detected in >70% of the panel AND median above the all-protein panel-high cutoff → broadly_high
    (proves the on-read surface null feeds the panel-relative high cutoff — the H3 discipline)."""
    _patch_map(monkeypatch, {"EGFR": ["P00533"]})
    _patch_panel(monkeypatch, 64)
    tgt = [_row("P00533", "EGFR_HUMAN", f"ACH{i:04d}", 6.0) for i in range(52)]  # ~81% detected, high
    prod = _mk_null_background(tmp_path, tgt)
    out = cli.load_and_classify("EGFR", product_path=prod, null_path=prod)
    assert out["protein_expression_class"] == "broadly_high"


def test_surface_undetected_line_not_counted(tmp_path, monkeypatch):
    """A line where the surface layer was NOT detected (surface_log2 null) must not inflate the
    detection fraction — only surface-detected lines count toward the abundance summary."""
    _patch_map(monkeypatch, {"EGFR": ["P00533"]})
    _patch_panel(monkeypatch, 64)
    tgt = [_row("P00533", "EGFR_HUMAN", f"ACH{i:04d}", 5.0) for i in range(10)]
    tgt += [_row("P00533", "EGFR_HUMAN", f"ACHnull{i:04d}", None, whole=3.0) for i in range(5)]
    prod = _mk_null_background(tmp_path, tgt)
    out = cli.load_and_classify("EGFR", product_path=prod, null_path=prod)
    assert out["n_cell_lines_evaluated"] == 10  # the 5 surface-null lines are excluded


def test_intracellular_contaminant_localization(tmp_path, monkeypatch):
    """Surface-detected but NOT surface-enriched (negative enrichment, classifier says not-enriched)
    → intracellular_contaminant."""
    _patch_map(monkeypatch, {"ACTB": ["P60709"]})
    _patch_panel(monkeypatch, 64)
    tgt = [
        _row("P60709", "ACTB_HUMAN", f"ACH{i:04d}", 4.0, whole=6.0, enrich=-2.0, pred=False, auc=0.4) for i in range(20)
    ]
    prod = _mk_null_background(tmp_path, tgt)
    out = cli.load_and_classify("ACTB", product_path=prod, null_path=prod)
    assert out["median_enrichment_log2ratio"] == -2.0
    assert out["fraction_lines_predicted_enriched"] == 0.0
    assert out["surface_localization_class"] == "intracellular_contaminant"


def test_mixed_localization(tmp_path, monkeypatch):
    """Positive median enrichment but only ~half the classifier calls predicted-enriched, or vice
    versa → mixed (heterogeneous)."""
    _patch_map(monkeypatch, {"MIXY": ["P11111"]})
    _patch_panel(monkeypatch, 64)
    tgt = [
        _row("P11111", "MIXY_HUMAN", f"ACH{i:04d}", 4.0, whole=3.0, enrich=1.0, pred=(i % 3 == 0), auc=0.6)
        for i in range(12)
    ]  # positive enrichment, but only 1/3 predicted-enriched (< 0.5) → not surface_confirmed
    prod = _mk_null_background(tmp_path, tgt)
    out = cli.load_and_classify("MIXY", product_path=prod, null_path=prod)
    assert out["median_enrichment_log2ratio"] == 1.0
    assert 0.0 < out["fraction_lines_predicted_enriched"] < 0.5
    assert out["surface_localization_class"] == "mixed"


def test_insufficient_localization_when_too_few_enrichment_lines(tmp_path, monkeypatch):
    """Fewer than the minimum lines with a BOTH-layers enrichment ratio → insufficient (the surface
    abundance summary can still be emitted; the localization lens is just too sparse to characterize)."""
    _patch_map(monkeypatch, {"EGFR": ["P00533"]})
    _patch_panel(monkeypatch, 64)
    # 10 surface-detected lines, but only 2 have BOTH layers (a non-null enrichment ratio).
    tgt = [_row("P00533", "EGFR_HUMAN", f"ACH{i:04d}", 5.0) for i in range(10)]
    tgt[0] = _row("P00533", "EGFR_HUMAN", "ACH0000", 5.0, whole=3.0, enrich=2.0, pred=True, auc=0.9)
    tgt[1] = _row("P00533", "EGFR_HUMAN", "ACH0001", 5.0, whole=3.0, enrich=2.0, pred=True, auc=0.9)
    prod = _mk_null_background(tmp_path, tgt)
    out = cli.load_and_classify("EGFR", product_path=prod, null_path=prod)
    assert out["n_lines_enrichment_evaluated"] == 2
    assert out["surface_localization_class"] == "insufficient"
    assert out["n_cell_lines_evaluated"] == 10  # abundance summary unaffected


def test_unresolved_symbol_is_data_unavailable(tmp_path, monkeypatch):
    _patch_map(monkeypatch, {})
    _patch_panel(monkeypatch, 64)
    prod = _mk_null_background(tmp_path, [])
    out = cli.load_and_classify("GHOST", product_path=prod, null_path=prod)
    assert out["protein_expression_class"] == "data_unavailable"
    assert out["protein_abundance_source"] == "data_unavailable"
    assert out["allgene_percentile"] is None
    assert out["allgene_percentile_class"] == "data_unavailable"
    assert out["surface_localization_class"] == "insufficient"
    assert out["median_enrichment_log2ratio"] is None
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
    } | _ENRICHMENT_FIELDS
    assert set(out) >= _GAP_CORE


def test_accession_absent_from_panel_is_data_unavailable(tmp_path, monkeypatch):
    _patch_map(monkeypatch, {"EGFR": ["Q99999"]})  # resolves, but not in the product
    _patch_panel(monkeypatch, 64)
    tgt = [_row("P00533", "EGFR_HUMAN", f"ACH{i:04d}", 5.0) for i in range(10)]
    prod = _mk_null_background(tmp_path, tgt)
    out = cli.load_and_classify("EGFR", product_path=prod, null_path=prod)
    assert out["protein_expression_class"] == "data_unavailable"


def test_read_target_summary_degrades_on_fault(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(cli, "load_and_classify", _boom)
    out = read.read_target_summary("EGFR", indication="STAD")
    assert out["_live_read_error"] == "depmap_surfaceome_protein_abundance_read_failed"
    assert out["protein_expression_class"] == "data_unavailable"
    assert out["protein_abundance_source"] == "data_unavailable"
    assert out["allgene_percentile"] is None and out["median_log2_abundance_panel"] is None
    assert out["per_lineage_stats"] == [] and out["method_version"] == cli.METHOD_VERSION
    assert out["surface_localization_class"] == "insufficient"


def test_missing_panel_size_is_data_unavailable_not_full_panel(tmp_path, monkeypatch):
    _patch_map(monkeypatch, {"EGFR": ["P00533"]})
    _patch_panel(monkeypatch, None)  # manifest genuinely missing the panel-size constant
    tgt = [_row("P00533", "EGFR_HUMAN", f"ACH{i:04d}", 5.0) for i in range(30)]
    prod = _mk_null_background(tmp_path, tgt)
    out = cli.load_and_classify("EGFR", product_path=prod, null_path=prod)
    assert out["protein_expression_class"] == "data_unavailable"
    assert out["protein_abundance_source"] == "data_unavailable"
    assert out["fraction_detected"] == 0.0  # the fabricated full-panel 1.0 is NOT emitted
    assert out["n_cell_lines_in_panel"] is None
    assert out["allgene_percentile_class"] == "data_unavailable"


def test_pct_cutoffs_track_default_cutoffs():
    from onc_methods.percentile_null import DEFAULT_CUTOFFS

    assert cli._PCT_CUTOFFS == DEFAULT_CUTOFFS


def test_s3fs_singleton_is_shared(monkeypatch):
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
    cli._S3FS = None


def test_transient_null_scan_failure_not_memoized(monkeypatch):
    """A transient failure of the on-read null scan must NOT stick session-wide (success-only memo)."""
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
    assert cli._allprotein_median_null_live() == (1.0, 2.0, 3.0)  # retried, succeeded
    assert cli._allprotein_median_null_live() == (1.0, 2.0, 3.0)  # success now memoized
    assert calls["n"] == 2


def test_isoform_tiebreak_picks_min_uniprot_id(tmp_path, monkeypatch):
    """Two uniprot_id share the base accession → deterministically pick the min."""
    _patch_map(monkeypatch, {"EGFR": ["P00533"]})
    _patch_panel(monkeypatch, 64)
    tgt = [_row("P00533", "EGFR_HUMAN", f"ACH{i:04d}", 5.0) for i in range(20)] + [
        _row("P00533", "AAAA_HUMAN", f"ACH{i:04d}", 1.0) for i in range(20)
    ]  # min uid = AAAA_HUMAN
    prod = _mk_null_background(tmp_path, tgt)
    out = cli.load_and_classify("EGFR", product_path=prod, null_path=prod)
    assert out["median_log2_abundance_panel"] == 1.0  # AAAA_HUMAN rows chosen


def test_null_scan_drops_surface_undetected_proteins(tmp_path):
    """A protein with ALL surface_log2 null (only wholecell detected) contributes no null entry —
    the surface abundance null is over surface-detected medians only."""
    rows = [_row("P00001", "A_HUMAN", "ACH1", 5.0), _row("P00001", "A_HUMAN", "ACH2", 5.0)]
    rows += [_row("P00002", "B_HUMAN", "ACH1", None, whole=4.0), _row("P00002", "B_HUMAN", "ACH2", None, whole=4.0)]
    prod = _write_product(tmp_path, rows)
    null_vec = cli._compute_null_from_table(str(prod))
    assert null_vec == (5.0,)  # only P00001; P00002 (all surface-null) dropped
