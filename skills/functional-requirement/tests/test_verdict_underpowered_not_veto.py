"""DepMap-power admissibility guard: an under-powered pooled negative must NOT veto.

When a lineage/genotype-restricted dependency is under-sampled in DepMap (EGFR-mut
lung, FLT3-mut AML, IDH1-mut), the pooled pan-cancer fraction falls below the floor and
the classifier emits `non_dependent_underpowered` (not `non_dependent`). The
non-dependent-killer rule does not fire; _verdict must return a distinct
`insufficient_underpowered` verdict — NEVER `non_dependent` — so the nomination gate
(which vetoes only on `non_dependent`) treats it as a coverage gap, not a false negative.
Sibling of test_verdict_rnai_not_veto.py (both are 'X must not veto' guards)."""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

fr = load_run_py(Path(__file__).resolve().parent.parent, "fr_run")


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


# --- pan-essential admissibility guard (H fix 2026-07-20) ------------------

def test_underpowered_pan_essential_does_not_veto():
    """H fix: a >=85% pan-essential call on an underpowered panel (< coverage floor)
    escapes the pan-essential VETO — routes to a distinct insufficient verdict, checked
    BEFORE the pan-essential killer. Symmetric to the non_dependent underpowered guard."""
    for rid in ("common-essential-underpowered-insufficient",
                "rnai-common-essential-underpowered-insufficient"):
        v, drv = fr._verdict([{"rule_id": rid}])
        assert v == "insufficient_underpowered_pan_essential", (
            f"{rid} must escape the pan-essential veto")
        assert drv == rid


def test_genuine_pan_essential_still_vetoes_control():
    """CONTROL: a real pan-essential (adequate panel) must still veto — the guard only
    spares the underpowered case."""
    assert fr._verdict([{"rule_id": "pan-essential-killer"}]) == (
        "pan_essential_killer", "pan-essential-killer")


def test_underpowered_pan_essential_precedence_over_killer():
    """If both somehow co-fire (defensive — the classifier emits one or the other),
    the underpowered guard wins (checked first) so an underpowered call never vetoes."""
    v, _ = fr._verdict([{"rule_id": "common-essential-underpowered-insufficient"},
                        {"rule_id": "pan-essential-killer"}])
    assert v == "insufficient_underpowered_pan_essential"
