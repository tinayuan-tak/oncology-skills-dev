"""The two-axis field-disposition contract: ``semantic_role`` × ``interpretation_reach`` (issue #1525).

WHY TWO AXES
------------
A single ``role`` token (``signal`` / ``context`` / ``provenance`` / ``display``) was overloaded to
answer two DIFFERENT questions at once:

  1. WHAT KIND of thing is this field?  — a decisive call, a qualifier, an audit token, a display detail.
  2. HOW FAR does its interpretation reach? — is it read by anything, and if so, WHERE?

Conflating them produced two recurring errors. A field could be tagged ``display`` ("verdict-inert by
design") purely because the auto-draft heuristic's fallback was ``display`` — the field was never
judged, only defaulted (see the tumor-presence ledger ``_meta``). And a raw measurement consumed ONLY
by the cross-repo analysis-methods property resolver looked like a dead ``context`` scalar, because the
skills-side census cannot see a reader in another repo — so it could neither be shown to have reach nor
correctly kept OFF ``signal``.

THE TWO AXES ARE ORTHOGONAL
---------------------------
``semantic_role`` and ``interpretation_reach`` are independent. The load-bearing example is the
cell-line RNA distribution family:

  * ``distribution_pattern`` / ``coefficient_of_variation`` have ``interpretation_reach =
    cross_repo_resolver`` — they ARE consumed, by the analysis-methods ``_heterogeneity`` resolver —
    yet their ``semantic_role`` stays ``context``, NOT ``signal``. In the evidence-property ontology the
    SIGNAL attaches to the RESOLVED PROPERTY (``expression_properties``, computed in analysis-methods),
    never to the raw skills-side measurement. So "it has reach" (axis 2) must not be read as "it is a
    signal" (axis 1). Reach answers *is this field consumed, and where*; role answers *what is it*.

This is the correction the reach axis exists to make: a cross-repo resolver input is no longer a
census-invisible orphan (it has ``cross_repo_resolver`` reach), and it is no longer mis-promoted to
``signal`` (its role is still the qualifier it always was).

VERDICT-INERT / DATA-PACKAGE
----------------------------
Neither axis feeds a verdict. This is the L1 disposition layer of the evidence-property architecture
(#1507): its job is to make the emitted data package accurate and fully-attributed — every field
correctly typed (role) and correctly shown to be consumed or not (reach) — not to move
``presence_verdict``. "verdict-inert is the point," not a limitation.
"""

from __future__ import annotations

# ── axis 1: semantic role ───────────────────────────────────────────────────────────────────────────
ROLE_SIGNAL = "signal"
ROLE_CONTEXT = "context"
ROLE_PROVENANCE = "provenance"
ROLE_DISPLAY = "display"
SEMANTIC_ROLES = (ROLE_SIGNAL, ROLE_CONTEXT, ROLE_PROVENANCE, ROLE_DISPLAY)

# ── axis 2: interpretation reach ──────────────────────────────────────────────────────────────────
#: No declared reader reaches the field — a candidate orphan (a REVIEW queue, never a delete list).
REACH_UNREACHED = "unreached"
#: Reached by a reader inside the skills tree (a rule, capsule, salience ruler, code read, gloss, …).
REACH_SKILLS_LOCAL = "skills_local"
#: Reached by the analysis-methods property resolver — realised in another repo, on the resolved
#: property, not on this raw measurement. The strongest reach a raw skills-side field can carry.
REACH_CROSS_REPO_RESOLVER = "cross_repo_resolver"
INTERPRETATION_REACH = (REACH_UNREACHED, REACH_SKILLS_LOCAL, REACH_CROSS_REPO_RESOLVER)

# Ordered weakest → strongest, so a field reached BOTH locally and cross-repo reports its FURTHEST
# reach. "How far does its interpretation travel" is a max over its readers, not a set.
_REACH_ORDER = {REACH_UNREACHED: 0, REACH_SKILLS_LOCAL: 1, REACH_CROSS_REPO_RESOLVER: 2}


def interpretation_reach_for(reader_set: dict, cross_repo_kinds=None) -> str:
    """Map a census reader-set ``{"exact": {kind,...}, "name_only": {kind,...}}`` to its reach axis value.

    Furthest reach wins: any cross-repo kind ⇒ ``cross_repo_resolver``; else any reader at all ⇒
    ``skills_local``; else ``unreached``. Both ``exact`` and ``name_only`` count for the local/unreached
    boundary — a field is "unreached" only when NOTHING declares it — but a cross-repo kind is credited
    exactly as the census records it.
    """
    if cross_repo_kinds is None:
        from _skills_common.field_disposition import CROSS_REPO_KINDS as cross_repo_kinds
    cross = set(cross_repo_kinds)
    exact = set(reader_set.get("exact") or ())
    name_only = set(reader_set.get("name_only") or ())
    if exact & cross or name_only & cross:
        return REACH_CROSS_REPO_RESOLVER
    if exact or name_only:
        return REACH_SKILLS_LOCAL
    return REACH_UNREACHED


# ── the 4-case migration audit (legacy_role × is-it-an-L2-input) ──────────────────────────────────
# The legacy single-role ledger drafted its fallback as ``display`` ("verdict-inert by design"). But a
# field with reach — local OR cross-repo — is an INPUT to an L2 claim/property, not a display detail.
# Crossing the legacy role against "does it reach an L2 input" (== has any interpretation reach) sorts
# every field into four cases; the one the audit ACTS on is the under-consumption corner: a field parked
# in ``display`` that in fact reaches an input.
CASE_INPUT_ALREADY_TYPED = "input_correctly_typed"  # non-display legacy role + reaches an input → keep
CASE_DISPLAY_UNDER_CONSUMED = "display_under_consumed"  # display legacy role + reaches an input → PROMOTE
CASE_DISPLAY_GENUINE = "display_genuine"  # display legacy role + no reach → genuine display, keep
CASE_TYPED_UNREACHED = "typed_unreached"  # non-display legacy role + no reach → review (over-claim?)


def migration_case(legacy_role: str, reach: str) -> str:
    """Which of the four migration cases a ``(legacy_role, interpretation_reach)`` pair falls into."""
    is_input = reach != REACH_UNREACHED
    is_display = legacy_role == ROLE_DISPLAY
    if is_display and is_input:
        return CASE_DISPLAY_UNDER_CONSUMED
    if is_display:
        return CASE_DISPLAY_GENUINE
    if is_input:
        return CASE_INPUT_ALREADY_TYPED
    return CASE_TYPED_UNREACHED
