"""Scorecard L1 accuracy (#1988, A0c exemplar) — EPCAM/COADREAD re-derivation from raw substrate.

This is the criterion-(a) evidence for the tumor-presence scorecard's L1 cell: emitted card numbers
must reconcile against an INDEPENDENT re-derivation from raw substrate, never against a fixture of
already-derived values (a fixture of derived values can never fail).

It reuses the EXISTING analysis-methods T3 recomputation anchors (plan `foamy-bird` Stage I) — each
anchor stores the IRREPRODUCIBLE raw input (a gene's per-model/per-donor raw column, committed as a
lossless parquet) plus the value the REAL method code re-derives from it — and BRIDGES them one step
further than analysis-methods' own tests do: it asserts the re-derived number also equals what
tumor-presence's own committed golden (`tests/fixtures/epcam_coadread_decision.json`) emits for the
same card, for the same target/indication. Two repos' independent captures (analysis-methods' anchor,
tumor-presence's golden) meeting at the same float64 value is the reconciliation; either repo drifting
independently would show up here as a real red, not a self-echo.

Covers the two verdict-bearing cards with a landed T3 anchor for EPCAM:
  - cellline-rna-distribution        (DepMap 26Q1 log2(TPM+1) panel -> compute_summary_stats)
  - tumor-scrna-celltype-expression  (per-(dataset,donor,compartment) sc pseudobulk rows ->
                                      read_sc_expression_presence)

The other 5 verdict-bearing cards (tumor-rna-vs-adjacent, tumor-rna-distribution,
tumor-protein-abundance-cptac, cellline-protein-abundance, tumor-elevation-breadth) have no landed T3
anchor yet — the scorecard shard's L1 accuracy evidence says so explicitly rather than claiming a
reading this test cannot support.

OFFLINE — reads only committed fixtures (this repo's golden + analysis-methods' committed anchor
parquets), no S3, no creds. Skips (not fails) if the analysis-methods sibling checkout is absent, so a
partial checkout degrades honestly instead of red on an unrelated absence.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
for _p in (str(SKILLS_ROOT),):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from _skills_common.paths import analysis_methods_root  # noqa: E402

AM_ROOT = analysis_methods_root()
RECOMPUTATION_DIR = AM_ROOT / "tests" / "calibration" / "recomputation"
ANCHOR_DIR = RECOMPUTATION_DIR / "anchors"
GOLDEN = SKILL_DIR / "tests" / "fixtures" / "epcam_coadread_decision.json"

pytestmark = pytest.mark.skipif(
    not ANCHOR_DIR.exists(),
    reason=f"analysis-methods recomputation anchors not found at {ANCHOR_DIR} (sibling checkout absent/partial)",
)


def _golden_card(card_id: str) -> dict:
    d = json.loads(GOLDEN.read_text())
    for c in d["cards"]:
        if c["card_id"] == card_id:
            return c["summary"]
    raise AssertionError(f"golden fixture carries no card {card_id!r}")


# ── cellline-rna-distribution ────────────────────────────────────────────────────────────────────


def _load_expression_module():
    if str(AM_ROOT) not in sys.path:
        sys.path.insert(0, str(AM_ROOT))
    cli = AM_ROOT / "methods" / "depmap_expression_distribution" / "cli.py"
    spec = importlib.util.spec_from_file_location("t1988_expression_distribution_under_test", cli)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _load_expression_anchor() -> dict:
    p = ANCHOR_DIR / "epcam_26q1.cellline_rna_distribution.json"
    if not p.exists():
        pytest.skip(f"no EPCAM cellline_rna_distribution anchor at {p}")
    return json.loads(p.read_text())


def _load_expression_vector(anchor: dict) -> tuple[dict, dict]:
    table = pq.read_table(RECOMPUTATION_DIR / anchor["vector_fixture"], columns=["model_id", "log2tpm", "lineage"])
    model_ids = table.column("model_id").to_pylist()
    log2tpm = table.column("log2tpm").to_pylist()
    lineages = table.column("lineage").to_pylist()
    tpm_by_model = dict(zip(model_ids, log2tpm))
    model_metadata = {
        m: {"OncotreeLineage": (float("nan") if lin is None else lin)} for m, lin in zip(model_ids, lineages)
    }
    return tpm_by_model, model_metadata


def test_cellline_rna_distribution_rederives_from_raw_substrate_and_matches_golden():
    """EPCAM/26Q1 raw per-cell-line log2(TPM+1) column -> compute_summary_stats must reproduce BOTH the
    analysis-methods anchor's pinned numbers AND the tumor-presence golden's cellline-rna-distribution
    card summary for EPCAM/COADREAD — two independent captures agreeing at full float64 precision."""
    anchor = _load_expression_anchor()
    ed = _load_expression_module()
    tpm_by_model, model_metadata = _load_expression_vector(anchor)
    assert len(tpm_by_model) >= 500, f"raw panel too small ({len(tpm_by_model)}) — fixture truncated?"

    summary = ed.compute_summary_stats(tpm_by_model, model_metadata)

    # Anchor-side reconciliation (analysis-methods' own promise).
    assert summary["expression_class"] == anchor["expected_class"]
    assert summary["fraction_expressed"] == anchor["expected_fraction_expressed"]
    assert summary["fraction_highly_expressed"] == anchor["expected_fraction_highly_expressed"]

    # THE BRIDGE: the skill's own committed golden must carry the identical numbers, independently.
    golden = _golden_card("cellline-rna-distribution")
    assert golden["n_cell_lines_evaluated"] == len(tpm_by_model) == anchor["n_cell_lines_evaluated"]
    assert golden["fraction_expressed"] == summary["fraction_expressed"]
    assert golden["fraction_highly_expressed"] == summary["fraction_highly_expressed"]
    assert golden["expression_class"] == summary["expression_class"]


def test_cellline_rna_distribution_teeth_mutated_input_breaks_the_golden_match():
    """Teeth: if the raw substrate is not what the golden was captured against, the bridge assertion
    above must NOT hold — proving it is a real reconciliation, not a vacuous self-comparison. Silencing
    every cell line is a legitimate different-input probe (EPCAM's real panel is not all-zero)."""
    anchor = _load_expression_anchor()
    ed = _load_expression_module()
    tpm_by_model, model_metadata = _load_expression_vector(anchor)
    golden = _golden_card("cellline-rna-distribution")

    mutated = {m: 0.0 for m in tpm_by_model}
    summary = ed.compute_summary_stats(mutated, model_metadata)

    assert summary["fraction_expressed"] != golden["fraction_expressed"]
    assert summary["expression_class"] != golden["expression_class"]


# ── tumor-scrna-celltype-expression ──────────────────────────────────────────────────────────────

_ROW_COLS = [
    "gene_symbol",
    "dataset_id",
    "donor_id",
    "compartment",
    "n_cells",
    "detection_fraction",
    "abundance_log1p_cp10k",
]


def _load_sc_module():
    if str(AM_ROOT) not in sys.path:
        sys.path.insert(0, str(AM_ROOT))
    import methods.sc_tumor_expression_celltype.read as rd  # noqa: PLC0415

    return rd


def _load_sc_anchor() -> dict:
    p = ANCHOR_DIR / "epcam_coadread.sc_celltype.json"
    if not p.exists():
        pytest.skip(f"no EPCAM sc_celltype anchor at {p}")
    return json.loads(p.read_text())


def _load_sc_rows(anchor: dict):
    table = pq.read_table(RECOMPUTATION_DIR / anchor["rows_fixture"]).to_pandas()
    sub = table[(table["anchor_target"] == anchor["target"]) & (table["anchor_indication"] == anchor["indication"])]
    return sub[_ROW_COLS].reset_index(drop=True)


def test_sc_celltype_rederives_from_raw_rows_and_matches_golden(monkeypatch):
    """EPCAM/COADREAD raw per-(dataset,donor,compartment) pseudobulk rows -> read_sc_expression_presence
    must reproduce BOTH the analysis-methods anchor's pinned numbers AND the tumor-presence golden's
    tumor-scrna-celltype-expression card summary — independently."""
    anchor = _load_sc_anchor()
    rd = _load_sc_module()
    rows = _load_sc_rows(anchor)
    monkeypatch.setattr(rd, "read_gene_compartment_rows", lambda t, i: rows)

    summary = rd.read_sc_expression_presence(anchor["target"], anchor["indication"])

    assert summary["sc_expression_class"] == anchor["expected_sc_expression_class"]
    assert summary["malignant_detection_fraction"] == anchor["expected_malignant_detection_fraction"]
    assert summary["malignant_n_donors"] == anchor["expected_malignant_n_donors"]
    assert summary["malignant_n_cells"] == anchor["expected_malignant_n_cells"]

    golden = _golden_card("tumor-scrna-celltype-expression")
    assert golden["sc_expression_class"] == summary["sc_expression_class"]
    assert golden["malignant_detection_fraction"] == summary["malignant_detection_fraction"]
    assert golden["malignant_abundance_log1p_cp10k"] == summary["malignant_abundance_log1p_cp10k"]
    assert golden["malignant_n_donors"] == summary["malignant_n_donors"]
    assert golden["malignant_n_cells"] == summary["malignant_n_cells"]
    assert golden["top_microenvironment_compartment"] == summary["top_microenvironment_compartment"]
    assert golden["top_microenvironment_detection_fraction"] == summary["top_microenvironment_detection_fraction"]


def test_sc_celltype_teeth_dropping_malignant_rows_breaks_the_golden_match(monkeypatch):
    """Teeth: removing the malignant compartment's rows must collapse the class away from the golden's
    `malignant_broadly_detected` — proving the match above is a real function of the row substrate."""
    anchor = _load_sc_anchor()
    rd = _load_sc_module()
    rows = _load_sc_rows(anchor)
    golden = _golden_card("tumor-scrna-celltype-expression")

    starved = rows[rows["compartment"] != "malignant"].reset_index(drop=True)
    monkeypatch.setattr(rd, "read_gene_compartment_rows", lambda t, i: starved)
    summary = rd.read_sc_expression_presence(anchor["target"], anchor["indication"])

    assert summary["sc_expression_class"] != golden["sc_expression_class"]
    assert summary["malignant_compartment_available"] is False
