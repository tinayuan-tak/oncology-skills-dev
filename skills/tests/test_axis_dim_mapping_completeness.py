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

Oracles (both in-repo, neither hand-maintained here):
  - the roster        = target-profile's SUB_SKILLS literal (+ SUBTYPE_SHORT), parsed via ast like
                        test_data_product_lock_coverage.py, so no heavy tp_fanout import;
  - verdict-bearing   = `_skills_common.narrator_lenses.LENSES[<skill dir>].verdict_key is not None`.
"""

from __future__ import annotations

import ast
from pathlib import Path

from _skills_common.narrator_lenses import LENSES
from _skills_common.risk_projection import (
    AXIS_DIM_EXCLUSION_STATES,
    AXIS_DIM_EXCLUSIONS,
    AXIS_TO_DIM,
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
    RESOLVING one (mapping it, which moves bins) is a deliberate edit to this list.

    RE-MEASURED 2026-09-16 on the 504-target corpus (corpus-20260915). Live verdict counts at the time:
    cis_coherence 504/504 non-null over 7 states; immune_context 504/504 over 5; subtype_fit 71/504
    non-null over 3 (and 0/504 skill_reports, so no cards_used provenance at all).
    """
    open_axes = {s for s, e in AXIS_DIM_EXCLUSIONS.items() if e["state"] == OPEN_PENDING_REVIEW}
    assert open_axes == {"cis_coherence", "immune_context", "subtype_fit"}, (
        f"the set of undecided axes changed: {sorted(open_axes)}. If an axis was MAPPED, drop it from "
        "AXIS_DIM_EXCLUSIONS here too (and note that mapping moves bins => golden snapshots + a corpus "
        "re-measure). If a NEW axis appeared, it needs a direction decision, not a quiet exclusion."
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
