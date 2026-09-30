"""THE UNIT OF THE COHORT RULER IS THE TARGET, NOT THE CORPUS ROW.

`cohort_percentile` produces sentences of the form "stronger LoF-constraint than 82% of 262 known
targets". The ruler behind that sentence was built one entry per corpus ROW, and corpus rows are
`(target, indication)` pairs: at n=504 the atlas holds 504 rows over 262 distinct targets, 50 of them
replicated, and BRAF / CCND1 / CDK4 / CTNNB1 / EZH2 / FGFR3 / IDH1 / KEAP1 each occupy nine. So a
replicated target could vote up to nine times in a ranking that claims to be over targets.

It is not a rounding-scale mismatch. 116 of the 176 atlas columns — and 39 of the 64 `::num::` columns
— are entirely TARGET-INTRINSIC: identical across every one of a target's rows. On those columns the
extra votes are pure duplication of a single measurement, and they moved both the percentile and the
`n` the reader printed.

★ WHY THE RULE IS "EACH TARGET'S DISTINCT VALUES", NOT "ONE ROW PER TARGET". 60 columns genuinely vary
within a target across indications (`tumor_vs_adjacent_expression::num::log2_fc` moves for 42 targets,
and should). Electing one representative row would discard those real observations; averaging would
invent a value no row holds. Contributing each target's SET of measured values needs no per-column
classification and no hand-maintained roster, and it degenerates correctly at both ends — one entry on
an intrinsic column, k entries on one that varies k ways.

WHAT THESE TESTS ASSERT, and why each one is here rather than being implied by the others:

  1. THE EXACT SEMANTICS, on a synthetic atlas — a replicated target with one value votes once, with
     three values votes three times, and an identical repeat is not two pieces of evidence. Synthetic
     because the shipped artifact cannot exhibit those three cases on one column on demand.
  2. THE SHIPPED CONSEQUENCE — on the real artifact, `n` on a target-intrinsic column equals the number
     of targets measured, and it is strictly smaller than the row count. A synthetic-only test would
     pass against an atlas whose `targets` list the reader never actually consults.
  3. `distinct` IS EXACTLY INVARIANT, over all 176 columns. This is the load-bearing safety property:
     `tier_rarity`'s USABLE_TIER_RARITY_DISTINCT gate, SHIPPED_CORROB_REACH and the five columns pinned
     by name in test_tier_rarity_frame.py all read `len(set(column))`, and per-target dedup changes
     multiplicities only. Asserted over every column, not sampled, because "the gate did not move" is
     the claim that let this change land next to a just-completed re-freeze.
  4. THE SCOPED PATH IS NOT IMMUNE, contra the design note this fix started from. `(target, indication)`
     is unique 504/504, which makes it tempting to argue an indication group holds one row per target.
     `_cohort_indication_groups` POOLS aliases through `canonical_subtype_code`, so LUAD, LUSC and NSCLC
     land in one 60-row group and a target carrying two of those spellings appears twice in it. Measured
     on the shipped atlas: exactly one of 24 canonical groups, one target, twice. Asserted as a
     structural property of the code rather than as today's count, since the next alias registration can
     enlarge it silently.
  5. THE BEHAVIOURAL CONSEQUENCE, BY NAME — `surface_density::num::absolute_copies_per_cell` falls n=32
     to 18 and goes silent under min_n=20. Its 32 rows were only ever 18 targets, so the gauge it used
     to emit ranked against a cohort it did not have. Pinned by name so the silence is a recorded
     decision rather than a mystery for the next reader of that card.
  6. FAIL-SOFT — an artifact whose `targets` is absent or not parallel to `X` degrades to the row-wise
     column rather than raising. A display frame must never break a render, and older artifacts exist.

★ NOTE ON CACHES. The column readers are lru_cached and `_target_row_groups` deliberately is NOT: it
takes the atlas as an argument precisely so no test has to know it exists. Tests here that swap the
artifact still clear the four caches that ARE keyed on nothing, using the same list and the same
"patch the RESOLVING namespace" idiom as test_tier_rarity_frame.py.
"""

import pytest  # noqa: E402
from _skills_common import archetype_core as ac  # noqa: E402

MIN_N = 20
# target-intrinsic on the shipped artifact: every one of a target's rows carries the same value.
INTRINSIC_KEY = "gnomad_lof_constraint::num::loeuf_score"
# genuinely varies within a target across indications — the case a "one row per target" fix would break.
VARYING_KEY = "tumor_vs_adjacent_expression::num::log2_fc"
# the one column whose per-target n crosses BELOW min_n, measured over all 176.
GOES_SILENT_KEY = "surface_density::num::absolute_copies_per_cell"

_CACHES = (
    ac._shipped_atlas_or_none,
    ac._cohort_sorted_column,
    ac._scoped_sorted_column,
    ac._cohort_indication_groups,
)


@pytest.fixture
def swap_atlas():
    """Replace the artifact loader for one test, clearing every cache keyed on nothing on both sides.

    Patching the loader without clearing tests the WARM CACHE and passes for the wrong reason; not
    clearing on the way OUT leaves the synthetic atlas visible to every later test in the session."""

    def _swap(atlas):
        for c in _CACHES:
            c.cache_clear()
        ac._shipped_atlas_or_none = lambda: atlas

    original = ac._shipped_atlas_or_none
    try:
        yield _swap
    finally:
        ac._shipped_atlas_or_none = original
        for c in _CACHES:
            c.cache_clear()


@pytest.fixture(scope="module")
def atlas():
    a = ac._shipped_atlas_or_none()
    if a is None:
        pytest.skip("no shipped atlas artifact in this checkout")
    if not a.targets or len(a.targets) != len(a.X):
        pytest.fail("shipped atlas has no `targets` parallel to `X` — the ruler's unit cannot be tested")
    return a


def _row_column(a, key):
    """The column one entry per ROW — the pre-fix ruler, kept as the thing to measure the change AGAINST."""
    j = a.feature_order.index(key)
    return sorted(r[j] for r in a.X if j < len(r) and r[j] is not None)


def _target_column(a, key):
    """The column in the RULER's unit, derived here from `X`/`targets` rather than from the code under test."""
    j = a.feature_order.index(key)
    per_target: dict = {}
    for i, t in enumerate(a.targets):
        if j < len(a.X[i]) and a.X[i][j] is not None:
            per_target.setdefault(t, set()).add(a.X[i][j])
    return sorted(v for vals in per_target.values() for v in vals)


def _crosses_min_n(a, key):
    """True when `key`'s cohort is powered ROW-wise but under-powered per TARGET — i.e. dedup silences it.

    Deliberately shared by the by-name pin and the all-176-columns sweep below, so the two cannot drift
    apart: `>=` vs `>` on either side of min_n is exactly the kind of edit that would leave one of them
    measuring a different question while both still passed."""
    return len(_row_column(a, key)) >= MIN_N > len(_target_column(a, key))


def _synthetic(values, targets, indications=None, key="synthetic::num::probe"):
    return ac.Atlas(
        {
            "feature_order": [key],
            "mu": [0.0],
            "sd": [1.0],
            "X": [[v] for v in values],
            "targets": list(targets),
            "indications": list(indications or [""] * len(targets)),
            "labels": ["?"] * len(targets),
        }
    )


# ── 1. the exact semantics, where all three cases can be exhibited on one column ──────────────────────
def test_a_replicated_target_contributes_its_distinct_values_once_each(swap_atlas):
    """The whole rule, on one synthetic column, in the three cases that decide the design.

    A votes once from three identical rows; B contributes both of its distinct values; C is a plain
    single-row target. n = 4, not the 6 rows — and NOT 3, which is what electing one row per target
    would give, silently discarding B's second measurement."""
    key = "synthetic::num::probe"
    swap_atlas(_synthetic([1.0, 1.0, 1.0, 2.0, 3.0, 4.0], ["A", "A", "A", "B", "B", "C"]))

    col = ac._cohort_sorted_column(key)
    assert col == (1.0, 2.0, 3.0, 4.0), col
    assert len(col) == 4, "n must count per-target distinct values: 1 from A, 2 from B, 1 from C"
    assert col.count(1.0) == 1, "A's three identical rows are one measurement, not three"
    assert sorted(set(col)) == [1.0, 2.0, 3.0, 4.0], "the SET of values present must be untouched"


def test_the_rule_is_not_one_row_per_target_which_would_discard_real_observations(swap_atlas):
    """A target measured three DIFFERENT ways across three indications keeps all three entries.

    This is the assertion that distinguishes the shipped design from the obvious alternative. Elect a
    representative row (first, median, mean) and this column's ruler collapses from 3 entries to 1,
    which on the shipped artifact would throw away the 122 extra observations the 60 genuinely-varying
    columns carry."""
    key = "synthetic::num::probe"
    swap_atlas(_synthetic([1.0, 2.0, 3.0], ["A", "A", "A"]))
    assert ac._cohort_sorted_column(key) == (1.0, 2.0, 3.0)


def test_a_column_with_no_replication_is_bit_for_bit_unchanged(swap_atlas):
    """ANTI-VACUITY IN THE OTHER DIRECTION: with no replicated target the ruler is exactly the old one.

    Without this, every assertion above is consistent with a reader that mangles unreplicated corpora
    too — and 212 of the 262 shipped targets are unreplicated."""
    key = "synthetic::num::probe"
    values = [3.0, 1.0, 2.0, 5.0, 4.0]
    swap_atlas(_synthetic(values, ["A", "B", "C", "D", "E"]))
    assert ac._cohort_sorted_column(key) == tuple(sorted(values))


# ── 2 & 3. the shipped artifact: the consequence, and the safety property ─────────────────────────────
def test_a_target_intrinsic_column_reports_one_entry_per_measured_target(atlas):
    """On the real artifact, `n` on an intrinsic column is the count of TARGETS measured, not rows."""
    if INTRINSIC_KEY not in atlas.feature_order:
        pytest.skip(f"{INTRINSIC_KEY} absent from this atlas vintage")
    j = atlas.feature_order.index(INTRINSIC_KEY)
    measured_targets = {t for i, t in enumerate(atlas.targets) if j < len(atlas.X[i]) and atlas.X[i][j] is not None}
    col = ac._cohort_sorted_column(INTRINSIC_KEY)

    assert len(col) == len(measured_targets), (
        f"{INTRINSIC_KEY}: ruler n={len(col)} but {len(measured_targets)} targets are measured — either the "
        "column stopped being target-intrinsic (re-measure; the fix is still correct, this pin is not) or "
        "the dedup is not being applied"
    )
    rows = _row_column(atlas, INTRINSIC_KEY)
    assert len(col) < len(rows), (
        f"{INTRINSIC_KEY} shows no replication at all (rows={len(rows)}) — this test can no longer see the "
        "defect it exists to pin; re-pin it to a replicated intrinsic column"
    )
    assert tuple(_target_column(atlas, INTRINSIC_KEY)) == col, "the reader disagrees with the independent read"


def test_a_varying_column_keeps_every_distinct_observation(atlas):
    """The counterpart: a column that varies within a target must exceed one entry per target."""
    if VARYING_KEY not in atlas.feature_order:
        pytest.skip(f"{VARYING_KEY} absent from this atlas vintage")
    j = atlas.feature_order.index(VARYING_KEY)
    measured_targets = {t for i, t in enumerate(atlas.targets) if j < len(atlas.X[i]) and atlas.X[i][j] is not None}
    col = ac._cohort_sorted_column(VARYING_KEY)
    assert len(col) > len(measured_targets), (
        f"{VARYING_KEY}: ruler n={len(col)} == one per target ({len(measured_targets)}), so this column no "
        "longer varies within a target and the 'not one row per target' half of the design is untested"
    )
    assert tuple(_target_column(atlas, VARYING_KEY)) == col


def test_the_set_of_values_is_invariant_on_every_column(atlas):
    """★ THE SAFETY PROPERTY, over all 176 columns: dedup changes MULTIPLICITIES, never the value SET.

    Everything reading `len(set(column))` — USABLE_TIER_RARITY_DISTINCT, SHIPPED_CORROB_REACH, the five
    columns test_tier_rarity_frame pins by name — is therefore provably unmoved by this change. Asserted
    exhaustively rather than sampled, because that provability is what made it safe to land this on top
    of a just-completed re-freeze rather than folding it into the next one."""
    moved, changed_n = [], 0
    for key in atlas.feature_order:
        rows, targets_col = _row_column(atlas, key), _target_column(atlas, key)
        if set(rows) != set(targets_col):
            moved.append(key)
        if len(rows) != len(targets_col):
            changed_n += 1
    assert not moved, f"{len(moved)} columns changed their value SET, not just multiplicities: {moved[:5]}"
    assert changed_n > 100, (
        f"only {changed_n} of {len(atlas.feature_order)} columns changed n — if the corpus ever stops "
        "replicating targets this whole fix is a no-op and the invariance above proves nothing"
    )


# ── 4. the scoped path, where the immunity argument fails ─────────────────────────────────────────────
def test_the_scoped_path_dedups_too_because_alias_pooling_repeats_a_target(atlas):
    """`(target, indication)` uniqueness does NOT make an indication GROUP one-row-per-target.

    Asserted structurally: for every canonical group and a broadly-measured column, the scoped ruler
    must equal the independently-computed per-target read of that group. Anti-vacuity: at least one
    group must actually contain a repeated target, or the assertion is only restating uniqueness."""
    if INTRINSIC_KEY not in atlas.feature_order:
        pytest.skip(f"{INTRINSIC_KEY} absent from this atlas vintage")
    j = atlas.feature_order.index(INTRINSIC_KEY)
    groups = ac._cohort_indication_groups()
    assert len(groups) > 5, f"only {len(groups)} canonical groups — the scoped path is barely populated"

    pooled_repeats = {}
    for canon, idxs in groups.items():
        counts: dict = {}
        for i in idxs:
            counts[atlas.targets[i]] = counts.get(atlas.targets[i], 0) + 1
        repeats = {t: c for t, c in counts.items() if c > 1}
        if repeats:
            pooled_repeats[canon] = repeats

        scoped = ac._scoped_sorted_column(INTRINSIC_KEY, canon)
        per_target: dict = {}
        for i in idxs:
            if j < len(atlas.X[i]) and atlas.X[i][j] is not None:
                per_target.setdefault(atlas.targets[i], set()).add(atlas.X[i][j])
        expected = tuple(sorted(v for vals in per_target.values() for v in vals))
        assert scoped == expected, f"{canon}: scoped ruler is not the per-target read of its own group"

    assert pooled_repeats, (
        "no canonical indication group contains a repeated target, so the scoped dedup is currently a "
        "no-op and this test cannot see it. That is a property of the alias registry, not of the code — "
        "the dedup stays. Re-check `canonical_subtype_code` before deleting anything here."
    )
    # and the pooling is the CAUSE: the group's raw labels must be more than one spelling
    for canon in pooled_repeats:
        raw = {str(atlas.indications[i] or "").strip().upper() for i in groups[canon]}
        assert len(raw) > 1, (
            f"{canon} repeats a target but pools only one raw label {raw} — then `(target, indication)` "
            "uniqueness is violated in the ARTIFACT, which is a build defect, not an aliasing effect"
        )


def test_the_scoped_ruler_is_never_larger_than_its_group(atlas):
    """A scoped cohort cannot out-count the rows it was sliced from — the cheap guard against an
    off-by-one in the grouping that would over-report `n` inside an indication."""
    if INTRINSIC_KEY not in atlas.feature_order:
        pytest.skip(f"{INTRINSIC_KEY} absent from this atlas vintage")
    for canon, idxs in ac._cohort_indication_groups().items():
        assert len(ac._scoped_sorted_column(INTRINSIC_KEY, canon)) <= len(idxs), canon


# ── 5. the one behavioural consequence, pinned by name ────────────────────────────────────────────────
def test_the_one_column_that_goes_silent_is_recorded_by_name(atlas):
    """`surface_density::num::absolute_copies_per_cell`: 32 rows, 18 targets ⇒ now below min_n=20.

    THIS IS THE GATE WORKING, NOT A REGRESSION. The pan-cancer gauge this column used to emit ranked a
    value against a cohort of 32 that was really 18 — exactly the over-count min_n exists to refuse. It
    is pinned here so a reader who notices the card lost its percentile finds the reason, and so that a
    future re-freeze which lifts it back over the gate reds here and gets a fresh look rather than
    silently resuming. No other column crosses the gate in either direction."""
    if GOES_SILENT_KEY not in atlas.feature_order:
        pytest.skip(f"{GOES_SILENT_KEY} absent from this atlas vintage")
    rows, targets_col = _row_column(atlas, GOES_SILENT_KEY), _target_column(atlas, GOES_SILENT_KEY)
    assert _crosses_min_n(atlas, GOES_SILENT_KEY), (
        f"{GOES_SILENT_KEY} no longer straddles min_n={MIN_N} (rows={len(rows)}, targets={len(targets_col)}) "
        "— re-measure which columns cross and update this pin with the reason"
    )
    assert ac.cohort_percentile(GOES_SILENT_KEY, rows[len(rows) // 2]) is None, (
        "an under-powered cohort emitted a percentile — min_n is not being applied to the per-target n"
    )

    crossers = [k for k in atlas.feature_order if _crosses_min_n(atlas, k)]
    assert crossers == [GOES_SILENT_KEY], (
        f"the set of columns silenced by per-target dedup changed to {crossers}. Each one is a card that "
        "stops reporting a percentile, so name them here deliberately rather than discovering it in a report"
    )


# ── 6. fail-soft on an artifact that cannot support the grouping ──────────────────────────────────────
@pytest.mark.parametrize(
    "targets,why",
    [
        ([], "no targets list at all"),
        (["A", "B"], "targets shorter than X"),
        (["A", "B", "C", "D", "E", "F", "G"], "targets longer than X"),
    ],
)
def test_an_unusable_targets_list_degrades_to_the_row_wise_ruler(swap_atlas, targets, why):
    """An older or hand-edited artifact must degrade to the pre-fix column, not raise.

    `_target_row_groups` returns () and both readers fall back to the row-wise column. A display-only
    ruler that raises takes the whole render down with it, so the failure mode has to be a WORSE ruler,
    never no report."""
    key = "synthetic::num::probe"
    values = [3.0, 1.0, 2.0, 5.0, 4.0, 1.0]
    a = _synthetic(values, ["A", "A", "B", "C", "D", "E"])
    a.targets = list(targets)  # the artifact shapes Atlas.__init__ would not itself produce
    swap_atlas(a)

    col = ac._cohort_sorted_column(key)
    assert col == tuple(sorted(values)), f"{why}: expected the row-wise fallback, got {col}"
    assert ac._target_row_groups(a) == (), why


def test_a_missing_atlas_still_yields_an_empty_ruler_rather_than_raising(swap_atlas):
    swap_atlas(None)
    assert ac._cohort_sorted_column(INTRINSIC_KEY) == ()
    assert ac._scoped_sorted_column(INTRINSIC_KEY, "COADREAD") == ()
    assert ac._target_row_groups(None) == ()
