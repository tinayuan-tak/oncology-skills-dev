"""The claim tier ladders are copied and PROJECTED across the fleet; this file holds every copy in step.

`claim_vector_core.SIGNAL_ORD` / `CORROBORATION_ORD` are the RUNTIME ladders — read only relationally
(`weakest()`, `sig_ge`), so they may renumber freely. `archetype_core.CLAIM_SIG_ORD` / `CLAIM_CORR_ORD` are
the ATLAS ENCODER, whose literal values were written into `atlas.json` and may not move without a rebuild.
Two coordinate systems on purpose; two vocabularies by accident is the bug.

★ AND THE CORROBORATION AXIS IS PROJECTED A THIRD WAY, which the first version of this file missed.

Three more maps take a corroboration token and return something else entirely — a confidence tier, a dot
count. They are consumers of this vocabulary just as much as the encoder is, and they were missed because
the sweep that found the encoder searched for maps whose VALUES are numbers (`"(high|moderate|low)":\\s*[0-9]`).
`_CORR_TO_CONF` maps to STRINGS. The predicate had quietly encoded "ordinal implies numeric" — a property of
the map that happened to be under repair, not of the defect. A consumer that maps to a string is still a
consumer. The population here is therefore derived from the PRECONDITION instead: who reads a
`corroboration` field at all (`_corroboration_reader_modules`), classified one module at a time.

Keying on the maps' own key names would be both noisier and wrong: `surface_claims._DENSITY_SIGNAL` is keyed
`high`/`moderate`/`low`/`unmeasured` too, but it reads `surface_density_class` — a different axis wearing the
same words. Conversely `presence_cardboard_figure._RELDOT` looks like a corroboration map and is not: its
input is minted locally from a q-value ternary, so no new rung can ever reach it. The discriminator is the
CALL SITE, never the key names.

★ THE PROJECTIONS FAIL IN THE OPPOSITE DIRECTION FROM THE ENCODER, so the two need different assertions.
The encoder fails OPEN: an unknown rung encodes to None and `_align_z_impute` sends it to the corpus mean,
which IS `moderate` — the value the new rung exists to remove. The projections fail CLOSED: an unknown rung
takes a `.get()` fallback that is the vocabulary's abstention (`insufficient`, or zero dots), so a MEASURED
claim reports as UNMEASURED. `headline_core` makes that self-contradictory — the confidence level collapses
to `insufficient` while the sibling `basis` string still reads "weakest-link corroboration = <the rung>".
Over-read and under-read both violate gap != absent; closed is the safer default, so it is pinned too
(`test_live_projections_abstain_on_an_unknown_rung_rather_than_guessing`) — the tempting repair for a
collapse is to make the fallback a plausible middle value, which silently converts it into the encoder bug.

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

import ast
import subprocess
import sys
from pathlib import Path

_SKILLS_ROOT = Path(__file__).resolve().parents[2]
_REPO_ROOT = _SKILLS_ROOT.parent
sys.path.insert(0, str(_SKILLS_ROOT))

# Directory prefixes holding FIRST-PARTY python. The reader sweep below is rooted at the REPO, not at
# `skills/`: a guard whose name claims "the set of corroboration readers" must not silently mean "readers
# under one subtree". `eval/` is a SIBLING of `skills/`, so a walk rooted at `skills/` could never reach
# `eval/build_discordance_ledger.py` however the AST predicate were written — the population was narrowed
# by the ROOT, one level above every filter. Asserted as a floor by
# `test_the_reader_population_covers_every_first_party_source_dir`, so the next reorg reds rather than
# re-narrowing in silence.
_FIRST_PARTY_SOURCE_DIRS = ("skills/", "eval/", "batch/")

from _skills_common import figure_palette, headline_core, question_table_core  # noqa: E402
from _skills_common.archetype_core import (  # noqa: E402
    CLAIM_CORR_ORD,
    CLAIM_SIG_ORD,
    claim_features,
)
from _skills_common.claim_vector_core import CORROBORATION_ORD, SIGNAL_ORD  # noqa: E402

# Vestigial from the shared-map era that caused the only-moderate bug: no producer emits these on the
# corroboration axis and no frozen cell holds their value. They are dead decoration, which is precisely why
# they are the cheapest place for a future author to park a new meaning — see the rank-floor test below.
# JUSTIFIED ADDITION (2026-09-21, `underpowered` tier): `underpowered` differs in KIND from the three above
# — it IS a deliberate `CORROBORATION_ORD` key (None, off-scale), carried there for signal/corroboration
# symmetry with SIGNAL_ORD. But like them, NO corroboration producer emits it: a gap-with-intent on the
# corroboration axis collapses to `unmeasured` (the `_cn_corroboration`/`_fus_corroboration` off-scale
# guards return `"unmeasured"`, never `"underpowered"`), so it is not a LIVE projection rung and must be
# excluded from the per-projection coverage requirement below. If a producer ever mints it, it needs a rung
# of its own and an ordering argument, exactly as this note demands of the others.
_VESTIGIAL_CORROBORATION_RUNGS = {"absent", "negative", "none", "underpowered"}

# Encoder keys that no producer emits, tolerated as an UPPER BOUND rather than pinned by equality. This set
# should only ever SHRINK — and it just did. `single_arm` was listed here because the encoder rung landed
# forward-compatibly, AHEAD of the branch that mints its producer; this IS that branch
# (`claim_vector_core.corroboration_from_arms` returns it below `CORROBORATION_ARM_FLOOR`), so the rung is
# mirrored on both ladders now and the tolerance is spent.
#
# WHAT SPENDING IT ACTUALLY BUYS, stated as measured rather than as argued — the first version of this note
# claimed more and was wrong. Listing a key here removes it from the rank-distinctness population in
# `test_absent_and_negative_are_deliberately_tied_on_both_sides`. For `single_arm`'s OWN value that exclusion
# costs nothing today: `test_single_arm_is_ordered_between_low_and_moderate` already pins it strictly between
# `low` and `moderate` AND off every integer, so it cannot tie with anything on the current ladder, and a
# mutant moving it to 1.0 reds two other tests whether or not it is listed here. The exclusion bites on the
# rung AFTER this one. A newly minted rung tying to 1.5 — mirrored consistently on both ladders so rank
# CLASSES still agree, and mapped into all three projections so the coverage guard is satisfied — passes
# EVERY assertion in this file while `single_arm` is exempt, and is caught by distinctness alone once it is
# not. That is the two-cell result: with the exemption removed the tie reds exactly one test, and with it
# present the whole file is green.
#
# So the hazard is not "a redundant re-check"; it is the NARROWED POPULATION. An exemption granted for
# ABSENCE keeps narrowing the set it was carved out of long after the absence ends, and nothing reds at the
# moment the justification expires — the guard simply covers one rung less than its name implies. A NEW name
# appearing here means a second copy of a vocabulary has drifted again and must be justified.
#
# `set(...)` rather than a bare alias on purpose: `_DOCUMENTED_ENCODER_ONLY = _VESTIGIAL_CORROBORATION_RUNGS`
# would bind the SAME object under two names, so a future `.add()` on either would silently move the other.
_DOCUMENTED_ENCODER_ONLY = set(_VESTIGIAL_CORROBORATION_RUNGS)


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
    contradicted claim inverts the axis. `single_arm` is not in this set at all — it describes EVIDENCE
    rather than the absence of it, it now has a producer on both ladders, and it is pinned by
    `test_single_arm_is_ordered_between_low_and_moderate` instead.
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


# ══ the NON-NUMERIC projections of the same axis ═══════════════════════════════════════════════════
# Each entry: (label, the map, its DECLARED `.get()` fallback, a rank fn over its OWN value vocabulary,
# the modules that call `.get()` on it, why it matters). The rank fn exists because two of the three
# return dot COUNTS and one returns confidence TIER NAMES — the thing being asserted is the same in both
# cases, which is the point. The declared fallback is cross-checked against the call sites below rather
# than trusted: a literal copied into a test is a comment, and a comment is not a mirror.
_LIVE_CORROBORATION_PROJECTIONS = (
    (
        "headline_core._CORR_TO_CONF",
        headline_core._CORR_TO_CONF,
        "insufficient",
        lambda v: headline_core.CONFIDENCE_ORD[v],
        ("_skills_common/headline_core.py",),
        "weakest-link corroboration -> headline confidence.level. DECISION-FACING, and the only one of "
        "the three that is: read as `.get(weakest_corr, 'insufficient')`, while the sibling `basis` "
        "string on the next line still names the measured tier — so the report contradicts itself",
    ),
    (
        "question_table_core.CONF_DOTS",
        question_table_core.CONF_DOTS,
        0,
        lambda v: v,
        ("_skills_common/question_table_core.py",),
        "corroboration -> confidence dots in every per-question table, via `conf()` — reached from "
        "cv_axis_row (the shared builder for 7 descriptive skills) plus 11 explicit `conf(corr, ...)` "
        "call sites in the presence/selectivity/dependency/differentiation tables. Verdict-inert by its "
        "own docstring, but zero dots is indistinguishable from `unmeasured` while the cell's label "
        "prints the rung's name",
    ),
    (
        "figure_palette.REL_DOTS",
        figure_palette.REL_DOTS,
        0,
        lambda v: v,
        ("_skills_common/headline_hero.py", "_skills_common/presence_claims_figure.py"),
        "corroboration -> relation-dot count in the hero and presence-claims figures, both "
        "`.get(<claim>['corroboration'], 0)`. Defined in figure_palette but never called there",
    ),
)


def _fallbacks_at_call_sites(label: str, call_sites) -> dict:
    """`{"<module>:<line>": <literal default>}` for every `<map>.get(x, DEFAULT)` in `call_sites`.

    Two deliberate choices, both of which are the discrimination this whole section exists to teach:

      * Matched by name SUFFIX, because both figure_palette consumers import `REL_DOTS as _REL_DOTS`.
        An exact-name match finds nothing and greens by emptiness.
      * Scoped to the DECLARED call-site modules, not swept fleet-wide, because `evidence_graph._CONF_DOTS`
        also ends in `CONF_DOTS` and is a DIFFERENT AXIS — its level comes from a ternary on
        `evidence_state`, never from a corroboration token. Same words, different axis; the call site is
        the discriminator, and a fleet-wide suffix sweep would silently annex it.

    NOTE ON PATHS — this file carries two conventions on purpose, because they are two populations.
    `_LIVE_CORROBORATION_PROJECTIONS` call sites are `skills/`-relative and resolve against `_SKILLS_ROOT`
    (below): a projection is a python-importable map, so its call sites are necessarily inside `skills/`.
    `_CORROBORATION_READERS` keys are REPO-relative, because that population is deliberately wider than
    `skills/` — the point of the sweep root being the repo. A call site written repo-relative by analogy
    fails LOUD here (`FileNotFoundError` on `skills/skills/...`), which is why the two can coexist.
    """
    base = label.rsplit(".", 1)[-1]
    seen = {}
    for rel in call_sites:
        tree = ast.parse((_SKILLS_ROOT / rel).read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id.endswith(base)
                and len(node.args) == 2
                and isinstance(node.args[1], ast.Constant)
            ):
                seen[f"{rel}:{node.lineno}"] = node.args[1].value
    return seen


# Every non-test module that READS a `corroboration` field, with why it is safe. The population is
# derived by AST sweep below, so a NEW reader reds `test_the_set_of_corroboration_readers_is_classified`
# and forces this triage. Keyed by REPO-relative path with NO line numbers, so an unrelated edit elsewhere
# in the module cannot red this file. (Keys were relative to `skills/` until the sweep root moved to the
# repo; `eval/` readers have no spelling under the old root, which is the defect that forced the move.)
_CORROBORATION_READERS = {
    # --- the numeric encoder, covered by the assertions above -------------------------------------
    "skills/_skills_common/archetype_core.py": "ENCODER (CLAIM_CORR_ORD)",
    # --- the projections asserted in _LIVE_CORROBORATION_PROJECTIONS -------------------------------
    "skills/_skills_common/headline_core.py": "PROJECTION _CORR_TO_CONF; also echoes the token verbatim into the axis list",
    "skills/_skills_common/question_table_core.py": "PROJECTION CONF_DOTS via conf()",
    "skills/_skills_common/headline_hero.py": "PROJECTION figure_palette.REL_DOTS; also renders the token as prose",
    "skills/_skills_common/presence_claims_figure.py": "PROJECTION figure_palette.REL_DOTS; also renders it as prose",
    # --- delegate to question_table_core.conf, so covered by CONF_DOTS above -----------------------
    "skills/_skills_common/dependency_question_table.py": "DELEGATES to question_table_core.conf",
    "skills/_skills_common/differentiation_question_table.py": "DELEGATES to question_table_core.conf",
    "skills/_skills_common/presence_question_table.py": (
        "DELEGATES row confidence to question_table_core.conf; also PASS-THROUGH — copies the L2b "
        "coverage / abundance / subtype_restriction concordance claims' `corroboration` token VERBATIM "
        "into each family's `integrated_signal` annotation (no map, nothing to keep in step; an "
        "unrecognised rung reads as itself — honest). This is the G3.1 coverage annotation the "
        "safety/selectivity/genomic question_table entries reference as the mirror of their own L2b "
        "surface pass-through (SK#1856)."
    ),
    "skills/_skills_common/safety_question_table.py": (
        "DELEGATES row confidence to question_table_core.conf; also PASS-THROUGH — copies the L2b-3 "
        "claim's `corroboration` token VERBATIM into the Normal-tissue row's integrated_signal annotation "
        "(no map, nothing to keep in step). Mirrors presence_question_table's G3.1 coverage annotation."
    ),
    "skills/_skills_common/selectivity_question_table.py": (
        "DELEGATES row confidence to question_table_core.conf; also PASS-THROUGH — copies the L2b-5 "
        "selectivity_concordance claim's `corroboration` token VERBATIM into the Q1 (tumor-vs-normal / "
        "axis-A window) row's integrated_signal annotation (SK#1803; no map, nothing to keep in step). "
        "Mirrors genomic/safety question_table's L2b surface annotation."
    ),
    "skills/_skills_common/genomic_question_table.py": (
        "DELEGATES row confidence to question_table_core.conf; also PASS-THROUGH — copies the L2b-5 "
        "recurrence_concordance claim's `corroboration` token VERBATIM into the SNV row's integrated_signal "
        "annotation (SK#1750; no map, nothing to keep in step). Mirrors safety/presence question_table's "
        "L2b surface annotation."
    ),
    # --- PASS-THROUGH: renders or copies the token verbatim. An unrecognised rung reads as ITSELF,
    #     which is honest — no map, so nothing to keep in step. This is the safe way to consume the axis.
    "skills/_skills_common/narrative_grounding.py": (
        "PASS-THROUGH — INV-6 grounding guard reads the cited claims' `corroboration` tokens only to "
        "rank them via `_ord(CORROBORATION_ORD, ...)` for a non-exceedance comparison against the "
        "narrative's asserted `strength`. No map, no projection: an unrecognised rung reads off-scale "
        "(_ord -> None) as itself, which is honest. VERDICT-INERT (reads only)."
    ),
    "skills/_skills_common/literature_synthesis.py": "PASS-THROUGH (prose line)",
    "skills/_skills_common/report_render/backends/text.py": "PASS-THROUGH (prose line)",
    "skills/_skills_common/signals_first.py": "PASS-THROUGH (prose line)",
    "skills/_skills_common/skill_report.py": "PASS-THROUGH (copied verbatim into the report atom)",
    "skills/_skills_common/subgroup_derivation.py": "PASS-THROUGH (copied verbatim into the per-stratum atom)",
    "skills/_skills_common/evidence_frame.py": (
        "PASS-THROUGH — the L3 typed-evidence frame (design G) reads a consumed canonical-property "
        "claim's `corroboration` tier only to gauge decision confidence (a weak tier adds a reservation "
        "that down-ranks the frame's OWN decision). No map, no projection: an unrecognised rung is not a "
        "member of _WEAK_CORROBORATION and reads as itself. ADDITIVE / verdict-INERT to every existing "
        "skill (routes nothing back into any claim_vector / question_table / resolver). The single "
        "`from_concordance` adapter feeds EVERY production frame (dependency / presence / "
        "presence_priority_frame / per-modality), so minting a new frame adds NO new corroboration reader "
        "here (SK#1856)."
    ),
    "skills/cross-evidence-hypothesis/scripts/run.py": "PASS-THROUGH (prose; the gate reads `signal`, not this)",
    "skills/example-gallery/scripts/generate_example_gallery.py": "PASS-THROUGH (gallery prose)",
    "skills/target-profile/scripts/tp_synthesis_prompt.py": "PASS-THROUGH (prompt prose)",
    "skills/tumor-presence/scripts/run.py": "PASS-THROUGH (copied verbatim under a `certainty` key)",
    "skills/tumor-presence/scripts/presence_l3d_story.py": (
        "PASS-THROUGH — the L3d within-domain tumor-expression biology story (SK#1940) copies each "
        "traversed L2b island's `corroboration` token VERBATIM into that chapter (no map, no projection; "
        "an unrecognised rung reads as itself — honest). VERDICT-INERT: a pure deterministic traversal "
        "that reads the already-computed L2 claims and routes nothing back into any claim_vector / "
        "question_table / resolver."
    ),
    # --- OUTSIDE `skills/`, and invisible to every guard on this axis until the sweep root moved. The
    #     eval harness carries its OWN vocabulary — 8 literal token sets, and it imports no canonical
    #     ladder — so nothing here is kept in step by construction. Both entries are MEMBERSHIP TESTS
    #     against a literal set, which is the one shape that neither reds nor renders honestly: an
    #     unrecognised rung silently fails the test and takes the `else` branch.
    "eval/build_discordance_ledger.py": (
        "MEMBERSHIP `_DISAGREEMENT_CORROBORATION == {'low'}`, PROSE-ONLY reach — it appends a routing "
        "clause; the GAP_CALIBRATION/GAP_VERDICT_RULE decision is made by `in_calibration`, not by this. "
        "`low` is reserved for arms that genuinely DISAGREED, so a rung meaning `one arm, unopposed` is "
        "correctly a non-member — see the comment at archetype_core.py's CLAIM_CORR_ORD, which names this "
        "very set as the reason `low < single_arm`. NOT a projection: no map, no key coverage to keep."
    ),
    "eval/run_known_target_panel.py": "PASS-THROUGH (copied verbatim into the panel row)",
}


def _tracked_python_files() -> list:
    """Repo-relative paths of every TRACKED `.py` file, newline-safe, in git's order.

    The population comes from git rather than from a filesystem walk, and that is load-bearing three
    times over. Each of these was measured on this repo, and each fires BEFORE a walk could reach the
    AST predicate, so none of them would present as a coverage gap:

    * SCOPE — 677 `.py` files are tracked; 14,262 exist on disk. A walk rooted at the repo descends into
      the vendored `.pixi/` environment: ~21x the work, and it admits third-party modules into a
      population whose entire purpose is to make a FIRST-PARTY author triage a new reader.
    * DECODABILITY — zero TRACKED files fail to decode as UTF-8; vendored ones do. `read_text()` then
      raises `UnicodeDecodeError`, which is not a `SyntaxError` and so escapes the guard below.
    * REPRODUCIBILITY — the vendored tree holds symlinks into OTHER worktrees under `/tmp/wt/`, which
      parallel sessions create and delete. A walk raises `FileNotFoundError` on a dangling one, making
      this guard's verdict depend on whether a peer session had cleaned up its worktree. That is the
      worst property a test on a shared checkout can have, and it is silent.

    Not wrapped in a try: if git cannot answer, the population is unknown, and an unknown population
    must not be silently spelled as an empty one — see the anti-vacuity floor in the tests below.
    """
    out = subprocess.run(
        ["git", "-C", str(_REPO_ROOT), "ls-files", "-z", "*.py"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [p for p in out.split("\0") if p]


def _corroboration_reader_modules() -> set:
    """REPO-relative paths of every non-test module that reads a `corroboration` field.

    The PRECONDITION for this defect class is receiving a corroboration token — a map is only dangerous
    if something feeds it one — so that is what the sweep looks for, via AST rather than text so a
    mention in a comment or a docstring cannot enter the population.
    """
    found = set()
    for rel in _tracked_python_files():
        if "__pycache__" in rel or "/tests/" in rel:
            continue
        path = _REPO_ROOT / rel
        try:
            tree = ast.parse(path.read_text())
        except (SyntaxError, UnicodeDecodeError, OSError):  # pragma: no cover - not this file's business
            continue
        for node in ast.walk(tree):
            reads = (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "corroboration"
            ) or (
                isinstance(node, ast.Subscript)
                and isinstance(node.slice, ast.Constant)
                and node.slice.value == "corroboration"
            )
            if reads:
                found.add(rel)
                break
    return found


def test_every_corroboration_rung_survives_every_live_projection():
    """The string-valued twin of `test_every_rankable_corroboration_rung_is_encodable`.

    Inert on trunk by construction — `CORROBORATION_ORD` is exactly high/moderate/low/unmeasured today
    and all three maps carry all four keys — and it bites the moment a producer mints a rung, which is
    the same argument that licensed landing the encoder fix ahead of its producer.
    """
    required = set(CORROBORATION_ORD) - _VESTIGIAL_CORROBORATION_RUNGS
    # Anti-vacuity BY NAME: an emptied or relocated runtime ladder must not silence this.
    assert {"high", "moderate", "low", "unmeasured"} <= required
    assert _LIVE_CORROBORATION_PROJECTIONS, "the projection registry is empty"
    # Accumulated rather than asserted per projection: minting a rung leaves ALL THREE maps behind at
    # once, and a fail-fast assert would name one, get fixed, and red again twice — three round trips for
    # one change, each looking like a new and separate problem.
    gaps = []
    for label, mapping, _fallback, _rank, _sites, why in _LIVE_CORROBORATION_PROJECTIONS:
        assert mapping, f"{label} is empty — the projection was relocated, not covered"
        missing = sorted(required - set(mapping))
        if missing:
            gaps.append(f"  - {label}: no entry for {missing}\n      {why}")
    assert not gaps, (
        "corroboration rung(s) reach a projection that cannot render them, so each takes the map's "
        "`.get()` fallback and reads as an ABSTENTION — a MEASURED claim reported as unmeasured. Every "
        "one of these must be mapped in the SAME change that mints the rung:\n" + "\n".join(gaps)
    )


def test_each_projection_has_a_live_call_site_matching_its_declared_fallback():
    """The registry above is only as good as its correspondence to the code.

    Without this, the fallback column is a literal transcribed by hand — someone widening
    `CONF_DOTS.get(tier, 0)` to `.get(tier, 2)` would leave the fail-direction test below asserting
    against a value the code no longer uses, and it would stay green while the behaviour inverted.
    """
    for label, _mapping, declared, _rank, sites, _why in _LIVE_CORROBORATION_PROJECTIONS:
        observed = _fallbacks_at_call_sites(label, sites)
        assert observed, (
            f"{label} is declared live at {list(sites)} but no `.get(x, DEFAULT)` call was found there. "
            "The projection moved, or its consumers now index it directly — in which case an unknown "
            "rung raises rather than abstaining, and the fail direction changed."
        )
        drifted = {site: got for site, got in observed.items() if got != declared}
        assert not drifted, (
            f"{label}'s declared fallback {declared!r} no longer matches its call site(s): {drifted}. "
            "Update the registry AND re-check the fail-direction argument — that literal is the entire "
            "behaviour for any rung the map does not carry."
        )


def test_live_projections_abstain_on_an_unknown_rung_rather_than_guessing():
    """Pin the fail DIRECTION, not just the coverage.

    Failing closed is what these maps do today and it is the safer default. It is asserted because the
    tempting repair for the collapse above is to give the fallback a plausible MIDDLE value — which
    converts an under-read into an over-read and reproduces the encoder's mean-imputation bug in a
    place where nothing would flag it. Driven off the defaults READ FROM THE CALL SITES, so the check
    survives the registry going stale.
    """
    for label, mapping, _declared, rank, sites, _why in _LIVE_CORROBORATION_PROJECTIONS:
        floor = min(rank(v) for v in mapping.values())
        for site, fallback in _fallbacks_at_call_sites(label, sites).items():
            # Checked BEFORE ranking: `rank` is a bare subscript for the string projection, so an
            # off-vocabulary fallback would raise here instead of reporting — the same bare-subscript
            # hazard the confidence-ladder test below asserts about production code.
            assert fallback in set(mapping.values()), (
                f"{site}: {label}'s fallback {fallback!r} is not a value the map itself ever produces, "
                "so 'abstain' is not even expressible in the vocabulary the consumer renders"
            )
            assert rank(fallback) == floor, (
                f"{site}: {label}'s unknown-rung fallback {fallback!r} does not sit at its own vocabulary "
                f"floor ({floor}). A fallback above the floor makes an unrecognised rung read as a "
                "measured, plausible tier — silent, and in the confident direction."
            )


def test_the_confidence_projection_lands_on_the_confidence_ladder():
    """`headline_core` does `CONFIDENCE_ORD[_CORR_TO_CONF.get(...)]` — a bare subscript, not a `.get()`.
    So a projection value outside the confidence vocabulary is a KeyError at report time, not a
    mis-read. Cheap to assert and it constrains what a new rung's mapping may say."""
    off_ladder = sorted(set(headline_core._CORR_TO_CONF.values()) - set(headline_core.CONFIDENCE_ORD))
    assert not off_ladder, (
        f"_CORR_TO_CONF maps a rung onto {off_ladder}, which CONFIDENCE_ORD does not contain — "
        "headline_core.py:104 subscripts it directly and would raise KeyError."
    )


def test_the_set_of_corroboration_readers_is_classified():
    """The assertion that would have caught the omission this section exists to fix.

    A registry of three hand-listed maps is exactly the narrow population that let `_CORR_TO_CONF`
    hide. Deriving the CANDIDATE set mechanically and requiring the CLASSIFICATION to be explicit means
    a fourth consumer cannot be added silently — the author is forced to say which kind it is.
    """
    found = _corroboration_reader_modules()
    # Anti-vacuity BY NAME: a broken sweep (wrong root, changed AST shape) must not green this. The
    # `eval/` member is not decoration — it is the whole point. A floor drawn only from `skills/` stays
    # satisfied if the root is narrowed back to `skills/`, so the previous version of this guard would
    # have gone GREEN on the very regression it now exists to catch.
    assert {
        "skills/_skills_common/archetype_core.py",
        "skills/_skills_common/headline_core.py",
        "skills/_skills_common/question_table_core.py",
        "eval/build_discordance_ledger.py",
    } <= found, f"the reader sweep is broken — it found {len(found)} module(s): {sorted(found)}"

    unclassified = sorted(found - set(_CORROBORATION_READERS))
    assert not unclassified, (
        f"module(s) newly reading a `corroboration` field and not yet triaged: {unclassified}. Classify "
        "by the CALL SITE, never by a map's key names: if the token is rendered or copied verbatim it is "
        "a PASS-THROUGH (an unknown rung reads as itself — honest); if it is looked up in a map, add that "
        "map to _LIVE_CORROBORATION_PROJECTIONS so the coverage assertion above covers it."
    )
    stale = sorted(set(_CORROBORATION_READERS) - found)
    assert not stale, (
        f"_CORROBORATION_READERS names module(s) that no longer read the field: {stale}. A stale entry is "
        "a standing exemption for code that moved — delete it, or the next reader inherits its excuse."
    )


def test_the_reader_population_covers_every_first_party_source_dir():
    """Guard the guard's ROOT, which is the one thing the sweep above cannot check about itself.

    `test_the_set_of_corroboration_readers_is_classified` asserts completeness over "the set of
    corroboration readers". For most of its life it meant "readers under `skills/`", because the root was
    `skills/` and `eval/` is a SIBLING — so two readers, one of them the module that turns a rung into a
    claimed discordance, sat outside the population while the guard read green. Nothing failed: a walk
    that cannot reach a file does not report it missing.

    The lesson generalises past this axis. A DATA-DERIVED population is only as wide as the tree it is
    pointed at, so `declared list = FLOOR, data = SCOPE` is not sufficient on its own — the ROOT needs a
    floor of its own, or the narrowing just moves up a level. Hence equality, not containment: a new
    top-level directory of first-party python must RED here and force a deliberate decision about whether
    the axis guards cover it, rather than being quietly outside them.
    """
    tracked = _tracked_python_files()
    # Anti-vacuity: an unknown population must not be spelled as an empty one. `git ls-files` returning
    # nothing (wrong cwd, not a repo, an export with no .git) would otherwise green every sweep here.
    assert len(tracked) > 100, (
        f"the tracked-python population is implausibly small ({len(tracked)}) — `git ls-files` is not "
        f"answering for {_REPO_ROOT}, so every reader sweep in this file is vacuous."
    )

    top_level = {p.split("/")[0] + "/" for p in tracked if "/" in p}
    assert top_level == set(_FIRST_PARTY_SOURCE_DIRS), (
        f"first-party python now lives in {sorted(top_level)}, but _FIRST_PARTY_SOURCE_DIRS declares "
        f"{sorted(_FIRST_PARTY_SOURCE_DIRS)}. Reconcile them deliberately: a directory that appears here "
        "and is NOT swept is a reader population that silently narrowed, which is exactly the defect this "
        "test exists to prevent. Adding the name is the fix ONLY if the sweep genuinely reaches it."
    )

    # And the sweep must actually be reaching outside `skills/` — the property that regressed before.
    outside = {r for r in _corroboration_reader_modules() if not r.startswith("skills/")}
    assert outside, (
        "the reader sweep found no corroboration reader outside `skills/`. Either every eval-side reader "
        "was deleted (then drop them from _CORROBORATION_READERS and this assertion), or the sweep root "
        "has been narrowed back to a subtree and the completeness claim in this file is false again."
    )
