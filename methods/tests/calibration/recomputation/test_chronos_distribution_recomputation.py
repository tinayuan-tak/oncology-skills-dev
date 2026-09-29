"""T3 recomputation anchors — pan-cancer CRISPR (Chronos) dependency distribution.

Plan foamy-bird, Stage I / tier T3 (the ONLY tier that proves a NUMBER is right), third-and-fourth skill.
Re-derives the pan-cancer-crispr-dependency-distribution card's headline fields — median_chronos_panel,
fraction_strongly_dependent, dependency_class, distribution_shape — from the IRREPRODUCIBLE raw input (the
per-cell-line Chronos gene-effect vector, one column of the ~564 MB CRISPRGeneEffect matrix, plus each
line's resolved lineage) through the REAL methods.depmap_chronos_distribution.read pipeline. See
capture_chronos_anchor.py for how an anchor is made.

Why this is not the green-for-the-wrong-reason trap the calibration snapshots fall into: a snapshot stores
a DERIVED value and asserts the code reproduces its own output — it can never catch a wrong computation.
Here the fixture is the raw per-line SCORES; the median/fraction are re-reduced over them, the shape is
re-classified by Sarle's bimodality coefficient the pipeline runs, and dependency_class is re-derived
through the real classifier including its curated-core-essential anchor. The teeth below prove the
assertions bite: shift every score down and the median must move; truncate the panel and n must change;
drop the curated core-essential anchor and the pan-essential call must lose its killer.

Anchors span the classifier's branches: KRAS/CTNNB1 (strongly_selective, bimodal_selective), MET/TEAD1/
WWTR1/SMARCA2/EPAS1 (non_dependent, non_essential), RPL3 (common_essential, pan_essential — a curated
core-essential positive control). KRAS additionally carries the functional-requirement roster's own
_crispr_provenance block, so its re-derivation is cross-checked against that independently-captured record.

OFFLINE — reads only committed fixtures, monkeypatches the S3 loaders + the additive control axis, no creds.
Runs in CI.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"

# The pipeline module does absolute `from methods.…` imports at module scope, so the analysis-methods root
# must be importable. Insert it explicitly (the sibling tests/methods/… tests import the same way). We test
# the REAL card code — re-deriving through it is what makes T3 a real test, not a self-echo.
_AM_ROOT = HERE.parents[2]
if str(_AM_ROOT) not in sys.path:
    sys.path.insert(0, str(_AM_ROOT))

import methods.depmap_chronos_distribution.cli as cli  # noqa: E402
import methods.depmap_chronos_distribution.read as rd  # noqa: E402

MIN_ANCHORS = 6  # anti-vacuity floor below the current 8; a zeroed dir must never read as green
MIN_DISTINCT_CLASSES = 3  # the set must span classifier branches, not all sit in one
MIN_PANEL_ROWS = 500  # a truncated per-gene vector would collapse the distribution the fields summarize
_FIELDS = (
    "n_cell_lines_evaluated",
    "median_chronos_panel",
    "fraction_strongly_dependent",
    "dependency_class",
    "distribution_shape",
)


def _anchor_files() -> list[Path]:
    return sorted(ANCHOR_DIR.glob("*.chronos_distribution.json"))


def _load_anchor(path: Path) -> dict:
    return json.loads(path.read_text())


def _load_gene_slice(anchor: dict) -> tuple[dict, dict]:
    """({model_id: chronos_score}, {model_id: {'OncotreeLineage': lineage}}) for this anchor's gene, read
    exactly as frozen — the irreproducible input slice. lineage is stored already-RESOLVED, so a metadata
    dict carrying only OncotreeLineage reproduces the grouping the live full Model.csv produced."""
    table = pq.read_table(HERE / anchor["counts_fixture"]).to_pydict()
    target = anchor["target"]
    chronos: dict[str, float] = {}
    meta: dict[str, dict] = {}
    for gene, model_id, score, lineage in zip(
        table["gene_symbol"], table["model_id"], table["chronos_score"], table["lineage"], strict=True
    ):
        if gene == target:
            chronos[model_id] = float(score)
            meta[model_id] = {"OncotreeLineage": lineage}
    return chronos, meta


def _rederive(monkeypatch, chronos: dict, meta: dict, target: str, curated: bool | None) -> dict:
    """Force the pipeline down the frozen-slice path. load_depmap_files → the frozen vector; the curated
    core-essential set → a set reproducing the frozen boolean (or None to simulate an unreachable list);
    the additive control axis → inert. Then call the REAL library entry point."""
    monkeypatch.setattr(cli, "load_depmap_files", lambda release_pin, target_symbol: (dict(chronos), dict(meta), []))
    if curated is None:
        curated_set = None
    else:
        curated_set = frozenset({target}) if curated else frozenset()
    monkeypatch.setattr(cli, "_load_curated_common_essentials", lambda release_pin="26q1": curated_set)
    # The dep-control axis is additive + verdict-inert and does its own live read; make it deterministic
    # offline so the summary is a pure function of the frozen slice.
    monkeypatch.setattr("methods.dependency_controls.control_position_dependency", lambda *a, **k: {})
    return rd.read_pan_cancer_distribution(target)


ANCHOR_FILES = _anchor_files()
ANCHOR_PARAMS = [pytest.param(p, id=p.name.replace(".chronos_distribution.json", "")) for p in ANCHOR_FILES]


def test_anchor_set_is_not_vacuous():
    # A silently-empty anchor dir is indistinguishable from a passing suite — the trap this tier removes.
    assert len(ANCHOR_FILES) >= MIN_ANCHORS, (
        f"expected >= {MIN_ANCHORS} recomputation anchor(s), found {len(ANCHOR_FILES)} in {ANCHOR_DIR}"
    )
    classes = {_load_anchor(p)["expected_dependency_class"] for p in ANCHOR_FILES}
    assert len(classes) >= MIN_DISTINCT_CLASSES, (
        f"anchors must exercise >= {MIN_DISTINCT_CLASSES} classifier branches; found {sorted(classes)}"
    )


def test_fixture_md5_matches_anchors():
    # Every anchor pins the same source-slice md5; the committed parquet must still hash to it, or a
    # re-derivation is running against a different (possibly hand-edited) input than was captured.
    for path in ANCHOR_FILES:
        anchor = _load_anchor(path)
        fixture = HERE / anchor["counts_fixture"]
        md5 = hashlib.md5(fixture.read_bytes()).hexdigest()
        assert md5 == anchor["_source"]["counts_fixture_md5"], f"{path.name}: fixture md5 drift"


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_panel_is_full_not_truncated(anchor_path: Path):
    # The distribution fields summarize the WHOLE panel; a truncated per-gene vector would silently change
    # every one of them. Assert the frozen slice still holds the full panel the anchor was captured over.
    anchor = _load_anchor(anchor_path)
    chronos, _ = _load_gene_slice(anchor)
    assert len(chronos) == anchor["n_cell_lines_evaluated"], "frozen vector size drifted from captured n"
    assert len(chronos) >= MIN_PANEL_ROWS, f"panel too small ({len(chronos)}) — fixture truncated?"


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_rederives_from_raw_scores(monkeypatch, anchor_path: Path):
    """The pinned median, fraction, class and shape must re-derive from the raw per-line Chronos scores via
    the REAL pipeline — exact float64 reproduction, not a stored echo."""
    anchor = _load_anchor(anchor_path)
    chronos, meta = _load_gene_slice(anchor)
    r = _rederive(monkeypatch, chronos, meta, anchor["target"], anchor["curated_common_essential"])

    assert r["n_cell_lines_evaluated"] == anchor["n_cell_lines_evaluated"]
    assert r["median_chronos_panel"] == anchor["expected_median_chronos_panel"]
    assert r["fraction_strongly_dependent"] == anchor["expected_fraction_strongly_dependent"]
    assert r["dependency_class"] == anchor["expected_dependency_class"]
    assert r["distribution_shape"] == anchor["expected_distribution_shape"]


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_agrees_with_roster_snapshot(anchor_path: Path):
    """Where the functional-requirement calibration roster independently recorded this gene's chronos
    provenance, the anchor's expected values must equal it — two records of the same number that must not
    diverge. Anchors the roster does not cover carry a null cross_ref and are skipped here."""
    anchor = _load_anchor(anchor_path)
    cross = anchor.get("snapshot_cross_ref")
    if cross is None:
        pytest.skip("gene not in the roster _crispr_provenance set")
    assert cross["n_cell_lines_evaluated"] == anchor["n_cell_lines_evaluated"]
    assert cross["median_chronos_panel"] == anchor["expected_median_chronos_panel"]
    assert cross["fraction_strongly_dependent"] == anchor["expected_fraction_strongly_dependent"]
    assert cross["dependency_class"] == anchor["expected_dependency_class"]
    assert cross["distribution_shape"] == anchor["expected_distribution_shape"]


def test_at_least_one_roster_cross_ref_present():
    # The cross-repo check above pytest.skips when a gene is not in the roster; guard against ALL of them
    # skipping (which would make test_agrees_with_roster_snapshot vacuously green).
    assert any(_load_anchor(p).get("snapshot_cross_ref") for p in ANCHOR_FILES), (
        "no anchor carries a roster snapshot_cross_ref — the cross-repo assertion is vacuous"
    )


# ---------------------------------------------------------------------------
# Teeth: the assertions above must FAIL when the input moves. If they don't, the test is comparing a
# derived fixture to itself. Each mutation runs on a COPY of the frozen slice.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_shifting_scores_down_moves_the_number(monkeypatch, anchor_path: Path):
    """Subtracting a constant from every Chronos score (making the whole panel more dependent) must lower
    the re-derived median strictly and never lower the strongly-dependent fraction — proving the reduction
    is live over the frozen scores, not an echo of the pin."""
    anchor = _load_anchor(anchor_path)
    chronos, meta = _load_gene_slice(anchor)
    shifted = {m: v - 2.0 for m, v in chronos.items()}
    r = _rederive(monkeypatch, shifted, meta, anchor["target"], anchor["curated_common_essential"])
    assert r["median_chronos_panel"] < anchor["expected_median_chronos_panel"]
    assert r["fraction_strongly_dependent"] >= anchor["expected_fraction_strongly_dependent"]


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_truncating_the_panel_changes_n(monkeypatch, anchor_path: Path):
    """Keeping only a handful of cell lines must change n_cell_lines_evaluated — proving n is re-counted
    from the frozen vector, not read back from the pin."""
    anchor = _load_anchor(anchor_path)
    chronos, meta = _load_gene_slice(anchor)
    keep = dict(sorted(chronos.items())[:40])
    kept_meta = {m: meta[m] for m in keep}
    r = _rederive(monkeypatch, keep, kept_meta, anchor["target"], anchor["curated_common_essential"])
    assert r["n_cell_lines_evaluated"] == len(keep)
    assert r["n_cell_lines_evaluated"] != anchor["n_cell_lines_evaluated"]


def test_teeth_dropping_the_curated_anchor_flips_the_essential_class(monkeypatch):
    """For a common_essential anchor, making the curated core-essential control set unreachable (None) must
    drop the pan-essential KILLER — the class re-routes to common_essential_unanchored (skills #1794:
    a well-powered >=85% fraction with an unreachable anchor is a DISTINCT, safety-conservative class,
    no longer conflated into the safety-dark common_essential_underpowered). Proves the curated-anchor
    threading in read.py (not just the raw fraction) is load-bearing for the class."""
    essential = [
        _load_anchor(p)
        for p in ANCHOR_FILES
        if _load_anchor(p)["expected_dependency_class"] == "common_essential"
        and _load_anchor(p)["curated_common_essential"] is True
    ]
    assert essential, "no curated common_essential anchor present — this tooth is vacuous"
    for anchor in essential:
        chronos, meta = _load_gene_slice(anchor)
        # curated=None → the reader threads curated_common_essential=None → offline-fallback routing.
        r = _rederive(monkeypatch, chronos, meta, anchor["target"], None)
        assert r["dependency_class"] != anchor["expected_dependency_class"]
        assert r["dependency_class"] == "common_essential_unanchored", (
            f"{anchor['target']}: dropping the curated anchor on a well-powered panel should route to "
            f"common_essential_unanchored (never the safety-dark underpowered, never a clean class); "
            f"got {r['dependency_class']!r}"
        )
