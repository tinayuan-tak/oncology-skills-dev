"""The claim tier ladders exist TWICE, and this file is the only thing holding the two copies in step.

`claim_vector_core.SIGNAL_ORD` / `CORROBORATION_ORD` are the RUNTIME ladders — read only relationally
(`weakest()`, `sig_ge`), so they may renumber freely. `archetype_core.CLAIM_SIG_ORD` / `CLAIM_CORR_ORD` are
the ATLAS ENCODER, whose literal values were written into `atlas.json` and may not move without a rebuild.
Two coordinate systems on purpose; two vocabularies by accident is the bug.

★ WHY THIS FILE EXISTS, and why a comment could not do its job.

`archetype_core.py` already carried a comment recording a PRIOR instance of this exact failure (the
"only-moderate" bug, where a single shared map silently nulled `low` and `high`). It was written to prevent
recurrence and it did not: a new corroboration rung was later minted in `claim_vector_core` and the encoder
never learned it. `claim_features` looks the token up with a bare `.get()`, so every cell carrying it became
None — and `Atlas._align_z_impute` maps None to `0.0` in z-space, which IS the corpus mean. An axis demoted
to "only one arm looked" was therefore placed at AVERAGE corroboration, and `n_features_measured` counted it
as unmeasured at the same time: under-confident in its provenance, confidently mis-placed in the geometry.
Fail-open through a plausible value rather than through an error, which is why review did not catch it.

`vocabulary_drift` cannot see this class of defect — it guards keys ABSENT from the frozen `feature_order`,
and here the key is present and its VALUE went null. Nor can a path-overlap scan between branches: the
defect is the ABSENCE of a mirrored edit, and no write-write check can see a write that never happened.

★ WHY THE ASSERTIONS ARE THE SHAPE THEY ARE. Three cheaper formulations were tried and rejected, each for a
measured reason:

  1. NOT value equality. The two maps agree numerically on trunk today, so `==` passes — but the runtime
     ladder renumbers when a rung is inserted (it is free to) while the encoder cannot. Value equality
     would red on a legitimate runtime renumber and drag the atlas re-freeze into that PR.
  2. NOT a strict order comparison. `SIGNAL_ORD` puts `absent` and `negative` at the SAME value on purpose
     (both are measured; they only read differently in prose). Comparing sorted sequences either reds
     spuriously or greens by accident depending on how the tied pair happens to iterate — the version that
     looks correct in review. So the comparison is over rank CLASSES: tied keys must be tied on both sides.
  3. NOT `set(A) - set(B) == set()` alone. That is vacuous-by-emptiness: it passes when the left population
     is empty or has been relocated, which is precisely the refactor that creates a second copy. The
     population is therefore pinned BY KIND (named rungs, each rankable on both sides), not by a count.

The direction of containment is chosen by which way can produce a WRONG ARTIFACT. A runtime rung the encoder
lacks silently mis-encodes real cells; an encoder rung no producer emits is only dead decoration. So runtime
-> encoder is asserted as coverage, and encoder -> runtime only as a documented upper bound that should
shrink over time (equality there would red the moment a producer legitimately catches up).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from _skills_common.archetype_core import (  # noqa: E402
    CLAIM_CORR_ORD,
    CLAIM_SIG_ORD,
    claim_features,
)
from _skills_common.claim_vector_core import CORROBORATION_ORD, SIGNAL_ORD  # noqa: E402

# Vestigial from the shared-map era that caused the only-moderate bug: no producer emits these on the
# corroboration axis and no frozen cell holds their value. They are dead decoration, which is precisely why
# they are the cheapest place for a future author to park a new meaning — see the rank-floor test below.
_VESTIGIAL_CORROBORATION_RUNGS = {"absent", "negative", "none"}

# Encoder keys that no producer emits, tolerated as an UPPER BOUND rather than pinned by equality. This set
# should only ever SHRINK: the vestigial rungs above, plus `single_arm`, which is different in kind — a live
# rung landed forward-compatibly, ahead of the branch that mints its producer. A NEW name appearing here
# means a second copy of a vocabulary has drifted again and must be justified.
_DOCUMENTED_ENCODER_ONLY = _VESTIGIAL_CORROBORATION_RUNGS | {"single_arm"}


def _rankable(ladder: dict) -> set:
    """Keys the ladder can actually ORDER. `unmeasured` is None by design (a gap is not a rung) and is
    excluded — it is the one token that SHOULD reach the imputer."""
    return {k for k, v in ladder.items() if v is not None}


def _rank_classes(ladder: dict, keys) -> tuple:
    """Ascending tuple of tied-key groups — the WEAK ordering, so a deliberate tie compares equal."""
    sub = {k: ladder[k] for k in keys}
    return tuple(frozenset(k for k, v in sub.items() if v == val) for val in sorted(set(sub.values())))


def _shared_rankable(runtime: dict, encoder: dict) -> set:
    return _rankable(runtime) & _rankable(encoder)


# ---- the population is alive (anti-vacuity for every assertion below) ----------------------------
def test_the_ladder_populations_are_alive_by_kind():
    """Every test in this file derives its population from the live dicts, so an emptied or relocated
    ladder would make all of them vacuously green. Pin the rungs BY NAME, never by a count."""
    assert {"low", "moderate", "high"} <= _rankable(CORROBORATION_ORD)
    assert {"weak", "moderate", "strong", "absent", "negative"} <= _rankable(SIGNAL_ORD)
    assert {"low", "moderate", "high"} <= _rankable(CLAIM_CORR_ORD)
    assert {"weak", "moderate", "strong", "absent", "negative"} <= _rankable(CLAIM_SIG_ORD)
    # `unmeasured` must remain the abstention on BOTH sides — if it ever became rankable, the gap/absent
    # distinction the ladders exist to preserve would collapse.
    assert CORROBORATION_ORD.get("unmeasured") is None
    assert SIGNAL_ORD.get("unmeasured") is None
    assert CLAIM_CORR_ORD.get("unmeasured") is None
    assert CLAIM_SIG_ORD.get("unmeasured") is None


# ---- coverage: every rung the runtime can rank must survive the encoder --------------------------
def test_every_rankable_corroboration_rung_is_encodable():
    missing = sorted(_rankable(CORROBORATION_ORD) - set(CLAIM_CORR_ORD))
    assert not missing, (
        f"corroboration rungs the atlas encoder cannot encode: {missing}. These do not abstain — "
        "claim_features() returns None and _align_z_impute maps None to the CORPUS MEAN."
    )
    nulled = sorted(k for k in _rankable(CORROBORATION_ORD) if CLAIM_CORR_ORD.get(k) is None)
    assert not nulled, f"corroboration rungs present in the encoder but mapped to None: {nulled}"


def test_every_rankable_signal_rung_is_encodable():
    missing = sorted(_rankable(SIGNAL_ORD) - set(CLAIM_SIG_ORD))
    assert not missing, f"signal rungs the atlas encoder cannot encode: {missing}"
    nulled = sorted(k for k in _rankable(SIGNAL_ORD) if CLAIM_SIG_ORD.get(k) is None)
    assert not nulled, f"signal rungs present in the encoder but mapped to None: {nulled}"


# ---- the same guard at the BOUNDARY, where the damage actually lands -----------------------------
def test_no_rankable_rung_reaches_the_mean_imputer():
    """The set checks prove the keys exist; this proves nothing rankable comes OUT of the real vectoriser as
    None. Driven through `claim_features` because that is the single function both the offline atlas build
    and the runtime query call — a defect here reaches the frozen artifact."""
    corr = sorted(_rankable(CORROBORATION_ORD))
    sig = sorted(_rankable(SIGNAL_ORD))
    cv = {"probe": {}}
    for i, rung in enumerate(corr):
        cv["probe"][f"CORR_{i}"] = {"signal": "strong", "corroboration": rung}
    for i, rung in enumerate(sig):
        cv["probe"][f"SIG_{i}"] = {"signal": rung, "corroboration": "high"}
    f = claim_features(cv)

    for i, rung in enumerate(corr):
        assert f[f"probe::claim::CORR_{i}::corrob"] is not None, (
            f"corroboration {rung!r} encodes to None and would be mean-imputed to the corpus mean"
        )
    for i, rung in enumerate(sig):
        assert f[f"probe::claim::SIG_{i}::signal"] is not None, f"signal {rung!r} encodes to None"

    # The converse, so the guard cannot be satisfied by making EVERYTHING non-None: a real gap must still
    # abstain rather than be coerced onto the ladder.
    gap = claim_features({"probe": {"G": {"signal": "unmeasured", "corroboration": "unmeasured"}}})
    assert gap["probe::claim::G::signal"] is None
    assert gap["probe::claim::G::corrob"] is None


# ---- order agreement, over the WEAK ordering so deliberate ties survive --------------------------
def test_corroboration_rank_classes_agree_across_the_two_ladders():
    shared = _shared_rankable(CORROBORATION_ORD, CLAIM_CORR_ORD)
    assert _rank_classes(CORROBORATION_ORD, shared) == _rank_classes(CLAIM_CORR_ORD, shared), (
        "the runtime and encoder corroboration ladders disagree on ORDER. Values may differ freely — the "
        "runtime map renumbers, the encoder is frozen into atlas.json — but the ranking may not."
    )


def test_signal_rank_classes_agree_across_the_two_ladders():
    shared = _shared_rankable(SIGNAL_ORD, CLAIM_SIG_ORD)
    assert _rank_classes(SIGNAL_ORD, shared) == _rank_classes(CLAIM_SIG_ORD, shared)


def test_absent_and_negative_are_deliberately_tied_on_both_sides():
    """The tie is itself the invariant. A generic order comparison would let a future split of `negative`
    off `absent` pass while silently moving the geometry, so pin the collapse explicitly."""
    assert SIGNAL_ORD["absent"] == SIGNAL_ORD["negative"]
    assert CLAIM_SIG_ORD["absent"] == CLAIM_SIG_ORD["negative"]
    # Corroboration has no such tie among its rankable rungs — every rung is a distinct rank.
    ranks = [CLAIM_CORR_ORD[k] for k in _rankable(CLAIM_CORR_ORD) if k not in _DOCUMENTED_ENCODER_ONLY]
    assert len(ranks) == len(set(ranks))


def test_vestigial_corroboration_rungs_rank_below_the_live_ladder():
    """The dead rungs are the cheapest place to park a new meaning, so bound them rather than ignore them.

    Because nothing emits `absent`/`negative`/`none` on this axis, their values are unconstrained by the
    frozen artifact — a future author can move one without reding a single existing test. What must hold is
    the DIRECTION: these all mean "nothing corroborated this", and `low` is reserved for arms that looked and
    genuinely disagreed (`_DISAGREEMENT_CORROBORATION == {"low"}` in the discordance ledger). So a vestigial
    rung repurposed for real data must rank at or below `low`; ranking a coverage failure ABOVE a
    contradicted claim inverts the axis. `single_arm` is deliberately exempt and pinned separately — it is
    the one encoder-only rung that describes evidence rather than the absence of it.
    """
    shared = _shared_rankable(CORROBORATION_ORD, CLAIM_CORR_ORD)
    assert "low" in shared, "the two ladders no longer share a `low` rung — the floor this test needs is gone"
    weakest_live = min(CLAIM_CORR_ORD[k] for k in shared)
    # Anti-vacuity: the floor must be the rung we think it is, not whatever survived a renumber.
    assert weakest_live == CLAIM_CORR_ORD["low"]
    for k in sorted(_VESTIGIAL_CORROBORATION_RUNGS):
        v = CLAIM_CORR_ORD.get(k)
        if v is None:
            continue  # abstaining is a stronger form of the same guarantee than ranking low
        assert v <= weakest_live, (
            f"vestigial corroboration rung {k!r} = {v} ranks ABOVE {weakest_live} (`low`). If it was "
            "repurposed to carry real data, it needs a rung of its own and an ordering argument, not a "
            "value borrowed from a dead key."
        )


# ---- the reverse direction, as an upper bound that should shrink ---------------------------------
def test_encoder_only_rungs_stay_within_the_documented_set():
    """Containment, not equality: this set shrinks as producers catch up, and equality would red on that
    legitimate shrink. What it still catches is a NEW unmirrored encoder key."""
    for name, encoder, runtime in (
        ("corroboration", CLAIM_CORR_ORD, CORROBORATION_ORD),
        ("signal", CLAIM_SIG_ORD, SIGNAL_ORD),
    ):
        undocumented = sorted(set(encoder) - set(runtime) - _DOCUMENTED_ENCODER_ONLY)
        assert not undocumented, (
            f"{name} encoder rungs with no runtime counterpart and no entry in _DOCUMENTED_ENCODER_ONLY: "
            f"{undocumented}. Either mirror it into claim_vector_core or document why it is encoder-only."
        )


def test_single_arm_is_ordered_between_low_and_moderate():
    """The one property that must hold regardless of the provisional fraction. `low` is RESERVED for arms
    that genuinely disagreed (the discordance ledger's sharpness predicate is exactly {"low"}), so a lone
    unopposed arm must rank ABOVE it — thin, not contradicted — and below two agreeing arms."""
    assert CLAIM_CORR_ORD["low"] < CLAIM_CORR_ORD["single_arm"] < CLAIM_CORR_ORD["moderate"]
    # Coordinate compatibility with the shipped artifact: the three long-standing rungs keep the exact
    # values atlas.json was frozen with, so the insertion needs no rebuild to be correct.
    assert (CLAIM_CORR_ORD["low"], CLAIM_CORR_ORD["moderate"], CLAIM_CORR_ORD["high"]) == (1.0, 2.0, 3.0)
    # ...and it lands on a coordinate no frozen cell holds, so new encodings stay distinguishable from old.
    assert CLAIM_CORR_ORD["single_arm"] not in (0.0, 1.0, 2.0, 3.0)
