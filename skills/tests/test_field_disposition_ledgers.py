"""FLEET guard over every per-skill field-disposition ledger, whichever skills happen to have one.

Discovery is by GLOB (`skills/*/field_disposition.yaml`), so a ledger is gated by the act of existing.
That is the whole point of this file: only ONE skill has a ledger today, so "ship the guard fleet-wide"
cannot mean adding a test to fourteen skills — there is nothing yet to check in the other thirteen. It
means the guard is already waiting when the second ledger lands, with nobody having to remember to wire
a test. Forgetting is not hypothetical: `skills/tests/` itself was invisible to CI until PR #361,
because the workflow's `for d in skills/*/tests` glob does not match `skills/tests` — "the check didn't
run" wearing the costume of "the check passed".

The per-skill suite (`skills/tumor-presence/tests/test_field_disposition_complete.py`) keeps what is
genuinely skill-specific: that the ledger covers exactly that skill's `run.py` CARDS, and its own
row-count pins. Everything skill-agnostic lives in `_skills_common.field_disposition_ledger` and is
enforced here, once.

NOT ENFORCED HERE: role CORRECTNESS. Roles are a human judgement and only `reviewed: true` marks one as
made. Step 4 established that the auto-drafted roles in the one existing ledger are noise — the same
quantity on two arms of `tumor-elevation-breadth` landed in opposite buckets — so nothing in this file
treats a `role` string as ground truth. It checks that the declaration is well-formed and that a
`signal` is wired or waived.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _skills_common import field_disposition as fd
from _skills_common import field_disposition_ledger as fdl

SKILLS_ROOT = Path(__file__).resolve().parents[1]

# ★ RATCHET ON WHICH SKILLS ARE LEDGERED — a skill that has a ledger may never quietly lose it.
# Without this, discovery makes the fleet guard trivially satisfiable by DELETING the file it checks:
# the sweep would find nothing to complain about and go green. Frozen 2026-09-13. Grow it when a skill
# gains a ledger; removing a name needs a reason in the PR body, not a quiet edit.
LEDGERED_SKILLS_FLOOR = frozenset(
    {
        "cis-feature-coherence",
        "combination-and-vulnerability",
        "differentiation-landscape",
        "functional-requirement",
        "genomic-alteration-profile",
        "immune-context",
        "literature-context",
        "literature-risk-assessment",
        "mechanism-and-pharmacology",
        "on-target-safety-liability",
        "surface-modality-fit",
        "target-intrinsic",
        "target-profile",
        "tractability-small-molecule",
        "translational-readiness",
        "tumor-presence",
        "tumor-selectivity",
    }
)

# Total `role: signal` rows across all ledgers. A floor, so a ledger that loses its signal rows (or a
# loader change that stops seeing them) cannot make the reach ratchet below pass by measuring nothing.
# 550 on trunk today (17 ledgers, 2026-09-27); 400 leaves room for re-triage without leaving room
# for a collapse (e.g. a loader change that stops seeing an entire ledger's signals).
MIN_FLEET_SIGNAL_ROWS = 400


def _contracts_absent() -> bool:
    try:
        from _skills_common.paths import target_contracts_root

        return not (target_contracts_root() / "cards").is_dir()
    except Exception:
        return True


needs_contracts = pytest.mark.skipif(_contracts_absent(), reason="target-contracts absent")


@pytest.fixture(scope="module")
def ledgers() -> dict:
    """``{skill: doc}`` for every discovered ledger."""
    found = fdl.discover_ledgers(SKILLS_ROOT)
    assert found, (
        f"no {fdl.LEDGER_NAME} found under {SKILLS_ROOT} — every test in this file would pass "
        "vacuously. If the filename changed, fix fdl.LEDGER_NAME; do not leave the sweep blind."
    )
    return {skill: fdl.load_ledger(path) for skill, path in found.items()}


@pytest.fixture(scope="module")
def fleet_reach(ledgers) -> dict:
    """``{skill: {(card, field): {kind, ...}}}`` — signal reach per ledger, census parsed ONCE.

    `census()` walks every card contract and every `.py` in the tree, so building it per-ledger would
    make this suite scale badly for exactly no gain.
    """
    if _contracts_absent():
        pytest.skip("target-contracts absent — reach not measurable")
    cen = fd.census(SKILLS_ROOT)
    return {skill: fdl.signal_reach(doc, cen) for skill, doc in ledgers.items()}


def test_ledgered_skills_only_grow(ledgers):
    """A skill that has a ledger may never silently lose it — see LEDGERED_SKILLS_FLOOR."""
    missing = sorted(LEDGERED_SKILLS_FLOOR - set(ledgers))
    assert not missing, (
        f"skill(s) {missing} lost their {fdl.LEDGER_NAME}. Deleting a ledger removes every disposition "
        "guard over that skill's fields, which is the silent-drop failure the ledger exists to prevent."
    )


def test_every_ledger_is_wellformed(ledgers):
    """Valid roles, non-empty reasons, waivers only on signals and saying something, `reviewed` a bool.

    Reported across ALL ledgers at once rather than failing on the first, so a sweep over a growing
    fleet does not turn into one-fix-per-CI-run.
    """
    problems = {skill: fdl.wellformedness_problems(doc) for skill, doc in ledgers.items()}
    problems = {k: v for k, v in problems.items() if v}
    assert not problems, "malformed field-disposition rows:\n" + "\n".join(
        f"  [{skill}] {p}" for skill, ps in sorted(problems.items()) for p in ps
    )


@needs_contracts
def test_the_fleet_reach_measurement_is_not_vacuous(fleet_reach):
    """CAN the ratchet below fail, and can it PASS for the right reason?

    Two ways it could not. (1) No signal rows at all — then it iterates nothing and is green. (2) The
    census silently half-degraded: the contracts-declared kinds resolve while the tree-parsing half
    finds nothing, so most reach survives and only a handful of fields flip. Measured on tumor-presence,
    pointing `skills_root` at a nonexistent directory dropped only 11 of 93 signals — a plain
    `reached >= 40` sailed straight past a completely dead parser. So liveness is asserted per input.
    """
    total = sum(len(r) for r in fleet_reach.values())
    assert total >= MIN_FLEET_SIGNAL_ROWS, (
        f"only {total} role:signal rows across {len(fleet_reach)} ledger(s) (floor "
        f"{MIN_FLEET_SIGNAL_ROWS}) — the population collapsed, so the reach ratchet measures nothing"
    )
    merged = {k: v for r in fleet_reach.values() for k, v in r.items()}
    dark = fdl.dark_reach_sources(merged)
    assert not dark, (
        f"census input(s) {dark} reach NO signal field anywhere in the fleet. The instrument is broken, "
        f"not the wiring — fix the census, do not waive rows. (sources checked: "
        f"{sorted(fd.exact_capable_sources())})"
    )


@needs_contracts
def test_signal_fields_are_reader_reached_or_waived(ledgers, fleet_reach):
    """THE REACH RATCHET, fleet-wide: a `role: signal` field is reached by a declared reader, or says
    why not.

    `role: signal` means "feeds a claim / verdict", so a signal nothing reads is a field the skill
    computes, ships, and then ignores. Reach is measured BLIND to the ledger, so this cannot be
    satisfied by editing the file being checked. The escape hatch is `waived_because`, which keeps the
    field in a review queue rather than letting it be relabelled into a verdict-inert bucket.
    """
    unwired = {skill: fdl.unwired_signals(ledgers[skill], reach) for skill, reach in fleet_reach.items()}
    unwired = {k: v for k, v in unwired.items() if v}
    n = sum(len(v) for v in unwired.values())
    assert not unwired, (
        f"{n} field(s) declare role:signal but NO declared reader reaches them, and they carry no "
        "waived_because. Either wire a reader, or change the role with a reason saying what the field "
        "actually does, or add a waived_because naming the missing consumer:\n"
        + "\n".join(f"  [{skill}] {f}" for skill, fs in sorted(unwired.items()) for f in fs)
    )
