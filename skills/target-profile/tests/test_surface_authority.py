"""Cross-surface agreement teeth for the TYPED SURFACE AUTHORITY contract.

Contract: `docs/UNIFIED_OUTPUT_CONTRACT.md` § "Typed surface authority". Corpus:
`fixtures/polarity_surface_projection.json`, built from live runs by
`build_polarity_surface_projection.py` (37 target×indication pairs, latest-per-pair, 629 axis rows).

WHAT THIS FILE IS FOR
---------------------
A composed nomination emits the same axis's judgement on nine surfaces carrying FIVE types. The failure
this guards is not "two surfaces disagree" — it is a reader **comparing two surfaces of different
types** and reporting the type error as a data error (or, worse, resolving it by moving a value). So:

  * where two surfaces are the SAME type, equality is asserted (and the one known exception is a
    DECLARED expected fork carrying a prose reason, pinned by row count, not waived);
  * where two surfaces are DIFFERENT types, the DISJOINTNESS of their vocabularies is asserted, so the
    incommensurability is a checked fact rather than a comment;
  * where two vocabularies PARTIALLY overlap — the dangerous case, because a naive equality check is
    right most of the time — the exact shared token set and both disjoint remainders are pinned.

RATCHETS RUN BOTH WAYS. A known-violation count that GROWS fails (the violation spread); a count that
SHRINKS also fails (either it was fixed — update the pin and say so — or the corpus quietly stopped
covering it, which is the "a check that passes because its population died" failure mode). Every
population is asserted non-empty before anything is asserted over it, for the same reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "fixtures" / "polarity_surface_projection.json"

# Two checks below assert against the PRODUCER's own vocabulary/behaviour rather than against the
# frozen corpus, because a snapshot cannot observe a producer change. That needs `skills/` importable.

SCHEMA = "polarity_surface_projection/v1"

# ── corpus floors ────────────────────────────────────────────────────────────────────────────────
# Not equalities: a re-freeze over MORE runs is welcome, a corpus that shrank below the size these
# measurements were taken on is not (every rate below would be computed on a different population).
MIN_PAIRS = 30
MIN_ROWS = 500

# ── the closed vocabularies, pinned BY VALUE (a split/rename of any token must land here) ─────────
POLARITY_TOKENS = {"killer", "opposing", "neutral", "supportive", "not_scored"}  # skill_report (4)
# Surface (5) needs TWO sets, and conflating them is what hid a real defect for the life of this file.
# DECLARED is the ordinal_view scale `evidence_graph.py` says it emits (asserted against the code
# below, so the two can never drift again). OBSERVED_FROZEN is what this pre-fix SNAPSHOT happens to
# contain. The old single `EG_POLARITY_TOKENS = {opposing, neutral, supportive}` was the observed set
# recorded as though it were the declared one — from which it followed that `killer` was structurally
# unreachable on (5) and its loss was therefore benign. It was neither: `killer` was in the
# vocabulary the whole time and simply never plumbed in. See `_verdict_polarity`.
#
# ★ IF YOU ARE RE-FREEZING THIS FIXTURE, READ THIS. Runs produced after the veto join emit `killer`
# on (5), so a re-freeze makes exactly two assertions here go red, both deliberately:
#   1. `test_the_graph_polarity_vocabulary_matches_THE_CODE_not_this_corpus` — the observed set gains
#      `killer`. Fix by adding it to EG_POLARITY_OBSERVED_FROZEN. Do NOT touch EG_POLARITY_DECLARED,
#      which is asserted against the producer and is not a record of any corpus.
#   2. `test_a_declared_veto_is_no_longer_flattened_by_current_code` — its bridge assertion (every
#      frozen veto row carries `canon("negative")`) becomes false, because the rows now carry
#      `killer`. That bridge exists only to license reconstructing a pre-fix row's headline band; on a
#      post-fix corpus the reconstruction is unnecessary, so replace it with the direct assertion that
#      all KILLER_SPINE_ROWS rows carry `killer` on BOTH surfaces — which is the stronger check the
#      frozen corpus could not support.
# Neither red means a regression, and neither should be silenced by relaxing a pin. If instead the
# observed set gains a token that is NOT in EG_POLARITY_DECLARED, that IS a real finding: a producer
# is emitting off-vocabulary polarity.
EG_POLARITY_DECLARED = {"opposing", "neutral", "supportive", "killer"}  # evidence_graph (5)
EG_POLARITY_OBSERVED_FROZEN = {"opposing", "neutral", "supportive"}  # what THIS pre-fix fixture holds
SCORECARD_STATUS_TOKENS = {"opposing", "neutral", "supportive", "coverage_gap"}  # (6)
HARD_GATE_STATUS_TOKENS = {"fired", "latent", "suppressed", "reconciled", "excluded", "opposing"}  # (7)
# (8) is owned by target-contracts (`policy_source: vocab`); `uncorroborated` arrives with v1.20.0 and
# is absent from a corpus frozen before it, so this is the DECLARED set, checked as a superset.
DISPOSITION_TOKENS = {"gated", "excluded_modality_scoped", "contradiction", "uncorroborated"}

# ── known violations, pinned exactly (see the contract's "Known violations" section) ─────────────
# `surface_modality` is NO LONGER a violation. `evidence_graph.verdict.id` is surface (2) = the skill's
# OWN call token, not the resolver token, so it is not the same type as `sub_verdicts.<axis>.verdict`
# and the two are not required to be equal. The equality that DOES hold — (2) == `skill_report.call`,
# 683/683 composed and 218/218 per-skill — is a producer property and is asserted against the LIVE
# producers in skills/_skills_common/tests/test_evidence_graph_verdict_call_token.py, NOT here: a frozen
# projection cannot observe a producer change, so this file pins the POPULATION and that one pins the
# BEHAVIOUR. See docs/UNIFIED_OUTPUT_CONTRACT.md § "Type 1" for why the old 619/683 was a confound.
# `VERDICT_FORK_AXIS` is GONE on purpose: the axis is now a key of EXPECTED_CALL_FORKS below, and a
# second constant naming the same axis would be a second source of truth that can drift from the
# declaration it duplicates.
DECLARED_CALL_FORK_ROWS = 35

# ── declared expected forks ───────────────────────────────────────────────────────────────────────
# An axis whose CALL is deliberately not its resolver verdict. Shape borrowed from 47's
# `expected_inert_arms` (target-contracts #752), because that precedent got the important part right:
# a declaration is only load-bearing if a STALE one is an ERROR. The four checks are transcribed below
# as three tests plus one structural guarantee — dangling, misdeclared, stale-is-an-error, duplicate —
# with a mandatory prose reason. 47 uses a 25-character floor precisely to reject "by design", which is
# a restatement, not a reason.
EXPECTED_CALL_FORKS: dict = {
    "surface_modality": (
        "surface-modality-fit declares its call to be the composed adc-tce-modality-fit `fit_class` "
        '(run.py:1154 `_v = hl.get("fit_class")` -> skill_report.call; run.py:258 '
        "`verdict_token=fit_class` -> headline_block.verdict.call), deliberately keeping the resolver's "
        "safety / density / shed DOWNGRADE out of the call and in the top tension instead, so a "
        "one-word favourable call cannot hide it. The two vocabularies intersect only on "
        "`modality_ambiguous`, and their null tokens differ (`insufficient` vs `data_unavailable`)."
    ),
}
EXPECTED_CALL_FORK_REASON_MIN_LEN = 25
NOT_SCORED_AS_SUPPORTIVE_ROWS = 41
# Rows whose AUTHORITATIVE spine declares a veto. Renamed from `KILLER_TO_OPPOSING_ROWS` when the
# collapse was fixed: the population is unchanged (25 rows, `surface_modality` 15 + `selectivity` 10,
# all role `gating`), but the name asserted the OUTCOME, which is no longer the behaviour. A pin whose
# name states a behaviour keeps reading as a decision after that behaviour is retired.
KILLER_SPINE_ROWS = 25


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    assert FIXTURE.is_file(), (
        f"missing projection fixture {FIXTURE} — rebuild with build_polarity_surface_projection.py"
    )
    doc = json.loads(FIXTURE.read_text())
    assert doc["_schema"] == SCHEMA, f"unexpected fixture schema {doc['_schema']!r}"
    return doc["rows"]


def test_corpus_is_big_enough_to_measure_on(rows):
    """Anti-vacuity floor. Every assertion in this file is a count or a rate over this corpus; a
    corpus that shrank to a handful of rows would make most of them pass for free."""
    pairs = {(r["target"], r["indication"]) for r in rows}
    assert len(pairs) >= MIN_PAIRS, f"corpus shrank to {len(pairs)} pairs (floor {MIN_PAIRS})"
    assert len(rows) >= MIN_ROWS, f"corpus shrank to {len(rows)} rows (floor {MIN_ROWS})"
    # Each surface must be ALIVE in the corpus, independently — a projection where one surface came
    # back all-null would silently make its comparisons vacuous rather than failing.
    for key in (
        "sub_verdict",
        "skill_report_polarity",
        "skill_report_role",
        "evidence_graph_verdict_id",
        "evidence_graph_verdict_polarity",
        "scorecard_status",
    ):
        alive = sum(1 for r in rows if r.get(key))
        assert alive > 0, f"surface {key!r} is null on every row — its comparisons below are vacuous"
    assert sum(len(r["hard_gates"]) for r in rows) > 0, "no hard_gate rows — Type 3/4 checks vacuous"


# ── Type 1 — verdict token ───────────────────────────────────────────────────────────────────────


def _forking_rows(rows) -> list[dict]:
    both = [r for r in rows if r["sub_verdict"] and r["evidence_graph_verdict_id"]]
    assert both, "no row carries both verdict surfaces — vacuous"
    return [r for r in both if r["sub_verdict"] != r["evidence_graph_verdict_id"]]


def test_the_call_token_matches_the_resolver_only_where_no_fork_is_declared(rows):
    """`evidence_graph.verdict.id` is surface (2) — the skill's OWN call token. For ten of the eleven
    skills that token IS their resolver verdict, because they pass it straight into
    `build_skill_report(verdict=…)`, so (2) == (1) on their rows. Any axis where it does NOT must be
    DECLARED in `EXPECTED_CALL_FORKS` with a reason.

    ⚠️This is deliberately no longer phrased as "the same type, must be identical". It was, and the
    619/683 that appeared to support it was a CONFOUND: on those ten skills "(2) == (1)" and
    "(2) == skill_report.call" are the same assertion, so their agreement could not distinguish the two.
    An undeclared fork appearing here is still a real finding — a skill's call diverging from its
    resolver verdict is a decision someone must make on purpose — it is just not a type error."""
    differ = _forking_rows(rows)
    offending_axes = {r["axis"] for r in differ}
    undeclared = sorted(offending_axes - set(EXPECTED_CALL_FORKS))
    assert not undeclared, (
        f"axes {undeclared} fork their call from their resolver verdict with NO declaration. Either the "
        f"skill regressed, or the divergence is intended and belongs in EXPECTED_CALL_FORKS with a "
        f"reason — do not silence this by widening a count"
    )


def test_declared_call_forks_carry_a_real_reason(rows):
    """Check 1 of 4 — the reason floor. A declaration with no prose is a waiver wearing a declaration's
    clothes; the length floor is what rejects "by design"."""
    assert isinstance(EXPECTED_CALL_FORKS, dict), (
        "EXPECTED_CALL_FORKS became a non-dict — the DUPLICATE check (check 4 of 4) is discharged by dict "
        "keys being unique, so a list/tuple form needs an explicit duplicate assertion added here"
    )
    assert EXPECTED_CALL_FORKS, "no declared forks — every assertion in this group is vacuous"
    for axis, reason in EXPECTED_CALL_FORKS.items():
        assert isinstance(reason, str) and len(reason.strip()) >= EXPECTED_CALL_FORK_REASON_MIN_LEN, (
            f"declared fork {axis!r} has a reason of {len(str(reason).strip())} chars (floor "
            f"{EXPECTED_CALL_FORK_REASON_MIN_LEN}) — say WHY the call is not the resolver verdict"
        )


def test_declared_call_fork_axes_are_neither_DANGLING_nor_MISDECLARED(rows):
    """Checks 2 and 3 of 4. **Dangling**: a declared axis that does not exist in the corpus at all names
    nothing and would sit here forever reading as coverage. **Misdeclared**: it must be in the population
    the declaration is about — i.e. it must actually carry both surfaces, or the declaration is about
    rows that cannot be compared."""
    axes_in_corpus = {r["axis"] for r in rows}
    comparable_axes = {r["axis"] for r in rows if r["sub_verdict"] and r["evidence_graph_verdict_id"]}
    for axis in EXPECTED_CALL_FORKS:
        assert axis in axes_in_corpus, (
            f"declared fork {axis!r} is DANGLING — no such axis in the corpus, so the declaration is "
            f"unverifiable and silently permanent"
        )
        assert axis in comparable_axes, (
            f"declared fork {axis!r} is MISDECLARED — it carries no row with BOTH verdict surfaces, so "
            f"there is nothing for the declaration to be about"
        )


def test_a_declared_call_fork_that_STOPPED_HAPPENING_is_an_ERROR(rows):
    """Check 4 — the one that makes the mechanism safe to add, and an ERROR rather than a warning. If a
    declared axis stops forking, the reason above now documents the OPPOSITE of the behaviour, and a
    reader who trusts it will believe the call is still not the resolver verdict when it is. This also
    catches the corpus quietly ceasing to cover the case, which otherwise looks exactly like a fix."""
    forking_axes = {r["axis"] for r in _forking_rows(rows)}
    stale = sorted(set(EXPECTED_CALL_FORKS) - forking_axes)
    assert not stale, (
        f"declared fork(s) {stale} no longer occur. Do NOT just delete the declaration: establish which "
        f"happened — the skill's call became its resolver verdict (then remove the entry AND update "
        f"docs/UNIFIED_OUTPUT_CONTRACT.md Known violation 1), or the corpus stopped covering the axis "
        f"(then the projection needs rebuilding, and nothing was fixed)"
    )


def test_declared_call_fork_row_count_is_pinned(rows):
    """The count survives the retyping unchanged. A DECLARED fork still may not spread or grow silently:
    the declaration explains why `surface_modality` diverges, not why it should diverge on more rows."""
    differ = _forking_rows(rows)
    assert len(differ) == DECLARED_CALL_FORK_ROWS, (
        f"declared call-fork row count moved: {len(differ)} != {DECLARED_CALL_FORK_ROWS}. If it GREW the fork "
        f"spread; if it SHRANK either the skill changed its call (update this pin and the contract) or "
        f"the corpus stopped covering it (which would make this check pass for the wrong reason)"
    )
    # And the honest part: on every axis with NO declared fork the equality actually holds, over a real
    # population — which is what makes the declaration above a narrow exception rather than a blanket.
    clean = [
        r for r in rows if r["sub_verdict"] and r["evidence_graph_verdict_id"] and r["axis"] not in EXPECTED_CALL_FORKS
    ]
    assert len(clean) > 100, f"only {len(clean)} non-forked rows — too few to call the equality tested"
    assert all(r["sub_verdict"] == r["evidence_graph_verdict_id"] for r in clean)


# ── Type 2 — polarity ────────────────────────────────────────────────────────────────────────────


def test_polarity_agrees_perfectly_on_the_shared_vocabulary(rows):
    """`skill_report.polarity` is authoritative. `evidence_graph.verdict.polarity` carries 4 of its 5
    tokens (no off-axis `not_scored`). Restricted to rows whose authoritative polarity is in the set
    this FROZEN corpus observed, the two agree perfectly — so any raw-equality "disagreement" count is
    entirely an artefact of the collapses pinned below, not of a value moving.

    Deliberately still filtered on `EG_POLARITY_OBSERVED_FROZEN`, not on the DECLARED set: this corpus
    predates the `killer` plumbing fix, so its 25 veto rows still carry the pre-fix `opposing` and
    would read as 25 value moves here. Their live behaviour is asserted against current code in
    `test_a_declared_veto_is_no_longer_flattened_by_current_code` below, and end-to-end in
    `skills/_skills_common/tests/test_evidence_graph_verdict_polarity.py`."""
    shared = [
        r
        for r in rows
        if r["skill_report_polarity"] in EG_POLARITY_OBSERVED_FROZEN and r["evidence_graph_verdict_polarity"]
    ]
    assert len(shared) > 100, f"only {len(shared)} comparable polarity rows — too few to be meaningful"
    differ = [r for r in shared if r["skill_report_polarity"] != r["evidence_graph_verdict_polarity"]]
    assert not differ, (
        f"{len(differ)} rows disagree on polarity within the SHARED vocabulary (a real value move, not "
        f"a projection loss): {[(r['target'], r['axis'], r['skill_report_polarity'], r['evidence_graph_verdict_polarity']) for r in differ[:5]]}"
    )


def test_the_graph_polarity_vocabulary_matches_THE_CODE_not_this_corpus(rows):
    """The guard that would have prevented the `killer` defect, and the reason it is worth adding after
    the fact: nothing here ever compared the vocabulary this file DECLARES against the one the producer
    declares. `evidence_graph._CANON_POLARITY` has always mapped onto `{supportive, neutral, opposing,
    killer}` (+ off-scale `not_applicable`), while this file asserted a 3-token set — because 3 was
    what the corpus contained. From that mistaken premise it followed that `killer` was unreachable on
    surface (5) and its loss was an unavoidable refinement loss, which is exactly how a plumbing gap
    got documented as a design decision and pinned in CI for the life of the file.

    So: the DECLARED set is checked against the code, and the corpus is allowed to be a subset of it.
    An observation about a corpus may never again be recorded as a property of a field."""
    from _skills_common.evidence_graph import _CANON_POLARITY

    code_scale = set(_CANON_POLARITY.values()) - {"not_applicable"}  # off-scale by construction
    assert code_scale == EG_POLARITY_DECLARED, (
        f"surface (5)'s vocabulary moved in the producer: code={sorted(code_scale)} vs declared here "
        f"{sorted(EG_POLARITY_DECLARED)}. Update this file AND docs/UNIFIED_OUTPUT_CONTRACT.md's "
        f"surface table in the same commit — a token that exists in the map but is reachable from no "
        f"input is the shape of the bug this test was added for"
    )
    observed = {r["evidence_graph_verdict_polarity"] for r in rows if r["evidence_graph_verdict_polarity"]}
    assert observed <= EG_POLARITY_DECLARED, (
        f"the corpus carries graph polarity token(s) the producer cannot emit: "
        f"{sorted(observed - EG_POLARITY_DECLARED)}"
    )
    assert observed == EG_POLARITY_OBSERVED_FROZEN, (
        f"this frozen corpus's observed graph polarity set moved to {sorted(observed)} — if the fixture "
        f"was rebuilt from post-fix runs, `killer` is now expected and BOTH this pin and "
        f"`test_a_declared_veto_is_no_longer_flattened_by_current_code` should be re-derived from it"
    )


def test_a_declared_veto_is_no_longer_flattened_by_current_code(rows):
    """The retired collapse, asserted against CURRENT CODE rather than against the snapshot.

    A frozen corpus cannot observe a producer change — its 25 veto rows will read the pre-fix
    `opposing` forever — so leaving the old assertion in place would have left CI green while
    documenting behaviour that no longer exists. Instead: the fixture supplies the POPULATION (that
    these 25 rows, on 2 real axes, exist at all) and the live helper supplies the BEHAVIOUR.

    The bridge between the two is asserted, not assumed: every frozen row's graph value must be
    exactly the canonicalization of the 3-band `negative` the reconstruction feeds in, which is what
    makes the reconstruction faithful for these rows specifically."""
    from _skills_common.evidence_graph import _canon_polarity, _verdict_polarity

    killer = [r for r in rows if r["skill_report_polarity"] == "killer" and r["evidence_graph_verdict_polarity"]]
    assert killer, "no veto rows in the corpus — this check is vacuous"
    assert len(killer) == KILLER_SPINE_ROWS, (
        f"veto-row population moved: {len(killer)} != {KILLER_SPINE_ROWS}. GROWING means more axes now "
        f"declare vetoes (fine — re-derive the pin); SHRINKING means the corpus stopped covering the "
        f"case, which would make this check vacuous rather than passing"
    )
    # A veto is a GATE call by construction — pin the mechanism, not just the count.
    assert {r["skill_report_role"] for r in killer} == {"gating"}, (
        "a non-gating axis declared a veto — `canonical_polarity_override` is only meaningful for a "
        "role whose verdict can move the recommendation"
    )
    assert {r["axis"] for r in killer} == {"surface_modality", "selectivity"}, (
        f"the veto-declaring axis set moved: {sorted({r['axis'] for r in killer})}"
    )
    # The reconstruction is faithful for these rows: pre-fix, all 25 carried canon('negative').
    assert all(r["evidence_graph_verdict_polarity"] == _canon_polarity("negative") for r in killer), (
        "a frozen veto row does not carry the canonicalized 3-band negative, so reconstructing its "
        "headline band as `negative` below would be unsound — re-derive this check"
    )
    for r in killer:
        got = _verdict_polarity({"skill_report": {"polarity": "killer"}}, {"polarity": "negative"})
        assert got == "killer", (
            f"current code still flattens a declared veto to {got!r} on {r['target']}/{r['axis']} — "
            f"surface (5) is the one `report_render` reads, so a KILL would render as merely negative"
        )


def test_the_off_axis_polarity_collapse_is_named_and_pinned(rows):
    """`not_scored` is off-axis and has no place on the measurement scale, so the graph places the axis
    ON that scale. Unlike the veto collapse this is NOT being fixed — the graph's polarity is a read
    DIRECTION and blanking it would empty the direction badge on hundreds of rows — but the harmful
    direction (an axis that was never scored rendering as the favourable measured class) is pinned so
    it cannot grow."""
    not_scored = [r for r in rows if r["skill_report_polarity"] == "not_scored"]
    assert not_scored, "no `not_scored` rows — the off-axis collapse check is vacuous"
    as_supportive = [r for r in not_scored if r["evidence_graph_verdict_polarity"] == "supportive"]
    assert len(as_supportive) == NOT_SCORED_AS_SUPPORTIVE_ROWS, (
        f"`not_scored` rendering as `supportive` moved: {len(as_supportive)} != "
        f"{NOT_SCORED_AS_SUPPORTIVE_ROWS}. GROWING means an off-axis (role descriptive/inert) axis is "
        f"newly rendering as the favourable MEASURED class on another axis; SHRINKING means it was "
        f"fixed — update this pin and the contract rather than loosening it"
    )
    # `not_scored` is off-axis BY ROLE — pin the mechanism, not just the count, so a role reassignment
    # that changes which axes are off-axis can't keep this count stable by coincidence.
    assert {r["skill_report_role"] for r in not_scored} <= {"descriptive", "inert", None}, (
        "a `gating` axis reported polarity `not_scored` — off-axis is a property of the role taxonomy"
    )


# ── Types 3 + 4 — gate lifecycle and contracts disposition ───────────────────────────────────────


def test_gate_lifecycle_and_disposition_vocabularies(rows):
    """`hard_gates[].status` is a LIFECYCLE, not a polarity; `hard_gates[].disposition` is owned by
    target-contracts and only mirrored here."""
    statuses = {g["status"] for r in rows for g in r["hard_gates"] if g.get("status")}
    dispositions = {g["disposition"] for r in rows for g in r["hard_gates"] if g.get("disposition")}
    assert statuses, "no hard_gate statuses — vacuous"
    assert dispositions, "no hard_gate dispositions — vacuous"
    assert statuses <= HARD_GATE_STATUS_TOKENS, (
        f"unknown gate lifecycle token(s): {sorted(statuses - HARD_GATE_STATUS_TOKENS)}"
    )
    assert dispositions <= DISPOSITION_TOKENS, (
        f"unknown disposition(s) {sorted(dispositions - DISPOSITION_TOKENS)} — disposition is owned by "
        f"target-contracts (`policy_source: vocab`); a new one lands in nomination_verdict_gate.yaml first"
    )
    # Every mirrored row must SAY it is mirrored: an unsourced disposition is a local redefinition.
    sources = {g.get("policy_source") for r in rows for g in r["hard_gates"] if g.get("disposition")}
    assert sources == {"vocab"}, f"hard_gate dispositions not all vocab-sourced: {sorted(sources, key=str)}"


# ── the incommensurable pairs, asserted as such ──────────────────────────────────────────────────


def test_declared_incommensurable_pairs_have_disjoint_vocabularies(rows):
    """These pairs cannot agree or disagree: their token sets are DISJOINT, so a difference between
    them is a category error, not a finding. Asserting the disjointness makes that a checked fact —
    and turns a future token collision (which WOULD make a naive comparison start looking meaningful)
    into a failure here."""
    sub_verdicts = {r["sub_verdict"] for r in rows if r["sub_verdict"]}
    polarities = {r["skill_report_polarity"] for r in rows if r["skill_report_polarity"]}
    statuses = {r["scorecard_status"] for r in rows if r["scorecard_status"]}
    assert len(sub_verdicts) > 20, f"only {len(sub_verdicts)} verdict tokens — disjointness is cheap here"
    assert polarities and statuses

    assert not (sub_verdicts & statuses), (
        f"verdict tokens and scorecard STATUS now share {sorted(sub_verdicts & statuses)} — these are "
        f"different types (open resolver vocabulary vs 4-token polarity); a shared token invites a "
        f"reader to compare them"
    )
    assert not (sub_verdicts & polarities), (
        f"verdict tokens and skill_report POLARITY now share {sorted(sub_verdicts & polarities)}"
    )


def test_partially_overlapping_pairs_are_pinned_exactly(rows):
    """The dangerous case: overlapping-but-unequal vocabularies, where equality is right most of the
    time and silently wrong on the remainder. Pin the shared set AND both remainders, so any token
    moving between them fails here instead of changing what a naive comparison means."""
    polarities = {r["skill_report_polarity"] for r in rows if r["skill_report_polarity"]}
    statuses = {r["scorecard_status"] for r in rows if r["scorecard_status"]}
    assert polarities == POLARITY_TOKENS, f"skill_report polarity vocabulary moved: {sorted(polarities)}"
    assert statuses == SCORECARD_STATUS_TOKENS, f"scorecard status vocabulary moved: {sorted(statuses)}"
    assert polarities & statuses == {"neutral", "supportive", "opposing"}
    assert polarities - statuses == {"killer", "not_scored"}
    assert statuses - polarities == {"coverage_gap"}

    # Lifecycle × polarity share EXACTLY one token, and it means two different things (contract Type 3).
    lifecycle = {g["status"] for r in rows for g in r["hard_gates"] if g.get("status")}
    assert lifecycle & statuses == {"opposing"}, (
        f"gate lifecycle and scorecard status now share {sorted(lifecycle & statuses)} — they shared "
        f"exactly {{'opposing'}}, with different meanings; a second shared token makes the two look joinable"
    )
