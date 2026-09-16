"""Completeness guard for AXIS_TO_DIM: no subskill axis may reach no risk dim SILENTLY.

The 6-dim risk projection (`_skills_common/risk_projection.py`) maps verdict-bearing subskill axes onto
the 5R governance dims. An axis MISSING from that map is invisible: nothing distinguished

    "this axis must never reach a risk dim"        (settled, correct)
    "nobody wired this axis up yet"                (a gap nobody can see)

and both read as an absence. An absence cannot be reviewed, so the map drifted — the 2026-08-21
consolidation dropped two mapped axes (synthetic_lethal_partners / combinatorial_dependency) while the
comment above AXIS_TO_DIM went on claiming "every grounded axis now reaches a risk dim". Measured on the
504-target corpus, 7 of the 16 rostered axes reach no dim, so that claim was false.

The repair is a PARTITION, not a wider map: every rostered axis must be in exactly one of
{AXIS_TO_DIM, AXIS_DIM_EXCLUSIONS}. This file is the ratchet.

THE MAP MUST NOT BECOME A RUG. The load-bearing test here is
`test_declared_descriptive_axes_are_genuinely_verdictless`: a `declared_descriptive` entry claims the
axis has NO verdict to project, and that claim is checked against narrator_lenses' own `verdict_key`.
Without it, silencing this guard for a live verdict-bearing axis would be a one-line edit — i.e. the
guard would be satisfiable by assertion rather than by fact.

★ SCOPE CORRECTION 2026-09-16 (same day): "absent from AXIS_TO_DIM" does NOT mean "reaches no dim".
`report_render.ir._CONTEXT_DIM` is a SECOND map that already routes 6 of the 7 declared-excluded axes
onto a dim as `context` companions; only `subtype_fit` is in neither. The two maps are deliberately
disjoint — AXIS_TO_DIM is the verdict-bearing membership, _CONTEXT_DIM the descriptive companions — and
this file now pins that disjointness, because `_dim_members` renders both without deduping.

★ THERE ARE THREE MAPS, and this file is the ratchet over all three, because they answer three different
questions about the same axis and every pair of them can drift:

    AXIS_TO_DIM        is it a VERDICT-bearing member of the dim?         (risk_projection)
    ir._CONTEXT_DIM    is it DISPLAYED under the dim as a companion?      (report_render)
    COVERAGE_ONLY_AXES does its EVIDENCE count toward the dim's coverage? (risk_projection)

The defect that forced the third one (measured 2026-09-16): the report DISPLAYED 6 axes under `biological`
while the coverage line COUNTED 4, hiding 14291 resolved cards corpus-wide under dims whose own coverage
lines did not count them. Note the asymmetry these guards encode — coverage counts CARDS, so an axis with
`verdict_fn=None` can legitimately be counted (`combination_vulnerability`: no verdict, 3024 cards) while
a permanently-`undescribed` axis must NOT be, because its caveat would fire on every run.

Oracles (both in-repo, neither hand-maintained here):
  - the roster        = target-profile's SUB_SKILLS literal (+ SUBTYPE_SHORT), parsed via ast like
                        test_data_product_lock_coverage.py, so no heavy tp_fanout import;
  - verdict-bearing   = `_skills_common.narrator_lenses.LENSES[<skill dir>].verdict_key is not None`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _skills_common.narrator_lenses import LENSES
from _skills_common.report_render.ir import _CONTEXT_DIM
from _skills_common.risk_projection import (
    AXIS_DIM_EXCLUSION_STATES,
    AXIS_DIM_EXCLUSIONS,
    AXIS_TO_DIM,
    COVERAGE_ONLY_AXES,
    DECLARED_DESCRIPTIVE,
    OPEN_PENDING_REVIEW,
)

SKILLS_DIR = Path(__file__).resolve().parent.parent
TP_FANOUT = SKILLS_DIR / "target-profile" / "scripts" / "tp_fanout.py"

# The 6 governance dims. `clinical` / `commercial` are fed by engine-blind pseudo-cards, not by any
# subskill axis, so they legitimately appear in AXIS_TO_DIM without being rostered shorts.
KNOWN_DIMS = {"biological", "druggability", "safety", "translational", "clinical", "commercial"}
PSEUDO_CARD_AXES = {"clinical", "commercial"}


def _roster() -> dict[str, str]:
    """Rostered fan-out axis short -> its skill dir name, from tp_fanout's own literals."""
    tree = ast.parse(TP_FANOUT.read_text())
    shorts: dict[str, str] = {}
    subtype: str | None = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        names = {getattr(t, "id", None) for t in node.targets}
        if "SUB_SKILLS" in names:
            shorts.update({e.elts[1].value: e.elts[0].value for e in node.value.elts})
        elif "SUBTYPE_SHORT" in names:
            subtype = node.value.value
    assert shorts, "SUB_SKILLS literal not found in tp_fanout.py"
    assert subtype, "SUBTYPE_SHORT literal not found in tp_fanout.py"
    shorts[subtype] = ""  # rostered but NOT a fan-out member and NOT lens-backed (no skill dir here)
    return shorts


def _verdict_bearing(skill_dir: str) -> bool | None:
    """True/False from the lens' verdict_key; None when the axis has no lens (not lens-backed)."""
    lens = LENSES.get(skill_dir)
    return None if lens is None else lens.verdict_key is not None


def test_every_rostered_axis_is_mapped_or_declared():
    """The partition. A new axis cannot reach no dim without a DECLARED reason — that is the ratchet."""
    roster = set(_roster())
    mapped = set(AXIS_TO_DIM) & roster
    declared = set(AXIS_DIM_EXCLUSIONS)

    both = mapped & declared
    assert not both, f"axes both mapped AND declared-excluded (ambiguous): {sorted(both)}"

    silent = roster - mapped - declared
    assert not silent, (
        f"axes reach NO risk dim and NO declaration explains why: {sorted(silent)}. "
        "Add each to AXIS_TO_DIM, or to AXIS_DIM_EXCLUSIONS with a reason. Do not delete this test."
    )

    stray = declared - roster
    assert not stray, f"AXIS_DIM_EXCLUSIONS declares non-rostered axes: {sorted(stray)}"


def test_axis_to_dim_extra_keys_are_exactly_the_pseudo_card_dims():
    """AXIS_TO_DIM may hold non-roster keys ONLY for the engine-blind pseudo-card dims."""
    extra = set(AXIS_TO_DIM) - set(_roster())
    assert extra == PSEUDO_CARD_AXES, (
        f"unexpected non-roster keys in AXIS_TO_DIM: {sorted(extra - PSEUDO_CARD_AXES)}; "
        f"missing expected pseudo-card keys: {sorted(PSEUDO_CARD_AXES - extra)}"
    )


def test_axis_to_dim_targets_only_known_dims():
    unknown = set(AXIS_TO_DIM.values()) - KNOWN_DIMS
    assert not unknown, f"AXIS_TO_DIM points at dims outside the 5R set: {sorted(unknown)}"


def test_declared_descriptive_axes_are_genuinely_verdictless():
    """THE ANTI-RUG TEST. `declared_descriptive` asserts "no verdict to project" — check it against
    narrator_lenses rather than trusting the declaration, so this guard cannot be silenced by parking a
    live verdict-bearing axis in the exclusions map.
    """
    roster = _roster()
    offenders = []
    for short, entry in AXIS_DIM_EXCLUSIONS.items():
        if entry["state"] != DECLARED_DESCRIPTIVE:
            continue
        bearing = _verdict_bearing(roster[short])
        assert bearing is not None, (
            f"{short} is declared_descriptive but has no lens to check the claim against; "
            "a declaration nothing can falsify is not a declaration"
        )
        if bearing:
            offenders.append(short)
    assert not offenders, (
        f"declared_descriptive but VERDICT-BEARING (lens verdict_key is set): {sorted(offenders)}. "
        "A live axis cannot be excluded as 'descriptive' — either map it, or mark it "
        f"{OPEN_PENDING_REVIEW!r}."
    )


def test_open_pending_review_axes_are_verdict_bearing_or_lensless():
    """The converse: an OPEN entry must have something to project, else it belongs in the settled half."""
    roster = _roster()
    for short, entry in AXIS_DIM_EXCLUSIONS.items():
        if entry["state"] != OPEN_PENDING_REVIEW:
            continue
        bearing = _verdict_bearing(roster[short])
        assert bearing is not False, (
            f"{short} is {OPEN_PENDING_REVIEW!r} but its lens declares verdict_key=None — there is "
            f"nothing to decide; it belongs in {DECLARED_DESCRIPTIVE!r}"
        )


def test_open_pending_review_set_is_pinned():
    """Pin the OPEN set so neither direction happens silently: a NEW unjustified absence reds here, and
    RESOLVING one is a deliberate edit to this list.

    ★ RETRACTED 2026-09-16 (same day): this docstring used to say "mapping it, which moves bins", and
    the assertion message below claimed mapping needs "golden snapshots + a corpus re-measure". BOTH
    FALSE. `deterministic_bins` never reads AXIS_TO_DIM — mapping all three OPEN axes and re-projecting
    504 targets x 5 modalities moved 0 of 2520 bins while changing 2520 of 2520 evidence_coverage
    payloads (paired control, so the null is real). Mapping is a VISIBILITY change. See the retraction
    comment above AXIS_DIM_EXCLUSIONS in risk_projection.py for the three readers and why none bins.

    RE-MEASURED 2026-09-16 on the 504-target corpus (corpus-20260915). Live verdict counts at the time:
    cis_coherence 504/504 non-null over 7 states; immune_context 504/504 over 5; subtype_fit 71/504
    non-null over 3 (and 0/504 skill_reports, so no cards_used provenance at all).
    """
    open_axes = {s for s, e in AXIS_DIM_EXCLUSIONS.items() if e["state"] == OPEN_PENDING_REVIEW}
    assert open_axes == {"cis_coherence", "immune_context", "subtype_fit"}, (
        f"the set of undecided axes changed: {sorted(open_axes)}. If an axis was MAPPED, drop it from "
        "AXIS_DIM_EXCLUSIONS here too. Mapping does NOT move bins (measured: 0/2520), but it DOES change "
        "the dim's coverage line and its displayed member list => expect report goldens to move. If a "
        "NEW axis appeared, it needs a decision, not a quiet exclusion."
    )


def test_axis_to_dim_and_context_dim_are_disjoint():
    """THE DUPLICATE-MEMBER GUARD. `ir._dim_members` appends the AXIS_TO_DIM members and then the
    _CONTEXT_DIM members with NO DEDUPE, so an axis in both maps is DISPLAYED TWICE under the same dim —
    once as verdict-bearing, once as `context`. The two maps are disjoint today by discipline alone, and
    the obvious "just map it" fix for an OPEN axis (add cis_coherence to AXIS_TO_DIM, leave it in
    _CONTEXT_DIM) trips it immediately. Promote the axis, don't copy it.
    """
    both = sorted(set(AXIS_TO_DIM) & set(_CONTEXT_DIM))
    assert not both, (
        f"axes in BOTH AXIS_TO_DIM and ir._CONTEXT_DIM: {both}. ir._dim_members does not dedupe, so each "
        "would render twice under its dim. If an axis graduated to verdict-bearing, REMOVE it from "
        "_CONTEXT_DIM in the same change."
    )


def test_context_dim_axes_are_declared_in_the_exclusions_map():
    """A gateless axis may be a DISPLAY companion (_CONTEXT_DIM) while absent from AXIS_TO_DIM — but it
    must still carry a declared reason here, so "displayed but not counted as evidence" stays a reviewed
    state rather than an accident. Measured 2026-09-16: the 6 _CONTEXT_DIM axes carry 14291 resolved
    cards that their dim DISPLAYS but whose coverage line does not count.
    """
    undeclared = sorted(set(_CONTEXT_DIM) - set(AXIS_DIM_EXCLUSIONS) - set(AXIS_TO_DIM))
    assert not undeclared, (
        f"ir._CONTEXT_DIM routes axes to a dim with no entry in AXIS_DIM_EXCLUSIONS: {undeclared}. An "
        "axis displayed under a dim but uncounted in its coverage needs that asymmetry declared."
    )


def test_coverage_only_axes_are_context_axes_routed_to_the_SAME_dim():
    """THE ANTI-DRIFT GUARD for the counted-vs-displayed join. `COVERAGE_ONLY_AXES` exists to make the
    coverage line count what the dim already DISPLAYS, so every entry must (a) actually be a `_CONTEXT_DIM`
    display companion and (b) name the SAME dim. If the two disagreed, the report would count an axis's
    cards under one dim while listing the axis under another — a coverage number attributable to a member
    the reader cannot see, which is worse than the undercount this map was added to fix.
    """
    not_displayed = sorted(set(COVERAGE_ONLY_AXES) - set(_CONTEXT_DIM))
    assert not not_displayed, (
        f"COVERAGE_ONLY_AXES counts axes that ir._CONTEXT_DIM does not display: {not_displayed}. Counting "
        "an axis the dim never lists attributes evidence to an invisible member. Add it to _CONTEXT_DIM "
        "or drop it here."
    )
    mismatched = {a: (d, _CONTEXT_DIM[a]) for a, d in COVERAGE_ONLY_AXES.items() if _CONTEXT_DIM[a] != d}
    assert not mismatched, (
        f"COVERAGE_ONLY_AXES and ir._CONTEXT_DIM disagree about the dim, {{axis: (counted, displayed)}}: {mismatched}"
    )


def test_coverage_only_axes_are_disjoint_from_axis_to_dim():
    """An axis in BOTH would be counted twice in one dim's `axes_declared` — `evidence_coverage_by_dim`
    merges the two maps. AXIS_TO_DIM membership already implies being counted, so an entry here is
    redundant at best; the merge order would silently let this map RE-ROUTE a verdict-bearing axis to a
    different dim than the one it is displayed and literature-annotated under.
    """
    both = sorted(set(COVERAGE_ONLY_AXES) & set(AXIS_TO_DIM))
    assert not both, (
        f"axes in BOTH AXIS_TO_DIM and COVERAGE_ONLY_AXES: {both}. AXIS_TO_DIM axes are already counted; "
        "remove the duplicate rather than relying on the merge order."
    )


def test_coverage_only_axes_add_no_new_dim():
    """`evidence_coverage_by_dim` iterates the dim set from AXIS_TO_DIM alone, so an entry pointing at a
    dim no verdict-bearing axis feeds would be SILENTLY DROPPED — its cards counted nowhere, which reads
    exactly like the undercount this map fixes. Fail loudly instead.
    """
    orphans = sorted({d for d in COVERAGE_ONLY_AXES.values()} - set(AXIS_TO_DIM.values()))
    assert not orphans, (
        f"COVERAGE_ONLY_AXES points at dims absent from AXIS_TO_DIM.values(): {orphans}. "
        "evidence_coverage_by_dim would never emit those dims, so the entries would be inert."
    )


def test_coverage_only_axes_are_declared_and_verdictless():
    """Being COUNTED for coverage must not smuggle an axis out of the declaration partition. Coverage
    counts CARDS and AXIS_TO_DIM records VERDICT membership, so an axis can legitimately be counted while
    staying declared-excluded — but it must still carry a reason, and it must not be a verdict-bearing axis
    that is being quietly satisfied here INSTEAD of having its `open_pending_review` question answered.
    """
    undeclared = sorted(set(COVERAGE_ONLY_AXES) - set(AXIS_DIM_EXCLUSIONS))
    assert not undeclared, f"COVERAGE_ONLY_AXES entries with no AXIS_DIM_EXCLUSIONS reason: {undeclared}"

    # `immune_context` / `cis_coherence` are still OPEN as VERDICT members; counting their evidence does
    # not resolve that, and this test exists so nobody reads the coverage change as having resolved it.
    still_open = sorted(a for a in COVERAGE_ONLY_AXES if AXIS_DIM_EXCLUSIONS[a]["state"] == OPEN_PENDING_REVIEW)
    assert still_open == ["cis_coherence", "immune_context"], (
        f"the counted-but-still-OPEN set changed: {still_open}. Counting an axis's EVIDENCE is not the same "
        "decision as making it a VERDICT member of the dim; if that verdict question was answered, move "
        "the axis into AXIS_TO_DIM (and out of _CONTEXT_DIM and this map) rather than editing this list."
    )


def test_permanently_undescribed_axes_are_not_counted():
    """The inclusion rule, pinned. `translational_readiness` and `literature_context` are `undescribed` on
    504/504 corpus runs, so counting them adds a caveat that ALWAYS fires and no signal. `literature_context`
    is worse than useless: it is `commercial`'s only context axis, so counting it replaces that dim's honest
    "card-fed dim — no subskill axis reports into it" with "0/1 axes measured" — a MEASURED CLAIM OF
    BLINDNESS about a dim that is card-fed by design (measured: 504/504 targets change that line).

    Not a style rule: this is the corpus-measured reason the naive "union the two maps" fix is wrong. If a
    SALIENCE_SPEC later covers these measurement_types, re-measure first, then edit both this list and the
    inclusion-rule comment.
    """
    forbidden = sorted(set(COVERAGE_ONLY_AXES) & {"translational_readiness", "literature_context"})
    assert not forbidden, (
        f"permanently-undescribed axes counted in a dim's coverage: {forbidden}. They are undescribed on "
        "504/504 runs, so they contribute a constant caveat; literature_context additionally turns "
        "commercial's card-fed guard into '0/1 axes measured'. Re-measure before changing this."
    )


def test_exclusion_entries_are_well_formed():
    for short, entry in AXIS_DIM_EXCLUSIONS.items():
        assert set(entry) == {"state", "reason"}, f"{short}: unexpected keys {sorted(entry)}"
        assert entry["state"] in AXIS_DIM_EXCLUSION_STATES, f"{short}: bad state {entry['state']!r}"
        reason = entry["reason"]
        # A one-word reason is how a declaration decays back into an absence.
        assert isinstance(reason, str) and len(reason) >= 80, f"{short}: reason too thin to review"


def test_axis_to_dim_still_covers_every_verdict_bearing_lens_or_declares_it():
    """The oracle-driven form of the same invariant, stated over narrator_lenses rather than the roster —
    this is the one that would have caught the 2026-08-21 drift at the time it happened.
    """
    roster = _roster()
    undeclared = [
        short
        for short, skill_dir in roster.items()
        if _verdict_bearing(skill_dir) and short not in AXIS_TO_DIM and short not in AXIS_DIM_EXCLUSIONS
    ]
    assert not undeclared, f"verdict-bearing axes with no dim and no declaration: {sorted(undeclared)}"
