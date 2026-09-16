"""Stage 1 adoption of methods/cell_absence.py — the equivalence each swap CLAIMS, pinned.

Every adoption in this stage claims to be a no-op. A claim like that decays silently: someone widens
a predicate in cell_absence.py for a good reason at one call site and a different call site quietly
changes verdict. So each swap's PREVIOUS BODY is kept here as the oracle and the live code is
measured against it over a shared corpus of every shape these cells actually arrive in.

Two things this file is careful about:

  1. THE ORACLE IS THE OLD CODE, NOT MY DESCRIPTION OF IT. `_legacy_*` below are verbatim copies of
     the bodies that shipped before the swap, so the test cannot drift toward what I *meant*.

  2. IT PINS THE NEGATIVE TOO. `classify(x) == PRESENT` is a plausible-looking substitution for
     "is this a usable number?" that is measurably WRONG (17 divergences, all admitting non-numeric
     cells into a numeric path). #650's description tabled it. If it were ever swapped in, the
     positive tests would still pass — so the wrongness is asserted directly.

Libraries are imported at module scope, not via importorskip: a silent skip on the file that pins
these equivalences is indistinguishable from a pass.
"""

from __future__ import annotations

import importlib.util
import math
import sys
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods import cell_absence as ca  # noqa: E402

_STEP = REPO / "methods" / "cptac_protein_deg" / "steps" / "03_pool_and_write.py"


def _load_step():
    """Load 03_pool_and_write.py by path — its filename is not a valid identifier."""
    spec = importlib.util.spec_from_file_location("_pool03_adoption", _STEP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_pool03_adoption"] = mod
    spec.loader.exec_module(mod)
    return mod


# --- the shared corpus: every shape a cell arrives in on these paths ---------------------------
# Ordered roughly null → non-finite → finite. Names are used in failure messages.
CORPUS: list[tuple[str, object]] = [
    ("None", None),
    ("float_nan", float("nan")),
    ("np_nan", np.nan),
    ("np_float64_nan", np.float64("nan")),
    ("pd_NA", pd.NA),
    ("pd_NaT", pd.NaT),
    ("decimal_nan", Decimal("NaN")),
    ("str_nan", "nan"),
    ("str_NaN", "NaN"),
    ("str_NAN", "NAN"),
    ("str_nan_padded", "  nan  "),
    ("str_none", "none"),
    ("str_None", "None"),
    ("str_null", "null"),
    ("str_na", "na"),
    ("str_NA", "NA"),
    ("str_angle_NA", "<NA>"),
    ("str_nat", "nat"),
    ("str_nil", "<nil>"),
    ("empty_str", ""),
    ("whitespace_str", "   "),
    ("pos_inf", math.inf),
    ("neg_inf", -math.inf),
    ("np_inf", np.inf),
    ("str_inf", "inf"),
    ("str_neg_inf", "-inf"),
    ("str_Infinity", "Infinity"),
    ("str_1e400", "1e400"),
    ("zero_int", 0),
    ("zero_float", 0.0),
    ("false", False),
    ("true", True),
    ("int_7", 7),
    ("float_2p5", 2.5),
    ("np_float64_2p5", np.float64(2.5)),
    ("np_int64_7", np.int64(7)),
    ("decimal_2p5", Decimal("2.5")),
    ("str_2p5", "2.5"),
    ("str_0", "0"),
    ("str_text", "Detected in all"),
    ("str_hyphen", "-"),
    ("bytes", b"x"),
]


def _outcome(fn, value):
    """Evaluate a predicate, recording an exception as its own outcome so a RAISE-vs-False change
    is visible as a divergence rather than crashing the comparison."""
    try:
        return bool(fn(value))
    except Exception as exc:  # noqa: BLE001 — the exception TYPE is the observation
        return f"RAISE:{type(exc).__name__}"


def _divergences(oracle, live):
    return [
        (n, v, _outcome(oracle, v), _outcome(live, v)) for n, v in CORPUS if _outcome(oracle, v) != _outcome(live, v)
    ]


# --- SITE: cptac_protein_deg/steps/03_pool_and_write.py::_is_finite ----------------------------


def _legacy_is_finite(x) -> bool:
    """VERBATIM the body that shipped before the swap. Do not tidy — it is the oracle."""
    try:
        return x is not None and not pd.isna(x) and math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def test_pool_is_finite_is_unchanged_by_the_swap():
    """`_is_finite` now delegates to as_float(non_finite='missing'); prove that changed nothing.

    This guard decides whether an MSstatsTMT ±Inf (an unestimable contrast — a ratio with no
    denominator) reaches the `q >= 0.05` arm and gets labelled `not_significant`. A widening here
    reintroduces the exact defect test_unestimable_contrast.py exists to prevent.
    """
    step = _load_step()
    diffs = _divergences(_legacy_is_finite, step._is_finite)
    assert not diffs, "\n".join(f"  {n:18} {v!r:22} legacy={a!s:10} live={b!s:10}" for n, v, a, b in diffs)


def test_pool_is_finite_still_rejects_the_things_that_matter():
    """Belt-and-braces on the two shapes with a recorded incident behind them, so this file fails
    loudly rather than only reporting 'the oracle agrees' if the corpus is ever thinned."""
    step = _load_step()
    for bad in (math.inf, -math.inf, float("nan"), None, "", "not a number"):
        assert step._is_finite(bad) is False, f"{bad!r} must not read as a usable number"
    for good in (0.0, -1.5, 2.5, "0.04", 7):
        assert step._is_finite(good) is True, f"{good!r} must read as a usable number"


def test_classify_present_is_NOT_a_usable_number_test():
    """The falsified mapping from #650's description, asserted as wrong so it cannot be swapped back.

    `classify(x) == PRESENT` means 'not missing and not non-finite' — it says nothing about being
    numeric, so it admits text, '' and bytes into a numeric path. Every divergence runs in the
    permissive direction for a guard whose job is to REJECT garbage.
    """
    diffs = _divergences(_legacy_is_finite, lambda x: ca.classify(x) == ca.PRESENT)
    assert len(diffs) >= 15, f"expected the wrong mapping to diverge widely; got {len(diffs)}"
    # and specifically: it admits things that are plainly not numbers
    for text in ("Detected in all", "", "   ", "-"):
        assert ca.classify(text) == ca.PRESENT, "precondition: classify calls these PRESENT"
        assert _legacy_is_finite(text) is False, "precondition: the real guard rejects them"
    # the correct substitution, restated as an executable claim
    for name, value in CORPUS:
        assert _legacy_is_finite(value) == (ca.as_float(value, non_finite="missing") is not None), name


# --- SITE: depmap_common/loaders.py::model_metadata_by_id -------------------------------------


def _legacy_plain_cell(v):
    """VERBATIM the per-cell rule that shipped before the swap: {k: None if pd.isna(v) else v}."""
    return None if pd.isna(v) else v


def test_depmap_row_normalisation_is_unchanged_by_the_swap():
    """plain_row() must null exactly what `pd.isna` nulled — no more, no less.

    ±Inf is the load-bearing case: a ±Inf in a numeric metadata column is a VALUE, not a gap, and
    nulling it would destroy data. Both the old rule and plain_row leave it alone.
    """
    diffs = _divergences(
        lambda v: _legacy_plain_cell(v) is None,
        lambda v: ca.plain_row({"k": v})["k"] is None,
    )
    # np.ma.masked is deliberately excluded from CORPUS: pd.isna returns the masked constant itself
    # (which bools to False, i.e. "present") while it IS missing. plain_row is more correct there,
    # but no pandas reader emits it, so it is unreachable on this path and not worth a divergence.
    assert not diffs, "\n".join(f"  {n:18} {v!r:22} legacy_null={a!s:10} live_null={b!s:10}" for n, v, a, b in diffs)


def test_depmap_metadata_frame_round_trips_identically(tmp_path):
    """The frame-level claim, on a frame built the way the real loader builds one: a MIXED-dtype
    CSV read, which is the construction path that produces float nan in an object column."""
    from methods.depmap_common import loaders

    csv = tmp_path / "Model.csv"
    csv.write_text("ModelID,CCLEName,OncotreeLineage,Age\nACH-1,A549_LUNG,Lung,58\nACH-2,,,\n,ORPHAN,Skin,40\n")
    df = pd.read_csv(csv)

    legacy = {
        row["ModelID"]: {k: _legacy_plain_cell(v) for k, v in row.to_dict().items()}
        for _, row in df.iterrows()
        if not pd.isna(row["ModelID"])
    }
    live = loaders.model_metadata_by_id(df)
    assert live == legacy, f"live={live}\nlegacy={legacy}"

    # and the properties the docstring promises, stated directly rather than only via the oracle
    assert set(live) == {"ACH-1", "ACH-2"}, "the row with a MISSING KEY must be dropped, not kept under None"
    assert live["ACH-2"]["CCLEName"] is None, "a missing object-dtype cell must become None, not float nan"
    assert not any(isinstance(v, float) and math.isnan(v) for m in live.values() for v in m.values())


def test_depmap_normalisation_refuses_a_non_scalar_cell():
    """Previously a caveat in prose ('assumes scalar columns'); now enforced.

    `pd.isna` on a list-valued cell returns an ARRAY, so the old `if pd.isna(v)` raised only because
    bool() of a multi-element array raises. A LENGTH-1 container was the dangerous case: its truth
    value is well-defined, so it would have answered 'present' and shipped a container into JSON.
    """
    with pytest.raises(TypeError, match="SCALAR cell"):
        ca.plain_row({"k": [1, 2]})
    with pytest.raises(TypeError, match="SCALAR cell"):
        ca.plain_row({"k": [None]})  # the length-1 case bool() would NOT have caught
    with pytest.raises(TypeError, match="SCALAR cell"):
        ca.plain_row({"k": pd.Series([np.nan])})


# --- the corpus itself must stay able to express these failures --------------------------------


def test_the_corpus_is_not_vacuous():
    """A corpus that no longer discriminates turns every test above into a tautology.

    Asserts the corpus still contains all three classes AND that the two predicates under test
    genuinely disagree with a deliberately broken variant — so 'no divergences' is evidence.
    """
    classes = {ca.classify(v) for _, v in CORPUS}
    assert classes == {ca.MISSING, ca.NON_FINITE, ca.PRESENT}, classes
    # a broken _is_finite (drops the non-finite guard) MUST be caught by the oracle comparison
    broken = _divergences(_legacy_is_finite, lambda x: x is not None and not pd.isna(x))
    assert broken, "the corpus can no longer detect a dropped non-finite guard"
    assert any(n in {"pos_inf", "neg_inf", "np_inf"} for n, _, _, _ in broken), [n for n, *_ in broken]
