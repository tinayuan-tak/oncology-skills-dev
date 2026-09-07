"""resolve_cards COVERAGE contract: an errored / no-data card is NEVER counted as available.

Recovers the coverage the deleted compose-dashboard `test_live_error_not_green` guarded, now that
resolve_cards (+ its _missing tagging) lives in _skills_common. Regression this protects: an errored
dispatcher that returns a dict was once silently counted as an available card — overstating coverage
on every skill. resolve_cards must tag a `_live_read_error` (and an honest `data_unavailable`) as
`_missing: True`, distinguishing the two via `_data_unavailable`.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

import _skills_common as skc  # noqa: E402
from _skills_common import _live_readers  # noqa: E402


def test_live_read_error_is_missing_not_available(monkeypatch):
    """A dispatcher that returns a `_live_read_error` dict must be tagged _missing (NOT green), with
    a live_read_error reason, and NOT flagged as an honest data_unavailable."""
    monkeypatch.setattr(
        _live_readers, "read_live_summary", lambda *a, **k: {"_live_read_error": "boom: forced test failure"}
    )
    out = skc.resolve_cards(["cellline-rna-distribution"], "MYGENE", "COADREAD")
    assert len(out) == 1
    card = out[0]
    assert card["_missing"] is True, "an errored live read must count against coverage"
    assert "live_read_error" in card["_missing_reason"]
    assert card.get("_data_unavailable") is False, "an ERROR is not an honest data_unavailable"
    assert card["interpretation_call"] == "data_unavailable"


def test_dispatcher_none_is_missing(monkeypatch):
    """A dispatcher returning None (no live reader wired) is _missing with dispatcher_returned_none."""
    monkeypatch.setattr(_live_readers, "read_live_summary", lambda *a, **k: None)
    out = skc.resolve_cards(["cellline-rna-distribution"], "MYGENE", "COADREAD")
    assert out[0]["_missing"] is True
    assert out[0]["_missing_reason"] == "dispatcher_returned_none"


def test_real_summary_is_available(monkeypatch):
    """A dispatcher returning a real populated summary is NOT missing (the positive control that the
    _missing tagging isn't just always-True). Assert only coverage state — summary content may be
    reshaped by a per-card preprocessor, which is not what this contract guards."""
    monkeypatch.setattr(
        _live_readers, "read_live_summary", lambda *a, **k: {"expression_class": "broadly_high", "median_tpm": 7.2}
    )
    out = skc.resolve_cards(["cellline-rna-distribution"], "MYGENE", "COADREAD")
    assert not out[0].get("_missing"), "an available card must not be tagged _missing (key absent or False)"
    assert not out[0].get("_data_unavailable")
