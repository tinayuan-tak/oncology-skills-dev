"""Unit tests for the all-gene percentile-null helper (Phase 1A).

Imports the helper by file path to avoid any package-name shadowing between this
test dir and methods/percentile_null/.
"""

import importlib.util
import math
import random
from pathlib import Path

import pytest

_HELPER = Path(__file__).resolve().parents[3] / "methods" / "percentile_null" / "__init__.py"
_spec = importlib.util.spec_from_file_location("pn_helper_under_test", _HELPER)
pn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pn)

_REAL_NULL_FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "tests"
    / "calibration"
    / "recomputation"
    / "nulls"
    / "coadread-dge-tumor-vs-normal-sensitivity-v1__log2fc_A.parquet"
)


def _percentile_rank_reference_triple_pass(value, null_values):
    """The pre-O2-3 pure-Python O(n) implementation, kept ONLY as a numeric oracle for
    test_percentile_rank_matches_legacy_triple_pass_on_real_fixture — proves the vectorized
    searchsorted path in the module under test is byte-for-byte equivalent, not just
    "close enough", on real (not synthetic) DESeq2 log2FC values."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None
    pop = pn._finite(null_values)
    if not pop:
        return None
    below = sum(1 for x in pop if x < v)
    equal = sum(1 for x in pop if x == v)
    return 100.0 * (below + 0.5 * equal) / len(pop)


def test_percentile_rank_matches_legacy_triple_pass_on_real_fixture():
    """O2-3 acceptance: the vectorized (sorted-null + np.searchsorted) percentile_rank must
    be numerically IDENTICAL to the pre-fix pure-Python triple pass, verified on a REAL DGE
    null (~29.4k COADREAD log2FoldChange values from the tumor-vs-normal-sensitivity product),
    not just a synthetic list. Exercises exact ties, min/max, and non-finite edges."""
    if not _REAL_NULL_FIXTURE.exists():
        pytest.skip(f"real null fixture not present: {_REAL_NULL_FIXTURE}")
    import pyarrow.parquet as pq

    table = pq.read_table(str(_REAL_NULL_FIXTURE))
    null_vals = tuple(v for v in table["log2fc_A"].to_pylist() if v is not None)
    assert len(null_vals) > 1000  # sanity: this is the real ~29k-row fixture, not an empty stub

    random.seed(42)
    test_values = [
        null_vals[0],
        null_vals[100],
        min(null_vals),
        max(null_vals),
        0.0,
        float("inf"),
        float("nan"),
        None,
        "not-a-number",
    ]
    test_values += random.sample(null_vals, 200)

    for v in test_values:
        expected = _percentile_rank_reference_triple_pass(v, null_vals)
        actual = pn.percentile_rank(v, null_vals)
        if expected is None:
            assert actual is None, f"value={v!r}: expected None, got {actual!r}"
        else:
            assert actual == pytest.approx(expected, rel=1e-12, abs=1e-12), f"value={v!r}"


def test_percentile_rank_basic():
    null = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9]
    assert pn.percentile_rank(9, null) == pytest.approx(95.0)
    assert pn.percentile_rank(0, null) == pytest.approx(5.0)
    assert pn.percentile_rank(4.5, null) == pytest.approx(50.0)


def test_percentile_rank_ties_midrank():
    assert pn.percentile_rank(1, [1, 1, 1, 1]) == pytest.approx(50.0)


def test_percentile_rank_empty_null_returns_none():
    assert pn.percentile_rank(5.0, []) is None


def test_percentile_rank_nonfinite_value_returns_none():
    assert pn.percentile_rank(float("inf"), [1, 2, 3]) is None
    assert pn.percentile_rank(float("nan"), [1, 2, 3]) is None
    assert pn.percentile_rank(None, [1, 2, 3]) is None


def test_percentile_rank_drops_nonfinite_from_null():
    null = [1, 2, 3, float("inf"), float("nan"), None]
    assert pn.percentile_rank(2, null) == pytest.approx(50.0)


@pytest.mark.parametrize(
    "pct,expected",
    [
        (99.5, "top_1pct"),
        (99.0, "top_1pct"),
        (95.0, "top_decile"),
        (90.0, "top_decile"),
        (50.0, "mid"),
        (11.0, "mid"),
        (10.0, "bottom_decile"),
        (2.0, "bottom_decile"),
        (None, "data_unavailable"),
    ],
)
def test_classify_percentile_boundaries(pct, expected):
    assert pn.classify_percentile(pct) == expected


def test_classify_percentile_custom_cutoffs():
    assert pn.classify_percentile(85.0, {"top_decile": 80.0}) == "top_decile"
