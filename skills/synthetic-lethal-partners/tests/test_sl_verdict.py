"""synthetic-lethal-partners _verdict: the sub-verdict the gate suppressor keys on.

The gate's veto_suppressor names (synthetic_lethal_partners, has_experimental_sl_partner)
→ suppresses (dependency, non_dependent). So _verdict MUST emit that EXACT string for
the experimental-partner rule, and must NOT emit it for computational-only / no-partner
(which would falsely suppress a veto). Guards the verdict↔gate-tuple contract.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

sl = load_run_py(Path(__file__).resolve().parent.parent, "sl_run")


def test_experimental_partner_emits_gate_trigger_verdict():
    v, drv = sl._verdict([{"rule_id": "sl-experimental-partner-context-conditional"}])
    assert v == "has_experimental_sl_partner", "must equal the gate veto_suppressor trigger verdict exactly"
    assert drv == "sl-experimental-partner-context-conditional"


def test_computational_only_does_not_emit_gate_trigger():
    v, _ = sl._verdict([{"rule_id": "sl-computational-partner-informational"}])
    assert v == "has_computational_sl_partner"
    assert v != "has_experimental_sl_partner", (
        "computational-only must NOT emit the suppressor trigger (too weak to suppress a veto)"
    )


def test_no_partner_is_real_negative_not_gate_trigger():
    v, _ = sl._verdict([{"rule_id": "sl-no-partner-neutral"}])
    assert v == "no_curated_sl_partner"


def test_data_unavailable():
    v, _ = sl._verdict([{"rule_id": "sl-data-unavailable-insufficient"}])
    assert v == "data_unavailable"


def test_nothing_fired_is_insufficient():
    assert sl._verdict([]) == ("insufficient", None)
