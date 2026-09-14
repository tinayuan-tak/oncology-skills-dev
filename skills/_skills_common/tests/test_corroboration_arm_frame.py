"""The MEASURED-ARM corroboration frame: one arm is not corroboration, and coverage is REPORTED.

`moderate` used to be the fleet-wide ONE-ARMED DEFAULT. 22 of the 61 ClaimSpecs route through
`claim_vector_core.corr()`, whose own docstring said it yields `moderate` for a single source with
"never a second arm" — so a third of the fleet reported partial AGREEMENT for evidence that was never
corroborated, and `moderate` could not distinguish "two arms partly agree" from "nobody looked for a
second arm". Several axes went further: `translational_readiness` graded cohort DEPTH on the
corroboration axis (its own comment said "not a second arm"), `safety._paness_corr` returned `high`
from one arm, and `literature_context._corr` returned `low` — the eval ledger's DISAGREEMENT rung —
for an empty corpus, so "no papers found" was priced as conflicting evidence.

The population these checks run over is DERIVED by introspecting every ClaimSpec roster, never listed,
so a NEW claims module cannot regress the property by simply not appearing in a hardcoded set.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import itertools
import pathlib
import sys
import textwrap

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from _skills_common.claim_vector_core import (  # noqa: E402
    CORROBORATION_ARM_FLOOR,
    CORROBORATION_ORD,
    ClaimSpec,
    bump_corroboration,
    cap_corroboration,
    corr,
    corroboration_from_arms,
    n_arms_measured,
)
from _skills_common.figure_palette import REL_DOTS  # noqa: E402
from _skills_common.headline_core import _CORR_TO_CONF, CONFIDENCE_ORD  # noqa: E402
from _skills_common.headline_hero import render_headline_hero_svg  # noqa: E402
from _skills_common.presence_claims_figure import render_claim_vector_svg  # noqa: E402
from _skills_common.question_table_core import CONF_DOTS, conf  # noqa: E402

_CLAIMS_DIR = pathlib.Path(__file__).resolve().parents[1]


def _rosters() -> dict:
    """{"<module>:<VARNAME>": [ClaimSpec, …]} — DERIVED by isinstance introspection, not by name."""
    out: dict = {}
    for path in sorted(_CLAIMS_DIR.glob("*claims*.py")):
        mod = importlib.import_module(f"_skills_common.{path.stem}")
        for name in dir(mod):
            val = getattr(mod, name)
            if isinstance(val, (list, tuple)) and val and all(isinstance(x, ClaimSpec) for x in val):
                out[f"{path.stem}:{name}"] = list(val)
    return out


def _all_specs() -> list:
    return [(ref, spec) for ref, specs in _rosters().items() for spec in specs]


# ── the ladder ───────────────────────────────────────────────────────────────────────────────────


def test_single_arm_sits_between_low_and_moderate():
    """Both neighbours are load-bearing: ABOVE `low` so a coverage gap is not priced as a conflict,
    BELOW `moderate` so one arm never reads as corroborated."""
    o = CORROBORATION_ORD
    assert o["low"] < o["single_arm"] < o["moderate"] < o["high"]
    assert o["unmeasured"] is None, "a gap must stay incomparable — gap != absent, one level up"


def test_single_arm_projects_to_weak_confidence():
    """The CAP the frame exists to deliver: below the arm floor, confidence cannot exceed `weak`."""
    assert _CORR_TO_CONF["single_arm"] == "weak"
    assert CONFIDENCE_ORD[_CORR_TO_CONF["single_arm"]] < CONFIDENCE_ORD[_CORR_TO_CONF["moderate"]]


def test_every_corroboration_rung_has_a_confidence_projection():
    """A rung missing from `_CORR_TO_CONF` falls through its `.get(..., "insufficient")` default and
    silently reads as a coverage gap — the failure mode adding a rung invites."""
    missing = sorted(set(CORROBORATION_ORD) - set(_CORR_TO_CONF))
    assert not missing, f"corroboration rungs with no confidence projection: {missing}"


def test_no_display_projection_renders_a_MEASURED_rung_as_an_abstention():
    """THE AXIS HAS NON-NUMERIC PROJECTIONS TOO, and they fail in the opposite direction to the encoder.

    `_CORR_TO_CONF` above is a string projection; these two are INTEGER DOT projections, both read as
    `.get(corroboration, 0)`:
      * `question_table_core.CONF_DOTS`  — via `conf()` from `cv_axis_row`, shared by 7 skills
      * `figure_palette.REL_DOTS`        — `headline_hero.py:187`, `presence_claims_figure.py:61`
    In both, 0 is what `unmeasured` maps to, so an UNLISTED rung is drawn as an ABSTENTION while the
    sibling label still reads `corroboration: <rung>`: measured in text, unmeasured in dots, `gap !=
    absent` broken inside a single cell. That is the inverse of the encoder's failure, which fell OPEN
    (a null imputed to the corpus mean = `moderate`, the value the rung exists to remove). One axis,
    two fail directions — so a single "add a fallback" repair is wrong for one of them.

    This asserts the VALUE property (a measured rung never reaches an abstention coordinate), not mere
    key presence: a future author could satisfy key-coverage with `single_arm: 0` and reintroduce the
    exact bug. It deliberately does NOT assert `single_arm != low`, because the 0-3 integer scale cannot
    represent ORD 2 between `low` 1 and `moderate` 3 — that collision is a known, surfaced design
    question, not an invariant."""
    for name, dots in (("question_table_core.CONF_DOTS", CONF_DOTS), ("figure_palette.REL_DOTS", REL_DOTS)):
        abstain = {v for k, v in dots.items() if k in ("unmeasured", "unknown", "insufficient")}
        assert abstain, f"{name}: no abstention coordinate — cannot tell measured from unmeasured"
        for rung, ordinal in CORROBORATION_ORD.items():
            if ordinal is None:  # `unmeasured` IS the gap; it belongs at the abstention coordinate
                continue
            assert rung in dots, f"{name}: measured rung {rung!r} missing -> .get default draws an abstention"
            assert dots[rung] not in abstain, f"{name}: measured rung {rung!r} sits at abstention dots {dots[rung]}"
    # the two maps must not disagree about the same claim — one figure and one table, one number
    shared = set(CONF_DOTS) & set(REL_DOTS) & set(CORROBORATION_ORD)
    disagree = {k: (CONF_DOTS[k], REL_DOTS[k]) for k in shared if CONF_DOTS[k] != REL_DOTS[k]}
    assert not disagree, f"dot maps disagree on corroboration rungs: {disagree}"


def test_dot_colliding_rungs_still_render_DISTINGUISHABLY_in_both_figures():
    """WHAT MAKES THE PERMITTED COLLISION SAFE, asserted instead of merely commented.

    The test above deliberately allows `single_arm` and `low` to share dot coordinate 1 — a 0-3 integer
    scale cannot represent ORD 2 between `low` 1 and `moderate` 3. That is only tolerable because the rung
    NAME is rendered beside the dots, and nothing pinned that: the mitigation lived in a source comment in
    both dot maps. So deleting one `s.append(...)` in a figure refactor would silently make a
    MEASURED-BUT-THIN claim indistinguishable from a CONTRADICTED one — and `low` is exactly the
    discordance ledger's sharpness rung (`_DISAGREEMENT_CORROBORATION == {"low"}`), so the conflation
    happens in the figure a human reads to decide whether the evidence disagreed. Same shape as
    `gap != absent` one level up: two states that must never render as one.

    Asserts DISTINGUISHABLE OUTPUT, not the presence of a particular `<text>` element, so a legitimate
    re-implementation (moving the name into a `<title>` on the circles, say) still passes while an actual
    loss of disambiguation fires. The rung pairs are DERIVED from the dot map, so a collision minted by a
    future rung is covered without editing this test; the known pair is asserted as a FLOOR, never as the
    whole population, so growth widens the guard instead of narrowing it.
    """
    measured = sorted(r for r, o in CORROBORATION_ORD.items() if o is not None)
    colliding = [(a, b) for a, b in itertools.combinations(measured, 2) if REL_DOTS.get(a) == REL_DOTS.get(b)]
    # Anti-vacuity: with no collision this test proves nothing AND the "WHY 1 AND NOT 2" notes in both
    # dot maps have gone stale — so the floor is asserted, not assumed.
    assert ("low", "single_arm") in colliding, (
        f"`low`/`single_arm` no longer share a dot coordinate (collisions now {colliding}). If the scale "
        "widened, delete the collision notes in question_table_core.CONF_DOTS and figure_palette.REL_DOTS."
    )
    for a, b in colliding:
        hero = [
            render_headline_hero_svg(
                {"axes": [{"key": "P", "label": "presence", "signal": "strong", "corroboration": r}]}, "TGT", "IND"
            )
            for r in (a, b)
        ]
        assert hero[0] != hero[1], (
            f"headline_hero draws {a!r} and {b!r} IDENTICALLY — they share dot count {REL_DOTS[a]} and the "
            "rung name is no longer rendered, so a thin claim and a contradicted one are the same picture"
        )
        cv = [render_claim_vector_svg({"A": {"signal": "strong", "corroboration": r}}, "TGT", "IND") for r in (a, b)]
        assert cv[0] != cv[1], f"presence_claims_figure draws {a!r} and {b!r} IDENTICALLY (both at dots {REL_DOTS[a]})"
        # The table side disambiguates through its own label rather than the SVG, so pin it in the same place.
        assert conf(a)["label"] != conf(b)["label"], (
            f"question_table_core.conf() labels collide for {a!r}/{b!r}: {conf(a)['label']!r}"
        )


def test_bump_and_cap_are_not_no_ops_on_the_new_rung():
    """VACUITY GUARD. `bump_corroboration`/`cap_corroboration` return an unrecognised value UNCHANGED,
    so a rung omitted from their internal tables makes every bump and cap a silent no-op on it."""
    assert bump_corroboration("single_arm", True) != "single_arm", "bump is inert on single_arm"
    assert cap_corroboration("single_arm", "low") != "single_arm", "cap is inert on single_arm"


def test_a_second_agreeing_arm_lifts_a_one_armed_claim_to_high():
    """n=1 + an agreeing arm is n=2 all-agreeing, which is `high` by definition — the same answer
    `corroboration_from_arms` gives. If bump said `moderate` instead, the two would disagree."""
    assert bump_corroboration("single_arm", True) == "high"
    assert corroboration_from_arms([True, True]) == "high"
    assert bump_corroboration("single_arm", False) == "single_arm", "no arm arrived — no lift"


def test_a_disagreeing_arm_takes_a_one_armed_claim_to_conflict_not_to_a_gap():
    """A second arm that DISAGREES means the claim is no longer one-armed at all."""
    assert cap_corroboration("single_arm", "low") == "low"
    assert cap_corroboration("single_arm", "moderate") == "single_arm", "a ceiling above must not raise"


def test_bumping_a_conflict_does_not_report_it_as_one_armed():
    """The reason `_CORR_BUMP` is a table and not an index walk: an index walk over the rungs sends
    `low` to `single_arm`, i.e. relabels a measured DISAGREEMENT as a claim with one arm."""
    assert bump_corroboration("low", True) == "moderate"


# ── the measured-arm frame ───────────────────────────────────────────────────────────────────────


def test_an_absent_arm_leaves_both_sides_of_the_comparison():
    """Decision 1(a): an unmeasured arm neither raises nor lowers the tier — it is dropped, NOT scored
    as a neutral/partial agreement. So adding a None arm to a one-armed claim changes nothing."""
    assert corroboration_from_arms([True]) == corroboration_from_arms([True, None]) == "single_arm"
    assert corroboration_from_arms([True, None, None, None]) == "single_arm"
    assert corroboration_from_arms([True, True, None]) == "high"


def test_zero_measured_arms_is_a_gap_never_an_absence():
    assert corroboration_from_arms([]) == "unmeasured"
    assert corroboration_from_arms([None, None]) == "unmeasured"


def test_below_the_arm_floor_the_tier_is_capped_however_strong_the_arm():
    """Decision 1(b), verbatim: "corroboration cannot exceed `weak` however strong the measured arms
    are". There is no input to `corroboration_from_arms` that reaches above `single_arm` with fewer
    than CORROBORATION_ARM_FLOOR measured arms."""
    assert CORROBORATION_ARM_FLOOR == 2
    for arms in ([True], [True, None], [None, True, None]):
        got = corroboration_from_arms(arms)
        assert CORROBORATION_ORD[got] <= CORROBORATION_ORD["single_arm"], f"{arms} -> {got}"


def test_coverage_is_reported_separately_from_the_tier():
    """Decision 1(a)'s other half: the arm COUNT is available as its own field, so a reader can tell a
    corroborated claim from an uncovered one without decoding the tier."""
    assert n_arms_measured([True, True]) == 2
    assert n_arms_measured([True, None]) == 1
    assert n_arms_measured([None, None]) == 0
    assert n_arms_measured([True, False]) == 2, "a DISAGREEING arm was still measured"


def test_the_frame_distinguishes_the_two_states_moderate_used_to_conflate():
    """The whole point, as one assertion: "one arm, nobody looked for a second" and "arms compared,
    they disagree" must not be the same value — and neither may be `moderate`."""
    one_armed = corroboration_from_arms([True, None])
    conflicted = corroboration_from_arms([True, False])
    assert one_armed != conflicted
    assert "moderate" not in (one_armed, conflicted)


# ── the fleet-wide property ──────────────────────────────────────────────────────────────────────


def test_the_shared_single_source_factory_no_longer_claims_agreement():
    """`corr()` backs 22 of 61 specs at ONE fix point. Its measured value is the property under test."""
    fn = corr("some-card", "some_field", {"present": "moderate"})
    assert fn({}, {"some-card": {"some_field": "present"}}) == "single_arm"
    assert fn({}, {"some-card": {"some_field": "absent-from-smap"}}) == "unmeasured"
    assert fn({}, {}) == "unmeasured", "a missing card is a gap"


def _reachable_sources(fn, seen=None) -> dict:
    """{qualname: source} for `fn` AND, transitively, every function it can DELEGATE to.

    A plain `inspect.getsource(spec.corroboration_fn)` is NOT a sufficient instrument here, and that is
    not hypothetical — it is how the first version of this guard passed a mutation that reintroduced the
    bug. Most axes' corroboration_fn is a CLOSURE returned by a factory, and several factories are thin
    wrappers that hand off to a helper (`translational_readiness` builds `fn(h, _c)` around a `corr_fn`
    captured in a closure cell). Reading only the wrapper sees the delegation and none of the literals,
    so `moderate` could be restored inside the helper with the guard still green — a guard that reads
    the caller but not the callee has a DIRECTION, and this one pointed the wrong way.

    So follow both edges a Python function can delegate along: closure CELLS (factory-captured helpers)
    and module GLOBALS named in the code object (module-level helpers). Depth is bounded by `seen`."""
    seen = {} if seen is None else seen
    if not callable(fn) or getattr(fn, "__code__", None) is None:
        return seen
    key = f"{getattr(fn, '__module__', '?')}.{getattr(fn, '__qualname__', fn)}"
    if key in seen:
        return seen
    try:
        seen[key] = inspect.getsource(fn)
    except (OSError, TypeError):
        seen[key] = ""
        return seen
    for cell in fn.__closure__ or ():
        try:
            val = cell.cell_contents
        except ValueError:  # an empty cell (recursive definition still being bound)
            continue
        if callable(val):
            _reachable_sources(val, seen)
    globs = getattr(fn, "__globals__", {})
    for name in fn.__code__.co_names:
        val = globs.get(name)
        if callable(val) and getattr(val, "__module__", None) == fn.__module__:
            _reachable_sources(val, seen)
    return seen


# Which rungs may a CLAIMS module pin unconditionally? Not the ones that assert a second arm agreed.
# Derived from CORROBORATION_ORD so a new rung is covered by default rather than by amendment.
_UNEARNABLE_BY_ONE_ARM = frozenset(
    r for r, o in CORROBORATION_ORD.items() if o is not None and o > CORROBORATION_ORD["single_arm"]
)  # {"moderate", "high"}

# `claim_vector_core` OWNS the ladder — `corroboration_from_arms` legitimately ends `return "high"`, and
# `_CORR_BUMP` legitimately names every rung. The rule is that CLAIMS MODULES must not re-derive it, so
# the core is excluded from the scan by module, not by pattern.
_LADDER_OWNER = "_skills_common.claim_vector_core"


def _corroboration_only_sources(spec) -> dict:
    """The sources reachable from this axis's corroboration_fn and NOT from its signal_fn.

    The discriminator has to be structural, not lexical. `moderate` is a token the TWO ordinals SHARE,
    so a source-level literal is ambiguous on its own — and guessing the axis from vocabulary FAILED
    twice here, in both directions: literature-context's `_count_tier` was flagged for a legal SIGNAL
    `moderate`, and then genomic's `_cn_corroboration` was SKIPPED as "signal-producing" because it
    gates on `absent`/`negative` and delegates its rung to `corroboration_from_arms`, so it contains no
    corroboration-exclusive literal at all. That skip silently swallowed the exact defect this file
    exists to pin.

    The ClaimSpec already declares which function is which, so use the declaration: subtract the
    signal_fn's reachable set from the corroboration_fn's. What remains is on the corroboration axis by
    construction, whatever words it uses."""
    corr_side = _reachable_sources(spec.corroboration_fn)
    signal_side = _reachable_sources(spec.signal_fn)
    return {q: s for q, s in corr_side.items() if q not in signal_side and not q.startswith(_LADDER_OWNER)}


def _unconditional_pins(src: str) -> list:
    """Statements pinning a corroborated rung with NO guard above them, found by AST rather than by
    matching line text.

    The distinction between an UNCONDITIONAL pin and a GUARDED one is the whole property, and text
    cannot see it: `return "high"` reads identically whether it is a function's trailing fallthrough or
    the body of `if patient_arm_agrees:`. A text matcher flagged three legitimate two-arm comparisons
    here — cis-coherence's `if agree is True: return "high"` (a real patient arm agreeing) and
    selectivity's `if window_veto and liab: base = "high"` (two normal-side reads agreeing). So ask the
    grammar instead: a pin is unconditional iff it sits at its function's OWN top level, with no
    enclosing `if`/`match`/`try`/loop. That is exactly "this is what the axis returns when nothing
    distinguishes the input" — the one-armed default."""
    try:
        tree = ast.parse(textwrap.dedent(src))
    except (SyntaxError, IndentationError):
        return []
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for st in node.body:  # DIRECT children only — an enclosing `if` makes it conditional
            val = st.value if isinstance(st, (ast.Return, ast.Assign)) else None
            if not (isinstance(val, ast.Constant) and val.value in _UNEARNABLE_BY_ONE_ARM):
                continue
            if isinstance(st, ast.Return):
                out.append(f'{node.name}: return "{val.value}"')
            else:
                tgt = next((t.id for t in st.targets if isinstance(t, ast.Name)), "?")
                out.append(f'{node.name}: {tgt} = "{val.value}"')
    return out


def _one_armed_corroboration_offenders(spec) -> list:
    """Corroborated rungs pinned unconditionally on this axis's corroboration side.

    Narrow on purpose: a `moderate`/`high` produced by `bump_corroboration`, by a genuine multi-arm
    comparison, or by an explicit `cap_corroboration(..., ceiling)` is legitimate. Only an
    unconditional literal in the single-source position is not."""
    return [
        f"{qual}: {pin.split(': ', 1)[1]}"
        for qual, src in _corroboration_only_sources(spec).items()
        for pin in _unconditional_pins(src)
    ]


@pytest.mark.parametrize("ref_spec", _all_specs(), ids=lambda rs: f"{rs[0]}:{rs[1].axis_key}")
def test_no_claim_axis_hardcodes_a_corroborated_tier(ref_spec):
    """The regression this fix closes, pinned over the DERIVED population: no corroboration_fn may pin
    `moderate` or `high` as its ONE-ARMED fallback.

    Covers BOTH rungs above the floor, because the fleet misused both — `safety._paness_corr` returned
    `high` from a single arm, not merely `moderate`. A source read is the one instrument that catches
    the default BEFORE any input reaches it, so it is kept, but made transitive (`_reachable_sources`)
    and axis-scoped by declaration (`_corroboration_only_sources`)."""
    ref, spec = ref_spec
    offenders = _one_armed_corroboration_offenders(spec)
    assert not offenders, (
        f"{ref}:{spec.axis_key} hardcodes a corroborated tier on one arm ({offenders}). Anything above "
        f"`single_arm` asserts a SECOND arm agreed and needs >= {CORROBORATION_ARM_FLOOR} measured arms. "
        f"Use corroboration_from_arms([...]) so absent arms leave the frame."
    )


@pytest.mark.parametrize("ref_spec", _all_specs(), ids=lambda rs: f"{rs[0]}:{rs[1].axis_key}")
def test_an_axis_with_no_evidence_at_all_is_unmeasured(ref_spec):
    """BEHAVIOURAL companion to the source guard. With an empty headline and no cards, every axis must
    report exactly `unmeasured`.

    EXACTLY, not merely "at most `single_arm`": bounding only from above lets an axis return `low` for a
    target about which nothing was measured, and `low` is the eval ledger's DISAGREEMENT rung — the
    literature-context bug verbatim, where an empty corpus was filed as CONFLICTING evidence. A gap is
    neither corroboration nor conflict, in both directions.

    Needs zero fixtures, covers all 61 axes by EXECUTION rather than by reading, and incidentally proves
    every corroboration_fn is callable at the (headline, cards_by_id) arity the builder uses."""
    ref, spec = ref_spec
    got = spec.corroboration_fn({}, {})
    assert got in CORROBORATION_ORD, f"{ref}:{spec.axis_key} returned {got!r}, not a corroboration rung"
    assert got == "unmeasured", (
        f"{ref}:{spec.axis_key} reports corroboration {got!r} on an EMPTY headline with no cards. "
        f"Nothing was measured, so there is neither a second arm to agree ({sorted(_UNEARNABLE_BY_ONE_ARM)}) "
        f"nor one to disagree (`low`, which the eval ledger reads as a sharp discordance)."
    )


def _fake_spec(corroboration_fn, signal_fn=None):
    return ClaimSpec("AX", "ax", signal_fn or (lambda h, c: ("unmeasured", "", None)), corroboration_fn, "x")


def test_the_population_is_real_and_both_guards_can_fail():
    """ANTI-VACUITY. Each assertion below corresponds to a mutation that SURVIVED an earlier version of
    this file — the guard is only worth its runtime if these specific shapes are catchable."""
    specs = _all_specs()
    assert len(specs) >= 55, f"roster introspection found only {len(specs)} specs — it is broken"
    assert len({ref for ref, _ in specs}) >= 12, "too few claims modules discovered"

    def _offending_helper(h):
        return "moderate"

    def _factory():
        helper = _offending_helper  # captured in a CLOSURE CELL, exactly like translational's corr_fn

        def fn(h, _c):
            return helper(h)

        return fn

    # (1) DIRECT, and (2) reached only through a closure cell — the shape that let a mutation reverting
    # translational_readiness pass silently, because the wrapper's source shows the call, not the literal.
    assert _one_armed_corroboration_offenders(_fake_spec(_offending_helper)), "misses a DIRECT offender"
    assert _one_armed_corroboration_offenders(_fake_spec(_factory())), "misses a DELEGATED offender"

    # (3) `high`, not just `moderate` — safety._paness_corr's actual misuse.
    assert _one_armed_corroboration_offenders(_fake_spec(_high_offender)), "misses a one-armed `high`"

    # (4) The axis discriminator must not become a loophole. A corroboration fn that GATES on signal
    # tiers and delegates its rung has NO corroboration-exclusive literal, so a vocabulary-based
    # discriminator classified it as a signal producer and skipped it — swallowing the genomic CN defect.
    assert _one_armed_corroboration_offenders(_fake_spec(_signal_gated_offender)), (
        "a corroboration fn that gates on signal tiers was misclassified as a signal producer"
    )
    # …while a genuine signal-side helper SHARED with signal_fn stays out of scope (no false positive).
    assert not _one_armed_corroboration_offenders(
        _fake_spec(lambda h, c: _signal_tier_helper(h), lambda h, c: (_signal_tier_helper(h), "", None))
    ), "a signal-tier helper shared with signal_fn must not be scanned as corroboration"

    assert not _one_armed_corroboration_offenders(_fake_spec(lambda h, c: "single_arm")), "over-fires"
    assert _UNEARNABLE_BY_ONE_ARM == {"moderate", "high"}, f"rung set moved: {_UNEARNABLE_BY_ONE_ARM}"

    # (5) GUARDED pins must NOT fire — the false-positive direction, which a text matcher got wrong on
    # three live axes. A corroborated rung reached only when a real second arm agreed is the CORRECT use.
    assert not _one_armed_corroboration_offenders(_fake_spec(_genuine_two_arm)), (
        "flagged a genuine two-arm comparison — `high` guarded by an agreeing arm is exactly right"
    )
    assert not _one_armed_corroboration_offenders(_fake_spec(_genuine_two_arm_via_base)), (
        'flagged a guarded `base = "high"` assignment'
    )
    # …and the guarded/unconditional distinction is the AST's, not the text's: both shapes below contain
    # the byte-identical line `return "high"`.
    assert 'return "high"' in inspect.getsource(_genuine_two_arm)
    assert 'return "high"' in inspect.getsource(_high_offender)


def _genuine_two_arm(h, _c):
    """The cis-coherence shape: `high` ONLY when an independent patient arm agrees."""
    agree = h.get("patient_agrees")
    if agree is True:
        return "high"
    if agree is False:
        return "low"
    return "single_arm"


def _genuine_two_arm_via_base(h, _c):
    """The selectivity shape: a guarded `base = "high"` when two measured reads agree."""
    base = "single_arm"
    if h.get("veto") and h.get("liab"):
        base = "high"
    return base


def _high_offender(h, _c):
    return "high"


def _signal_tier_helper(h):
    """A legitimate SIGNAL-tier producer: `moderate` here is a signal tier, a different ordinal."""
    if h.get("n", 0) >= 20:
        return "strong"
    return "moderate"


def _signal_gated_offender(h, _c):
    """The genomic-CN shape: gates on signal tokens, pins a corroborated rung, names no corr rung."""
    if h.get("cn_class") in ("absent", "negative"):
        return "unmeasured"
    return "moderate"


def test_single_arm_is_not_a_disagreement():
    """The reason `single_arm` is a NEW rung instead of being folded into `low`. The eval ledger keys
    its SHARPNESS predicate on `_DISAGREEMENT_CORROBORATION`; routing one-armed claims there would file
    every coverage gap as a framework-internal disagreement and fabricate a sharp row per gap — the
    `fabricating contradictions out of coverage gaps` failure mode. Only `low` means arms disagreed."""
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[3] / "eval"))
    ledger = importlib.import_module("build_discordance_ledger")
    assert "single_arm" not in ledger._DISAGREEMENT_CORROBORATION
    assert ledger._DISAGREEMENT_CORROBORATION == {"low"}, "the disagreement rung set moved — re-check why"


# ── the floor must not be bypassable by a SAME-ARM QUALIFIER ─────────────────────────────────────────
# Declared qualifier sites: (module, function) -> why the trigger is NOT an independent arm. Anything
# that passes `arm=False` must be declared here, and everything declared must still do so. This is the
# expected-absence shape used elsewhere in the repo (dangling / stale / mandatory reason), not an
# allow-list of the compliant majority — the ten real-arm call sites are deliberately NOT enumerated, so
# adding a genuine second arm never reds this test.
_DECLARED_QUALIFIER_SITES = {
    ("genomic_claims", "_dep_corroboration"): (
        "within-indication localisation says WHERE the pharmacology arm's evidence was measured, which "
        "is a property of that one arm rather than a second arm agreeing with it"
    ),
    ("dependency_claims", "_dep_corroboration"): (
        "the omics-predictability model is fitted ON the same CRISPR dependency it would corroborate, so "
        "own_omics_driven is a restatement of that arm and cannot be independent of it"
    ),
}
_QUALIFIER_REASON_MIN_LEN = 40


def _arm_false_sites() -> set:
    """(module, enclosing function) for every `bump_corroboration(..., arm=False)` in production code,
    found by AST so a reformat or a renamed local cannot hide one from a text matcher."""
    found = set()
    for path in sorted(_CLAIMS_DIR.glob("*.py")):
        tree = ast.parse(path.read_text())
        for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            for call in [n for n in ast.walk(fn) if isinstance(n, ast.Call)]:
                name = getattr(call.func, "id", None) or getattr(call.func, "attr", None)
                if name != "bump_corroboration":
                    continue
                for kw in call.keywords:
                    if kw.arg == "arm" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                        found.add((path.stem, fn.name))
    return found


def test_every_same_arm_qualifier_is_declared_with_a_reason():
    """A qualifier bump is the floor's one loophole, so each use is declared and each declaration is
    checked live, in BOTH directions.

    Known residual hole, stated rather than papered over: nothing static can tell that a NEW bump
    trigger is a same-arm qualifier that FORGOT `arm=False` — that direction is covered behaviourally
    below for the two axes where it actually happened, and by review for the rest."""
    declared = set(_DECLARED_QUALIFIER_SITES)
    actual = _arm_false_sites()
    assert not (declared - actual), (
        f"DANGLING qualifier declaration(s) {sorted(declared - actual)}: declared as same-arm but no "
        f"`arm=False` bump found. If the site became a genuine second arm, drop the declaration."
    )
    assert not (actual - declared), (
        f"UNDECLARED same-arm qualifier(s) {sorted(actual - declared)}. Passing `arm=False` asserts the "
        f"trigger is not an independent arm — say why, next to the other declarations."
    )
    for site, reason in _DECLARED_QUALIFIER_SITES.items():
        assert len(reason) >= _QUALIFIER_REASON_MIN_LEN, f"{site}: reason too thin to audit ({reason!r})"


def test_a_qualifier_cannot_carry_a_lone_arm_to_the_top_rung():
    """BEHAVIOURAL companion, on the two axes that actually did it. Both headlines describe exactly ONE
    measured arm plus a qualifier, so anything above `single_arm` is the over-claim this branch exists to
    remove — reached, before 2026-09-14, at the TOP rung."""
    genomic = importlib.import_module("_skills_common.genomic_claims")
    dependency = importlib.import_module("_skills_common.dependency_claims")

    # DEP (genomic): the pharmacology arm ran and found no stratification -> the genetic arm stands
    # alone. A within-indication scope says that lone arm is well localised, not that a second agreed.
    got = genomic._dep_corroboration(
        {
            "drug_response_stratification_class": "not_drug_response_stratified",
            "stratified_evidence_scope": "within_indication",
        },
        {},
    )
    assert got == "single_arm", f"a scope token lifted one arm to {got!r}"

    # DEP (dependency): one CRISPR arm, no concordance read, no RNAi, no PRISM, no consortium arm —
    # only the predictability meta-signal, which is a model fit on that same arm.
    got = dependency._dep_corroboration(
        {"crispr_call": "strongly_selective", "predictability_class": "own_omics_driven"},
        {},
    )
    assert CORROBORATION_ORD[got] <= CORROBORATION_ORD["single_arm"], (
        f"own_omics_driven lifted a lone CRISPR arm to {got!r}, above the arm floor"
    )


# ── convention A: a MEASURED NEGATIVE keeps a corroboration tier (user decision, 2026-09-14) ─────────
def test_a_measured_negative_signal_keeps_a_corroboration_tier():
    """SPL and ROLE used to collapse a measured `absent` signal into `unmeasured` corroboration, which is
    `gap != absent` broken one level up: `no_registered_event` and `passenger` are findings, not gaps.
    Convention A (SNV/CN/FUS) is now fleet-wide."""
    genomic = importlib.import_module("_skills_common.genomic_claims")

    spl = genomic._spl_corroboration(
        {"genomic_alteration_by_class": {"splice": {"verdict": "no_registered_event", "n_depmap_carriers": 0}}}, {}
    )
    assert spl != "unmeasured", "a consulted splice registry reporting no event is not a gap"
    assert spl in CORROBORATION_ORD and CORROBORATION_ORD[spl] is not None

    role = genomic._role_corroboration({"alteration_role": "passenger", "functional_direction": "ambiguous"}, {})
    assert role != "unmeasured", "a curated passenger call is a finding, not a gap"
    assert role == "single_arm", f"one curated arm, no definitive direction -> single_arm, got {role!r}"


def test_the_second_arm_is_read_RELATIVE_to_a_negative_signal():
    """The half that makes convention A safe. Once a negative signal keeps a tier, the second arm has to
    be compared against the SIDE the first arm took — testing the second token on its own turns a real
    contradiction into agreement. This is the `_snv_corroboration` lesson applied to SPL and ROLE."""
    genomic = importlib.import_module("_skills_common.genomic_claims")

    # Registry says NO registered event; DepMap sees carriers. The arms CONTRADICT -> `low`, not `high`.
    conflict = genomic._spl_corroboration(
        {"genomic_alteration_by_class": {"splice": {"verdict": "no_registered_event", "n_depmap_carriers": 7}}}, {}
    )
    assert conflict == "low", f"registry-negative vs carriers-present is a conflict, got {conflict!r}"
    # Both arms agree there is no event -> a corroborated NEGATIVE.
    agree = genomic._spl_corroboration(
        {"genomic_alteration_by_class": {"splice": {"verdict": "no_registered_event", "n_depmap_carriers": 0}}}, {}
    )
    assert agree == "high", f"two arms agreeing on a measured negative is corroboration, got {agree!r}"
    # A positive signal keeps its old meaning: carriers CONFIRM a driver call.
    assert (
        genomic._spl_corroboration(
            {"genomic_alteration_by_class": {"splice": {"verdict": "recurrent_splice_driver", "n_depmap_carriers": 3}}},
            {},
        )
        == "high"
    )
    # DepMap not consulted -> the arm leaves the frame either way, on both signal sides.
    for verdict in ("recurrent_splice_driver", "no_registered_event"):
        assert (
            genomic._spl_corroboration(
                {"genomic_alteration_by_class": {"splice": {"verdict": verdict, "n_depmap_carriers": None}}}, {}
            )
            == "single_arm"
        ), verdict

    # ROLE: a definitive direction CONTRADICTS `passenger` and AGREES with a driver call.
    assert (
        genomic._role_corroboration({"alteration_role": "passenger", "functional_direction": "activating"}, {}) == "low"
    )
    assert (
        genomic._role_corroboration({"alteration_role": "direct_driver_gof", "functional_direction": "activating"}, {})
        == "high"
    )
