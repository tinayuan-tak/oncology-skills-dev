"""Unit tests for the all-gene percentile-null helper (Phase 1A).

Imports the helper by file path to avoid any package-name shadowing between this
test dir and methods/percentile_null/.
"""
import importlib.util
from pathlib import Path

import pytest

_HELPER = Path(__file__).resolve().parents[3] / "methods" / "percentile_null" / "__init__.py"
_spec = importlib.util.spec_from_file_location("pn_helper_under_test", _HELPER)
pn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pn)


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


@pytest.mark.parametrize("pct,expected", [
    (99.5, "top_1pct"), (99.0, "top_1pct"),
    (95.0, "top_decile"), (90.0, "top_decile"),
    (50.0, "mid"), (11.0, "mid"),
    (10.0, "bottom_decile"), (2.0, "bottom_decile"),
    (None, "data_unavailable"),
])
def test_classify_percentile_boundaries(pct, expected):
    assert pn.classify_percentile(pct) == expected


def test_classify_percentile_custom_cutoffs():
    assert pn.classify_percentile(85.0, {"top_decile": 80.0}) == "top_decile"
