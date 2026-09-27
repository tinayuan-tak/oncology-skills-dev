"""`uncorroborated` is a RELABEL, not a drop — the reader side (nomination_verdict_gate v1.20.0).

Two verdicts moved from `positive_contradictions` to the new `positive_uncorroborated` block:
`dependency/discordant` (CRISPR vs RNAi) and `selectivity/discordant_across_comparators` (two
comparator arms). In both, the axis's own ARMS disagree with each other — nothing was corroborated —
which is NOT the same claim as "the measurement opposes". "The arms disagree" != "the measurement
opposes"; the generalisation of `gap != absent`, one level up.

WHAT MUST NOT CHANGE, AND WHY IT IS THE WHOLE POINT
---------------------------------------------------
Removing a row from `positive_contradictions` RELAXES the `strong` gate — a fail-OPEN. So the
relabelling keeps the strong-BLOCK and moves only the LABEL, on each surface independently:

  * tier            — blocked, on a separate `uncorroborated` flag with identical effect;
  * gate scorecard  — `coverage_gap` instead of `opposing` (we DID look; the arms disagreed);
  * hard_gates[]    — `disposition` follows the vocab (it is mirrored, `policy_source: vocab`) but
                      the LIFECYCLE `status` deliberately HOLDS at `opposing`, because that field is
                      what the cross-evidence integrator's fail-closed ceiling switches on and it
                      ignores tokens it does not know. See `test_hard_gate_lifecycle_holds_at_opposing`.

SOURCE-AGNOSTIC BY CONSTRUCTION. `_load_positive_uncorroborated` reads the vocab when the block is
there and falls back to a hardcoded MIRROR when it is not — the empty set would be the wrong default
here, since it is the fail-open. So every test below asserts the BEHAVIOUR, never the source, and
passes on a pre-v1.20.0 and a v1.20.0 contracts checkout alike. That is also what makes the skills
side safe to land FIRST.

The witness corpus is `fixtures/polarity_surface_projection.json` — 37 target×indication pairs from
live runs, not hand-written inputs.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import pytest
from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parents[1], "tp_run")

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "polarity_surface_projection.json"

# The uncorroborated positive verdicts. Pinned BY VALUE: this is the set the whole file is about, and a
# new member arriving in the vocab must land here (and in the reader's mirror) rather than be discovered.
#   * the two RELABELLED discordant verdicts (dependency CRISPR-vs-RNAi, selectivity two comparator
#     arms) — moved from `positive_contradictions` to `positive_uncorroborated` in vocab v1.20.0;
#   * `selectivity/selective_pending_marrow_coverage` (#796) — born uncorroborated, never a
#     contradiction: a transient marrow-HPA read WITHHOLDS a selective call ("re-run to resolve"), which
#     blocks `strong` on the same coverage-gap footing. It never appears in the offline witness corpus
#     (a transient cannot occur in hermetic replay), so it is dormant across every corpus assertion
#     below and exercised only by the declaration/mirror-lockstep checks.
UNCORROBORATED = {
    ("dependency", "discordant"),
    ("selectivity", "discordant_across_comparators"),
    ("selectivity", "selective_pending_marrow_coverage"),
}

# `tractability_sm/discordant` deliberately STAYS a contradiction — two ligandability methods
# disagreeing IS a statement about the target, not about coverage. It is the control that proves the
# split relabels the named rows and not merely "everything called discordant".
CONTROL_CONTRADICTION = ("tractability_sm", "discordant")

# The residual cross-surface inconsistency this change LEAVES BEHIND, pinned rather than waived.
# `skill_reports.<axis>.polarity` is the AUTHORITATIVE polarity surface, and each emitting skill
# supplies its own 3-band reading of its verdict — which on `dependency` still calls these rows
# `opposing` while the derived scorecard now says `coverage_gap`. Note the two axes already disagree
# with EACH OTHER on the identical situation, which is the argument that the authority is the wrong one
# here: see UNIFIED_OUTPUT_CONTRACT.md for the traced fix site.
RESIDUAL_AUTHORITY_POLARITY = {("dependency", "opposing"): 6, ("selectivity", "neutral"): 1}


@pytest.fixture(scope="module")
def raw_rows() -> list[dict]:
    """The projection rows as emitted — needed for the surfaces the gate helpers do not recompute."""
    assert FIXTURE.is_file(), f"missing {FIXTURE} — rebuild with build_polarity_surface_projection.py"
    return json.loads(FIXTURE.read_text())["rows"]


@pytest.fixture(scope="module")
def corpus() -> dict:
    """{(target, indication): sub_results} in the shape the gate helpers read."""
    assert FIXTURE.is_file(), f"missing {FIXTURE} — rebuild with build_polarity_surface_projection.py"
    out: dict[tuple[str, str], dict] = {}
    for r in json.loads(FIXTURE.read_text())["rows"]:
        if r["sub_verdict"]:
            out.setdefault((r["target"], r["indication"]), {})[r["axis"]] = {
                "verdict": (r["sub_verdict"], r["sub_verdict_driving_rule_id"])
            }
    assert len(out) >= 30, f"corpus shrank to {len(out)} pairs — the counts below stop being meaningful"
    return out


# ── the declaration ──────────────────────────────────────────────────────────────────────────────


def test_the_declaration_is_the_same_set_however_it_is_read():
    """Whichever surface answers, the ANSWER is the same — which is what lets the reader ship before
    or after the vocab. Also the lockstep guard: if the vocab grows a third pair and the mirror does
    not, the two contracts versions would silently block different things."""
    pairs, source = tp._load_positive_uncorroborated()
    assert source in {"vocab", "fallback_pre_1_20", "fallback"}, f"unknown loader source {source!r}"
    assert pairs == UNCORROBORATED, f"loader returned {sorted(pairs)}"
    assert tp._FALLBACK_POSITIVE_UNCORROBORATED == UNCORROBORATED, (
        "the hardcoded mirror has drifted from the declared set. The mirror is what a checkout WITHOUT "
        "the `positive_uncorroborated` block falls back to, so drift makes the gate block different "
        "things depending on which contracts version is readable"
    )


def test_splitting_preserves_the_union_that_blocks_strong():
    """The byte-stability argument in one assertion. The strong-block reads
    `contradictions | uncorroborated`; the split only decides which NAME each member gets, so the
    union — and therefore the tier — cannot move."""
    _pos, contra, _cfg, _src = tp._load_positive_signals()
    opposing, uncorr = tp._split_contradictions(set(contra))
    assert uncorr, "the split produced an empty uncorroborated set — it is a no-op and every test below is vacuous"
    assert uncorr == UNCORROBORATED
    assert not (opposing & uncorr), f"a verdict is in BOTH sets: {sorted(opposing & uncorr)}"
    assert opposing | uncorr == set(contra) | UNCORROBORATED, (
        "the split changed the UNION, not just the labels — the strong-block moved, which is the "
        "fail-open this relabelling exists to avoid"
    )
    assert CONTROL_CONTRADICTION in opposing, (
        f"{CONTROL_CONTRADICTION} was swept into `uncorroborated`. Two ligandability METHODS "
        f"disagreeing is a statement about the target; it stays a contradiction"
    )


def test_reconcilers_never_touch_the_uncorroborated_pairs(corpus):
    """A cross-axis reconciler drops a contradiction on the grounds that a co-present verdict proves
    it was measured on the WRONG BASIS. An axis whose own arms disagree measured nothing to be on the
    wrong basis about — and reconciling one would drop it from the strong-block, i.e. fail open. Today
    both declared reconcilers target `selectivity/selective_but_broadly_normal`; this asserts that
    rather than relying on it."""
    seen = set()
    for sub in corpus.values():
        seen |= tp._reconciled_contradiction_keys(sub)
    assert seen, "no reconciler fired anywhere in the corpus — this check is vacuous"
    assert not (seen & UNCORROBORATED), (
        f"a reconciler drops {sorted(seen & UNCORROBORATED)}, which is an UNCORROBORATED verdict. That "
        f"would remove it from the strong-block: a reconciler's premise does not apply to an axis whose "
        f"own arms disagree"
    )


# ── the tier: blocked, and byte-stable across the relabelling ────────────────────────────────────


def test_tier_is_byte_stable_across_the_relabelling(corpus, monkeypatch):
    """Compute every pair's tier twice: once as shipped (split), once as the PRE-relabel reader saw it
    (the uncorroborated pairs folded back into the contradiction set). Identical everywhere — the
    relabelling cannot promote or demote a target, on either contracts version."""
    shipped = {k: tp._positive_tier(sub)[0] for k, sub in corpus.items()}

    # Patch the DEFINING module, not the re-exporting one. `tp` is `tp_run`, which imports these names
    # from `tp_gates`; `_positive_tier` and `_split_contradictions` resolve them in `tp_gates`' OWN
    # globals, so assigning `tp.<name>` rebinds a name the definer never reads — the real loader stays
    # live and the comparison below degrades to `shipped == shipped`. It DID, silently, until a mutation
    # harness noticed that deleting the strong-block red'd nothing here.
    gates = sys.modules[tp._positive_tier.__module__]
    real_signals = gates._load_positive_signals
    # Pre-relabel reader: nothing is `uncorroborated`, and the pairs live in `contradictions`.
    monkeypatch.setattr(gates, "_load_positive_uncorroborated", lambda *_a, **_k: (set(), "test_pre_relabel"))
    monkeypatch.setattr(
        gates,
        "_load_positive_signals",
        lambda *a, **k: (lambda t: (t[0], set(t[1]) | UNCORROBORATED, t[2], t[3]))(real_signals(*a, **k)),
    )
    # Anti-vacuity SELF-check: prove the substitution reached the code under test before trusting the
    # comparison. With the patch live, the split can no longer name anything `uncorroborated`.
    assert gates._split_contradictions(set(real_signals()[1]) | UNCORROBORATED)[1] == set(), (
        "the pre-relabel patch did not reach `_split_contradictions`, so `before` is computed with the "
        "SHIPPED reader and this test proves nothing"
    )

    before = {k: tp._positive_tier(sub)[0] for k, sub in corpus.items()}

    moved = {k: (before[k], shipped[k]) for k in corpus if before[k] != shipped[k]}
    assert not moved, f"the relabelling MOVED a tier: {moved}"
    assert "strong" in shipped.values(), "no pair reaches `strong` in this corpus — the comparison is weak"


def test_the_strong_block_is_load_bearing_on_a_live_witness(corpus):
    """Anti-vacuity, and the reason the block is kept rather than dropped: at least one real pair is
    exactly one uncorroborated row away from `strong`. Deleting the row (the naive "it's not a
    contradiction, so remove it" fix) PROMOTES it."""
    carriers = {
        k: sub for k, sub in corpus.items() if any((s, r["verdict"][0]) in UNCORROBORATED for s, r in sub.items())
    }
    assert carriers, "no pair in the corpus carries an uncorroborated verdict — every check here is vacuous"

    promoted = []
    for key, sub in carriers.items():
        assert tp._positive_tier(sub)[0] != "strong", f"{key} reached `strong` WITH an uncorroborated axis"
        stripped = {s: r for s, r in sub.items() if (s, r["verdict"][0]) not in UNCORROBORATED}
        if tp._positive_tier(stripped)[0] == "strong":
            promoted.append(key)
    assert promoted, (
        "removing the uncorroborated rows promotes nobody in this corpus, so the strong-block is not "
        "demonstrably load-bearing here. Re-measure before weakening it"
    )


# ── the labels: one per surface, each moving only as far as its own readers allow ─────────────────


def test_scorecard_says_coverage_gap_not_opposing(corpus):
    """`coverage_gap` is the honest chip: we DID look, and the axis's arms disagreed, so there is no
    corroborated measurement — but there is no opposing one either. The control row must still read
    `opposing`, or this would just be relabelling everything."""
    seen, control = 0, 0
    for key, sub in corpus.items():
        rows = {r["short"]: r for r in tp._gate_scorecard(sub)}
        for short, r in sub.items():
            if (short, r["verdict"][0]) in UNCORROBORATED:
                assert rows[short]["status"] == "coverage_gap", (
                    f"{key} {short}={r['verdict'][0]} reads {rows[short]['status']!r}; an axis whose own "
                    f"arms disagree is a coverage gap, not opposing evidence"
                )
                seen += 1
            if (short, r["verdict"][0]) == CONTROL_CONTRADICTION:
                assert rows[short]["status"] == "opposing", f"{key} control row reads {rows[short]['status']!r}"
                control += 1
    assert seen >= 5, f"only {seen} uncorroborated scorecard rows in the corpus"
    assert control >= 5, f"only {control} control rows — the 'not everything got relabelled' half is weak"


def test_hard_gate_lifecycle_holds_at_opposing(corpus):
    """THE FAIL-OPEN GUARD, one surface further out.

    `hard_gates[].disposition` is mirrored from the vocab and moves with it. `hard_gates[].status` is
    a LIFECYCLE token, and it is the ONLY field of this block that the cross-evidence integrator's
    fail-closed ceiling switches on (`hypothesis_core._gate_ceiling`, which handles exactly
    {fired, blind, opposing, excluded} and ignores everything else). So a matched uncorroborated row
    dropping to `latent` — or being given a new `uncorroborated` status token — would fall through
    that switch with NO signal and silently remove the `advanceable_with_caveat` clamp. The lifecycle
    split lands WITH the integrator change; until then this token holds."""
    matched = 0
    for key, sub in corpus.items():
        rows = {(g["short"], g["verdict"]): g for g in tp._hard_gates_status(sub, [], [])}
        for short, verdict in UNCORROBORATED:
            g = rows.get((short, verdict))
            if g is None or g["live_verdict"] != verdict:
                continue  # declared but dormant this run — `latent` is correct there
            assert g["status"] == "opposing", (
                f"{key} {short}/{verdict} matched live but reads status {g['status']!r}. The downstream "
                f"fail-closed ceiling switches on `status` alone and ignores unknown tokens, so anything "
                f"other than `opposing` here silently drops its clamp"
            )
            matched += 1
    assert matched >= 5, f"only {matched} matched uncorroborated hard_gate rows — the guard is weak"


def test_the_authoritative_polarity_has_not_caught_up_and_that_is_pinned(raw_rows):
    """WHAT THIS CHANGE DOES NOT FIX, stated as an assertion so it cannot drift.

    The scorecard is a DERIVED polarity surface; `skill_reports.<axis>.polarity` is the authoritative
    one. Relabelling only the derived surface leaves 6 `dependency` rows reading
    `scorecard=coverage_gap` + `authority=opposing` — the derived surface is now the more accurate of
    the two, which inverts the declared authority on exactly those rows.

    Two reasons that is the right trade here rather than a half-measure:

      * the authority is already inconsistent WITH ITSELF on the identical situation — the same "the
        axis's own arms disagree" verdict reads `opposing` on `dependency` and `neutral` on
        `selectivity`. This change makes the derived surface consistent across both axes; it does not
        create the authority's disagreement, it exposes it.
      * the fix is outside this branch's scope, and the correct value is `neutral` — an EXISTING
        polarity token, so no reader switching on polarity can fail open on it. (Contrast the hard_gate
        lifecycle, where minting a new token WOULD fail open; see
        `test_hard_gate_lifecycle_holds_at_opposing`.)

    WHERE the fix goes is traced in UNIFIED_OUTPUT_CONTRACT.md, and it is NOT
    `_skills_common/skill_report.canonical_polarity` — that helper is correct. The defect is that
    `discordant` is a member of `functional-requirement`'s `_DEP_NEG`, a set read by THREE consumers
    with three different meanings (magnitude / evidence-state / polarity), so only the polarity reader
    may move. Do not "fix" this by dropping the token from the set.

    Ratchets both ways: if the authoritative polarity learns the distinction, this test reds and the
    declaration must be updated in the same PR — it may not be silently satisfied.
    """
    carriers = [r for r in raw_rows if (r["axis"], r["sub_verdict"]) in UNCORROBORATED]
    assert len(carriers) == sum(RESIDUAL_AUTHORITY_POLARITY.values()), (
        f"the corpus carries {len(carriers)} uncorroborated rows, not "
        f"{sum(RESIDUAL_AUTHORITY_POLARITY.values())} — the pin below stops describing the population"
    )
    got = Counter((r["axis"], r["skill_report_polarity"]) for r in carriers)
    assert dict(got) == RESIDUAL_AUTHORITY_POLARITY, (
        f"the authoritative polarity on uncorroborated rows moved: {dict(got)} != "
        f"{RESIDUAL_AUTHORITY_POLARITY}. If `canonical_polarity` now reports `neutral`, this is the "
        f"intended fix — update the declaration here AND in UNIFIED_OUTPUT_CONTRACT.md. If it moved "
        f"some other way, the authoritative polarity surface changed meaning underneath this axis"
    )


def test_the_lifecycle_vocabulary_did_not_grow(corpus):
    """Companion to the above, stated as a vocabulary fact so it is legible from the contract side:
    the relabelling adds a DISPOSITION token, not a LIFECYCLE one."""
    lifecycle = {g["status"] for sub in corpus.values() for g in tp._hard_gates_status(sub, [], [])}
    assert lifecycle, "no hard_gate rows — vacuous"
    assert lifecycle <= {"fired", "suppressed", "excluded", "opposing", "reconciled", "blind", "latent"}, (
        f"a new hard_gate LIFECYCLE token appeared: {sorted(lifecycle - {'fired', 'suppressed', 'excluded', 'opposing', 'reconciled', 'blind', 'latent'})}. "
        f"Adding one requires updating every consumer that switches on `status` — including "
        f"cross-evidence-hypothesis's fail-closed ceiling, which ignores tokens it does not know"
    )
