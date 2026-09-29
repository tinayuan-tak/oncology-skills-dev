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

GENERALIZED 2026-09-13 (D3). The skill-agnostic checks — role/reason/waiver/`reviewed` well-formedness
and the signal reach ratchet — now live in `_skills_common.field_disposition_ledger` and are enforced
over EVERY ledger in the tree by `skills/tests/test_field_disposition_ledgers.py`. What stays here is
what only means something for this skill: that the ledger covers exactly this skill's `run.py` CARDS and
matches its cards' emitted `summary_fields`, plus this ledger's own row-count pins. The duplicated
bodies delegate rather than being deleted, so a red still names tumor-presence when running this skill's
suite alone.

Scope note: this is a PER-SKILL ratchet, NOT the fleet-wide aperture gate — that one is a merge gate on
the whole domain and lives in `skills/_skills_common/tests/test_field_disposition.py`. `role: context`
is deliberately NOT gated: 39 context rows are unread and whether a qualifier needs a code reader (vs
being satisfied by the emitted card) is unsettled.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml
from _skills_common import field_disposition_ledger as fdl
from _test_support import load_run_py

SKILL_DIR = Path(__file__).resolve().parent.parent
LEDGER = SKILL_DIR / "field_disposition.yaml"
VALID_ROLES = fdl.VALID_ROLES

# This ledger's own signal-row count (93 on trunk 2026-09-13). Kept skill-local because the fleet sweep
# can only assert a fleet TOTAL, and a total is satisfied by any one ledger — so once a second skill is
# ledgered, the fleet floor would stop being able to see this one collapse.
MIN_SIGNAL_ROWS = 60


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


# ── the EMIT-vs-DECLARED reconciliation (#2016; actions the deferred #1506 systemic-finding-2) ───────
#
# `_emitted` above is MISNAMED for history: it returns the card's DECLARED `outputs.summary_fields`, not
# what a run actually EMITS. So `test_ledger_matches_emitted_fields` only ever reconciles the ledger
# against the DECLARED set. A field a reader EMITS into the summary but the card never DECLARES is in
# NEITHER the ledger nor the declared set, so it is invisible to the ledger, to the fleet-aperture
# census (whose domain is likewise `declared_fields`, see _skills_common/tests/test_field_disposition.py),
# and to CI, all at once. That is the census fail-open TC#863 landed only as a warning (fail-open) and
# #1506 systemic-finding-2 documented and then deferred; it is the REVERSE direction of the open #1353
# (declared-but-never-emitted) and the emitted-but-undeclared audit #1510.
#
# This closes it in the load-bearing direction: reconcile the OBSERVED emit — the summary keys of the
# frozen maximal-run fixture the replay guard already ships (epcam_coadread.yaml, refreshed by the
# card-behavior-matrix-nightly re-freeze) — against the declared contract, and go RED on any PUBLIC
# (non-`_`-prefixed) emitted key the card does not declare.
#
# A RATCHET, NOT A HARD WALL — because clearing an emitted-but-undeclared field is the CROSS-REPO
# declare-or-remove half (pin + TC `outputs.summary_fields` + a field_disposition.yaml row + a
# census-visible reader = ONE atomic unit, land TC first) and the fleet already carries a backlog of
# them. Mirroring the fleet-aperture ratchet and its SAFETY CONTRACT — an unremediated field is a
# REVIEW QUEUE, never a delete list — the grandfathered set below is pinned as a set: a NEW
# emitted-but-undeclared public field reds immediately (the fail-open is closed GOING FORWARD), while
# the backlog is burned down field-by-field, each removal RE-BANKING this set (a stale entry reds too,
# so the queue cannot silently rot). VERDICT-INERT: it reads the same frozen fixture the replay froze
# and moves no verdict / no golden. The count is aperture-INERT: this measures emit − declared, the
# opposite subtraction from the aperture's declared − reached, and touches no census code.
_OBSERVED_EMIT_FIXTURE = SKILL_DIR / "tests" / "fixtures" / "epcam_coadread.yaml"


def _load_observed_emit() -> dict:
    """The frozen maximal-run reader summaries (the observed emit), keyed by card id; {} if absent."""
    if not _OBSERVED_EMIT_FIXTURE.exists():
        return {}
    return yaml.safe_load(_OBSERVED_EMIT_FIXTURE.read_text()) or {}


def _observed_public_keys(summary) -> set[str]:
    """PUBLIC emitted keys of one card's frozen summary: real string keys, `_`-prefixed excluded by
    convention (a run's own private/scratch keys), and only for a REAL reader summary — a freeze or
    dispatcher error carries no emit to reconcile."""
    if not isinstance(summary, dict) or summary.get("_freeze_error") or summary.get("_dispatcher_returned_none"):
        return set()
    return {k for k in summary if isinstance(k, str) and not k.startswith("_")}


def emitted_but_undeclared(fixture: dict, declared_of) -> set:
    """`{(card_id, field)}` for every PUBLIC key a card EMITS in `fixture` that it does not DECLARE.

    Pure and injectable: `declared_of(card_id) -> iterable[str]` supplies the declared contract, so the
    reconciliation can be exercised (mutation teeth) on a synthetic fixture with no target-contracts
    checkout. A card the roster does not know declares nothing, so all its emits read as undeclared —
    the safe direction for a completeness instrument."""
    out: set = set()
    for cid, summary in fixture.items():
        if not isinstance(cid, str):
            continue
        emitted = _observed_public_keys(summary)
        if not emitted:
            continue
        declared = set(declared_of(cid) or ())
        out |= {(cid, f) for f in emitted - declared}
    return out


# The grandfathered emitted-but-undeclared PUBLIC (card, field) pairs, MEASURED on the frozen
# epcam_coadread fixture against the target-contracts SHA skills-validate.yml pins (36cfd74, 2026-09-28)
# — the tree CI actually reads, NOT contracts `main` (which carries #980/#981 the pin deliberately
# excludes). Local `main` and the pin measure the SAME 39 pairs for these cards, so the set is robust to
# the pin. This is the review queue for the deferred CROSS-REPO declare-or-remove (part b of #2016);
# each field leaves via an atomic unit and RE-BANKS this set. Two clusters, decided per field at the
# DATA level, NOT here (an instrument does not declare contracts):
#   • run-provenance echoes the producers stamp on the summary — target / indication / method_version /
#     cohort / control_position_method_version / control_percentile_source — candidates to either
#     `_`-prefix at the producer or declare as provenance rows (I6 notes control_target_* are an
#     unconditional echo);
#   • genuine measurement blind-spots — control_target_percentile / control_target_class, the
#     normal-relative overlay normal_p95_log2tpm / normal_p99_log2tpm, the min/max_log2tpm extremes,
#     is_actionable_provider_call (TC#942 declared only 3 of 4 provider-call fields), the subtype
#     spillover (n_subtypes_measured / n_subtypes_enriched / spotlight_subtype / subtype_axis_available
#     / subtype_signals_nonuniform), assignment_manifest, adjacent_mean_tpm / tumor_mean_tpm,
#     indications_tested.
_KNOWN_EMITTED_BUT_UNDECLARED = frozenset(
    {
        ("cellline-rna-distribution", "control_negatives_excluded_lineage_conflict"),
        ("cellline-rna-distribution", "control_percentile_source"),
        ("cellline-rna-distribution", "control_position_method_version"),
        ("cellline-rna-distribution", "control_target_class"),
        ("cellline-rna-distribution", "control_target_percentile"),
        ("cellline-rna-distribution-by-subtype", "indication"),
        ("cellline-rna-distribution-by-subtype", "target"),
        ("cellline-rna-protein-concordance", "method_version"),
        ("cellline-rna-protein-concordance", "target"),
        ("expression-purity-confound", "indication"),
        ("expression-purity-confound", "method_version"),
        ("expression-purity-confound", "target"),
        ("rna-protein-concordance-tumor", "indication"),
        ("rna-protein-concordance-tumor", "method_version"),
        ("rna-protein-concordance-tumor", "target"),
        ("tumor-elevation-breadth", "indications_tested"),
        ("tumor-protein-abundance-cptac", "cohort"),
        ("tumor-rna-distribution", "assignment_manifest"),
        ("tumor-rna-distribution", "control_percentile_source"),
        ("tumor-rna-distribution", "control_position_method_version"),
        ("tumor-rna-distribution", "control_target_class"),
        ("tumor-rna-distribution", "control_target_percentile"),
        ("tumor-rna-distribution", "max_log2tpm"),
        ("tumor-rna-distribution", "method_version"),
        ("tumor-rna-distribution", "min_log2tpm"),
        ("tumor-rna-distribution", "n_subtypes_enriched"),
        ("tumor-rna-distribution", "n_subtypes_measured"),
        ("tumor-rna-distribution", "normal_p95_log2tpm"),
        ("tumor-rna-distribution", "normal_p99_log2tpm"),
        ("tumor-rna-distribution", "spotlight_subtype"),
        ("tumor-rna-distribution", "subtype_axis_available"),
        ("tumor-rna-distribution", "subtype_signals_nonuniform"),
        ("tumor-rna-distribution-by-subtype", "indication"),
        ("tumor-rna-distribution-by-subtype", "method_version"),
        ("tumor-rna-distribution-by-subtype", "target"),
        ("tumor-rna-vs-adjacent", "adjacent_mean_tpm"),
        ("tumor-rna-vs-adjacent", "is_actionable_provider_call"),
        ("tumor-rna-vs-adjacent", "tumor_mean_tpm"),
        ("tumor-scrna-celltype-expression", "method_version"),
    }
)


def test_ledger_covers_exactly_run_py_cards():
    """The ledger's card set == this skill's `run.py` CARDS.

    Skill-specific by nature — the fleet sweep has no way to know which cards a given skill consumes,
    so this half cannot be generalized. Row-level well-formedness is delegated (see the shared checker),
    and asserted again here rather than assumed, because a mapping-shaped `spec` is the precondition for
    every other check reading it.
    """
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
            if field.startswith("_"):
                continue
            assert isinstance(spec, dict), f"{cid}.{field}: expected a mapping, got {type(spec).__name__}"
    assert not fdl.wellformedness_problems(doc), "see test_waiver_and_review_keys_are_wellformed"


def test_waiver_and_review_keys_are_wellformed():
    """A `waived_because` is only meaningful on a signal, and `reviewed` must be a real boolean.

    Guards the two ways the keys could be used to launder something: a waiver parked on a
    `context`/`display` row (where nothing was ever required, so the waiver reads as a decision that
    was never made), and a `reviewed:` value that is a truthy STRING rather than a boolean — the
    latter matters because `reviewed` is what tells a reader whether a role is a human judgement or
    a name-shape draft, so a sloppy value silently over-claims review.

    Delegates to the shared checker; kept as a named test in this skill's suite so a red here names
    tumor-presence when the skill is gated on its own (CI runs each skill in its own process).
    """
    problems = fdl.wellformedness_problems(_load_ledger())
    assert not problems, "malformed field-disposition rows:\n  " + "\n  ".join(problems)


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
    import _skills_common.field_disposition as fd

    cen = fd.census(SKILL_DIR.parent, _contracts_root())
    return fdl.signal_reach(_load_ledger(), cen)


def test_the_reach_measurement_is_not_vacuous(signal_reach):
    """CAN the guard below fail, and can it PASS for the right reason?

    If the census silently degraded, every field would read as unreached and the ratchet would red
    for a reason that has nothing to do with wiring. The subtle version is a PARTIAL degradation:
    the contracts-declared kinds resolve fine while the tree-parsing half finds nothing, so reach
    stays high and only a handful of fields flip. That is the failure a total-count threshold cannot
    see, so assert each half is independently alive.
    """
    assert len(signal_reach) >= MIN_SIGNAL_ROWS, (
        f"only {len(signal_reach)} role:signal rows found — the ledger or the census population "
        "collapsed, so the reach guard below is measuring nothing"
    )
    dark = fdl.dark_reach_sources(signal_reach)
    assert not dark, (
        f"census input(s) {dark} reach NO signal field in this ledger. field_disposition.census is not "
        f"resolving target-contracts at {_contracts_root()} and/or not parsing the skills tree at "
        f"{SKILL_DIR.parent} — fix the instrument, not the ledger"
    )


def test_signal_fields_are_reader_reached_or_waived(signal_reach):
    """THE REACH RATCHET: a `role: signal` field is reached by a declared reader, or says why not.

    `role: signal` means "feeds a claim / verdict". A signal no reader touches is a field the skill
    computes, ships, and then ignores — the exact failure the ledger was built to make visible and
    the one completeness could not see. The escape hatch is `waived_because`, which keeps the field
    in a REVIEW QUEUE (mirroring the module SAFETY CONTRACT: unreached is a candidate orphan, never
    a delete list) rather than letting it be quietly relabelled into a verdict-inert bucket.
    """
    unwired = fdl.unwired_signals(_load_ledger(), signal_reach)
    assert not unwired, (
        f"{len(unwired)} field(s) declare role:signal but NO declared reader reaches them, and they "
        "carry no waived_because. Either wire a reader, or change the role with a reason that says "
        "what the field actually does, or add a waived_because naming the missing consumer:\n  " + "\n  ".join(unwired)
    )


# ── the EMIT-vs-DECLARED ratchet: no NEW public field emitted without a declaration (#2016) ─────────


@pytest.mark.skipif(
    _contracts_root() is None,
    reason="target-contracts not resolvable (set TARGET_CONTRACTS_ROOT) — emit reconciliation skipped",
)
def test_observed_emit_reconciles_against_the_contract():
    """THE EMIT-vs-DECLARED RATCHET (#2016, the load-bearing half). Every PUBLIC field the frozen
    maximal run EMITS must be DECLARED in the card's `outputs.summary_fields`, or be a grandfathered
    member of the documented census fail-open backlog (`_KNOWN_EMITTED_BUT_UNDECLARED`).

    A NEW emitted-but-undeclared public field reds here — the fail-open that the ledger-vs-declared
    check (`test_ledger_matches_emitted_fields`) and the fleet-aperture census are BOTH structurally
    blind to, because such a field is in neither the ledger nor the declared set. A backlog field the
    frozen run no longer emits undeclared (it was declared or removed) also reds, forcing the set to be
    re-banked rather than left to rot."""
    fixture = _load_observed_emit()
    if not fixture:
        pytest.skip(f"no frozen fixture at {_OBSERVED_EMIT_FIXTURE} — run freeze_fixture.py against live S3")

    gap = emitted_but_undeclared(fixture, _emitted)  # _emitted returns the DECLARED summary_fields

    new = gap - _KNOWN_EMITTED_BUT_UNDECLARED
    assert not new, (
        "a reader EMITS these PUBLIC field(s) that the card does not DECLARE in outputs.summary_fields "
        "— the census fail-open this instrument closes (#2016). Declare each (pin + TC "
        "outputs.summary_fields + a field_disposition.yaml row + a census-visible reader = ONE atomic "
        f"unit, land TC first) or remove it from the emit:\n  {sorted(new)}"
    )
    stale = _KNOWN_EMITTED_BUT_UNDECLARED - gap
    assert not stale, (
        "these were grandfathered emitted-but-undeclared but the frozen run no longer emits them "
        "undeclared (declared or removed) — re-bank _KNOWN_EMITTED_BUT_UNDECLARED by dropping them:\n"
        f"  {sorted(stale)}"
    )


def test_the_emit_reconciliation_has_teeth():
    """MUTATION TEETH, credential-less. Inject a synthetic run that EMITS an undeclared public field and
    prove the reconciliation FLAGS it — while a declared field, a `_`-prefixed private key, and a
    non-summary (freeze/dispatcher error) are all correctly NOT flagged.

    This is exactly the failure the pre-#2016 instrument is blind to: an emitted-but-undeclared field is
    absent from both `_emitted` (the DECLARED set) and the ledger, so `test_ledger_matches_emitted_fields`
    green-passes it (asserted below). `emitted_but_undeclared` is RED on it."""
    fixture = {
        "card-x": {"declared_f": 1, "SENTINEL_undeclared_emit": 2, "_private_scratch": 3},
        "card-y": {"_freeze_error": "boom", "would_be_undeclared": 9},  # not a real summary → no emit
    }
    declared_map = {"card-x": {"declared_f"}}

    def _declared_of(cid):
        return declared_map.get(cid, set())

    gap = emitted_but_undeclared(fixture, _declared_of)

    assert ("card-x", "SENTINEL_undeclared_emit") in gap, (
        "the reconciliation is blind to a NEW emitted-but-undeclared field — the #2016 census fail-open"
    )
    # the pre-#2016 view (declared-only, what the ledger reconciles against) cannot see it — the bug:
    assert "SENTINEL_undeclared_emit" not in _declared_of("card-x"), (
        "fixture assumption: the sentinel is UNDECLARED, so the declared-only comparison green-passes it"
    )
    assert ("card-x", "declared_f") not in gap, "a DECLARED field must not be flagged"
    assert not any(f.startswith("_") for _c, f in gap), "a `_`-prefixed private key must be excluded by convention"
    assert ("card-y", "would_be_undeclared") not in gap, "a freeze/dispatcher error carries no emit to reconcile"
