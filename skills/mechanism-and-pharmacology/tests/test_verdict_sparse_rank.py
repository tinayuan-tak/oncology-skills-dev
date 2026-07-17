"""C2b regression: a sparse network must not be masked by has_pd_marker.

Before 2026-07-17, has_pd_marker (fires on >=1 downstream effector — also true for
many sparse networks) outranked sparse in _verdict, so a sparse network with any PD
marker reported the supportive-flavored `has_pd_marker` and the `sparse`→opposing
signal never surfaced. Fix: network shape (well/partial/sparse) resolves before the
PD-marker flag.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("me_run", RUN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


me = _load()


def test_sparse_beats_pd_marker():
    v, _ = me._verdict([{"rule_id": "mechanism-sparse-warning"},
                        {"rule_id": "has-pd-marker-supportive"}])
    assert v == "sparse", "sparse network's opposing signal must not be buried by a PD marker"


def test_partial_beats_pd_marker():
    v, _ = me._verdict([{"rule_id": "mechanism-partial-neutral"},
                        {"rule_id": "has-pd-marker-supportive"}])
    assert v == "partial"


def test_pd_marker_alone_still_reports():
    v, _ = me._verdict([{"rule_id": "has-pd-marker-supportive"}])
    assert v == "has_pd_marker"


def test_well_characterized_still_top():
    v, _ = me._verdict([{"rule_id": "mechanism-well-characterized-supportive"},
                        {"rule_id": "has-pd-marker-supportive"}])
    assert v == "well_characterized"
