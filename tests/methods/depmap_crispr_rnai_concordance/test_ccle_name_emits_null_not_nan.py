"""per_line_concordance[] must be serialisable — the single largest source of invalid JSON in the corpus.

Measured over the 504-package archetype corpus before this fix: `per_line_concordance[].ccle_name` and
`.lineage` held `float('nan')` in **119,536 leaves across 496 of 504 packages — 98.2% of every non-finite
value the framework emitted**, and 501 of 504 packages failed a strict JSON parse as a direct result.
Fixing this one frame boundary takes that 501 down to 163.

The card code here never changed: it always wrote a bare `meta.get("CCLEName")`, which is correct. What
changed is that `depmap_common.model_metadata_by_id` now guarantees the dict holds None rather than NaN, so
the bare `.get()` abstains instead of shipping a float where a cell-line name belongs.

★ This is the "guard that would have caught it" for producer fix A: the first test asserts the pre-fix
expression still fails, so this file cannot degrade into testing a tautology.
"""

from __future__ import annotations

import json
import math
from io import StringIO

import pytest

pd = pytest.importorskip("pandas")

from methods.depmap_common import model_metadata_by_id  # noqa: E402
from methods.depmap_crispr_rnai_concordance.cli import compute_concordance  # noqa: E402

# ACH-000009 is the real shape: CCLEName is a legacy field genuinely absent for newer DepMap models, so a
# missing name sits beside a present lineage. ACH-000010 lacks both.
MODEL_CSV = """ModelID,CellLineName,CCLEName,OncotreeLineage,OncotreeSubtype
ACH-000001,NIHOVCAR3,NIHOVCAR3_OVARY,Ovary/Fallopian Tube,High-Grade Serous
ACH-000002,HL-60,HL60_HAEMATOPOIETIC,Myeloid,AML
ACH-000009,NEWMODEL1,,Lung,LUAD
ACH-000010,,,,
"""

CHRONOS = {"ACH-000001": -1.4, "ACH-000002": -0.2, "ACH-000009": -0.9, "ACH-000010": 0.1}
DEMETER = {"ACH-000001": -0.8, "ACH-000002": -0.1, "ACH-000009": -0.05}


def _metadata():
    return model_metadata_by_id(pd.read_csv(StringIO(MODEL_CSV)))


def test_the_pre_fix_frame_boundary_still_produces_unserialisable_output():
    """Pin the pre-state: the naive dict comprehension every call site used to spell."""
    df = pd.read_csv(StringIO(MODEL_CSV))
    naive = {row["ModelID"]: row.to_dict() for _, row in df.iterrows()}
    out = compute_concordance(CHRONOS, DEMETER, naive)
    leaked = [r for r in out["per_line_concordance"] if isinstance(r["ccle_name"], float)]
    assert leaked, "fixture no longer reproduces the leak — the assertions below would be vacuous"
    assert all(math.isnan(r["ccle_name"]) for r in leaked)
    with pytest.raises(ValueError, match="Out of range float"):
        json.dumps(out, allow_nan=False)


def test_missing_ccle_name_emits_none():
    out = compute_concordance(CHRONOS, DEMETER, _metadata())
    by_id = {r["model_id"]: r for r in out["per_line_concordance"]}
    assert by_id["ACH-000009"]["ccle_name"] is None
    assert by_id["ACH-000009"]["lineage"] == "Lung", "a present sibling must survive untouched"
    assert by_id["ACH-000010"]["ccle_name"] is None
    assert by_id["ACH-000010"]["lineage"] is None
    assert by_id["ACH-000001"]["ccle_name"] == "NIHOVCAR3_OVARY"


def test_the_whole_card_summary_serialises_under_allow_nan_false():
    """The structural claim, at the grain Stage 2's writer will enforce (501 → 163 packages)."""
    out = compute_concordance(CHRONOS, DEMETER, _metadata())
    json.dumps(out, allow_nan=False)  # must not raise

    bad = [(path, v) for path, v in _walk(out) if isinstance(v, float) and not math.isfinite(v)]
    assert bad == [], f"non-finite values survived into the card summary: {bad}"


def test_an_unknown_name_abstains_rather_than_borrowing_the_model_id():
    """model_id is emitted alongside, so None is the honest value — do not back-fill an ID as a name."""
    out = compute_concordance(CHRONOS, DEMETER, _metadata())
    by_id = {r["model_id"]: r for r in out["per_line_concordance"]}
    assert by_id["ACH-000010"]["ccle_name"] != "ACH-000010"
    assert by_id["ACH-000010"]["model_id"] == "ACH-000010", "the ID is still reachable, just not as a name"


def _walk(obj, path="$"):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, obj
