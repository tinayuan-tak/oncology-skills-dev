"""field_disposition_projection.py — a REVIEW-RANKING baseline for the field-disposition ledger.

Two role vocabularies describe the same fields from orthogonal angles:

  * STRUCTURAL — field_descriptor.ROLES (11): what a field *is* inside its measurement shape
    (effect / significance / omnibus / n / categorical / frame_value / …).
  * EDITORIAL — field_disposition_ledger.VALID_ROLES (4): what a reader is *licensed to do* with it
    (signal / context / provenance / display).

This module declares a many-to-one DEFAULT projection structural → editorial, and uses it to RANK
which unreviewed ledger rows to review first (a row whose human/heuristic-drafted editorial role
contradicts its structural default is the likeliest mislabel). It is deliberately NOT inside
field_disposition_ledger.py: that module refuses to hold any role-drafting heuristic
(`reviewed: true` is its only truth marker), and the projection MUST NOT write roles into the
ledger — it only points a reviewer at the rows worth looking at. The ledger stays authoritative;
this is an advisory lens.

The projection is a documented heuristic, not ground truth: the whole point of the review queue is
that a `context` field the projection calls `signal` is a QUESTION for a human, not a correction.
What IS enforced (by tests) is that the projection is total over the structural roles and lands only
in the editorial vocabulary.
"""

from __future__ import annotations

from typing import Iterator, Optional

from _skills_common import field_descriptor as _fd
from _skills_common import field_disposition_ledger as _ledger

# ── the projection ──────────────────────────────────────────────────────────────────────────────
# Grounded in the ledger's own _meta definitions:
#   signal     = feeds a claim / verdict
#   context    = qualifies a signal (power, certainty, statistical qualifier, cross-axis pointer)
#   provenance = audit / identity / method token — surfaced, never a signal
#   display    = human-facing detail or large container; verdict-inert
STRUCTURAL_TO_EDITORIAL: dict[str, str] = {
    _fd.ROLE_EFFECT: "signal",  # the measured effect feeds the claim
    _fd.ROLE_FRAME_VALUE: "signal",  # a value gauged on a reference frame — atlas-live, feeds the claim
    _fd.ROLE_CATEGORICAL: "signal",  # the derived `_class` token a rule pattern-matches
    _fd.ROLE_SIGNIFICANCE: "context",  # a q/p value — a statistical qualifier
    _fd.ROLE_OMNIBUS: "context",  # an omnibus test statistic — a statistical qualifier
    _fd.ROLE_N: "context",  # a count — a power qualifier
    _fd.ROLE_STRATA: "context",  # a per-stratum array — a cross-axis (subgroup) qualifier
    _fd.ROLE_EXTRA_SCALAR: "context",  # an auxiliary scalar — most often a qualifier
    _fd.ROLE_LABEL: "display",  # a human-facing name/label — verdict-inert detail
    _fd.ROLE_ENVELOPE: "provenance",  # framework plumbing / identity / method token
}

# Deliberately NOT projected: an `unclassified` field has no structural descriptor, so there is
# nothing to project FROM — it is the descriptor-coverage work queue, a different backlog. Projecting
# it would fabricate an editorial role from the absence of information.
UNPROJECTABLE_ROLES: frozenset = frozenset({_fd.ROLE_UNCLASSIFIED})


def project(structural_role: str) -> Optional[str]:
    """The default editorial disposition for a structural role, or None if unprojectable
    (`unclassified`) or unknown. Never raises."""
    return STRUCTURAL_TO_EDITORIAL.get(structural_role)


# ── the review queue ──────────────────────────────────────────────────────────────────────────────
class Contradiction:
    """One ledger row whose editorial role contradicts its structural default. Ordered so unreviewed
    rows (the actionable backlog) sort before reviewed ones (a human already adjudicated those, and a
    reviewed contradiction is a deliberate override, not a mislabel)."""

    __slots__ = ("card_id", "field", "structural_role", "current_role", "projected_role", "reviewed")

    def __init__(self, card_id, field, structural_role, current_role, projected_role, reviewed):
        self.card_id = card_id
        self.field = field
        self.structural_role = structural_role
        self.current_role = current_role
        self.projected_role = projected_role
        self.reviewed = reviewed

    def _sort_key(self):
        return (self.reviewed, self.card_id, self.field)

    def __repr__(self):
        flag = "reviewed" if self.reviewed else "UNREVIEWED"
        return (
            f"{self.card_id}.{self.field}: {self.structural_role} "
            f"[current={self.current_role} projected={self.projected_role}] {flag}"
        )


def iter_contradictions(doc: dict) -> Iterator[Contradiction]:
    """Every ledger row whose current editorial role differs from its structural default. Rows whose
    structural role is unprojectable (`unclassified`) are skipped — the projection cannot speak to
    them. Uses the ledger's own row iterator so `_meta`/`_`-prefixed keys are handled identically."""
    for card_id, field, spec in _ledger.iter_rows(doc):
        structural = _fd.classify_field(field)
        projected = project(structural)
        if projected is None:
            continue
        current = spec.get("role")
        if current != projected:
            yield Contradiction(card_id, field, structural, current, projected, spec.get("reviewed") is True)


def review_queue(doc: dict) -> list[Contradiction]:
    """The ranked review queue: contradictions, unreviewed first (see Contradiction._sort_key)."""
    return sorted(iter_contradictions(doc), key=lambda c: c._sort_key())


def coverage_summary(doc: dict) -> dict:
    """A DIMENSION (not a gate) over one ledger: how many rows the projection can/can't speak to.
    `unprojectable` is the descriptor-coverage backlog (structural role `unclassified`) — reported,
    never asserted."""
    total = agree = contradict = unprojectable = 0
    for _cid, field, spec in _ledger.iter_rows(doc):
        total += 1
        projected = project(_fd.classify_field(field))
        if projected is None:
            unprojectable += 1
        elif projected == spec.get("role"):
            agree += 1
        else:
            contradict += 1
    return {
        "rows": total,
        "agree": agree,
        "contradict": contradict,
        "unprojectable": unprojectable,  # structural role == unclassified (descriptor gap)
    }


def format_review_queue(doc: dict) -> str:
    """A human-readable report block (report-only; asserts nothing — mirrors the fleet-report
    precedent of a CI-safe advisory). Lists the ranked contradictions and the coverage dimension."""
    cov = coverage_summary(doc)
    lines = [
        "field-disposition review queue (advisory — the projection is a heuristic, not a correction)",
        f"  rows={cov['rows']} agree={cov['agree']} contradict={cov['contradict']} "
        f"unprojectable(unclassified)={cov['unprojectable']}",
    ]
    for c in review_queue(doc):
        lines.append(f"  - {c!r}")
    return "\n".join(lines)


__all__ = [
    "STRUCTURAL_TO_EDITORIAL",
    "UNPROJECTABLE_ROLES",
    "project",
    "Contradiction",
    "iter_contradictions",
    "review_queue",
    "coverage_summary",
    "format_review_queue",
]
