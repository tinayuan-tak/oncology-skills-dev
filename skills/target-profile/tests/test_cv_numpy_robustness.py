"""Regression: _cv must not crash on numpy floats (DLL3/SCLC heterogeneity-facet crash).

numpy.float64 passes isinstance(v, float) (it subclasses float), but statistics.mean/pstdev
raise "'float' object has no attribute 'numerator'" on numpy scalars in py3.12. _heterogeneity_facet
fed the selectivity card's log2fc_cell_a/b/c (numpy floats) straight into _cv, so any
strong_tumor_selective target with all three cells populated crashed the whole run. _cv now
coerces to Python float (and drops bool/NaN).
"""
from __future__ import annotations

import importlib.util
import math
from pathlib import Path

import pytest

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("tp_run", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


tp = _load()
np = pytest.importorskip("numpy")


def test_cv_on_numpy_floats_does_not_crash():
    """The DLL3/SCLC regression: three numpy.float64 log2fc values must yield a finite CV."""
    vals = [np.float64(2.0), np.float64(4.0), np.float64(6.0)]
    cv = tp._cv(vals)
    assert cv is not None
    assert isinstance(cv, float) and math.isfinite(cv)


def test_cv_matches_python_floats():
    """numpy and python-float inputs give the same CV (coercion is value-preserving)."""
    assert tp._cv([np.float64(2.0), np.float64(4.0), np.float64(6.0)]) == pytest.approx(
        tp._cv([2.0, 4.0, 6.0])
    )


def test_cv_excludes_bool_and_nan_and_needs_two():
    assert tp._cv([True, False, 5.0]) is None          # bools excluded → <2 numerics
    assert tp._cv([np.float64("nan"), 3.0]) is None      # NaN dropped → <2 numerics
    assert tp._cv([5.0]) is None                          # <2
    assert tp._cv([0.0, 0.0]) is None                     # mean 0 → undefined CV
