"""Scorecard L1 fail-open probe (#1991, copying the tumor-presence exemplar #1988) — criterion-(c)
evidence for the surface-modality-fit scorecard's L1 cell.

The claim-record shadow builder (`_claim_record` in `run.py`, feeding `_skills_common.claim_record`)
already carries the open-world invariant "ignorance != negation": `_sm_availability()` maps a
`data_unavailable`/`None` verdict token through the skill's OWN open-world set (`_SM_OPEN_WORLD`) to
`availability="not_wired"`, which `assemble_claim_record` then forces to `state='unknown'`,
`direction='neutral'`, and a flattened `none` magnitude — never a directional finding manufactured out
of absence. `test_claim_record_shadow.py::test_data_unavailable_is_open_world` already pins the
ORDINARY path (existing coverage; not duplicated here).

What that test cannot show on its own is that the assertion has TEETH — that removing the guard would
actually change the observable output. This module supplies that: it defeats the ONE supply mechanism
this skill's shadow builder rests on for open-world classification (`run.py::_SM_OPEN_WORLD`, the
frozenset `_sm_availability` checks membership against) and shows the record's `state`/`availability`
leak the raw, no-longer-neutralized verdict token instead of `unknown`/`not_wired` — i.e. seeding the
fail-open bug flips a currently-green probe RED, proving the guard (not some other code path) is what
holds the conservative degrade.

The monkeypatch is local to this test (explicit `monkeypatch` fixture, reverted at teardown) — no
production file is edited.
"""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

sm = load_run_py(Path(__file__).resolve().parent.parent, "smf_run_failopen")


def test_data_unavailable_degrades_conservatively_ordinary_path():
    """The guard intact: an unreachable/absent bucket must render as ignorance, never a valence."""
    rec = sm._claim_record([], fired=[], verdict_pair=("data_unavailable", None))
    f = rec["finding"]
    assert f["state"] == "unknown"
    assert f["direction"] == "neutral"
    assert f["magnitude"]["level"] == "none"
    assert f["availability"] == "not_wired"


def test_teeth_defeating_the_open_world_guard_lets_the_raw_token_leak(monkeypatch):
    """Seed the fail-open: neutralize the ONE mechanism (`_SM_OPEN_WORLD`) that makes
    `_sm_availability` classify an unreachable bucket as `not_wired`. Without it, the raw
    `data_unavailable` token — which looks like a real (negative-shaped) finding to anything reading
    `state` alone — reaches the record unmasked. This is exactly the failure the guard exists to
    prevent: an absent measurement rendering as if it had been measured. Confirms the probe above is
    not vacuously green."""
    monkeypatch.setattr(sm, "_SM_OPEN_WORLD", frozenset())

    rec = sm._claim_record([], fired=[], verdict_pair=("data_unavailable", None))
    f = rec["finding"]

    # The guard removed: state/availability are no longer forced to unknown/not_wired — the raw token
    # leaks through as a manufactured measured_negative finding.
    assert f["state"] == "data_unavailable"
    assert f["state"] != "unknown", (
        "expected the fail-open probe to go RED once _SM_OPEN_WORLD is defeated — if this assertion "
        "itself fails, the guard is redundant with something else and the probe above would not "
        "actually catch its removal"
    )
    assert f["availability"] != "not_wired"
