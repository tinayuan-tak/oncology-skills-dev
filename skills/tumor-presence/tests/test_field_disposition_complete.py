"""Completeness guard for the field-disposition ledger (field_disposition.yaml).

The ledger makes "are we using all the extracted data?" machine-checkable: every emitted card
summary_field must carry an explicit disposition (signal | context | provenance | display), so a
field is never dropped SILENTLY. This test enforces COMPLETENESS + well-formedness, not tag
correctness (roles are a human judgement, editable by hand).

Two tiers, mirroring the freeze/replay split:
  - test_ledger_wellformed        — always runs (credential-less): valid roles + reasons, covers
                                     exactly run.py CARDS, no duplicate/empty entries.
  - test_ledger_matches_emitted   — skipif target-contracts absent: the RATCHET — the ledger's
                                     fields per card == the card's outputs.summary_fields, so a NEW
                                     emitted field with no disposition (orphan) or a STALE ledger
                                     entry fails CI.

THE REACH TIER (added 2026-09-13, field-disposition Stage 1b step 4). Completeness alone cannot see
the failure that actually matters: a field can carry `role: signal` — "feeds a claim / verdict" — while
NO declared reader in the tree ever touches it. There were 31 of those, and they were invisible here
because this file only ever checked that the `role` string was spelled correctly.

`_meta.roles` already promised that a signal "must be wired or explicitly waived", but no waiver key
existed, so there was nothing to enforce against. `test_signal_fields_are_reader_reached_or_waived`
closes that loop: a `role: signal` field must be reached by some declared reader (measured BLIND to
this ledger by `_skills_common.field_disposition`) or carry a `waived_because` naming what is missing.

Scope note: this is a PER-SKILL ratchet, like the completeness ratchet above it, NOT the fleet-wide
aperture gate — that one would red every PR in the repo that adds a summary_field and is a separate,
open decision. `role: context` is deliberately NOT gated: 39 context rows are unread and whether a
qualifier needs a code reader (vs being satisfied by the emitted card) is unsettled.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent
LEDGER = SKILL_DIR / "field_disposition.yaml"
VALID_ROLES = {"signal", "context", "provenance", "display"}


def _load_ledger() -> dict:
    assert LEDGER.exists(), f"missing field-disposition ledger at {LEDGER}"
    return yaml.safe_load(LEDGER.read_text()) or {}


def _cards() -> list[str]:
    return list(load_run_py(SKILL_DIR, "_tp_run_cards").CARDS)


def _contracts_root() -> Path | None:
    root = Path(
        os.environ.get(
            "TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"
        )
    )
    return root if (root / "cards").is_dir() else None


def _emitted(cid: str) -> list[str]:
    root = _contracts_root()
    p = root / "cards" / f"{cid}.card.yaml"
    if not p.exists():
        return []
    y = yaml.safe_load(p.read_text()) or {}
    return [x for x in (((y.get("outputs") or {}).get("summary_fields")) or []) if isinstance(x, str)]


def test_ledger_wellformed():
    """Every entry has a valid role + non-empty reason; the ledger covers exactly run.py's CARDS."""
    doc = _load_ledger()
    cards = set(_cards())
    ledger_cards = {k for k in doc if not k.startswith("_")}
    assert ledger_cards == cards, (
        f"ledger cards != run.py CARDS. missing={sorted(cards - ledger_cards)} extra={sorted(ledger_cards - cards)}"
    )
    for cid in ledger_cards:
        entry = doc[cid]
        if entry.get("_no_contract_fields"):
            continue
        for field, spec in entry.items():
            assert isinstance(spec, dict), f"{cid}.{field}: expected a mapping, got {type(spec).__name__}"
            assert spec.get("role") in VALID_ROLES, f"{cid}.{field}: bad role {spec.get('role')!r}"
            assert str(spec.get("reason") or "").strip(), f"{cid}.{field}: empty reason"


def test_waiver_and_review_keys_are_wellformed():
    """A `waived_because` is only meaningful on a signal, and `reviewed` must be a real boolean.

    Guards the two ways the new keys could be used to launder something: a waiver parked on a
    `context`/`display` row (where nothing was ever required, so the waiver reads as a decision that
    was never made), and a `reviewed:` value that is a truthy STRING rather than a boolean — the
    latter matters because `reviewed` is what tells a reader whether a role is a human judgement or
    a name-shape draft, so a sloppy value silently over-claims review.
    """
    doc = _load_ledger()
    problems = []
    for cid, entry in doc.items():
        if cid.startswith("_") or not isinstance(entry, dict):
            continue
        for field, spec in entry.items():
            if field.startswith("_") or not isinstance(spec, dict):
                continue
            waiver = spec.get("waived_because")
            if waiver is not None:
                if spec.get("role") != "signal":
                    problems.append(f"{cid}.{field}: waived_because on role={spec.get('role')!r}, only legal on signal")
                elif not str(waiver).strip():
                    problems.append(f"{cid}.{field}: empty waived_because")
            if "reviewed" in spec and not isinstance(spec["reviewed"], bool):
                problems.append(f"{cid}.{field}: reviewed must be a bool, got {spec['reviewed']!r}")
    assert not problems, "malformed waiver/review keys:\n  " + "\n  ".join(problems)


@pytest.mark.skipif(
    _contracts_root() is None,
    reason="target-contracts not resolvable (set TARGET_CONTRACTS_ROOT) — drift check skipped",
)
def test_ledger_matches_emitted_fields():
    """THE RATCHET: ledger fields per card == the card's emitted summary_fields. A new emitted field
    with no disposition (silent-drop risk) or a stale ledger entry fails here."""
    doc = _load_ledger()
    problems = []
    for cid in _cards():
        emitted = set(_emitted(cid))
        if not emitted:
            continue
        entry = {k: v for k, v in (doc.get(cid) or {}).items() if not k.startswith("_")}
        ledger_fields = set(entry)
        orphans = emitted - ledger_fields  # emitted, NO disposition → would be dropped silently
        stale = ledger_fields - emitted  # in ledger, no longer emitted
        if orphans:
            problems.append(f"{cid}: UNCLASSIFIED emitted fields (add a disposition): {sorted(orphans)}")
        if stale:
            problems.append(f"{cid}: STALE ledger fields (card no longer emits): {sorted(stale)}")
    assert not problems, "field-disposition ledger out of sync:\n  " + "\n  ".join(problems)


# ── the REACH tier: role:signal must be wired or explicitly waived ──────────────────────────────


# The census draws on two INDEPENDENT halves: kinds declared in target-contracts (rules, capsules,
# salience specs) and kinds parsed out of the skills TREE. Only the second depends on `skills_root`,
# so a broken skills root leaves most reach intact — which is exactly how a weaker non-vacuity check
# missed it (mutating skills_root to a nonexistent dir dropped only 11 of 93 signals, sailing past a
# plain `reached >= 40`). Both halves are therefore asserted BY KIND, not by a total.
_CONTRACTS_SIDE_KINDS = frozenset({"gating_rule", "display_rule", "capsule", "salience"})
_CODE_SIDE_KINDS = frozenset({"skill_code", "claim_passthrough", "question_table", "figure", "narrative"})


@pytest.fixture(scope="module")
def signal_reach():
    """``{(card_id, field): {kind, ...}}`` — the EXACT-evidence reader kinds per `role: signal` row.

    Reach is measured by `_skills_common.field_disposition.census`, which parses the live tree and
    reads NO field_disposition.yaml — so the guard cannot be satisfied by editing this ledger. Only
    `exact` evidence (literal card id AND literal field name at one read site) counts as reached;
    `name_only` does not, because a bare field name over-credits every card declaring that name.

    Returns the KINDS rather than a bool so the non-vacuity check below can tell WHICH half of the
    instrument is alive.
    """
    if _contracts_root() is None:
        pytest.skip("target-contracts not resolvable (set TARGET_CONTRACTS_ROOT) — reach check skipped")
    fd = pytest.importorskip("_skills_common.field_disposition")
    cen = fd.census(SKILL_DIR.parent, _contracts_root())
    doc = _load_ledger()
    out = {}
    for cid, entry in doc.items():
        if cid.startswith("_") or not isinstance(entry, dict):
            continue
        for field, spec in entry.items():
            if field.startswith("_") or not isinstance(spec, dict) or spec.get("role") != "signal":
                continue
            readers = cen.get((cid, field))
            out[(cid, field)] = set(readers["exact"]) if readers else set()
    return out


def test_the_reach_measurement_is_not_vacuous(signal_reach):
    """CAN the guard below fail, and can it PASS for the right reason?

    If the census silently degraded, every field would read as unreached and the ratchet would red
    for a reason that has nothing to do with wiring. The subtle version is a PARTIAL degradation:
    the contracts-declared kinds resolve fine while the tree-parsing half finds nothing, so reach
    stays high and only a handful of fields flip. That is the failure a total-count threshold cannot
    see, so assert each half is independently alive.
    """
    assert len(signal_reach) >= 60, (
        f"only {len(signal_reach)} role:signal rows found — the ledger or the census population "
        "collapsed, so the reach guard below is measuring nothing"
    )
    kinds = set().union(*signal_reach.values()) if signal_reach else set()
    assert kinds & _CONTRACTS_SIDE_KINDS, (
        f"no contracts-declared reader kind reaches ANY signal field (saw {sorted(kinds)}). "
        "field_disposition.census is not resolving target-contracts — fix the instrument, not the ledger"
    )
    assert kinds & _CODE_SIDE_KINDS, (
        f"no code reader kind reaches ANY signal field (saw {sorted(kinds)}). "
        f"field_disposition.census is not parsing the skills tree at {SKILL_DIR.parent} — "
        "fix the instrument, not the ledger"
    )


def test_signal_fields_are_reader_reached_or_waived(signal_reach):
    """THE REACH RATCHET: a `role: signal` field is reached by a declared reader, or says why not.

    `role: signal` means "feeds a claim / verdict". A signal no reader touches is a field the skill
    computes, ships, and then ignores — the exact failure the ledger was built to make visible and
    the one completeness could not see. The escape hatch is `waived_because`, which keeps the field
    in a REVIEW QUEUE (mirroring the module SAFETY CONTRACT: unreached is a candidate orphan, never
    a delete list) rather than letting it be quietly relabelled into a verdict-inert bucket.
    """
    doc = _load_ledger()
    unwired = []
    for (cid, field), reader_kinds in sorted(signal_reach.items()):
        if reader_kinds:
            continue
        if str((doc[cid][field].get("waived_because") or "")).strip():
            continue
        unwired.append(f"{cid}.{field}")
    assert not unwired, (
        f"{len(unwired)} field(s) declare role:signal but NO declared reader reaches them, and they "
        "carry no waived_because. Either wire a reader, or change the role with a reason that says "
        "what the field actually does, or add a waived_because naming the missing consumer:\n  " + "\n  ".join(unwired)
    )
