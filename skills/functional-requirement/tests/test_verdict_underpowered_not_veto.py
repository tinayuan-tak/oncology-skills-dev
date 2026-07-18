"""DepMap-power admissibility guard: an under-powered pooled negative must NOT veto.

When a lineage/genotype-restricted dependency is under-sampled in DepMap (EGFR-mut
lung, FLT3-mut AML, IDH1-mut), the pooled pan-cancer fraction falls below the floor and
the classifier emits `non_dependent_underpowered` (not `non_dependent`). The
non-dependent-killer rule does not fire; _verdict must return a distinct
`insufficient_underpowered` verdict — NEVER `non_dependent` — so the nomination gate
(which vetoes only on `non_dependent`) treats it as a coverage gap, not a false negative.
Sibling of test_verdict_rnai_not_veto.py (both are 'X must not veto' guards)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("fr_run", RUN)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


fr = _load()


def test_underpowered_maps_to_insufficient_not_non_dependent():
    v, drv = fr._verdict([{"rule_id": "non-dependent-underpowered-insufficient"}])
    assert v != "non_dependent", "underpowered pooled negative must not reach the veto verdict"
    assert v == "insufficient_underpowered"
    assert drv == "non-dependent-underpowered-insufficient", "driving rule recorded for provenance"


def test_genuine_non_dependent_still_vetoes_control():
    """CONTROL: a real pan-negative (non-dependent-killer) must still veto — the guard
    only spares the underpowered case, not genuine non-dependence."""
    assert fr._verdict([{"rule_id": "non-dependent-killer"}]) == (
        "non_dependent", "non-dependent-killer")


def test_pan_essential_precedence_intact():
    """A pan-essential killer still wins even if the underpowered rule somehow co-fires
    (defensive: the classifier emits one class, but precedence must hold)."""
    v, _ = fr._verdict([{"rule_id": "pan-essential-killer"},
                        {"rule_id": "non-dependent-underpowered-insufficient"}])
    assert v == "pan_essential_killer"
