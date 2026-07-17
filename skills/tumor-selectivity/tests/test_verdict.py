"""Test the tumor-selectivity _verdict() (added 2026-07-17).

Before this, tumor-selectivity passed no verdict_fn — Phase-B selectivity (a
first-order nomination criterion) was computed as selectivity_class but silently
dropped (verdict=None), never reaching synthesis / the gate / the risk table.
These tests pin the rule-id → verdict mapping and that verdict strings equal the
selectivity_class values (so the risk-table _biological() reshape consumes them).
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _load():
    spec = importlib.util.spec_from_file_location("ts_run", RUN_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ts = _load()


def _fire(rule_id):
    return ts._verdict([{"rule_id": rule_id}])


def test_strong_selective_maps_to_class_string():
    assert _fire("tvn-strong-selective-supportive") == (
        "strong_tumor_selective", "tvn-strong-selective-supportive")


def test_not_selective_maps():
    assert _fire("tvn-not-selective-neutral") == (
        "not_selective", "tvn-not-selective-neutral")


def test_discordant_maps():
    assert _fire("tvn-discordant-neutral-flagged")[0] == "discordant_across_comparators"


def test_data_unavailable_maps():
    assert _fire("tvn-data-unavailable-insufficient")[0] == "data_unavailable"


def test_no_rules_is_insufficient():
    assert ts._verdict([]) == ("insufficient", None)


def test_verdict_strings_match_risk_table_biological_keys():
    """The risk-table reshape's _biological() keys off these exact strings —
    guard against a rename that would silently stop selectivity feeding biological risk."""
    strong = _fire("tvn-strong-selective-supportive")[0]
    notsel = _fire("tvn-not-selective-neutral")[0]
    assert strong == "strong_tumor_selective"   # consumed by _biological() LOW branch
    assert notsel == "not_selective"            # consumed by _biological() HIGH branch


def test_verdict_fn_is_discoverable_by_composer():
    """target-profile's _load_sub_skill_verdict_fn looks for _verdict OR _snapshot."""
    assert hasattr(ts, "_verdict") or hasattr(ts, "_snapshot")
