"""The SECOND disposition axis for functional-requirement: `interpretation_reach` (#2494, epic #1937 A2).

WHAT THIS GUARDS. `skills/functional-requirement/field_disposition.yaml` now declares
`interpretation_reach` beside the legacy `role` on every row. The reach axis is NOT a judgement: its
value is `field_disposition_contract.interpretation_reach_for()` applied to the reader set that
`field_disposition.census()` measures for that `(card_id, field)` — and the census reads NO
`field_disposition.yaml` (its module docstring and `census()`'s own docstring both say so). So the
ledger's reach column is a RECORDED MEASUREMENT, and the only honest guard over a recorded measurement
is to RE-DERIVE it from the irreproducible input and reconcile row by row. That is
`test_declared_reach_reconciles_with_the_blind_census` below; everything else here is either the
mechanical read path (`reach_map`) or a direction-specific restatement with its own remedy.

WHY NOT "assert the value is one of the three tokens". `skills/_skills_common/tests/test_presence_claims.py`
::test_source_properties_anchors_are_recoverable_and_two_axis_typed asserts exactly that — `reach in
("unreached", "skills_local", "cross_repo_resolver")`. That is the whole closed set, so it passes for
every possible value and can only fail on a crash. Here the anchor test asserts the EXACT token, re-read
from the ledger FILE at assert time, so a wrong token in the YAML reds.

WHAT IS DELIBERATELY NOT HERE.
  * `APERTURE_CEILING` (`skills/_skills_common/tests/test_field_disposition.py`) is NOT touched and NOT
    re-derived. It cannot be: the aperture is measured by `census()`, which is blind to this ledger, so
    declaring reach moves the orphan count by exactly ZERO (measured for this PR: 720 declared-but-unread
    pairs before, 720 after). Re-tightening the ceiling is #2521's separate pass. Note also that the
    ceiling assertion is one-sided (`orphans <= APERTURE_CEILING`), so its green says nothing about this
    change in either direction.
  * No verdict-inertness test (SK#2091). This change DOES alter emitted bytes — `typed_anchor` attaches
    `interpretation_reach` to every dependency `source_properties` anchor the moment this ledger declares
    it (see `test_dependency_anchor_carries_the_ledger_declared_reach`) — and that is the point of thread
    A1, not a defect. Correctness is argued at the data level above, not from verdict movement.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml
from _skills_common import field_disposition as fd
from _skills_common import field_disposition_ledger as fdl
from _skills_common.field_disposition_contract import (
    _REACH_ORDER,
    INTERPRETATION_REACH,
    REACH_CROSS_REPO_RESOLVER,
    REACH_SKILLS_LOCAL,
    REACH_UNREACHED,
    interpretation_reach_for,
)
from _skills_common.source_properties_core import reach_map

SKILL = "functional-requirement"
SKILLS_ROOT = Path(__file__).resolve().parents[2]
LEDGER_PATH = SKILLS_ROOT / SKILL / fdl.LEDGER_NAME

# Row-count FLOOR, not a pin: every guard below iterates the ledger's rows, so an empty or truncated
# ledger would make all of them vacuous-and-green. 180 is under the 207 rows this PR tagged, leaving
# room for a card retiring a field without leaving room for the file going dark.
MIN_ROWS = 180


def _rows_from_file() -> dict:
    """``{(card_id, field): spec}`` parsed from the ledger FILE — the instrument for every assertion
    here, so nothing is compared against a value this test computed itself."""
    doc = fdl.load_ledger(LEDGER_PATH)
    return {(cid, field): spec for cid, field, spec in fdl.iter_rows(doc)}


@pytest.fixture(scope="module")
def census():
    """The reader census over the full declared domain — measured BLIND to any field_disposition.yaml.

    NOT skipped when contracts look unresolvable: a skip here would turn the reconciliation tooth below
    into a silent pass. A broken census must RED, so the domain floor is asserted instead.
    """
    cen = fd.census(SKILLS_ROOT)
    assert len(cen) > 1500, f"census domain collapsed to {len(cen)} — cards stopped being discovered"
    return cen


# ── the declaration itself ─────────────────────────────────────────────────────────────────────────


def test_every_row_declares_the_reach_axis_with_a_registered_token():
    """Coverage + closed-set membership, read off the raw YAML rather than through `reach_map`.

    CAN THIS FAIL: `reach_map` FILTERS rows whose token is not in `INTERPRETATION_REACH`, so an
    unregistered token (a typo, a value from the issue text's stale four-token vocabulary like
    `property_input`) would simply vanish from the map and every reach_map-based check would stay green
    while the row went blind. Reading the YAML directly is the only place that red can originate.
    Deleting the axis from a row fails the first assert; misspelling its value fails the second.
    """
    rows = _rows_from_file()
    assert len(rows) >= MIN_ROWS, f"only {len(rows)} ledger rows — every guard in this file is vacuous"
    missing = sorted(f"{c}.{f}" for (c, f), spec in rows.items() if "interpretation_reach" not in spec)
    assert not missing, (
        f"{len(missing)} row(s) declare no interpretation_reach — the axis must be declared on EVERY "
        f"row, additively beside `role`: {missing[:10]}"
    )
    bad = sorted(
        f"{c}.{f}={spec['interpretation_reach']!r}"
        for (c, f), spec in rows.items()
        if spec["interpretation_reach"] not in INTERPRETATION_REACH
    )
    assert not bad, (
        f"unregistered interpretation_reach token(s) {bad} — the closed set is "
        f"{list(INTERPRETATION_REACH)} (field_disposition_contract.py). reach_map() SILENTLY DROPS an "
        f"unregistered token, so this assert is the only thing that catches it."
    )


def test_the_role_axis_was_not_disturbed():
    """ADDITIVE constraint: every row still carries its legacy `role` in the closed role vocabulary.

    CAN THIS FAIL: a bulk edit that replaced `role:` with `interpretation_reach:` instead of inserting
    beside it, or renamed `role` to `semantic_role` (this repo has no such key), reds here.
    """
    rows = _rows_from_file()
    assert len(rows) >= MIN_ROWS
    bad = sorted(
        f"{c}.{f}={spec.get('role')!r}" for (c, f), spec in rows.items() if spec.get("role") not in fdl.VALID_ROLES
    )
    assert not bad, f"role axis disturbed on {len(bad)} row(s): {bad[:10]}"


# ── the read path: reach_map ───────────────────────────────────────────────────────────────────────


def test_reach_map_is_non_empty_and_equals_the_file():
    """`reach_map(SKILL)` returned `{}` before this PR (the ledger declared the axis on no row), so
    functional-requirement's L2a anchors could not type their second axis. It must now mirror the file
    exactly — key for key, value for value.

    CAN THIS FAIL: an equality against the FILE, not a subset/truthiness check. A row the loader drops,
    a key it mis-forms, or a value that disagrees with the YAML all red.
    """
    expected = {k: spec.get("interpretation_reach") for k, spec in _rows_from_file().items()}
    assert len(expected) >= MIN_ROWS
    assert reach_map(SKILL) == expected, "reach_map disagrees with the ledger file it reads"


def test_reach_map_follows_a_mutated_row_and_omits_a_dropped_one(tmp_path):
    """The map is LIVE off the file, not a snapshot: mutate a row's reach in a copy of the tree and the
    map reports the mutated value; delete the row and the key is OMITTED (never defaulted).

    CAN THIS FAIL: it is a three-way differential on a real copied ledger. If `reach_map` hardcoded,
    returned a stale cached answer, or defaulted a missing row to some token, each branch reds. The
    pre-change ledger makes the whole test red at the `baseline` assert and again at `victim = ...`,
    because there is no reach row to read or mutate.

    `reach_map` is `lru_cache`d on `(skill, skills_root)`, so each re-read clears the cache first —
    without that the mutations would be invisible and this test would be a green that proves nothing.
    """
    root = tmp_path / "skills"
    (root / SKILL).mkdir(parents=True)
    copy = root / SKILL / fdl.LEDGER_NAME
    shutil.copy(LEDGER_PATH, copy)
    doc = yaml.safe_load(copy.read_text())

    def _read() -> dict:
        reach_map.cache_clear()
        return reach_map(SKILL, str(root))

    baseline = _read()
    assert baseline == {k: spec.get("interpretation_reach") for k, spec in _rows_from_file().items()}

    # pick a row deterministically and flip it to a DIFFERENT legal token
    victim = sorted(baseline)[0]
    other = next(t for t in INTERPRETATION_REACH if t != baseline[victim])
    doc[victim[0]][victim[1]]["interpretation_reach"] = other
    copy.write_text(yaml.safe_dump(doc, sort_keys=False))
    assert _read()[victim] == other, "reach_map did not follow a mutated ledger row"

    # drop the row entirely → the KEY is absent, not defaulted
    del doc[victim[0]][victim[1]]
    copy.write_text(yaml.safe_dump(doc, sort_keys=False))
    dropped = _read()
    assert victim not in dropped, f"a dropped ledger row still reports a reach: {victim}"
    assert len(dropped) == len(baseline) - 1

    # an UNREGISTERED token is filtered out — this is the blindness the raw-YAML test above exists to cover
    doc[victim[0]][victim[1]] = {"role": "context", "reason": "x", "interpretation_reach": "property_input"}
    copy.write_text(yaml.safe_dump(doc, sort_keys=False))
    assert victim not in _read()
    reach_map.cache_clear()  # leave no tmp-rooted entry behind for the rest of the session


# ── the substantive claim: the declared reach IS the measured reach ────────────────────────────────


def test_declared_reach_reconciles_with_the_blind_census(census):
    """THE TOOTH. Every declared reach is re-derived from the census reader set and must match.

    The ledger stores the CONCLUSION; this test re-derives it from the irreproducible input (the live
    reader census over contracts/, methods/ and the skills tree). The census reads no
    `field_disposition.yaml`, so this can never be satisfied by editing the file under test.

    CAN THIS FAIL: mutate any one of the 207 reach values in the YAML and this reds naming the row.
    It is also the correct red when a PR wires (or removes) a reader for a functional-requirement card
    field without banking the new reach — REMEDY: re-derive this skill's reach column, do not edit this
    test.
    """
    rows = _rows_from_file()
    assert len(rows) >= MIN_ROWS
    mismatched = []
    for (cid, field), spec in sorted(rows.items()):
        measured = interpretation_reach_for(census.get((cid, field)) or {})
        if spec.get("interpretation_reach") != measured:
            mismatched.append(f"{cid}.{field}: ledger={spec.get('interpretation_reach')} census={measured}")
    assert not mismatched, (
        f"{len(mismatched)} row(s) declare a reach the blind census does not measure. Re-derive the "
        f"reach column (interpretation_reach_for over field_disposition.census); never edit the value "
        f"to match a stale belief: {mismatched[:12]}"
    )


def test_the_reconciliation_is_not_measuring_one_token(census):
    """Non-vacuity in BOTH directions for the test above: a census that reached NOTHING (or EVERYTHING)
    would still reconcile perfectly against a ledger written from that same broken census. So assert the
    measurement actually SEPARATES this skill's fields, and assert it per source — `dark_reach_sources`
    is calibrated per census input precisely because a total degrades into a check on the largest
    mechanism.

    CAN THIS FAIL: point the census at an empty tree and both reach buckets collapse to one; break the
    skills-tree parser specifically and `dark_reach_sources` names it while the totals still look fine.
    """
    rows = _rows_from_file()
    buckets: dict[str, int] = {}
    for cid, field in rows:
        m = interpretation_reach_for(census.get((cid, field)) or {})
        buckets[m] = buckets.get(m, 0) + 1
    assert buckets.get(REACH_UNREACHED, 0) > 0 and buckets.get(REACH_SKILLS_LOCAL, 0) > 0, (
        f"the census does not separate this skill's fields — measured buckets {buckets}. A detector that "
        f"finds everything is as broken as one that finds nothing, and both reconcile with a ledger "
        f"written from them."
    )
    reach = fdl.signal_reach(fdl.load_ledger(LEDGER_PATH), census)
    assert reach, "no role:signal rows — the source liveness check below would be vacuous"
    # EXACT equality, not `not dark`: every skills-side census input must reach some signal field here,
    # and `analysis_methods_resolver` must reach NONE — there is no dependency-property resolver under
    # methods/onc_methods/, so a dark cross-repo source is the CORRECT measurement for this skill (it is
    # what makes the cross_repo_resolver absence below honest). Pinning the set two-sidedly means a dead
    # skills-side parser reds, AND the day the methods seam does reach a dependency signal this reds too,
    # which is exactly when the reach column needs re-deriving.
    assert set(fdl.dark_reach_sources(reach)) == {"analysis_methods_resolver"}, (
        f"census source liveness changed: dark sources are {sorted(fdl.dark_reach_sources(reach))}, "
        f"expected exactly ['analysis_methods_resolver']"
    )


def test_no_row_overclaims_its_reach(census):
    """The ANTI-GAMING direction, stated separately because it has a different severity and a different
    remedy from the reconciliation above. A ledger may never claim its field travels FURTHER than the
    census can see; that is the direction in which the disposition metric starts measuring our own
    paperwork (`field_disposition.py`'s own warning). Reach is a max over readers, so "further" is
    `_REACH_ORDER`, not string inequality.

    CAN THIS FAIL: promote any row to `cross_repo_resolver` (or any `unreached` row to `skills_local`)
    without a reader and this reds. Unlike the reconciliation test it stays green when a peer PR wires a
    NEW reader — an under-claim is stale, not dishonest — so a red here is always a real over-claim.
    """
    rows = _rows_from_file()
    assert len(rows) >= MIN_ROWS
    over = []
    for (cid, field), spec in sorted(rows.items()):
        declared = spec.get("interpretation_reach")
        measured = interpretation_reach_for(census.get((cid, field)) or {})
        if _REACH_ORDER.get(declared, -1) > _REACH_ORDER[measured]:
            over.append(f"{cid}.{field}: claims {declared}, census measures only {measured}")
    assert not over, f"{len(over)} row(s) OVER-CLAIM their interpretation reach: {over[:12]}"


def test_cross_repo_reach_is_absent_and_the_seam_independently_agrees(census):
    """The reach guarantee for `cross_repo_resolver`, stated in the only non-vacuous form available here.

    A guard shaped "every `cross_repo_resolver` row has a resolver consumption edge" would be VACUOUS in
    this ledger — zero rows carry that token, so an empty parametrize would go green while asserting
    nothing. The claim with teeth is the TWO-SIDED absence: (1) no row declares the token, and (2) the
    seam, measured independently of this ledger, credits NO field of any card in it. Only one property
    resolver exists under `methods/onc_methods/` — `expression_properties/resolve.py`, bound in
    `RESOLVER_INPUT_BINDINGS` to `cellline-rna-distribution` alone — so a dependency field cannot be read
    across the seam today, and tagging one would be a fabricated consumption edge.

    CAN THIS FAIL: it reds if anyone tags a dependency field `cross_repo_resolver` (side 1), AND it reds
    if a real dependency-property resolver is bound and starts reading these fields while the ledger
    still says nothing does (side 2) — which is exactly when the reach column must be re-derived.
    """
    rows = _rows_from_file()
    declared_cross = sorted(
        f"{c}.{f}" for (c, f), spec in rows.items() if spec.get("interpretation_reach") == REACH_CROSS_REPO_RESOLVER
    )
    seam = fd.resolver_input_readers()
    assert seam, "resolver_input_readers() returned nothing — the seam instrument is dead, not quiet"
    our_cards = {cid for cid, _f in rows}
    seam_here = sorted(f"{c}.{f}" for (c, f) in seam if c in our_cards)
    assert declared_cross == seam_here == [], (
        f"cross-repo reach disagreement: ledger declares {declared_cross}, the live methods/ seam "
        f"credits {seam_here}. Both must stay empty until a dependency-property resolver exists and is "
        f"bound in field_disposition.RESOLVER_INPUT_BINDINGS."
    )


# ── thread A1: the emitted L2a anchor now types its second axis ────────────────────────────────────


def _kras_cards():
    """Minimal CRISPR card summary mirroring the frozen KRAS/COADREAD replay fixture — the RAW L1 values
    the dependency source-property recipe retains as anchors. Stored raw, re-derived in the test."""
    return [
        {
            "card_id": "pan-cancer-crispr-dependency-distribution",
            "summary": {
                "dependency_class": "strongly_selective",
                "bimodality_coefficient": 0.70,
                "distribution_shape": "bimodal_selective",
                "fraction_strongly_dependent": 0.176,
                "median_chronos_panel": -0.457,
                "p5_chronos_panel": -2.105,
                "n_cell_lines_evaluated": 1538,
                "selectivity_index": 0.855,
            },
        }
    ]


def _kras_headline():
    return {
        "crispr_call": "strongly_selective",
        "rnai_call": "strongly_selective",
        "concordance_call": "moderately_concordant_non_dependent",
        "lineage_selectivity": "lineage_selective",
        "cross_consortium_class": "concordant_dependent",
        "predictability_class": "own_omics_driven",
        "partner_conditional_class": "no_partner_mapped",
        "prism_concordance_class": "triangulated_target_engaged",
    }


def test_dependency_anchor_carries_the_ledger_declared_reach():
    """Thread A1: a real emitted L2a `source_properties` anchor now carries `interpretation_reach`, and
    its value is the one re-read from the ledger FILE for that exact `(card_id, field)`.

    This is where the ledger edit changes EMITTED BYTES — `typed_anchor` omits the key while the ledger
    declares nothing, and attaches it the moment the ledger does. That is thread A1's deliverable.

    CAN THIS FAIL: on the pre-change ledger the key is absent from every anchor → the `in anchor` assert
    reds (measured: it does). It also reds if the anchors stop being emitted, if the entry disappears, or
    if fewer than two anchors are ledger-classified — none of those degrade into a vacuous green.

    WHAT THIS DOES **NOT** PROVE, stated so nobody mistakes its green for more than it is: the equality
    `anchor[...] == declared[...]` is a PROJECTION check, not a value check. `typed_anchor` sources the
    token from this same ledger file, so a WRONG token in the YAML appears on both sides and this test
    stays green. Value correctness is owned by `test_declared_reach_reconciles_with_the_blind_census`,
    which re-derives from the census; the equality here exists to prove the projection reads the ledger
    rather than a constant.
    """
    from _skills_common.dependency_claims import dependency_claim_vector

    vec = dependency_claim_vector(_kras_headline(), _kras_cards())
    entry = (vec.get("source_properties") or {}).get("crispr_essentiality")
    assert entry, (
        f"no crispr_essentiality source_properties entry emitted: {sorted(vec.get('source_properties') or {})}"
    )
    anchors = {a["field"]: a for a in entry["anchors"]}
    assert anchors, "the entry emitted no anchors — this test would be vacuous"

    declared = {
        field: spec["interpretation_reach"]
        for (cid, field), spec in _rows_from_file().items()
        if cid == entry["card_id"] and "interpretation_reach" in spec
    }
    assert declared, (
        f"the ledger declares no interpretation_reach for any {entry['card_id']} field — nothing to project"
    )
    checked = 0
    for field, anchor in sorted(anchors.items()):
        if field not in declared:
            continue
        assert "interpretation_reach" in anchor, (
            f"anchor {entry['card_id']}.{field} carries no interpretation_reach — the ledger declares "
            f"{declared[field]!r} for it, so typed_anchor must project it"
        )
        assert anchor["interpretation_reach"] == declared[field]
        assert anchor["semantic_role"] in fdl.VALID_ROLES  # axis 1 still projected, additively
        checked += 1
    assert checked >= 2, f"only {checked} anchor(s) were reach-checked — not enough to be a real pin"
