"""T3 recomputation anchors — cellline-rna-distribution `expression_class`.

Plan foamy-bird, Stage I / tier T3: the ONLY tier that proves a NUMBER is right. It re-derives
the field from the IRREPRODUCIBLE raw input (the gene's log2(TPM+1) per DepMap cell line + the
resolved per-model lineage, committed as a lossless parquet) through the REAL method code, and
asserts the live-captured value. See capture_expression_anchor.py for what an anchor is.

Why this is not the green-for-the-wrong-reason trap the calibration snapshots fall into: a
snapshot stores a DERIVED value and asserts the code reproduces its own output — it can never
catch a wrong computation. Here the fixture is the raw INPUT (the per-cell-line TPM column + the
lineage labels), the expected class + fractions are re-derived by the same compute_summary_stats
the pipeline runs, and the mutation tests below prove the assertion has teeth: perturb the input
and the re-derived number must move. A downsampled or rounded column would BE the wrong-denominator
bug this tier exists to catch (fraction_expressed is a mean over the whole column), so
capture_expression_anchor.py stores it at full float64 precision.

Anchors are the curated known tumor-presence targets spanning the classifier's branches —
broadly_high / broadly_moderate / lineage_restricted / broadly_low — so the set exercises real
alternative paths, not one saturated class.

OFFLINE — reads only committed fixtures, no S3, no creds. Runs in CI.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"

# Import the REAL pipeline compute by file path — robust to package shadowing under
# --import-mode=importlib. This is the code the corpus runs; re-deriving through it is what makes
# T3 a real test. cli.py has package-relative imports (`from methods.catalog_query...`), so the
# repo root must be importable before the module executes.
_AM_ROOT = HERE.parents[2]
if str(_AM_ROOT) not in sys.path:
    sys.path.insert(0, str(_AM_ROOT))
_CLI = _AM_ROOT / "methods" / "depmap_expression_distribution" / "cli.py"
_spec = importlib.util.spec_from_file_location("t3_expression_distribution_under_test", _CLI)
_ed = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_ed)
compute_summary_stats = _ed.compute_summary_stats

MIN_ANCHORS = 6  # anti-vacuity floor; a zeroed dir must never read as green
MIN_MODELS = 500  # a truncated fixture is the wrong-denominator bug (card fires low-coverage < 500)
MIN_DISTINCT_CLASSES = 3  # the set must span classifier branches, not all sit in one class
HIGHLY_EXPRESSED_THRESHOLD = 5.0  # card threshold; used by the teeth mutations


def _anchor_files() -> list[Path]:
    return sorted(ANCHOR_DIR.glob("*.cellline_rna_distribution.json"))


def _load_anchor(path: Path) -> dict:
    return json.loads(path.read_text())


def _load_vector(anchor: dict) -> tuple[dict, dict]:
    """Reconstruct (tpm_by_model, model_metadata) EXACTLY as the reader passes them into
    compute_summary_stats — the resolved lineage sits under OncotreeLineage."""
    table = pq.read_table(HERE / anchor["vector_fixture"], columns=["model_id", "log2tpm", "lineage"])
    model_ids = table.column("model_id").to_pylist()
    log2tpm = table.column("log2tpm").to_pylist()
    lineages = table.column("lineage").to_pylist()
    tpm_by_model = dict(zip(model_ids, log2tpm))
    # A null lineage was a NaN OncotreeLineage in the raw Model.csv — reconstruct it as float('nan')
    # so the reader's resolver (cli.py:291) short-circuits to NaN and groupby drops the same rows.
    model_metadata = {
        m: {"OncotreeLineage": (float("nan") if lin is None else lin)} for m, lin in zip(model_ids, lineages)
    }
    return tpm_by_model, model_metadata


def _anchor_id(path: Path) -> str:
    return path.name.replace(".cellline_rna_distribution.json", "")


ANCHOR_FILES = _anchor_files()
ANCHOR_PARAMS = [pytest.param(p, id=_anchor_id(p)) for p in ANCHOR_FILES]


def test_anchor_set_is_not_vacuous():
    # A silently-empty anchor dir is indistinguishable from a passing suite — the exact trap this
    # tier exists to remove. Assert the set is populated and spans classes.
    assert len(ANCHOR_FILES) >= MIN_ANCHORS, (
        f"expected >= {MIN_ANCHORS} recomputation anchor(s), found {len(ANCHOR_FILES)} in {ANCHOR_DIR}"
    )
    classes = {_load_anchor(p)["expected_class"] for p in ANCHOR_FILES}
    assert len(classes) >= MIN_DISTINCT_CLASSES, (
        f"anchors must exercise >= {MIN_DISTINCT_CLASSES} classifier branches; found {sorted(classes)}"
    )
    # The lineage-restriction teeth below only bite on an anchor with an enriched lineage; require
    # at least one so that path is never silently unexercised.
    assert any(_load_anchor(p)["expected_n_lineage_restricted_lineages"] > 0 for p in ANCHOR_FILES), (
        "at least one anchor must have an enriched lineage (n_lineage_restricted > 0) to exercise the lineage teeth"
    )


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_class_rederives_from_raw_panel(anchor_path: Path):
    """The pinned class + fractions must re-derive from the raw per-cell-line panel via the REAL
    compute_summary_stats."""
    anchor = _load_anchor(anchor_path)
    tpm_by_model, model_metadata = _load_vector(anchor)

    # Anti-vacuity: the raw input must be a real, full-length panel.
    assert len(tpm_by_model) >= MIN_MODELS, f"panel too small ({len(tpm_by_model)}) — fixture truncated?"
    assert len(tpm_by_model) == anchor["n_cell_lines_evaluated"], "panel size drifted from the captured count"

    summary = compute_summary_stats(tpm_by_model, model_metadata)

    # Deterministic arithmetic over the same float64 values ⇒ exact reproduction.
    assert summary["expression_class"] == anchor["expected_class"], (
        f"{anchor['target']}: re-derived {summary['expression_class']} != pinned {anchor['expected_class']}"
    )
    assert summary["fraction_expressed"] == anchor["expected_fraction_expressed"]
    assert summary["fraction_highly_expressed"] == anchor["expected_fraction_highly_expressed"]
    assert summary["n_lineage_restricted_lineages"] == anchor["expected_n_lineage_restricted_lineages"]


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_class_agrees_with_independent_snapshot(anchor_path: Path):
    """The expected class must agree with the target-contracts calibration snapshot that
    independently recorded it — two records of the same value that must not diverge."""
    anchor = _load_anchor(anchor_path)
    cross = anchor.get("snapshot_class_cross_ref")
    if cross is None:
        pytest.skip("no target-contracts snapshot cross-reference recorded for this anchor")
    assert cross == anchor["expected_class"], f"anchor class {anchor['expected_class']} disagrees with snapshot {cross}"


# ---------------------------------------------------------------------------
# Teeth: the assertions above must FAIL when the input moves. If they don't, the test is comparing
# a derived fixture to itself. Each mutation runs on a COPY.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_raising_every_line_high_forces_broadly_high(anchor_path: Path):
    """Pushing every cell line above the highly-expressed threshold must drive fraction_highly to
    1.0 and the class to broadly_high — proving fraction_highly is re-derived from the full column,
    not echoed from the pin. Guarded: the pinned fraction is < 1.0 so the mutation genuinely moves."""
    anchor = _load_anchor(anchor_path)
    if anchor["expected_fraction_highly_expressed"] >= 1.0:
        pytest.skip("anchor already fully highly-expressed — no headroom for this mutation")
    tpm_by_model, model_metadata = _load_vector(anchor)
    mutated = {m: HIGHLY_EXPRESSED_THRESHOLD + 1.0 for m in tpm_by_model}
    summary = compute_summary_stats(mutated, model_metadata)
    assert summary["fraction_highly_expressed"] == 1.0
    assert summary["fraction_highly_expressed"] != anchor["expected_fraction_highly_expressed"]
    assert summary["expression_class"] == "broadly_high"


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_silencing_every_line_forces_broadly_low(anchor_path: Path):
    """Dropping every cell line below the expressed threshold must collapse fraction_expressed to
    0.0 and the class to broadly_low — proving fraction_expressed is a live mean over the whole
    column. Guarded: the pinned fraction is > 0 so this genuinely moves the number."""
    anchor = _load_anchor(anchor_path)
    if anchor["expected_fraction_expressed"] <= 0.0:
        pytest.skip("anchor already fully silent — no headroom for this mutation")
    tpm_by_model, model_metadata = _load_vector(anchor)
    mutated = {m: 0.0 for m in tpm_by_model}
    summary = compute_summary_stats(mutated, model_metadata)
    assert summary["fraction_expressed"] == 0.0
    assert summary["fraction_expressed"] != anchor["expected_fraction_expressed"]
    assert summary["expression_class"] == "broadly_low"


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_flattening_lineage_collapses_restriction(anchor_path: Path):
    """Collapsing every model onto one lineage removes any lineage enrichment, so
    n_lineage_restricted must fall to 0 — proving the per-model lineage labels are load-bearing.
    Only meaningful where the anchor actually had an enriched lineage."""
    anchor = _load_anchor(anchor_path)
    if anchor["expected_n_lineage_restricted_lineages"] == 0:
        pytest.skip("anchor has no enriched lineage to collapse")
    tpm_by_model, _ = _load_vector(anchor)
    flat_meta = {m: {"OncotreeLineage": "unknown"} for m in tpm_by_model}
    summary = compute_summary_stats(tpm_by_model, flat_meta)
    assert summary["n_lineage_restricted_lineages"] == 0
    assert summary["n_lineage_restricted_lineages"] != anchor["expected_n_lineage_restricted_lineages"]
