"""gate_ceiling must honor recommendation_gate.suppressed_vetoes ON THE HARD_GATES PATH.

Regression for #1605. A dependency veto DOWNGRADED to a hold by the spine
(`biology_axis_downgrade` / `gof_driver_downgrade`, `to_action: hold`) survives in BOTH the
gate hits AND `suppressed_vetoes`, so `tp_gates._hard_gates_status` labels its hard-gate row
`fired` (fired precedes suppressed at tp_gates.py:1079). Before the fix, gate_ceiling's
hard_gates loop read `suppressed_vetoes` ONLY in the fallback path, saw `status=="fired"` on the
sole veto axis, and returned `declined` — re-imposing a veto the spine deliberately RELEASED to a
hold (`forced_recommendation == "hold"`), over-vetoing 36/504 corpus packages. The integrator
ENRICHES, it never OVERRIDES: a spine-suppressed veto must cap at the hold grade, not decline.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent  # skills/
sys.path.insert(0, str(_ROOT / "cross-evidence-hypothesis" / "scripts"))

import hypothesis_core as hc  # noqa: E402


def _pkg(*, suppressed: bool):
    """A package whose SOLE veto-axis hard-gate row is a fired dependency `not_dependent_in_indication`.
    When `suppressed`, the same (short, verdict) sits in recommendation_gate.suppressed_vetoes with a
    biology_axis_downgrade to_action:hold — mirroring the spine's downgraded-but-still-fired rows."""
    supp = (
        [
            {
                "short": "dependency",
                "verdict": "not_dependent_in_indication",
                "suppressed_by": {"kind": "biology_axis_downgrade", "to_action": "hold"},
            }
        ]
        if suppressed
        else []
    )
    return {
        "synthesis": {
            "sub_verdicts": {"safety": {"verdict": None}, "dependency": {"verdict": ["not_dependent_in_indication"]}},
            "recommendation_gate": {
                "fired": True,
                "forced_recommendation": "hold" if suppressed else "veto",
                "suppressed_vetoes": supp,
                "hard_gates": [
                    {
                        "short": "dependency",
                        "verdict": "not_dependent_in_indication",
                        "disposition": "gated",
                        "status": "fired",
                    }
                ],
            },
        }
    }


def test_spine_suppressed_veto_on_hard_gates_path_is_not_declined():
    """The defect case: a fired dependency veto the spine downgraded to a hold must cap at
    advanceable_flagged (a hold), NEVER declined — the ceiling must not re-impose the released veto."""
    g = hc.gate_ceiling(_pkg(suppressed=True))
    assert g["ceiling"] == "advanceable_flagged", g
    assert g["ceiling"] != "declined"
    # the released veto is recorded as excluded, not an active veto
    assert "dependency:not_dependent_in_indication" not in g["active_vetoes"]
    assert "dependency:not_dependent_in_indication" in g["excluded"]


def test_unsuppressed_veto_on_hard_gates_path_still_declines():
    """Control: an identical fired dependency veto NOT in suppressed_vetoes stays a genuine veto →
    declined. The fix must narrow to spine-suppressed pairs only, never blanket-release the axis."""
    g = hc.gate_ceiling(_pkg(suppressed=False))
    assert g["ceiling"] == "declined", g
    assert "dependency:not_dependent_in_indication" in g["active_vetoes"]
