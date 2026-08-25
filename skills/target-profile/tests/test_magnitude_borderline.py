"""M4 magnitude-borderline consumer (VERDICT_REPRESENTATION move #5 / R5 over-precision) — reads the
record's magnitude value + distance_to_cut and flags knife-edge calls (a categorical verdict that
hard-cut a near-boundary continuous value). S3-free: pure over synthetic claim_record_shadow."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
SKILLS = SCRIPTS.parent.parent
for _p in (str(SKILLS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from tp_facets import _magnitude_borderline  # noqa: E402


def _rec(value, dist, scale="log2fc", level="moderate"):
    return {"claim_record_shadow": {"axis": "selectivity", "finding": {
        "magnitude": {"level": level, "value": value, "scale": scale, "distance_to_cut": dist}}}}


def test_knife_edge_call_is_flagged():
    sr = {"selectivity": _rec(0.6, 0.1)}          # 0.1 <= 0.25 band -> borderline
    out = _magnitude_borderline(sr)
    assert len(out) == 1 and out[0]["axis"] == "selectivity"
    assert out[0]["distance_to_cut"] == 0.1 and out[0]["band"] == 0.25


def test_well_clear_call_is_not_flagged():
    sr = {"selectivity": _rec(3.1, 1.6)}          # 1.6 > 0.25 -> not borderline
    assert _magnitude_borderline(sr) == []


def test_no_distance_or_unknown_scale_is_skipped():
    assert _magnitude_borderline({"a": _rec(0.6, None)}) == []          # no distance_to_cut
    assert _magnitude_borderline({"a": _rec(0.6, 0.1, scale="ceres")}) == []  # no band for this scale
    assert _magnitude_borderline({}) == []


def test_categorical_axis_without_value_is_skipped():
    # a record with magnitude level only (no continuous value) contributes nothing
    sr = {"safety": {"claim_record_shadow": {"axis": "safety",
          "finding": {"magnitude": {"level": "strong", "value": None, "scale": None,
                                    "distance_to_cut": None}}}}}
    assert _magnitude_borderline(sr) == []
