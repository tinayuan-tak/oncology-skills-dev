"""Credential-less tests for the ProCan cell-line protein-abundance reader.

No S3: a synthetic local long/tidy parquet (the derived product's schema) is read via the
`product_path`/`null_path` offline seams, and the symbol->UniProt map is monkeypatched. Pins:
  * the emitted summary carries EVERY field the cellline-protein-abundance card declares (the
    reader-real-field-names drift class the tumor-presence replay exists to catch);
  * the distribution class + all-gene percentile are computed against the on-read all-protein null;
  * broadly_high is REACHABLE (proves the null wiring — the H3 fix the Gygi sibling carries);
  * absence discipline: unresolved symbol / accession-absent → data_unavailable (a coverage gap);
  * read_target_summary degrades to _live_read_error on a load fault (never crashes the compose path);
  * per-lineage stratification is empty (SIDM ids have no OncotreeLineage crosswalk yet).
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

cli = importlib.import_module("methods.procan_protein_abundance.cli")
read = importlib.import_module("methods.procan_protein_abundance.read")

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
    "protein_effect_size",
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
    cli._allprotein_median_null_live.cache_clear()
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
        "protein_effect_size",
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


def test_read_target_summary_degrades_on_fault(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(cli, "load_and_classify", _boom)
    out = read.read_target_summary("EGFR", indication="COADREAD")
    assert out["_live_read_error"] == "procan_protein_abundance_read_failed"
    assert out["protein_expression_class"] == "data_unavailable"
    assert out["protein_abundance_source"] == "data_unavailable"
    assert out["allgene_percentile"] is None and out["median_log2_abundance_panel"] is None
    assert out["per_lineage_stats"] == [] and out["method_version"] == cli.METHOD_VERSION


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
