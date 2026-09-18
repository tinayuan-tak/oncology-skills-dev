"""Hermetic tests for run_known_target_panel nominate-path attribution + the nominate-while-blind
detector — the instrument half of the positive_tier anti-blind cross-path fix.

Runs via: pixi run pytest eval/tests/test_known_target_panel_nominate_path.py -q  (from home checkout).

The panel report USED to carry no `forced_by`/`nominate_thesis`/`deciding_density` column, so a
dangerous positive_tier nominate on UNMEASURED density (MUC13, live on trunk) was indistinguishable in
the report from a thesis_decider nominate on MEASURED density (FOLR1). And because `_SCORED_SEV`
deliberately does NOT judge honest_blind targets, the panel had nowhere to catch it. These columns plus
the `nominated_while_blind` signal make the release-scope precondition ("holds rather than nominates
when blind") measurable.
"""

from __future__ import annotations

import sys
from pathlib import Path

_EVAL = Path(__file__).resolve().parents[1]
if str(_EVAL) not in sys.path:
    sys.path.insert(0, str(_EVAL))

import run_known_target_panel as panel  # noqa: E402


def _pkg(forced, forced_by, thesis_decider):
    return {
        "synthesis": {
            "recommendation_gate": {
                "forced_recommendation": forced,
                "forced_by": forced_by,
                "thesis_decider": thesis_decider,
            }
        }
    }


# MUC13 shape (live on trunk): positive_tier nominated while the thesis decider REFUSED for blindness.
_MUC13 = _pkg(
    "nominate",
    "positive_tier",
    {
        "thesis": "antigen_driven",
        "unsatisfied": [
            "requires(selectivity=field_effect_tumor_selective)",
            "unmeasured(surface-abundance-density.density_floor_verdict=unmeasured)",
        ],
    },
)
# FOLR1 shape: thesis_decider nominated on MEASURED density.
_FOLR1 = _pkg(
    "nominate",
    "thesis_decider",
    {
        "thesis": "antigen_driven",
        "measured_conjuncts": [
            {
                "card_id": "surface-abundance-density",
                "field": "density_floor_verdict",
                "value": "above_adc_high_payload_floor",
            }
        ],
    },
)
# EGFR/ERBB2 shape: positive_tier nominated, oncogene_addiction carries NO thesis block.
_EGFR = _pkg("nominate", "positive_tier", {})
# MUC13 AFTER the tp_gates cross-path fix: the tier's nominate is withheld → no longer `nominate`.
_MUC13_FIXED = _pkg(
    "hold",
    None,
    {
        "thesis": "antigen_driven",
        "unsatisfied": ["unmeasured(surface-abundance-density.density_floor_verdict=unmeasured)"],
    },
)


def test_forced_by_distinguishes_the_two_deterministic_paths():
    assert panel._forced_by(_MUC13) == "positive_tier"
    assert panel._forced_by(_FOLR1) == "thesis_decider"
    assert panel._forced_by(_MUC13_FIXED) is None


def test_deciding_density_reads_both_measured_and_unmeasured():
    assert panel._deciding_density(_FOLR1) == "above_adc_high_payload_floor"
    assert panel._deciding_density(_MUC13) == "unmeasured"
    assert panel._deciding_density(_EGFR) is None  # no density conjunct on a non-antigen thesis


def test_nominate_thesis_names_the_thesis_or_none():
    assert panel._nominate_thesis(_MUC13) == "antigen_driven"
    assert panel._nominate_thesis(_EGFR) is None


def test_nominated_while_blind_flags_the_leak_and_only_the_leak():
    """THE non-vacuity assertion: True on the leak, False on every non-leak shape — so the signal
    cannot silently pass by flagging nothing, nor false-alarm on a healthy nominate."""
    assert panel._nominated_while_blind(_MUC13) is True  # the live positive_tier leak
    assert panel._nominated_while_blind(_FOLR1) is False  # nominates, but density MEASURED
    assert panel._nominated_while_blind(_EGFR) is False  # nominates via tier, but no thesis block
    assert panel._nominated_while_blind(_MUC13_FIXED) is False  # withheld by the fix → not `nominate`


def test_the_only_thing_that_clears_the_flag_is_ceasing_to_nominate():
    """Proves the instrument tracks the tp_gates fix, not an incidental field: MUC13 stays BLIND on
    density in `_MUC13_FIXED` (the `unmeasured(...)` marker is still present) — the flag clears solely
    because the recommendation is no longer `nominate`, which is exactly what the cross-path withhold
    produces."""
    assert panel._anti_blind_refused(_MUC13_FIXED)  # still blind on the deciding axis
    assert panel._nominated_while_blind(_MUC13_FIXED) is False  # but no longer nominating → cleared
