"""Tests for the structural→editorial field-disposition projection + review queue.

The projection is a review-ranking HEURISTIC, so these tests do not pin the specific mapping
choices (those are documented, contestable defaults). They pin the two hard invariants — the
projection is TOTAL over the structural roles and lands only in the editorial vocabulary — plus the
non-vacuity of the review queue (it actually flags a contradiction) and the coverage arithmetic.
"""

from __future__ import annotations

from _skills_common import field_descriptor as fd
from _skills_common import field_disposition_ledger as ledger
from _skills_common import field_disposition_projection as proj


def _row(role, reviewed=None):
    r = {"role": role, "reason": "test row"}
    if reviewed is not None:
        r["reviewed"] = reviewed
    return r


# ── the hard invariant: TOTAL over the structural roles, both directions ────────────────────────
def test_projection_is_total_over_structural_roles():
    # every structural role is either projected or explicitly declared unprojectable — no role falls
    # through silently (this reds the day field_descriptor gains a 12th ROLE without a decision here).
    covered = set(proj.STRUCTURAL_TO_EDITORIAL) | set(proj.UNPROJECTABLE_ROLES)
    assert covered == set(fd.ROLES), {
        "missing": sorted(set(fd.ROLES) - covered),
        "extra": sorted(covered - set(fd.ROLES)),
    }


def test_projection_and_unprojectable_are_disjoint():
    assert not (set(proj.STRUCTURAL_TO_EDITORIAL) & set(proj.UNPROJECTABLE_ROLES))


def test_projected_values_are_editorial_vocabulary():
    assert set(proj.STRUCTURAL_TO_EDITORIAL.values()) <= set(ledger.VALID_ROLES)


def test_unclassified_is_unprojectable():
    assert proj.project(fd.ROLE_UNCLASSIFIED) is None
    assert fd.ROLE_UNCLASSIFIED in proj.UNPROJECTABLE_ROLES


def test_unknown_role_projects_to_none():
    assert proj.project("not_a_role") is None


# ── review queue: non-vacuity + specificity ─────────────────────────────────────────────────────
def _a_field_with_structural_role(role: str) -> str:
    """A real emitted field name that field_descriptor classifies as `role` (self-adjusting, so the
    test does not hard-code a name whose classification could drift)."""
    for f in fd._flat_index():
        if fd.classify_field(f) == role:
            return f
    raise AssertionError(f"no field classifies as {role!r}")


def test_review_queue_flags_a_contradiction():
    effect_field = _a_field_with_structural_role(fd.ROLE_EFFECT)
    assert proj.project(fd.ROLE_EFFECT) == "signal"
    # park a structural effect field under the editorial role `display` — a contradiction.
    doc = {"_meta": {"roles": {}}, "some-card": {effect_field: _row("display")}}
    q = proj.review_queue(doc)
    assert len(q) == 1
    assert q[0].field == effect_field
    assert q[0].current_role == "display"
    assert q[0].projected_role == "signal"


def test_review_queue_is_silent_when_role_matches_projection():
    effect_field = _a_field_with_structural_role(fd.ROLE_EFFECT)
    doc = {"_meta": {}, "some-card": {effect_field: _row("signal")}}
    assert proj.review_queue(doc) == []


def test_review_queue_skips_unprojectable_rows():
    # a field with no descriptor (unclassified) must not appear, whatever its editorial role.
    assert fd.classify_field("a_field_with_no_descriptor_xyz") == fd.ROLE_UNCLASSIFIED
    doc = {"some-card": {"a_field_with_no_descriptor_xyz": _row("display")}}
    assert proj.review_queue(doc) == []


def test_unreviewed_sorts_before_reviewed():
    effect_field = _a_field_with_structural_role(fd.ROLE_EFFECT)
    doc = {
        "card-a": {effect_field: _row("display", reviewed=True)},
        "card-b": {effect_field: _row("display", reviewed=False)},
    }
    q = proj.review_queue(doc)
    assert len(q) == 2
    assert q[0].reviewed is False and q[1].reviewed is True


# ── coverage dimension arithmetic ─────────────────────────────────────────────────────────────────
def test_coverage_summary_partitions_rows():
    effect_field = _a_field_with_structural_role(fd.ROLE_EFFECT)
    doc = {
        "card": {
            effect_field: _row("signal"),  # agree
            "a_field_with_no_descriptor_xyz": _row("display"),  # unprojectable
        }
    }
    cov = proj.coverage_summary(doc)
    assert cov["rows"] == cov["agree"] + cov["contradict"] + cov["unprojectable"]
    assert cov["rows"] == 2
    assert cov["agree"] == 1 and cov["unprojectable"] == 1


def test_real_ledger_is_computable():
    # the shipped tumor-presence ledger must produce a coherent (non-raising) summary. Numbers are a
    # DIMENSION, not a ratchet — they drift as descriptors/ledger evolve, so only the arithmetic is
    # pinned, never the counts.
    from pathlib import Path

    import yaml

    ledger_path = Path(__file__).resolve().parents[2] / "tumor-presence" / "field_disposition.yaml"
    doc = yaml.safe_load(ledger_path.read_text())
    cov = proj.coverage_summary(doc)
    assert cov["rows"] > 0
    assert cov["rows"] == cov["agree"] + cov["contradict"] + cov["unprojectable"]
    # the queue length equals the contradiction count
    assert len(proj.review_queue(doc)) == cov["contradict"]
