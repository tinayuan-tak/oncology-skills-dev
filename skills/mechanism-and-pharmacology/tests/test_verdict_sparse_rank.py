"""Network shape is the sole mechanism verdict axis; the PD marker never masks it.

Before 2026-07-17, has_pd_marker (fires on >=1 downstream effector — also true for many
sparse networks) outranked sparse, burying the shape read. That was fixed by ordering shape
first, but the has_pd_marker rung was then STRUCTURALLY DEAD (proven: has-pd-marker-supportive
fires iff n_downstream>=1, which forces network_class ∈ {well/partial/sparse}, so a shape rung
always co-fires and outranks it). The dead rung was REMOVED (2026-09-07, resolver v1.2.0); the PD
marker survives non-verdictally as headline.has_pd_marker. These tests pin that shape always wins
and that has-pd-marker-supportive alone no longer resolves to a verdict.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

me = load_run_py(Path(__file__).resolve().parent.parent, "me_run")


def test_sparse_beats_pd_marker():
    v, _ = me._verdict([{"rule_id": "mechanism-sparse-warning"}, {"rule_id": "has-pd-marker-supportive"}])
    assert v == "sparse", "sparse network's opposing signal must not be buried by a PD marker"


def test_partial_beats_pd_marker():
    v, _ = me._verdict([{"rule_id": "mechanism-partial-neutral"}, {"rule_id": "has-pd-marker-supportive"}])
    assert v == "partial"


def test_pd_marker_rung_removed_falls_to_default():
    """The has_pd_marker rung was removed as structurally dead (resolver v1.2.0): has-pd-marker-supportive
    on its own — a fired-set unreachable from the real reader, since n_downstream>=1 always co-fires a
    shape rule — no longer resolves to a verdict; it falls through to the resolver default `insufficient`.
    (In production a shape rule always co-fires, so the real verdict is always well/partial/sparse.)"""
    v, _ = me._verdict([{"rule_id": "has-pd-marker-supportive"}])
    assert v == "insufficient"


def test_well_characterized_still_top():
    v, _ = me._verdict(
        [{"rule_id": "mechanism-well-characterized-supportive"}, {"rule_id": "has-pd-marker-supportive"}]
    )
    assert v == "well_characterized"
