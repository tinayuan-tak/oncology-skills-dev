"""The SECOND disposition axis for tumor-selectivity: `interpretation_reach` (#2498, epic #1937 A2/A4).

WHAT LANDED (epic #1937 thread A2). `skills/tumor-selectivity/field_disposition.yaml` declared `role` on
228 rows and `interpretation_reach` on ZERO, so `reach_map("tumor-selectivity")` returned `{}` and this
skill's L2a `source_properties` anchors could not type their second axis at all. This pass adds
`interpretation_reach` to all 228 rows, ADDITIVELY beside `role` — no row's `role` was re-litigated
(every one already carried `reviewed: true`, a human judgement; a second axis is added beside it, the
first is not revised).

WHICH VOCABULARY. The CLOSED set is `field_disposition_contract.INTERPRETATION_REACH` ==
`("unreached", "skills_local", "cross_repo_resolver")` — the vocabulary the landed two-axis contract
(#1525) ships and the worked tumor-presence template uses on its 325 rows (#1870). The governing rule
"retention broad · exposure narrow · recovery broad" maps onto it directly: `skills_local` /
`cross_repo_resolver` are the EXPOSED (consumed) classes, claimable only where a real reader edge exists;
`unreached` is the RETAINED/RECOVERABLE class — a scientifically meaningful field no reader reaches is
kept, declared, and parked in a REVIEW queue, never deleted and never relabelled to move a count.

WHY THESE TEETH BITE. Every reach value is MACHINE-DERIVED from `field_disposition.census`, which reads
no `field_disposition.yaml` and so cannot be satisfied by editing the file it describes. The load-bearing
test below (`test_reach_guarantee_*`) RE-DERIVES all 228 values from that ledger-blind census and compares
them to the file — so a hand-edited row that over-claims reach (the direction that would let the ledger
congratulate itself) goes RED. That is this pass's version of "every exposed field has a real consumption
edge".

MEASURED, 2026-10-02, on this tree:
  * 228 ledger rows / 228 reach values; `reach_map` size 0 -> 228; 13 cards.
  * distribution: 157 `skills_local`, 71 `unreached`, **0** `cross_repo_resolver`.
  * ZERO `cross_repo_resolver` is a MEASURED result, not a dark instrument: the census `resolver_input`
    kind reaches 10 pairs fleet-wide and all 10 sit on `cellline-rna-distribution`, which is not one of
    this skill's 13 cards. tumor-selectivity reads expression/abundance data, but the only property
    resolver under `methods/onc_methods/` (`expression_properties/resolve.py`) is bound in
    `RESOLVER_INPUT_BINDINGS` to `cellline-rna-distribution` alone, so no tumor-selectivity field is read
    across the seam today. `test_no_row_claims_cross_repo_reach_*` asserts that instrument is alive rather
    than trusting the zero.

ORPHANS — WHICH METRIC, HONESTLY (thread A4). The FLEET aperture metric
(`field_disposition.summarise(...)["candidate_orphans"]`) is DELIBERATELY BLIND to every ledger, by
design, precisely so declaring a disposition cannot move it ("the metric would measure our own
paperwork"). It is therefore UNCHANGED by this additive, census-blind declaration, and this pass
deliberately does NOT touch `APERTURE_CEILING` (re-tightening is #2521; all 16 A2/A4 issues nominate that
one shared file, so a ceiling edit here conflicts by construction). The orphan this pass genuinely burns
down is the **axis-2 orphan**: a row that cannot type its second axis at all, i.e. one `reach_map` does
not return. 228 before, 0 after, and the delta is asserted DIRECTLY below by mutating a tagged row back to
untagged — not inferred from a one-sided `orphans <= CEILING` assertion, whose green is no evidence of
anything in the falling direction.

VERDICT. Neither axis feeds a verdict; this is the L1 disposition layer of #1507. The point is an
accurate, fully-attributed data package, not verdict movement in either direction.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

# No `sys.path` insert (#2144): `skills-common` is editable-installed into the workspace env, so
# `_skills_common.*` resolves by install. Never `methods.*` (#2257); nothing here reaches the methods tree.
from _skills_common import field_disposition as fd
from _skills_common import field_disposition_ledger as fdl
from _skills_common.field_disposition_contract import (
    INTERPRETATION_REACH,
    REACH_CROSS_REPO_RESOLVER,
    REACH_SKILLS_LOCAL,
    REACH_UNREACHED,
    interpretation_reach_for,
)
from _skills_common.source_properties_core import reach_map, typed_anchor

_SKILLS_ROOT = Path(__file__).resolve().parents[2]
_SKILL = "tumor-selectivity"
_LEDGER_PATH = _SKILLS_ROOT / _SKILL / fdl.LEDGER_NAME

# ── DENOMINATORS. Every floor below is justified from a measurement on this tree, never a round number.
# 228 rows / 157 skills_local / 71 unreached / 13 cards, measured 2026-10-02. The floors sit just under
# the measurement so a card retirement does not red them, while a COLLAPSE (a parse break, a renamed key,
# a ledger truncated to its _meta) cannot read as a pass. These are the counts the role/reach assertions
# in this module consume, so flooring them is flooring the assertions' own strength.
_ROW_FLOOR = 215
_SKILLS_LOCAL_FLOOR = 140
_UNREACHED_FLOOR = 60
_CARD_FLOOR = 11
#: Fleet-wide `resolver_input` census pairs, measured 2026-10-02 (10). Floored so "this skill has no
#: cross-repo reach" can never be an artifact of a dead cross-repo parser.
_RESOLVER_INPUT_PAIRS_FLOOR = 5


def _load_doc(path: Path = _LEDGER_PATH) -> dict:
    return yaml.safe_load(Path(path).read_text()) or {}


def _rows(doc: dict) -> dict:
    """``{(card_id, field): spec}`` for every real row — via the shared ``iter_rows`` metadata filter."""
    return {(cid, field): spec for cid, field, spec in fdl.iter_rows(doc)}


#: THE MODULE-LEVEL DISCOVERY SUBJECT every assertion in this file consumes.
_DOC = _load_doc()
_ROWS = _rows(_DOC)
_ROW_KEYS = tuple(sorted(_ROWS))


@pytest.fixture(scope="module")
def census() -> dict:
    """The ledger-BLIND reader census, built once (it walks every card contract and every ``.py``)."""
    return fd.census(_SKILLS_ROOT)


def _reach_problems(doc: dict) -> list[str]:
    """Closed-set validation of axis 2 — a LIST so one call reports every bad row. A missing axis, a
    non-string, or an unregistered token is a problem."""
    problems = []
    for (cid, field), spec in sorted(_rows(doc).items()):
        if "interpretation_reach" not in spec:
            problems.append(f"{cid}.{field}: no interpretation_reach (axis-2 orphan)")
        elif spec["interpretation_reach"] not in INTERPRETATION_REACH:
            problems.append(
                f"{cid}.{field}: bad interpretation_reach {spec['interpretation_reach']!r} "
                f"(expected one of {sorted(INTERPRETATION_REACH)})"
            )
    return problems


def _axis2_orphans(doc: dict) -> list[str]:
    """Rows ``reach_map`` cannot type — the orphan population THIS pass burns down (228 -> 0)."""
    typed = {
        (cid, field)
        for cid, field, spec in fdl.iter_rows(doc)
        if spec.get("interpretation_reach") in INTERPRETATION_REACH
    }
    return sorted(f"{c}.{f}" for (c, f) in _rows(doc) if (c, f) not in typed)


def _write_ledger_root(tmp_root: Path, doc: dict) -> Path:
    """A throwaway ``skills_root`` holding ONLY ``<skill>/field_disposition.yaml``.

    One root per call, never reused: ``reach_map``/``role_for`` are ``lru_cache``d per ``(root, skill)``,
    so probing a root BEFORE mutating it primes the cache and the mutation tooth then fails looking exactly
    like "the value is hardcoded". Baselines in this module are read from the YAML text, never by calling
    ``reach_map`` on a root we are about to rewrite.
    """
    d = tmp_root / _SKILL
    d.mkdir(parents=True, exist_ok=True)
    (d / fdl.LEDGER_NAME).write_text(yaml.safe_dump(doc, sort_keys=True))
    return tmp_root


# ══ denominator first — nothing below may go vacuous ══════════════════════════════════════════════


def test_row_denominator_is_not_vacuous():
    """THE floor. Every other test iterates `_ROWS`; if the ledger stopped parsing, were truncated to its
    `_meta`, or had `role:` renamed, those tests would all pass over an empty set. Pin the discovered row
    count, the card count, and BOTH reach classes to measured member counts, so a collapse reds here
    instead of shipping as a clean sweep."""
    assert len(_ROWS) == len(_ROW_KEYS) >= _ROW_FLOOR, (
        f"only {len(_ROWS)} rows parsed from {_LEDGER_PATH} (floor {_ROW_FLOOR}, measured 228) — the "
        "ledger stopped parsing or lost its rows; every assertion in this module would be vacuous."
    )
    cards = {cid for cid, _ in _ROW_KEYS}
    assert len(cards) >= _CARD_FLOOR, f"only {len(cards)} cards in the ledger (floor {_CARD_FLOOR}, measured 13)"
    # the first axis is still fully declared — this pass must not have disturbed it
    assert all(spec.get("role") in fdl.VALID_ROLES for spec in _ROWS.values()), "a row lost its `role`"
    # and BOTH reach classes are populated, so a reach assertion cannot be true by one-sidedness
    counts = {r: sum(1 for s in _ROWS.values() if s.get("interpretation_reach") == r) for r in INTERPRETATION_REACH}
    assert counts[REACH_SKILLS_LOCAL] >= _SKILLS_LOCAL_FLOOR, f"skills_local collapsed: {counts} (measured 157)"
    assert counts[REACH_UNREACHED] >= _UNREACHED_FLOOR, f"unreached collapsed: {counts} (measured 71)"
    assert sum(counts.values()) == len(_ROWS), f"a row carries an unregistered reach token: {counts}"


def test_the_role_axis_was_not_relitigated():
    """ADDITIVE constraint, mechanically. Every row was `reviewed: true` before this pass (a human
    judgement on axis 1); adding axis 2 may not have downgraded or dropped that marker, and the ledger
    must still be well-formed on axis 1."""
    unreviewed = sorted(f"{c}.{f}" for (c, f), s in _ROWS.items() if s.get("reviewed") is not True)
    assert not unreviewed, f"rows lost `reviewed: true` — axis 1 was disturbed: {unreviewed[:10]}"
    assert not fdl.wellformedness_problems(_DOC)


# ══ closed-set validation — an unregistered token REDS ════════════════════════════════════════════


def test_every_reach_value_is_in_the_closed_set():
    assert not _reach_problems(_DOC)


def test_an_unregistered_reach_token_is_caught(tmp_path_factory):
    """The teeth of the test above. A bogus token is NOT merely ignored — `reach_map` filters by
    `INTERPRETATION_REACH`, so an unregistered token would silently DROP the row from the axis (declared
    but invisible, the false-absence direction). The validator must name it, and the silent drop is
    proven real at the loader."""
    doc = _load_doc()
    cid, field = _ROW_KEYS[0]
    doc[cid][field]["interpretation_reach"] = "property_input"  # a token from the issue's stale vocabulary
    problems = _reach_problems(doc)
    assert any(f"{cid}.{field}" in p and "property_input" in p for p in problems), problems
    root = _write_ledger_root(tmp_path_factory.mktemp("reach_bogus"), doc)
    assert (cid, field) not in reach_map(_SKILL, str(root))


# ══ reach_map: non-empty, row-for-row, and it READS THE FILE ══════════════════════════════════════


def test_reach_map_is_non_empty_and_matches_the_ledger_row_for_row():
    """`reach_map("tumor-selectivity")` was `{}` before this pass. It must now return the DECLARED reach
    for every tagged row — compared against a map built by an independent read of the YAML, so the two
    paths cannot agree by sharing a bug."""
    live = reach_map(_SKILL)
    expected = {k: s["interpretation_reach"] for k, s in _ROWS.items() if "interpretation_reach" in s}
    assert live, "reach_map is empty — this skill's L2a anchors cannot type their second axis"
    assert len(live) >= _ROW_FLOOR
    assert live == expected


def test_a_dropped_ledger_row_disappears_from_reach_map(tmp_path_factory):
    """A dropped row REDS: deleting ONE row's axis-2 key must remove exactly that pair, nothing else."""
    doc = _load_doc()
    cid, field = _ROW_KEYS[0]
    baseline = doc[cid][field]["interpretation_reach"]  # read from the FILE, not from reach_map
    assert baseline in INTERPRETATION_REACH
    del doc[cid][field]["interpretation_reach"]
    got = reach_map(_SKILL, str(_write_ledger_root(tmp_path_factory.mktemp("reach_drop"), doc)))
    assert (cid, field) not in got
    assert len(got) == len(_ROWS) - 1, f"dropping one row changed the map by {len(_ROWS) - len(got)} entries"


def test_reach_map_follows_a_mutated_ledger_row(tmp_path_factory):
    """Prove `reach_map` READS THE FILE rather than returning a derived fixture: mutate one row to a
    DIFFERENT legal token and the returned value must follow. Two distinct throwaway roots, and the
    baseline read straight from the copied YAML — never by probing a root we then rewrite (that primes the
    `(root, skill)` lru_cache and the tooth fails looking exactly like a hardcoded value)."""
    doc = _load_doc()
    cid, field = next((k for k, s in _ROWS.items() if s["interpretation_reach"] == REACH_UNREACHED), _ROW_KEYS[0])
    baseline = doc[cid][field]["interpretation_reach"]
    mutated = REACH_CROSS_REPO_RESOLVER if baseline != REACH_CROSS_REPO_RESOLVER else REACH_SKILLS_LOCAL
    assert mutated != baseline

    root_a = _write_ledger_root(tmp_path_factory.mktemp("reach_base"), doc)
    assert reach_map(_SKILL, str(root_a))[(cid, field)] == baseline

    doc[cid][field]["interpretation_reach"] = mutated
    root_b = _write_ledger_root(tmp_path_factory.mktemp("reach_mut"), doc)
    assert reach_map(_SKILL, str(root_b))[(cid, field)] == mutated, (
        "reach_map did not follow the mutated ledger row — it is not reading the file"
    )


# ══ THE REACH GUARANTEE: every exposed row has a real, census-visible consumption edge ════════════


def test_reach_guarantee_every_declared_value_re_derives_from_the_ledger_blind_census(census):
    """THE load-bearing tooth. `field_disposition.census` reads no `field_disposition.yaml`, so it is the
    independent edge store: re-derive all 228 values from it and require the file to agree exactly.

    This is the Reach guarantee in this repo's vocabulary — the EXPOSED classes (`skills_local` /
    `cross_repo_resolver`) may only be claimed where a real reader edge exists, and a row cannot be demoted
    to `unreached` (nor promoted) by editing the ledger. Liveness is asserted BEFORE the comparison,
    because a census that parses nothing re-derives every row to `unreached` and would happily agree with a
    ledger someone had blanked."""
    alive = fd.reader_sources_alive(fd.summarise(census)["per_kind"])
    dark = sorted(src for src, ok in alive.items() if not ok)
    assert not dark, f"census input(s) {dark} produced ZERO reach — the instrument is broken, not the ledger"
    assert all(k in census for k in _ROW_KEYS), "a ledger row is outside the census domain"

    mismatches = {
        f"{c}.{f}": (_ROWS[(c, f)]["interpretation_reach"], interpretation_reach_for(census[(c, f)]))
        for (c, f) in _ROW_KEYS
        if _ROWS[(c, f)]["interpretation_reach"] != interpretation_reach_for(census[(c, f)])
    }
    assert not mismatches, f"declared reach disagrees with the ledger-blind census (declared, measured): {mismatches}"

    reached = [k for k in _ROW_KEYS if _ROWS[k]["interpretation_reach"] != REACH_UNREACHED]
    assert len(reached) >= _SKILLS_LOCAL_FLOOR
    for k in reached:
        readers = census[k]
        assert readers["exact"] or readers["name_only"], f"{k} claims reach with NO reader edge at all"


def test_the_reconciliation_separates_this_skills_fields(census):
    """Non-vacuity in BOTH directions for the test above: a census that reached NOTHING (or EVERYTHING)
    would still reconcile perfectly against a ledger written from that same broken census. Assert the
    measurement actually SEPARATES this skill's fields into more than one reach bucket."""
    buckets: dict[str, int] = {}
    for cid, field in _ROW_KEYS:
        m = interpretation_reach_for(census.get((cid, field)) or {})
        buckets[m] = buckets.get(m, 0) + 1
    assert buckets.get(REACH_UNREACHED, 0) > 0 and buckets.get(REACH_SKILLS_LOCAL, 0) > 0, (
        f"the census does not separate this skill's fields — measured buckets {buckets}. A detector that "
        f"finds everything is as broken as one that finds nothing, and both reconcile with a ledger written "
        f"from them."
    )


def test_an_over_claimed_reach_row_is_caught(census):
    """The teeth of the guarantee: promote one genuinely-`unreached` row to `skills_local` and the
    re-derivation must name it. Without this, "all 228 agree" could be true of any ledger."""
    victim = next(k for k in _ROW_KEYS if _ROWS[k]["interpretation_reach"] == REACH_UNREACHED)
    assert not (census[victim]["exact"] or census[victim]["name_only"]), f"{victim} is not actually unreached"
    claimed = REACH_SKILLS_LOCAL
    assert claimed != interpretation_reach_for(census[victim]), (
        "an over-claimed row re-derived to its own claim — the guarantee above would be unfalsifiable"
    )


def test_no_row_claims_cross_repo_reach_because_no_onc_methods_resolver_reads_this_skill(census):
    """`cross_repo_resolver` is claimable ONLY where an `onc_methods` resolver actually reads the field.
    Measured: the `resolver_input` kind reaches 10 pairs fleet-wide, every one on `cellline-rna-distribution`,
    which this skill does not declare — so ZERO rows here may claim it. The fleet floor is asserted first: a
    dead cross-repo parser would also produce zero, and that must RED rather than license the same
    conclusion."""
    resolver_pairs = {p for p, r in census.items() if "resolver_input" in r["exact"]}
    assert len(resolver_pairs) >= _RESOLVER_INPUT_PAIRS_FLOOR, (
        f"only {len(resolver_pairs)} resolver_input pairs fleet-wide (floor {_RESOLVER_INPUT_PAIRS_FLOOR}, "
        "measured 10) — the cross-repo parser is dark; 'no cross-repo reach here' would be an artifact."
    )
    mine = {(c, f) for (c, f) in resolver_pairs if c in {cid for cid, _ in _ROW_KEYS}}
    assert not mine, f"an onc_methods resolver DOES read {sorted(mine)} — those rows owe cross_repo_resolver"
    assert not [k for k in _ROW_KEYS if _ROWS[k]["interpretation_reach"] == REACH_CROSS_REPO_RESOLVER]


# ══ the orphan delta, asserted DIRECTLY (never via the one-sided ceiling) ═════════════════════════


def test_axis2_orphan_count_fell_to_zero_and_a_detagged_row_raises_it():
    """A4, honestly. The FLEET aperture assertion is `orphans <= APERTURE_CEILING` — one-sided, so lowering
    orphans can never turn it red and its green is NO evidence that a burn-down worked. Assert the delta
    directly instead, on the population this pass actually moves: rows that cannot type their second axis
    (228 before this PR, 0 after). Mutating a newly-tagged row back to untagged must RAISE the count — the
    falling direction is therefore proven, not assumed."""
    assert len(_ROWS) >= _ROW_FLOOR  # denominator: 0 orphans over 0 rows is not an achievement
    assert _axis2_orphans(_DOC) == [], f"rows still cannot type axis 2: {_axis2_orphans(_DOC)[:10]}"

    doc = _load_doc()
    cid, field = _ROW_KEYS[0]
    del doc[cid][field]["interpretation_reach"]
    after = _axis2_orphans(doc)
    assert after == [f"{cid}.{field}"], f"de-tagging one row produced orphans {after}"
    assert len(after) > len(_axis2_orphans(_DOC)), "orphan count did not rise when a row lost its axis"


# ══ the A1 tie-in: an emitted L2a anchor now carries the axis ═════════════════════════════════════


def test_a_typed_anchor_now_carries_both_axes_for_this_skill():
    """Thread A1's consumer. `typed_anchor` omits a typing key it cannot source; before this pass
    `reach_map` was `{}` so every tumor-selectivity L2a anchor omitted `interpretation_reach`. It must now
    carry BOTH axes for a ledger-declared field — and still omit both for a field the ledger does not
    classify, so the anchor never fabricates a disposition."""
    (cid, field) = _ROW_KEYS[0]
    anchor = typed_anchor(cid, field, 1.0, {}, _SKILL)
    assert anchor["semantic_role"] == _ROWS[(cid, field)]["role"]
    assert anchor["interpretation_reach"] == _ROWS[(cid, field)]["interpretation_reach"]

    unclassified = typed_anchor(cid, "a_field_this_ledger_does_not_classify", 1.0, {}, _SKILL)
    assert "semantic_role" not in unclassified and "interpretation_reach" not in unclassified
