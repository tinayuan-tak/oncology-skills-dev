"""Scorecard L1 fail-open probe (#1988, A0c exemplar) — criterion-(c) evidence for the tumor-presence
scorecard's L1 cell.

The claim-record shadow builder (`_claim_record` in `run.py`, feeding `_skills_common.claim_record`)
already carries the open-world invariant "ignorance != negation": when a bucket resolves to
`data_unavailable` (no measurement reached), the assembler forces `state='unknown'`,
`direction='neutral'`, and a flattened `none` magnitude — never a directional finding manufactured out
of absence. `test_claim_record_shadow.py::test_data_unavailable_open_world` already pins the ORDINARY
path (existing coverage; not duplicated here).

What that test cannot show on its own is that the assertion has TEETH — that removing the guard would
actually change the observable output, rather than the guard being redundant with something else that
already forces the same value. This module supplies that: it defeats the ONE supply mechanism the
open-world guard rests on (`_skills_common.claim_record.OPEN_WORLD_AVAILABILITY`, the frozenset the
assembler checks membership against) and shows the record's `state` field leaks the raw, no-longer-
neutralized verdict token instead of `unknown` — i.e. seeding the fail-open bug flips a currently-green
probe RED, proving the guard (not some other code path) is what holds the conservative degrade.

The monkeypatch is local to this test (autouse of pytest's `monkeypatch` fixture, reverted at teardown)
— no production file is edited.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

pr = load_run_py(Path(__file__).resolve().parent.parent, "tp_run_failopen")


def test_data_unavailable_degrades_conservatively_ordinary_path():
    """The guard intact: an unreachable/absent bucket must render as ignorance, never a valence."""
    rec = pr._claim_record([], fired=[], verdict_pair=("data_unavailable", None))
    f = rec["finding"]
    assert f["state"] == "unknown"
    assert f["direction"] == "neutral"
    assert f["magnitude"]["level"] == "none"
    assert f["availability"] == "not_wired"


def test_teeth_defeating_the_open_world_guard_lets_the_raw_token_leak(monkeypatch):
    """Seed the fail-open: neutralize the ONE mechanism (`OPEN_WORLD_AVAILABILITY`) that makes the
    assembler force state='unknown' on an unreachable bucket. Without it, the raw `data_unavailable`
    token — which looks like a real (negative-shaped) finding to anything reading `state` alone —
    reaches the record unmasked. This is exactly the failure the guard exists to prevent: an absent
    measurement rendering as if it had been measured. Confirms the probe above is not vacuously green."""
    import _skills_common.claim_record as cr

    monkeypatch.setattr(cr, "OPEN_WORLD_AVAILABILITY", frozenset())

    rec = pr._claim_record([], fired=[], verdict_pair=("data_unavailable", None))
    f = rec["finding"]

    # The guard removed: state is no longer forced to 'unknown' — the raw token leaks through.
    assert f["state"] == "data_unavailable"
    assert f["state"] != "unknown", (
        "expected the fail-open probe to go RED once OPEN_WORLD_AVAILABILITY is defeated — "
        "if this assertion itself fails, the guard is redundant with something else and the "
        "probe above would not actually catch its removal"
    )
