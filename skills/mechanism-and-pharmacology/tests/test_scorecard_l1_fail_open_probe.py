"""Scorecard L1 fail-open probe (#1993) — criterion-(c) evidence for the mechanism-and-pharmacology
scorecard's L1 cell.

mechanism-and-pharmacology has no per-skill open-world claim-record shadow (unlike tumor-presence/
#1988) — its `run.py` wires `subgroup_classify=make_value_classifier(_MECHANISM_VALUE_TIERS)` for the
`--figures` sub-group panel: every `*_class` token that reaches that panel passes through
`_skills_common.subgroup_derivation.default_classify` as the FALLBACK of `_MECHANISM_VALUE_TIERS` for
any token the skill's own explicit map omits — the SAME shared guard the sibling target-intrinsic
adapter (#1992) probes.

The fail-open invariant this probe exercises: `default_classify` checks `_UNMEASURED_TOKENS`
(`data_unavailable`, `not_measured`, `unmeasured`, `no_data`, `not_assessed`, `not_covered`,
`uninterpretable`, `_unreliable`) FIRST, before any presence-tier keyword scan — so a coverage gap
("we could not measure") degrades to the off-axis `unmeasured` abstention rather than falling through
the keyword scan to a manufactured `absent` ("we measured no signal"). Those are different claims;
collapsing the first into the second is exactly the "reads a withheld denominator as absence" failure
mode this framework treats as a defect elsewhere (see `_skills_common/subgroup_derivation.py`'s own
module comment on `UNMEASURED`).

This module supplies the TEETH `test_subgroup_value_tiers.py` does not: it defeats the ONE supply
mechanism the guard rests on (`_UNMEASURED_TOKENS`, the tuple `default_classify` scans membership
against) and shows a `data_unavailable` token then falls through to a manufactured `absent` read
instead of the honest `unmeasured` abstention — i.e. seeding the fail-open bug flips a currently-green
probe RED, proving the guard (not something else) holds the conservative degrade.

The monkeypatch is local to this test (pytest's `monkeypatch` fixture, reverted at teardown) — no
production file is edited.
"""

from __future__ import annotations

from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent

import _skills_common.subgroup_derivation as sd  # noqa: E402


def test_data_unavailable_degrades_conservatively_ordinary_path():
    """The guard intact: a coverage-gap token must abstain (`unmeasured`), never a fabricated `absent`."""
    assert sd.default_classify("data_unavailable") == sd.UNMEASURED
    assert sd.default_classify("not_assessed") == sd.UNMEASURED
    # and mechanism-and-pharmacology's own classifier (default_classify as its fallback) agrees for a
    # token its explicit map (_MECHANISM_VALUE_TIERS) omits:
    classify = sd.make_value_classifier({"well_characterized": "strong"})
    assert classify("data_unavailable") == sd.UNMEASURED


def test_teeth_defeating_the_unmeasured_token_guard_leaks_a_fabricated_absent(monkeypatch):
    """Seed the fail-open: neutralize the ONE mechanism (`_UNMEASURED_TOKENS`) that makes
    `default_classify` abstain on a coverage-gap token. Without it, `data_unavailable` no longer
    short-circuits to `unmeasured` — it falls through the keyword scan (no strong/moderate/weak
    keyword matches) straight to the `absent` default, i.e. a mechanism-and-pharmacology reader would
    report "no signaling annotation" for a target the source simply never covered. This is exactly the
    failure the guard exists to prevent: an absent measurement rendering as if it had been measured."""
    monkeypatch.setattr(sd, "_UNMEASURED_TOKENS", ())

    result = sd.default_classify("data_unavailable")

    # The guard removed: the token no longer abstains — it leaks through as a manufactured negative.
    assert result == "absent"
    assert result != sd.UNMEASURED, (
        "expected the fail-open probe to go RED once _UNMEASURED_TOKENS is defeated — if this "
        "assertion itself fails, the guard is redundant with something else and the probe above "
        "would not actually catch its removal"
    )
