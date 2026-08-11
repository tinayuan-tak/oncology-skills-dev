"""T4 (2026-08-11 engineering review): data_mode/release_pin thread to the data-access layer.

Previously data_mode + release_pin flowed only into run_plan/package ID strings — they never
reached a live reader, so 'pinned' and 'exploratory' read identical data. execute_run_plan now
extracts them into a data_context dict and _call_live_reader forwards them ONLY to readers whose
signature declares the kwargs (signature introspection, not blanket try/except), so:
  - a release-aware reader receives data_context;
  - a legacy (target, indication[, subgroup_context]) reader is untouched;
  - a TypeError raised INSIDE a reader is NOT masked by a retry.
"""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR.parent))

from scripts._execution import _call_live_reader  # noqa: E402


def test_release_aware_reader_receives_data_context():
    seen = {}

    def reader(card_id, target, indication, subgroup_context=None, data_context=None):
        seen["data_context"] = data_context
        seen["subgroup_context"] = subgroup_context
        return {"ok": True}

    out = _call_live_reader(reader, "c", "KRAS", "COADREAD",
                            subgroup_context={"s": 1}, data_context={"data_mode": "pinned"})
    assert out == {"ok": True}
    assert seen["data_context"] == {"data_mode": "pinned"}
    assert seen["subgroup_context"] == {"s": 1}


def test_subgroup_only_reader_does_not_get_data_context():
    seen = {}

    def reader(card_id, target, indication, subgroup_context=None):
        seen["subgroup_context"] = subgroup_context
        return {"ok": True}

    out = _call_live_reader(reader, "c", "KRAS", "COADREAD",
                            subgroup_context={"s": 1}, data_context={"data_mode": "pinned"})
    assert out == {"ok": True}
    assert seen["subgroup_context"] == {"s": 1}


def test_legacy_positional_reader_untouched():
    def reader(card_id, target, indication):
        return {"legacy": True}

    out = _call_live_reader(reader, "c", "KRAS", "COADREAD",
                            subgroup_context={"s": 1}, data_context={"data_mode": "pinned"})
    assert out == {"legacy": True}


def test_var_kwargs_reader_receives_both():
    seen = {}

    def reader(card_id, target, indication, **kw):
        seen.update(kw)
        return {"ok": True}

    _call_live_reader(reader, "c", "KRAS", "COADREAD",
                      subgroup_context={"s": 1}, data_context={"d": 2})
    assert seen.get("subgroup_context") == {"s": 1}
    assert seen.get("data_context") == {"d": 2}


def test_internal_typeerror_is_not_masked():
    """A TypeError raised INSIDE the reader (real bug) must propagate, not be swallowed by a
    kwarg-degradation retry (the failure mode the previous try/except shim risked)."""
    def reader(card_id, target, indication, subgroup_context=None, data_context=None):
        raise TypeError("genuine internal bug")

    try:
        _call_live_reader(reader, "c", "KRAS", "COADREAD", subgroup_context={}, data_context={})
    except TypeError as e:
        assert "genuine internal bug" in str(e)
    else:
        raise AssertionError("internal TypeError was masked — introspection shim regressed")
