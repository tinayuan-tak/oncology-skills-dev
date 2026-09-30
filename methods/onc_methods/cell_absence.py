"""Shared CELL-level absence discipline: does this one cell carry a value, and if so, is it usable?

⚠️ NOT the same axis as `target_id_sidecar.is_definitively_absent`, which classifies an EXCEPTION
(a genuine NoSuchKey/404 vs a transient/creds/broken-env failure) so a reader never reports a live
target as `data_unavailable`. THIS module classifies a VALUE that a reader already pulled out of a
frame. Both are "absence"; they fire at different seams and neither substitutes for the other.

WHY THIS EXISTS
---------------
The repo answers "does this cell have a value?" in FIVE mutually inconsistent ways, each correct
for the data it happens to see and each with a DIFFERENT blind spot (counts measured 2026-09-16
across methods/):

    pd.isna            53 sites   ADMITS ±Inf (fails OPEN); raises on empty under numpy 2
    pd.notna           31 sites   same
    np.isnan           23 sites   raises on object dtype / strings
    math.isnan         17 sites   raises TypeError on a str or None
    str(x) == "nan"     4 sites   misses None, since str(None) == "None"

and separately 661 `x is not None` (misses float nan ENTIRELY — nan is TRUTHY, so `or`-chains and
`if not x` guards written for absence never fire) plus 176 frame-level fillna/dropna.

Four of these traps were already found the hard way and fixed LOCALLY, each with a good docstring
and no shared home:
  - `cptac_protein_deg/steps/03_pool_and_write.py` open-codes `x is not None and not pd.isna(x)
    and math.isfinite(float(x))` because `pd.isna(Inf) is False` let ±Inf through to a `q >= 0.05`
    arm;
  - `cptac_protein_deg/read.py` does it again (`_is_num` + `math.isfinite`);
  - `depmap_common/loaders.py` open-codes the whole-row `{k: None if pd.isna(v) else v}` exit and
    documents why NaN-truthiness silently killed a `meta.get(...) or "unknown"` chain;
  - `target_id_sidecar._BAD_VALUES` holds a stringified-null token set for the same problem
    one coercion later.
This module is that shared home. It INVENTS nothing: every predicate below was already being
hand-rolled somewhere in this repo.

THREE STATES, NOT TWO
---------------------
`missing` and `non_finite` are kept DISTINCT and that is the central design decision. Collapsing
them — an `is_absent()` that answers True for ±Inf — would DROP a non-finite value, and in this
codebase a dropped measurement reads as the FAVOURABLE "no liability" class, so a safety veto
fires LESS (the recorded "a safety gate must LABEL, not DROP" failure). ±Inf is a NUMBER with
ordinary value semantics: it survives every absence guard and then wins every `argmax`. So callers
get told which of the two they have and choose; nothing here decides for them.

Both predicates are legitimate, and the choice is genuinely per-site. `depmap_common/loaders.py`
argues correctly that for a numeric METADATA column `pd.isna` (missing-only) is the right test —
"a ±Inf there is a value, not a gap, and silently nulling it would destroy data; if one appears it
must be refused at the writer, not laundered here." That is why `is_missing()` deliberately does
NOT consider ±Inf missing, and why `as_float()` makes its `non_finite` policy a REQUIRED argument
rather than defaulting: there is no safe universal default, and a default would be silently wrong
at roughly half the call sites.

DELIBERATE NON-FEATURES
-----------------------
  - `""` is NOT missing. An empty-but-present cell is a different fact from an absent one, and
    widening absence to cover it is a behaviour change dressed as a cleanup. (`target_id_sidecar`
    treats "" as bad because a native ID may not be empty — that is a field-specific rule, not a
    general one, and it stays where it is.)
  - Stringified nulls ("nan", "<NA>", ...) are NOT missing by default, only under an explicit
    `stringified=True`. They are an artifact of somebody having already called `str()` on a real
    null; a cell whose genuine string content is "NA" is not absent.
  - No pandas/numpy/polars import. This module works in a method that has none of them, and it
    must never be the reason a polars-only reader pulls in pandas.
"""

from __future__ import annotations

import math
from typing import Any, Mapping, Optional

PRESENT = "present"
MISSING = "missing"
NON_FINITE = "non_finite"

# Sentinel scalars whose SELF-COMPARISON does not return a plain bool, so the `value != value`
# nan test below cannot be used on them: `pd.NA != pd.NA` is `pd.NA`, and `bool(pd.NA)` raises
# "boolean value of NA is ambiguous". Matched by type NAME so this module imports no dataframe
# library. Covers pandas' NAType / NaTType and numpy's masked constant.
_NA_TYPE_NAMES = frozenset({"NAType", "NaTType", "MaskedConstant"})

# Lower-cased tokens that a real null becomes once something has called str() on it. NOTE: "" is
# absent from this set on purpose (see DELIBERATE NON-FEATURES above).
_STRINGIFIED_NULLS = frozenset({"nan", "none", "null", "na", "<na>", "nat", "<nil>"})


def _reject_non_scalar(value: Any) -> None:
    """Raise if `value` is a container. A Series/array self-compares to an ARRAY, and `bool()` of
    that either raises or — for a length-1 array — quietly succeeds, so a container would get a
    per-cell answer it has no business receiving. Answering False (`present`) for an all-NaN
    column would be the fail-OPEN direction, which is why this raises instead of guessing."""
    if isinstance(value, (str, bytes)):
        return
    if hasattr(value, "__len__") or hasattr(value, "__iter__"):
        raise TypeError(
            f"cell_absence takes a SCALAR cell, got {type(value).__name__}. Iterate the container "
            f"and ask per cell — a container answer here would be a per-cell answer to the wrong "
            f"question, and for an all-null column it would read as 'present'."
        )


def is_missing(value: Any, *, stringified: bool = False) -> bool:
    """True when this cell carries NO value.

    Recognises every shape a missing cell arrives in across this repo's readers:
      - `None`                      — polars' null, and pandas' object columns from parquet;
      - float `nan`                 — pandas' `read_csv`, including `dtype=str` (a missing STRING
                                      cell is float nan, and nan is TRUTHY);
      - `pd.NA` / `pd.NaT`          — pandas' nullable dtypes and datetimes;
      - `numpy.ma.masked`;
      - `Decimal("NaN")`.

    ±Inf is NOT missing — it is a value (see the module docstring). Use `is_non_finite` or
    `classify` for that.

    `stringified=True` additionally treats "nan"/"none"/"null"/"na"/"<na>"/"nat" (case- and
    whitespace-insensitive) as missing. Pass it ONLY where the value has already been through a
    `str()` coercion, which is the sole way those tokens are produced by a null. `""` is never
    missing, with or without the flag.

    Raises TypeError on a container — see `_reject_non_scalar`.
    """
    if value is None:
        return True
    if type(value).__name__ in _NA_TYPE_NAMES:
        return True
    if isinstance(value, str):
        return stringified and value.strip().lower() in _STRINGIFIED_NULLS
    if isinstance(value, bytes):
        return False
    _reject_non_scalar(value)
    # nan is the only value that is not equal to itself. Covers float, numpy scalars, Decimal
    # and pd.Timestamp("NaT") without naming any of their types.
    try:
        return bool(value != value)
    except (TypeError, ValueError):
        # A scalar whose __ne__ is not boolean-evaluable. Not a null shape we know; report it as
        # present rather than inventing absence, since a false "missing" is the fail-open answer.
        return False


def is_non_finite(value: Any) -> bool:
    """True when this cell holds ±Infinity — a real number that no threshold comparison can be
    trusted with, and which every absence guard in this repo admits.

    Also true for the STRING "inf"/"-inf"/"1e400", because a `dtype=str` read of an infinite cell
    produces exactly that and it is still non-finite. False for missing (ask `is_missing`) and
    false for anything non-numeric.
    """
    if is_missing(value):
        return False
    if isinstance(value, bytes):
        return False
    try:
        return math.isinf(float(value))
    except (TypeError, ValueError):
        return False


def classify(value: Any, *, stringified: bool = False) -> str:
    """Sort a cell into exactly one of PRESENT / MISSING / NON_FINITE.

    Use this wherever the three cases need DIFFERENT handling — which, for anything feeding a
    verdict, is most places: `missing` is an honest coverage gap, while `non_finite` is corrupt
    input that must be labelled rather than quietly binned with the gaps.

    ⚠️ `classify(x) == PRESENT` IS NOT A "IS THIS A USABLE NUMBER?" TEST, and must not be
    substituted for one. PRESENT means only *not missing and not non-finite*; it says nothing about
    whether the cell is numeric. It answers PRESENT for 'Detected in all', '', '   ', '-' and b'x'.
    #650's description tabled `x is not None and not pd.isna(x) and math.isfinite(float(x))` →
    `classify(x) == PRESENT`; that mapping is WRONG — measured over 43 input shapes it diverges on
    17 of them, every one admitting a non-numeric cell into a numeric path, which is the fail-open
    direction for a guard whose job is to reject garbage. For that question use:

        as_float(x, non_finite="missing") is not None      # MEASURED equivalent, both pandas majors

    Kept here rather than only in the PR thread because the wrong version reads perfectly plausibly
    at a call site, and a reviewer reaching for the shared helper will reach for this function first.
    """
    if is_missing(value, stringified=stringified):
        return MISSING
    if is_non_finite(value):
        return NON_FINITE
    return PRESENT


def as_str(value: Any, *, strip: bool = True, stringified: bool = False) -> Optional[str]:
    """Coerce a cell to `str`, or None when missing. Never returns the literal "nan".

    `strip=True` (default) trims surrounding whitespace. A cell that is only whitespace becomes
    "" and stays PRESENT — it is empty, not absent, and this function will not silently promote
    one to the other.
    """
    if is_missing(value, stringified=stringified):
        return None
    s = str(value)
    return s.strip() if strip else s


def as_float(value: Any, *, non_finite: str) -> Optional[float]:
    """Coerce a cell to `float`, or None when missing or unparseable.

    GUARANTEE: this NEVER returns a nan, under any policy. A nan return would pass a caller's
    `is not None` guard and then make every comparison against it False — the precise failure this
    module exists to prevent, so it must not leak back in here. The subtle route in is a cell whose
    STRING content is "nan"/"NaN"/"-nan": `is_missing` correctly calls that present (a string cell
    reading "nan" is text, not absence), and `float()` correctly parses it, and the composition of
    those two correct answers is a live nan. `dtype=str` reads of TSVs written by R (which emits
    "NaN"/"NA") hit this directly. A float coercion that lands on a not-a-number has not found a
    number, so the answer is None — the same as any other unparseable cell. This is NOT the
    `stringified` question, which is about whether the string "nan" counts as ABSENT; here the
    caller has explicitly asked for a NUMBER and there is none.

    `non_finite` is REQUIRED and has no default, because there is no answer that is right at even
    half of this repo's call sites and a wrong default here fails silently:
      - `"missing"` — fold ±Inf in with the gaps. Choose this ONLY when a gap and a corrupt value
        genuinely warrant the same downstream treatment; if a veto or a ranking reads the result,
        it almost certainly does not, because the two carry opposite evidential weight.
      - `"keep"`    — return the inf and let the caller deal with it. Correct when writing data
        through faithfully; remember `math.inf` beats every threshold and wins every argmax.
      - `"raise"`   — ValueError. Correct in a precompute/writer step, where a non-finite is a
        real upstream defect that should stop the run rather than land in an artifact.
    """
    if non_finite not in (MISSING, "keep", "raise"):
        raise ValueError(f"non_finite must be one of 'missing', 'keep', 'raise'; got {non_finite!r}")
    if is_missing(value):
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f):
        # A string like "nan" parsed cleanly but denotes no number. See the GUARANTEE above.
        return None
    if math.isinf(f):
        if non_finite == "raise":
            raise ValueError(f"non-finite value {value!r} where a finite number was required")
        if non_finite == MISSING:
            return None
    return f


def plain_row(row: Mapping[str, Any], *, stringified: bool = False) -> dict:
    """Normalise a whole row dict at the frame boundary: every missing cell becomes `None`.

    This is the seam that makes a reader's dataframe library an implementation detail. Once a row
    has been through here, downstream code sees ONE null shape regardless of whether the frame came
    from pandas (float nan), polars (None), or a hand-built test fixture — which is what lets a
    reader swap libraries without touching a single guard below it.

    Consciously does NOT touch ±Inf: a non-finite is a value, and laundering it to None here would
    hide a real upstream defect behind an honest-looking gap. Refuse it at the writer
    (`json.dumps(..., allow_nan=False)`) or label it via `classify`.
    """
    return {k: (None if is_missing(v, stringified=stringified) else v) for k, v in row.items()}
