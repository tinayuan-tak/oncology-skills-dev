"""model_metadata_by_id must convert every MISSING metadata value to None, never float('nan').

★ THE CONSTRUCTION PATH IS THE TEST. A DataFrame built from a Python dict of lists preserves `None` as
`None`, so it does NOT reproduce this bug and a test written that way passes against the broken code. Only
`pd.read_csv` — the production path — turns an empty CSV cell in a string column into `float('nan')`. Every
frame in this module is therefore parsed from CSV text, and `test_the_fixture_actually_reproduces_the_leak`
asserts the raw pre-fix behaviour so the fixture cannot silently stop being a reproduction.

Why this matters beyond JSON validity: `float('nan')` is TRUTHY, so the `or`-chain fallbacks the callers
already wrote (`meta.get("OncotreeLineage") or ... or "unknown"`) cannot fire on it. Converting to None
ACTIVATES those existing guards; converting to a literal default would bypass them. See the helper's
docstring.
"""

from __future__ import annotations

import json
import math
from io import StringIO

import pytest

pd = pytest.importorskip("pandas")

from methods.depmap_common import model_metadata_by_id  # noqa: E402

# A missing CCLEName (legacy field, genuinely absent for newer models) and a missing OncotreeLineage —
# the exact two columns behind 119,536 non-finite corpus leaves. ACH-9 carries neither.
MODEL_CSV = """ModelID,CellLineName,CCLEName,OncotreeLineage,OncotreeSubtype
ACH-000001,NIHOVCAR3,NIHOVCAR3_OVARY,Ovary/Fallopian Tube,High-Grade Serous
ACH-000002,HL-60,HL60_HAEMATOPOIETIC,Myeloid,AML
ACH-000009,,,,
"""


def _frame():
    return pd.read_csv(StringIO(MODEL_CSV))


def test_the_fixture_actually_reproduces_the_leak():
    """The pre-fix expression, on this fixture, must still produce truthy NaN — else the test is vacuous."""
    df = _frame()
    naive = {row["ModelID"]: row.to_dict() for _, row in df.iterrows()}
    leaked = naive["ACH-000009"]
    assert isinstance(leaked["CCLEName"], float) and math.isnan(leaked["CCLEName"]), (
        "pd.read_csv no longer yields float('nan') for an empty object-dtype cell; this fixture has "
        "stopped reproducing the bug and every assertion below is now vacuous."
    )
    # Consequence 1 — the behavioural one. NaN is truthy, so the callers' own fallback returns the NaN.
    fallback = leaked["CCLEName"] or "unknown"
    assert isinstance(fallback, float) and math.isnan(fallback), (
        f"expected the `or`-chain to be inert against a truthy NaN, got {fallback!r}"
    )
    # Consequence 2 — the structural one, and what Stage 2's writer will refuse.
    with pytest.raises(ValueError, match="Out of range float"):
        json.dumps(naive, allow_nan=False)


def test_missing_values_become_none():
    meta = model_metadata_by_id(_frame())
    absent = meta["ACH-000009"]
    assert absent["CCLEName"] is None
    assert absent["OncotreeLineage"] is None
    assert absent["CellLineName"] is None
    assert absent["OncotreeSubtype"] is None
    # ...and populated values are untouched, including the key column itself.
    assert meta["ACH-000001"]["CCLEName"] == "NIHOVCAR3_OVARY"
    assert meta["ACH-000001"]["OncotreeLineage"] == "Ovary/Fallopian Tube"
    assert meta["ACH-000002"]["ModelID"] == "ACH-000002"


def test_no_non_finite_float_survives_anywhere():
    """The structural claim, quantified over every leaf — this is what allow_nan=False will enforce."""
    meta = model_metadata_by_id(_frame())
    bad = [
        (mid, k, v)
        for mid, row in meta.items()
        for k, v in row.items()
        if isinstance(v, float) and not math.isfinite(v)
    ]
    assert bad == [], f"non-finite metadata survived the frame boundary: {bad}"
    json.dumps(meta, allow_nan=False)  # must not raise — the whole point of the fix


def test_none_activates_the_callers_existing_or_chain():
    """The behavioural claim: the fallback the callers already wrote now fires. NaN would not let it."""
    meta = model_metadata_by_id(_frame())
    absent = meta["ACH-000009"]
    lineage = absent.get("OncotreeLineage") or absent.get("lineage") or absent.get("PrimaryDisease") or "unknown"
    assert lineage == "unknown"
    name = absent.get("CellLineName") or "ACH-000009"
    assert name == "ACH-000009"


def test_key_column_resolution_matches_what_callers_open_coded():
    df = _frame()
    assert set(model_metadata_by_id(df)) == {"ACH-000001", "ACH-000002", "ACH-000009"}
    # No ModelID column → first column, the fallback every call site spelled by hand.
    no_id = pd.read_csv(StringIO("CCLE_ID,lineage\n127399_SOFT_TISSUE,soft_tissue\n"))
    assert set(model_metadata_by_id(no_id)) == {"127399_SOFT_TISSUE"}


def test_a_row_with_a_missing_key_is_dropped_not_keyed_by_none():
    """★ Found by this test file, not by the corpus: converting VALUES leaves the KEY unconverted.

    `row[model_id_col]` is taken raw, so ACH-9's blank CellLineName became a `float('nan')` DICT KEY —
    an entry no caller can reach (`.get(real_id)` never matches it) that json.dumps would coerce to the
    fabricated ID "NaN". Dropped instead, and asserted at the grain that matters: no key is non-finite,
    and no key is None either.
    """
    keyed = model_metadata_by_id(_frame(), "CellLineName")
    assert set(keyed) == {"NIHOVCAR3", "HL-60"}, "the keyless row must be dropped, not carried under None"
    assert all(isinstance(k, str) for k in keyed), f"a non-string model id survived: {list(keyed)}"
    # Round-trips without inventing an ID — json.dumps stringifies keys, so this is the real exposure.
    assert "NaN" not in json.dumps(keyed, allow_nan=False)


def test_infinity_is_preserved_because_it_is_a_value_not_a_gap():
    """★ pd.isna means MISSING here, and that is deliberate — nulling an Inf would destroy data.

    Recorded because the sibling trap runs the other way (`pd.isna(inf) is False` lets Inf through an
    absence guard). A ±Inf in a numeric metadata column must be refused at the writer, not laundered here,
    so this test pins the non-conversion rather than treating it as an oversight.
    """
    df = pd.read_csv(StringIO("ModelID,Age\nACH-000001,inf\nACH-000002,\n"))
    meta = model_metadata_by_id(df)
    assert math.isinf(meta["ACH-000001"]["Age"]), "Inf must survive — it is a value, not a missing cell"
    assert meta["ACH-000002"]["Age"] is None, "an empty numeric cell is still a gap"
