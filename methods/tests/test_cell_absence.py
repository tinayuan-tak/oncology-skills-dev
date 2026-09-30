"""Tests for methods/cell_absence.py — the shared cell-level absence discipline.

THE POINT OF THIS FILE is the construction-path matrix at the bottom. A missing cell is NOT one
shape: it depends on which reader produced it, and a test that builds its fixture as a Python dict
sees `None` and therefore PASSES against code that is broken for every real reader. That is exactly
how AM#644 shipped, and in the polars pilot (#648) one of my own new tests passed with
`infer_schema_length=0` deleted because the fixture held no numeric-looking cell. So the same
logical table is built FIVE ways here — pandas dtype=str, pandas type-inferred, pandas parquet,
polars, and dict — and the predicate must agree across all of them.

Libraries are imported at module scope, NOT via `pytest.importorskip`. pandas, polars and pyarrow
are all hard deps in pixi.toml; if one is missing this file must ERROR, because a silent skip on the
file that pins null semantics is indistinguishable from a pass.
"""

from __future__ import annotations

import math
from decimal import Decimal

import numpy as np
import pandas as pd
import polars as pl
import pytest

from onc_methods import cell_absence as ca

# --- is_missing: every shape a null arrives in ------------------------------


@pytest.mark.parametrize(
    "value",
    [
        None,
        float("nan"),
        np.nan,
        np.float64("nan"),
        pd.NA,
        pd.NaT,
        np.ma.masked,
        Decimal("NaN"),
    ],
    ids=["None", "float_nan", "np_nan", "np_float64_nan", "pd_NA", "pd_NaT", "np_masked", "decimal_nan"],
)
def test_is_missing_true_for_every_null_shape(value):
    assert ca.is_missing(value) is True
    assert ca.classify(value) == ca.MISSING


@pytest.mark.parametrize(
    "value",
    [0, 0.0, False, "", "   ", "0", "nan", "NA", "<NA>", "None", "text", b"", math.inf, -math.inf, Decimal("0")],
    ids=[
        "zero_int",
        "zero_float",
        "false",
        "empty_str",
        "whitespace_str",
        "str_zero",
        "str_nan",
        "str_NA",
        "str_angle_NA",
        "str_None",
        "str_text",
        "empty_bytes",
        "pos_inf",
        "neg_inf",
        "decimal_zero",
    ],
)
def test_is_missing_false_for_present_values(value):
    """Falsy-but-present values and ±Inf are NOT missing.

    `0`, `0.0`, `False`, `""` and `"   "` are the values a `if not x` guard wrongly folds in with
    absence. ±Inf is excluded deliberately: it is a value, and calling it missing would DROP it —
    which in this repo reads as the favourable 'no liability' class.
    """
    assert ca.is_missing(value) is False


def test_stringified_nulls_only_under_the_explicit_flag():
    """The "nan" token is an artifact of somebody having already called str() on a real null, so it
    is recognised ONLY on request. A cell whose genuine content is "NA" is not absent."""
    for token in ("nan", "NaN", "  NAN  ", "none", "None", "null", "NA", "<NA>", "nat"):
        assert ca.is_missing(token) is False, f"{token!r} must be present by default"
        assert ca.is_missing(token, stringified=True) is True, f"{token!r} under the flag"
    # "" is never missing, with or without the flag -- empty is not absent.
    assert ca.is_missing("", stringified=True) is False
    assert ca.is_missing("   ", stringified=True) is False
    # and a real value is untouched by the flag
    assert ca.is_missing("Detected in all", stringified=True) is False


def test_container_raises_rather_than_guessing():
    """A Series/array self-compares to an ARRAY. Answering False would be the fail-OPEN direction:
    an all-null column would read as 'present'."""
    for container in (pd.Series([1, 2]), np.array([1.0, np.nan]), [None], (None,), {"a": None}, {None}):
        with pytest.raises(TypeError, match="SCALAR cell"):
            ca.is_missing(container)
    # a length-1 container is the dangerous case -- bool() of its self-compare would SUCCEED
    with pytest.raises(TypeError, match="SCALAR cell"):
        ca.is_missing(pd.Series([np.nan]))
    # but strings and bytes are scalars, not containers, despite having __len__
    assert ca.is_missing("abc") is False
    assert ca.is_missing(b"abc") is False


# --- the ±Inf axis, kept distinct from missing ------------------------------


def test_non_finite_is_its_own_state_not_missing():
    """The recorded trap: `pd.isna(inf) is False`, so every absence guard admits ±Inf, and then
    `abs(inf)` wins every argmax. Here the two states are separate and both are reportable."""
    for inf in (math.inf, -math.inf, float("inf"), np.inf):
        assert ca.is_missing(inf) is False
        assert ca.is_non_finite(inf) is True
        assert ca.classify(inf) == ca.NON_FINITE
    # a dtype=str read of an infinite cell yields the STRING, still non-finite
    for s in ("inf", "-inf", "Infinity", "1e400"):
        assert ca.is_non_finite(s) is True, f"{s!r}"
    # missing is not non-finite, and finite numbers are neither
    assert ca.is_non_finite(None) is False
    assert ca.is_non_finite(float("nan")) is False
    assert ca.is_non_finite(3.5) is False
    assert ca.is_non_finite("text") is False
    assert ca.classify(3.5) == ca.PRESENT


def test_classify_partitions_exactly_three_ways():
    seen = {ca.classify(v) for v in (None, float("nan"), math.inf, 0, "x")}
    assert seen == {ca.MISSING, ca.NON_FINITE, ca.PRESENT}


# --- coercions --------------------------------------------------------------


def test_as_str_never_returns_the_literal_nan():
    """The bug this replaces: `str(cell)` on a pandas missing cell yields "nan", which then flows
    into a card field as if it were data."""
    assert ca.as_str(float("nan")) is None
    assert ca.as_str(None) is None
    assert ca.as_str(pd.NA) is None
    assert ca.as_str("  Detected in all  ") == "Detected in all"
    assert ca.as_str("  x  ", strip=False) == "  x  "
    # whitespace-only stays PRESENT as "" -- empty is not absent
    assert ca.as_str("   ") == ""
    assert ca.as_str(0) == "0"
    assert ca.as_str("nan") == "nan"  # present by default
    assert ca.as_str("nan", stringified=True) is None


def test_as_float_requires_an_explicit_non_finite_policy():
    """No default, on purpose: no single answer is right at even half the call sites, and a wrong
    default here fails SILENTLY."""
    with pytest.raises(TypeError):
        ca.as_float(1.0)  # missing the required keyword
    with pytest.raises(ValueError, match="non_finite must be one of"):
        ca.as_float(1.0, non_finite="whatever")


def test_as_float_non_finite_policies():
    assert ca.as_float("2.5", non_finite="raise") == 2.5
    assert ca.as_float(None, non_finite="raise") is None
    assert ca.as_float(float("nan"), non_finite="raise") is None
    assert ca.as_float("not a number", non_finite="raise") is None
    # keep -> the caller gets the inf and owns it
    assert ca.as_float(math.inf, non_finite="keep") == math.inf
    # missing -> folded in with the gaps (only where a gap and a corrupt value deserve the same fate)
    assert ca.as_float(math.inf, non_finite="missing") is None
    # raise -> a writer/precompute step stops instead of landing a non-finite in an artifact
    with pytest.raises(ValueError, match="non-finite"):
        ca.as_float(math.inf, non_finite="raise")
    with pytest.raises(ValueError, match="non-finite"):
        ca.as_float("-inf", non_finite="raise")


@pytest.mark.parametrize("policy", ["raise", "keep", "missing"])
@pytest.mark.parametrize("token", ["nan", "NaN", "-nan", "  nan  ", "NAN"])
def test_as_float_never_returns_a_nan_under_any_policy(token, policy):
    """A defect found by self-review, in the SEAM between two individually correct rules.

    `is_missing("nan") is False` is right — a string cell reading "nan" is text, not absence — and
    `float("nan")` parsing is right. Composed, they returned a live nan, which passes a caller's
    `is not None` guard and then makes EVERY comparison against it False. That is the exact trap
    this module exists to prevent, so it must not re-enter through the coercion. A `dtype=str` read
    of a TSV written by R (which emits "NaN"/"NA") produces this token directly.

    Note this is NOT the `stringified` question: there the issue is whether the STRING "nan" counts
    as absent. Here the caller asked for a NUMBER and there is none, so None is the only answer that
    keeps the contract "returns a float or None".
    """
    result = ca.as_float(token, non_finite=policy)
    assert result is None, f"as_float({token!r}, non_finite={policy!r}) leaked {result!r}"


def test_as_float_nan_guard_is_distinct_from_the_inf_guard():
    """±Inf and nan take DIFFERENT routes out, and conflating them would lose information.

    ±Inf is policy-dependent (a value the caller may legitimately want); nan is unconditionally
    None (never a value). The asymmetry is deliberate: I originally guarded only the inf axis --
    the one I was thinking about -- and missed nan entirely.
    """
    # inf is policy-sensitive
    assert ca.as_float("inf", non_finite="keep") == math.inf
    assert ca.as_float("inf", non_finite="missing") is None
    with pytest.raises(ValueError):
        ca.as_float("inf", non_finite="raise")
    # nan is not: None every time, and notably does NOT raise under "raise", because a nan is an
    # absent measurement rather than the corrupt-finite-value defect that policy is aimed at
    for policy in ("keep", "missing", "raise"):
        assert ca.as_float("nan", non_finite=policy) is None
    # and a real number still survives all of it
    assert ca.as_float("0.04", non_finite="raise") == 0.04
    assert ca.as_float(0.0, non_finite="raise") == 0.0


def test_plain_row_normalises_nulls_but_leaves_non_finite_alone():
    row = {"gene": "KRAS", "dist": float("nan"), "spec": None, "q": pd.NA, "score": math.inf, "n": 0}
    out = ca.plain_row(row)
    assert out == {"gene": "KRAS", "dist": None, "spec": None, "q": None, "score": math.inf, "n": 0}
    # every key survives -- normalising a row must not drop columns
    assert set(out) == set(row)
    # ±Inf deliberately untouched: laundering it to None would hide a defect behind an honest gap
    assert out["score"] == math.inf


# --- THE CONSTRUCTION-PATH MATRIX ------------------------------------------
# The same logical table, built five ways. A missing cell's SHAPE differs per path; the predicate
# must not. Build order matters: `dict` alone would pass against code that only handles None.

TSV = "gene\tdist\tnum\nKRAS\t\t\nEGFR\tDetected in all\t7\n"


def _paths(tmp_path):
    """Yield (label, row0_dict) for each construction path, all from the SAME source table."""
    tsv = tmp_path / "t.tsv"
    tsv.write_text(TSV)

    # 1. pandas, dtype=str -- what a "read everything as text" reader does. Missing STRING cell
    #    arrives as float nan (NOT None) under both pandas 2.3.3 and 3.0.3 (measured 2026-09-16).
    pdf_str = pd.read_csv(tsv, sep="\t", dtype=str)
    # 2. pandas, type-inferred -- the numeric column becomes float64, missing becomes nan
    pdf_typed = pd.read_csv(tsv, sep="\t")
    # 3. pandas via parquet -- a different null representation again (object cols can keep None)
    pq = tmp_path / "t.parquet"
    pdf_typed.to_parquet(pq)
    pdf_pq = pd.read_parquet(pq)
    # 4. polars -- a real null
    ldf = pl.read_csv(tsv, separator="\t", infer_schema_length=0)
    # 5. dict-built -- the fixture shape that hides every one of the above
    dct = {"gene": "KRAS", "dist": None, "num": None}

    return [
        ("pandas_dtype_str", pdf_str.iloc[0].to_dict()),
        ("pandas_typed", pdf_typed.iloc[0].to_dict()),
        ("pandas_parquet", pdf_pq.iloc[0].to_dict()),
        ("polars", ldf.row(0, named=True)),
        ("dict_built", dct),
    ]


def test_missing_cell_agrees_across_every_construction_path(tmp_path):
    """The invariant that makes a reader's library an implementation detail."""
    for label, row in _paths(tmp_path):
        assert ca.is_missing(row["dist"]) is True, f"{label}: dist={row['dist']!r} must read as missing"
        assert ca.is_missing(row["num"]) is True, f"{label}: num={row['num']!r} must read as missing"
        assert ca.is_missing(row["gene"]) is False, f"{label}: gene must read as present"
        assert ca.classify(row["dist"]) == ca.MISSING, label


def test_plain_row_gives_one_null_shape_from_every_path(tmp_path):
    """After the boundary, all five paths are indistinguishable. This is the property Stage 1
    adoption buys: downstream code stops needing to know which library read the frame."""
    normalised = {}
    for label, row in _paths(tmp_path):
        out = ca.plain_row(row)
        assert out["dist"] is None, f"{label}"
        assert out["num"] is None, f"{label}"
        normalised[label] = (out["gene"], out["dist"], out["num"])
    # the typed path reads gene as str in every case, so all five agree EXACTLY
    assert len(set(normalised.values())) == 1, f"paths disagree after normalisation: {normalised}"


def test_the_path_matrix_is_falsifiable_in_both_directions(tmp_path):
    """Guard against this file becoming the vacuous kind of test it exists to prevent.

    Asserts that the paths genuinely produce DIFFERENT raw shapes — so dropping either branch of
    is_missing() (the `None` check or the `value != value` nan check) reds the matrix above. If this
    ever fails, the matrix has stopped discriminating and is no longer evidence."""
    shapes = {label: type(row["dist"]).__name__ for label, row in _paths(tmp_path)}
    assert shapes["polars"] == "NoneType", shapes
    assert shapes["dict_built"] == "NoneType", shapes
    assert shapes["pandas_dtype_str"] == "float", shapes  # nan, NOT None -- the whole trap
    assert shapes["pandas_typed"] == "float", shapes
    assert len(set(shapes.values())) >= 2, f"matrix no longer discriminates: {shapes}"
    # and the nan really is truthy, which is why `if not x` guards miss it
    raw = dict(_paths(tmp_path))["pandas_dtype_str"]["dist"]
    assert bool(raw) is True, "a pandas missing cell must still be TRUTHY (the documented trap)"
    assert str(raw) == "nan"
