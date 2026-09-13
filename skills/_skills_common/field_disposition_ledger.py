"""Generic guard primitives for per-skill field-disposition ledgers (`<skill>/field_disposition.yaml`).

A ledger makes "are we using all the extracted data?" machine-checkable: every emitted card
`summary_field` carries an explicit disposition, so a field is never dropped SILENTLY. The checks here
are the SKILL-AGNOSTIC half of that — well-formedness, and the reach ratchet that a `role: signal`
field must be touched by some declared reader or say why not. They are consumed by
`skills/tests/test_field_disposition_ledgers.py`, which discovers every ledger in the tree, and by the
per-skill suites, which keep only their own pins.

WHY A SHARED MODULE RATHER THAN A COPY PER SKILL. Only one ledger exists today
(`skills/tumor-presence/`), so "ship the guard fleet-wide" cannot mean "add a test to fourteen skills"
— there is nothing yet to check in the other thirteen. It means the guard must already be waiting when
the second ledger lands. Discovery is by GLOB, so a new `field_disposition.yaml` is gated by the act of
existing; nobody has to remember to wire a test, which is the failure mode that left
`skills/tests/` itself unrun until PR #361. Same shape as the `hierarchy_connectivity` fixture in
`skills/conftest.py`, which consolidated a body that had been pasted byte-identically into 13 skills.

WHAT IS DELIBERATELY *NOT* HERE: any role-drafting heuristic. The tumor-presence ledger's roles were
auto-drafted from FIELD NAMES, and step 4 established that this produces noise — on
`tumor-elevation-breadth` the same quantity on two arms landed in OPPOSITE buckets, and the fallback
was unconditionally `display`, parking 18 unread fields in a bucket whose `_meta` claims
"verdict-inert BY DESIGN" with nobody having decided that. So the other skills get the GUARD, not
generated roles: a ledger is authored deliberately or not at all, and `reviewed: true` remains the only
marker of a human judgement.

REACH IS MEASURED BLIND TO THE LEDGER. `field_disposition.census` reads no `field_disposition.yaml`,
so no check here can be satisfied by editing the file it is checking.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import yaml

from _skills_common import field_disposition as fd

LEDGER_NAME = "field_disposition.yaml"

# The closed role vocabulary. `signal` = feeds a claim or verdict (the only role the reach ratchet
# gates); `context` = qualifies a signal; `provenance` = how/where the number came from; `display` =
# rendered for a human and verdict-inert.
VALID_ROLES = frozenset({"signal", "context", "provenance", "display"})

# A waiver must say something. Length, not prose matching: a substring check for "consumer" or a repo
# name would be a check on WORDING, and matching on prose is the failure mode that produced 17/17
# atlas misroutes. What is enforceable mechanically is that the field is not a shrug.
MIN_WAIVER_CHARS = 20


def discover_ledgers(skills_root: Path) -> dict:
    """``{skill_dir_name: path}`` for every `<skill>/field_disposition.yaml` under `skills_root`.

    Non-recursive below the skill dir on purpose: a ledger describes one skill's cards, so it lives at
    the skill root. Callers MUST assert the result is non-empty — a rename of `LEDGER_NAME` would
    otherwise turn every ledger guard into a vacuous pass, which is "the check didn't run" wearing the
    costume of "the check passed".
    """
    return {p.parent.name: p for p in sorted(Path(skills_root).glob(f"*/{LEDGER_NAME}"))}


def load_ledger(path: Path) -> dict:
    return yaml.safe_load(Path(path).read_text()) or {}


def iter_rows(doc: dict) -> Iterator[tuple[str, str, dict]]:
    """``(card_id, field, spec)`` for every real row, skipping `_`-prefixed metadata at both levels.

    `_meta` sits beside the card entries and `_no_contract_fields` sits beside the field entries, so
    both levels need the same filter — a single-level skip silently treats `_meta` as a card and its
    keys as fields.
    """
    for cid, entry in doc.items():
        if cid.startswith("_") or not isinstance(entry, dict):
            continue
        for field, spec in entry.items():
            if field.startswith("_") or not isinstance(spec, dict):
                continue
            yield cid, field, spec


def wellformedness_problems(doc: dict) -> list[str]:
    """Every structural problem in one pass — returns a LIST, never raises.

    Reporting all problems rather than asserting on the first matters for a fleet guard: a caller
    iterating fourteen ledgers should see every malformed row at once, not fix one and re-run.

    Checks: role in the closed vocabulary; a non-empty `reason`; `waived_because` only on
    `role: signal` (a waiver parked on a `context` row reads as a decision that was never required,
    hence never made) and long enough to name something; `reviewed` a real bool — a truthy STRING
    would silently over-claim review, and `reviewed` is precisely what distinguishes a human judgement
    from a name-shape draft.
    """
    problems = []
    for cid, field, spec in iter_rows(doc):
        role = spec.get("role")
        if role not in VALID_ROLES:
            problems.append(f"{cid}.{field}: bad role {role!r} (expected one of {sorted(VALID_ROLES)})")
        if not str(spec.get("reason") or "").strip():
            problems.append(f"{cid}.{field}: empty reason")
        waiver = spec.get("waived_because")
        if waiver is not None:
            if role != "signal":
                problems.append(f"{cid}.{field}: waived_because on role={role!r}, only legal on signal")
            elif len(str(waiver).strip()) < MIN_WAIVER_CHARS:
                problems.append(
                    f"{cid}.{field}: waived_because is {len(str(waiver).strip())} chars — name the missing "
                    f"consumer or the owning repo (>= {MIN_WAIVER_CHARS})"
                )
        if "reviewed" in spec and not isinstance(spec["reviewed"], bool):
            problems.append(f"{cid}.{field}: reviewed must be a bool, got {spec['reviewed']!r}")
    return problems


def signal_reach(doc: dict, cen: dict) -> dict:
    """``{(card_id, field): {kind, ...}}`` — EXACT-evidence reader kinds for each `role: signal` row.

    Takes a prebuilt census so a caller sweeping N ledgers parses the tree ONCE; `census()` walks every
    card contract and every `.py` in the tree.

    Only `exact` evidence counts (literal card id AND literal field name at one read site). `name_only`
    is excluded because a bare field name credits every card declaring that name — the over-crediting
    direction, which would let the ratchet congratulate itself. Returns the KINDS, not a bool, so
    callers can tell WHICH part of the instrument is alive; a bool collapses "unreached" and "the
    census broke" into the same value.
    """
    out = {}
    for cid, field, spec in iter_rows(doc):
        if spec.get("role") != "signal":
            continue
        readers = cen.get((cid, field))
        out[(cid, field)] = set(readers["exact"]) if readers else set()
    return out


def dark_reach_sources(reach: dict) -> list[str]:
    """Which independent census inputs reached NO signal field — the non-vacuity half of the ratchet.

    Per input rather than in aggregate, because a non-vacuity check calibrated on a TOTAL degrades
    into a check on the LARGEST mechanism. Measured on tumor-presence: pointing `skills_root` at a
    nonexistent directory dropped only 11 of 93 signals, so a plain `reached >= 40` sailed past a
    completely dead skills-side parser. Sources are derived via `exact_capable_sources()`, so a
    name-only kind cannot be asserted alive against exact evidence it can never produce.
    """
    kinds = set().union(*reach.values()) if reach else set()
    return sorted(src for src, src_kinds in fd.exact_capable_sources().items() if not (kinds & src_kinds))


def unwired_signals(doc: dict, reach: dict) -> list[str]:
    """``["card.field", ...]`` for `role: signal` rows with no reader AND no waiver.

    `role: signal` means "feeds a claim / verdict", so a signal nothing reads is a field the skill
    computes, ships, and then ignores. The escape hatch is `waived_because`, which keeps the field in a
    REVIEW QUEUE — mirroring the census SAFETY CONTRACT that unreached is a candidate orphan, never a
    delete list — instead of letting it be quietly relabelled into a verdict-inert bucket.
    """
    out = []
    for (cid, field), kinds in sorted(reach.items()):
        if kinds:
            continue
        if str(((doc.get(cid) or {}).get(field) or {}).get("waived_because") or "").strip():
            continue
        out.append(f"{cid}.{field}")
    return out
