"""T3 recomputation anchors — cellline-protein-abundance `protein_expression_class` (#2043).

Plan foamy-bird, Stage I / tier T3. Clone of test_expression_distribution_recomputation.py (the
cellline-rna-distribution sibling) — the PROTEIN twin. Re-derives the field from the IRREPRODUCIBLE
raw input (the gene's log2-abundance per DepMap cell line, Gygi TMT MS, + the resolved per-model
lineage + the panel-wide all-protein median null, committed as lossless parquet) through the REAL
methods.depmap_protein_abundance.cli.compute_summary. See capture_protein_abundance_anchor.py for
how an anchor is made.

Why this is not the green-for-the-wrong-reason trap: the fixture is the raw INPUT (the per-cell-line
abundance column + lineage labels + all-protein null), the expected class + fields are re-derived by
the same compute_summary the pipeline runs, and the mutation tests below prove the assertion has
teeth: perturb the input and the re-derived number must move.

OFFLINE — reads only committed fixtures, no S3, no creds. Runs in CI.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"

_AM_ROOT = HERE.parents[2]
if str(_AM_ROOT) not in sys.path:
    sys.path.insert(0, str(_AM_ROOT))

from methods.depmap_protein_abundance import cli as pa_cli  # noqa: E402

compute_summary = pa_cli.compute_summary

MIN_ANCHORS = 2  # anti-vacuity floor (EPCAM flagship + >=1 other panel target)
MIN_DISTINCT_CLASSES = 2
MIN_MODELS = 50


def _anchor_files() -> list[Path]:
    return sorted(ANCHOR_DIR.glob("*.cellline_protein_abundance.json"))


def _load_anchor(path: Path) -> dict:
    return json.loads(path.read_text())


def _load_vector(anchor: dict) -> tuple[dict, dict, tuple]:
    """Reconstruct (abundance_by_model, lineage_by_model, all_protein_medians) EXACTLY as the reader
    passes them into compute_summary."""
    table = pq.read_table(HERE / anchor["vector_fixture"], columns=["model_id", "log2_abundance", "lineage"])
    model_ids = table.column("model_id").to_pylist()
    abund = table.column("log2_abundance").to_pylist()
    lineages = table.column("lineage").to_pylist()
    abundance_by_model = dict(zip(model_ids, abund))
    lineage_by_model = {m: lin for m, lin in zip(model_ids, lineages) if lin is not None}
    null_table = pq.read_table(HERE / anchor["null_fixture"], columns=["median_log2_abundance"])
    all_protein_medians = tuple(float(v) for v in null_table.column("median_log2_abundance").to_pylist())
    return abundance_by_model, lineage_by_model, all_protein_medians


def _anchor_id(path: Path) -> str:
    return path.name.replace(".cellline_protein_abundance.json", "")


ANCHOR_FILES = _anchor_files()
ANCHOR_PARAMS = [pytest.param(p, id=_anchor_id(p)) for p in ANCHOR_FILES]


def test_anchor_set_is_not_vacuous():
    assert len(ANCHOR_FILES) >= MIN_ANCHORS, (
        f"expected >= {MIN_ANCHORS} recomputation anchor(s), found {len(ANCHOR_FILES)} in {ANCHOR_DIR}"
    )
    classes = {_load_anchor(p)["expected_class"] for p in ANCHOR_FILES}
    assert len(classes) >= MIN_DISTINCT_CLASSES, (
        f"anchors must exercise >= {MIN_DISTINCT_CLASSES} classifier branches; found {sorted(classes)}"
    )
    assert any(_anchor_id(p) == "epcam_gygi" for p in ANCHOR_FILES), "the EPCAM flagship anchor is required and missing"


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_class_rederives_from_raw_panel(anchor_path: Path):
    """The pinned class + fields must re-derive from the raw per-cell-line panel via the REAL
    compute_summary."""
    anchor = _load_anchor(anchor_path)
    abundance_by_model, lineage_by_model, all_protein_medians = _load_vector(anchor)

    assert len(abundance_by_model) >= MIN_MODELS, f"panel too small ({len(abundance_by_model)}) — fixture truncated?"
    assert len(abundance_by_model) == anchor["n_cell_lines_evaluated"], "panel size drifted from the captured count"

    summary = compute_summary(
        anchor["target"],
        abundance_by_model,
        lineage_by_model,
        n_panel=anchor["n_panel"],
        all_protein_medians=all_protein_medians,
    )

    assert summary["protein_expression_class"] == anchor["expected_class"], (
        f"{anchor['target']}: re-derived {summary['protein_expression_class']} != pinned {anchor['expected_class']}"
    )
    assert summary["fraction_detected"] == anchor["expected_fraction_detected"]
    assert summary["median_log2_abundance_panel"] == anchor["expected_median_log2_abundance_panel"]
    assert summary["n_lineages_evaluated"] == anchor["expected_n_lineages_evaluated"]
    assert summary["n_lineage_restricted_lineages"] == anchor["expected_n_lineage_restricted_lineages"]


# ---------------------------------------------------------------------------
# Teeth: the assertions above must FAIL when the input moves. Each mutation runs on a COPY.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_silencing_every_line_forces_broadly_low_or_falls(anchor_path: Path):
    """Removing every quantified value (empty abundance_by_model) must collapse fraction_detected to
    0.0 and the class to data_unavailable — proving fraction_detected is a live function of the
    substrate, not echoed from the pin."""
    anchor = _load_anchor(anchor_path)
    _, lineage_by_model, all_protein_medians = _load_vector(anchor)
    summary = compute_summary(
        anchor["target"], None, lineage_by_model, n_panel=anchor["n_panel"], all_protein_medians=all_protein_medians
    )
    assert summary["fraction_detected"] == 0.0
    assert summary["protein_expression_class"] == "data_unavailable"
    assert summary["protein_expression_class"] != anchor["expected_class"]


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_flattening_lineage_collapses_restriction(anchor_path: Path):
    """Collapsing every model onto one lineage removes any lineage stratification, so
    n_lineages_evaluated must fall to <= 1 — proving the per-model lineage labels are load-bearing.
    Only meaningful where the anchor actually measured >1 lineage."""
    anchor = _load_anchor(anchor_path)
    if anchor["expected_n_lineages_evaluated"] <= 1:
        pytest.skip("anchor has no multi-lineage breakdown to collapse")
    abundance_by_model, _, all_protein_medians = _load_vector(anchor)
    flat_lineage = {m: "unknown_flattened" for m in abundance_by_model}
    summary = compute_summary(
        anchor["target"],
        abundance_by_model,
        flat_lineage,
        n_panel=anchor["n_panel"],
        all_protein_medians=all_protein_medians,
    )
    assert summary["n_lineages_evaluated"] <= 1
    assert summary["n_lineages_evaluated"] != anchor["expected_n_lineages_evaluated"]


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_zeroing_the_allgene_null_changes_the_broadly_high_boundary(anchor_path: Path):
    """Shifting the panel-wide all-protein null far below the target's own values must lower the
    broadly_high cutoff so much that a target which was NOT broadly_high crosses into it (or one that
    already was broadly_high stays there) — proving high_cutoff is re-derived live from the null
    tuple, not a constant. Guarded: only meaningful when the anchor is NOT already broadly_high, so
    the mutation genuinely flips a boundary."""
    anchor = _load_anchor(anchor_path)
    if anchor["expected_class"] == "broadly_high":
        pytest.skip("anchor already broadly_high — the mutation has no headroom to demonstrate a flip")
    abundance_by_model, lineage_by_model, _ = _load_vector(anchor)
    crushed_null = tuple(-50.0 for _ in range(100))
    summary = compute_summary(
        anchor["target"],
        abundance_by_model,
        lineage_by_model,
        n_panel=anchor["n_panel"],
        all_protein_medians=crushed_null,
    )
    assert summary["protein_expression_class"] == "broadly_high"
    assert summary["protein_expression_class"] != anchor["expected_class"]
