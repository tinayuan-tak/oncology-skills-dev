"""T3 recomputation anchors — tumor-vs-normal selectivity all-gene percentile.

Plan foamy-bird, Stage I / tier T3: the ONLY tier that proves a NUMBER is right. It re-derives
the field from the IRREPRODUCIBLE raw input (the full all-gene log2fc_A null column, committed as
a parquet fixture) through the REAL method code, and asserts the live-captured value. See
capture_anchor.py for what an anchor is and how it is made.

Why this is not the green-for-the-wrong-reason trap the calibration snapshots fall into: a
snapshot stores a DERIVED value and asserts the code reproduces its own output — it can never
catch a wrong computation. Here the fixture is the raw INPUT (the null), the expected percentile
is re-derived by the same percentile_rank the pipeline runs, and the mutation tests below prove
the assertion has teeth: perturb the input and the re-derived number must move. A downsampled or
rounded null would BE the wrong-denominator bug this tier exists to catch, so capture_anchor.py
stores it at full float64 precision.

Anchors are the curated known-target tumor-selectivity set that have a finite log2fc_A against a
real all-gene comparator distribution (CEACAM5/APC/EPCAM/MET/TACSTD2-COADREAD, ERBB2-BRCA,
KLK3-PRAD, MSLN-PAAD) — spanning the classifier's mid / top_decile / top_1pct branches. Targets
with no comparator column (e.g. DLL3-SCLC: TCGA has no SCLC tumor-vs-adjacent arm ⇒ the whole
column is non-finite ⇒ data_unavailable) are NOT numeric anchors; that behavior is a T4 biology
anchor + the percentile_null empty-population unit test.

OFFLINE — reads only committed fixtures, no S3, no creds. Runs in CI.
"""

from __future__ import annotations

import importlib.util
import json
import math
from pathlib import Path

import pyarrow.parquet as pq
import pytest

HERE = Path(__file__).resolve().parent
ANCHOR_DIR = HERE / "anchors"
NULL_DIR = HERE / "nulls"

# Import the REAL pipeline compute by file path — the same discipline the sibling
# tests/methods/test_percentile_null_helper uses, robust to sys.path / package shadowing.
# This is the code the corpus runs; re-deriving through it is what makes T3 a real test.
_HELPER = HERE.parents[2] / "onc_methods" / "percentile_null" / "__init__.py"
_spec = importlib.util.spec_from_file_location("t3_percentile_null_under_test", _HELPER)
_pn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_pn)
percentile_rank = _pn.percentile_rank
classify_percentile = _pn.classify_percentile

MIN_ANCHORS = 6  # anti-vacuity floor below the current 8; a zeroed dir must never read as green
MIN_NULL_LEN = 1000  # a truncated/empty null fixture is the wrong-denominator bug
MIN_DISTINCT_CLASSES = 3  # the set must span classifier branches, not all sit in "mid"


def _anchor_files() -> list[Path]:
    return sorted(ANCHOR_DIR.glob("*.selectivity_percentile.json"))


def _load_anchor(path: Path) -> dict:
    return json.loads(path.read_text())


def _load_null(anchor: dict) -> list[float]:
    parquet = HERE / anchor["null_fixture"]
    col = anchor["cell_column"]
    table = pq.read_table(parquet, columns=[col])
    return table.column(col).to_pylist()


def _anchor_id(path: Path) -> str:
    return path.name.replace(".selectivity_percentile.json", "")


ANCHOR_FILES = _anchor_files()
ANCHOR_PARAMS = [pytest.param(p, id=_anchor_id(p)) for p in ANCHOR_FILES]


def test_anchor_set_is_not_vacuous():
    # A silently-empty anchor dir is indistinguishable from a passing suite — the exact
    # trap this tier exists to remove. Assert the set is populated and spans classes.
    assert len(ANCHOR_FILES) >= MIN_ANCHORS, (
        f"expected >= {MIN_ANCHORS} recomputation anchor(s), found {len(ANCHOR_FILES)} in {ANCHOR_DIR}"
    )
    classes = {_load_anchor(p)["expected_class"] for p in ANCHOR_FILES}
    assert len(classes) >= MIN_DISTINCT_CLASSES, (
        f"anchors must exercise >= {MIN_DISTINCT_CLASSES} classifier branches; found {sorted(classes)}"
    )


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_percentile_rederives_from_raw_null(anchor_path: Path):
    """The pinned percentile + class must re-derive from the raw null via the REAL functions."""
    anchor = _load_anchor(anchor_path)
    null = _load_null(anchor)

    # Anti-vacuity: the raw input must be a real, full-length distribution.
    assert len(null) >= MIN_NULL_LEN, f"null too small ({len(null)}) — fixture truncated?"
    assert len(null) == anchor["n_null"], "null length drifted from the captured count"
    target = anchor["target_log2fc"]
    assert isinstance(target, (int, float)) and math.isfinite(target), "target must be finite"

    pct = percentile_rank(target, null)
    cls = classify_percentile(pct)

    # Deterministic pure arithmetic over the same float64 values ⇒ exact reproduction.
    assert pct == anchor["expected_percentile"], (
        f"{anchor['target']}/{anchor['indication']}: re-derived {pct} != pinned {anchor['expected_percentile']}"
    )
    assert cls == anchor["expected_class"]


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
# Teeth: the assertions above must FAIL when the input moves. If they don't, the
# test is comparing a derived fixture to itself. Each mutation runs on a COPY.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_perturbing_target_moves_the_percentile(anchor_path: Path):
    """Pushing the target scalar above the null's max must drive the percentile to ~100
    and the class to top_1pct — proving re-derivation is live, not an echo of the pin."""
    anchor = _load_anchor(anchor_path)
    null = _load_null(anchor)
    # Max over FINITE values only — some null columns carry NaNs, which the real percentile_rank
    # drops via _finite; a raw max() could yield NaN and defeat the mutation.
    finite = [v for v in null if isinstance(v, (int, float)) and math.isfinite(v)]
    assert finite, "null has no finite values"
    mutated_target = max(finite) + 1.0
    pct = percentile_rank(mutated_target, null)
    assert pct != anchor["expected_percentile"]
    assert pct >= 99.0
    assert classify_percentile(pct) == "top_1pct"


@pytest.mark.parametrize("anchor_path", ANCHOR_PARAMS)
def test_teeth_dropping_below_null_values_moves_the_percentile(anchor_path: Path):
    """Dropping every null value below the target (a corrupted-population / wrong-denominator
    mutation) forces the below-count to zero, so the re-derived percentile must collapse toward
    0 — proving the full captured distribution is load-bearing, not a self-echo. Deterministic:
    we assert there really were below-values to drop, so this can never be a vacuous no-op."""
    anchor = _load_anchor(anchor_path)
    null = _load_null(anchor)
    target = anchor["target_log2fc"]
    at_or_above = [v for v in null if not (isinstance(v, (int, float)) and math.isfinite(v)) or v >= target]
    below = [v for v in null if isinstance(v, (int, float)) and math.isfinite(v) and v < target]
    assert below, "expected some finite null values below the target to drop"
    pct_full = percentile_rank(target, null)
    pct_dropped = percentile_rank(target, at_or_above)
    assert pct_dropped < pct_full
    assert pct_dropped != anchor["expected_percentile"]
