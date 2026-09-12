"""`stable_projection` is the drift guard's definition of "a wiring change".

Two failure modes, and this file pins both ends against each other:

  too WIDE  → --check fires on sibling churn (a skills-repo version bump, the live health
              overlay, the absolute checkout root), so STALE stops meaning anything and the
              committed feed can only be cleared by an unrelated target-contracts PR.
  too NARROW → --check stops firing on a real wiring change, and the guard is decoration.

The volatility tests below are only meaningful if the committed feed actually carries the
fields they strip, so each asserts the pre-strip difference is real before asserting the
post-strip equality.
"""

from __future__ import annotations

import copy
import json

import pytest
from _util import builder, load_committed

_VOLATILE_SKILL_FIELDS = ("version", "status", "health")
# The wiring the guard exists to protect: changing any of these MUST move the projection.
_WIRING_SKILL_FIELDS = (
    "cards_used",
    "rules_scope",
    "measurement_types_pulled",
    "verdict_bearing_cards",
    "display_cards",
    "gates",
    "fanout",
    "synthesis",
    "output_shape",
    "data_mode",
    "is_composed_root",
)


def _proj(graph: dict) -> str:
    return builder().stable_projection(graph)


def _skills(graph: dict) -> dict:
    skills = graph.get("skills") or {}
    assert isinstance(skills, dict) and skills, "committed atlas has no skills section"
    return skills


def test_committed_feed_carries_the_fields_these_tests_strip():
    """Non-vacuity for the whole file: if the feed stopped emitting these, the tests below
    would pass by having nothing to perturb."""
    skills = _skills(load_committed())
    for field in _VOLATILE_SKILL_FIELDS + ("md_path",):
        n = sum(1 for s in skills.values() if field in s)
        assert n == len(skills), f"only {n}/{len(skills)} skill entries carry '{field}'"


@pytest.mark.parametrize("field", _VOLATILE_SKILL_FIELDS)
def test_projection_ignores_per_skill_sibling_churn(field):
    """A skills-repo landing bumps `version`; a health run rewrites `status`/`health`. Neither
    is a target-contracts wiring change, so neither may make the committed feed STALE."""
    base = load_committed()
    churned = copy.deepcopy(base)
    for s in _skills(churned).values():
        s[field] = f"churn-{field}"
    assert json.dumps(base, sort_keys=True) != json.dumps(churned, sort_keys=True), (
        f"perturbing '{field}' did not change the graph — test is vacuous"
    )
    assert _proj(base) == _proj(churned), (
        f"stable_projection is sensitive to skill '{field}', which moves on sibling churn alone; "
        "--check will report STALE for changes no target-contracts PR caused"
    )


def test_projection_ignores_the_checkout_root_of_md_path():
    """`md_path` is absolute, so it differs between a /tmp worktree and the primary checkout.
    A guard whose verdict depends on WHERE it runs is not a guard."""
    base = load_committed()
    moved = copy.deepcopy(base)
    for s in _skills(moved).values():
        if s.get("md_path"):
            s["md_path"] = str(s["md_path"]).replace("/home/", "/tmp/wt/some-other-checkout/home/")
    assert json.dumps(base, sort_keys=True) != json.dumps(moved, sort_keys=True), (
        "no md_path was rewritten — test is vacuous"
    )
    assert _proj(base) == _proj(moved), "stable_projection depends on the checkout root of md_path"


def test_projection_still_sees_an_md_rename():
    """The other half of the md_path decision: the basename is kept, because a skill's md being
    renamed IS a wiring change. Reduced to a basename, not dropped."""
    renamed = copy.deepcopy(load_committed())
    victim = sorted(_skills(renamed))[0]
    md = _skills(renamed)[victim].get("md_path")
    assert md, f"skill {victim} has no md_path to rename"
    _skills(renamed)[victim]["md_path"] = str(md).replace("SKILL.md", "RENAMED.md")
    assert _proj(load_committed()) != _proj(renamed), (
        "stable_projection ignores the md basename — a skill file rename would land silently"
    )


@pytest.mark.parametrize("field", _WIRING_SKILL_FIELDS)
def test_projection_detects_a_skill_wiring_change(field):
    """The non-vacuity end. Every field the atlas presents as wiring must be guarded; adding
    one to the skills payload without adding it here leaves it unguarded, which is how
    `version` came to be treated as wiring in the first place."""
    base = load_committed()
    changed = copy.deepcopy(base)
    victim = next((k for k, s in sorted(_skills(changed).items()) if field in s), None)
    assert victim, f"no skill entry carries '{field}' — atlas payload changed, update this list"
    s = _skills(changed)[victim]
    cur = s[field]
    s[field] = (list(cur) + ["__sentinel__"]) if isinstance(cur, list) else f"__sentinel__{cur}"
    assert _proj(base) != _proj(changed), (
        f"stable_projection ignores skill '{field}' on {victim}: a change to it would not make "
        "the committed atlas STALE, so the guard would not ask for a regen"
    )


def test_projection_survives_a_list_shaped_skills_section():
    """`skills` is a dict today. The strip must not blow up (or silently no-op) if that ever
    becomes a list — the previous code shape would have skipped it entirely."""
    graph = load_committed()
    as_list = copy.deepcopy(graph)
    as_list["skills"] = list(_skills(as_list).values())
    for s in as_list["skills"]:
        s["version"] = "churn"
    out = json.loads(_proj(as_list))
    assert isinstance(out.get("skills"), list) and out["skills"], "skills list lost in projection"
    assert not any("version" in s for s in out["skills"]), "list-shaped skills kept volatile 'version'"


def test_projection_strips_top_level_snapshots():
    """Regression fence on the keys the projection already stripped, including the two whose
    per-skill copies were the actual leak (`health`)."""
    out = json.loads(_proj(load_committed()))
    for key in ("generated_at", "root_shas", "health_overlay_at", "health", "coverage", "gaps"):
        assert key not in out, f"stable_projection leaked time-varying top-level '{key}'"
    for s in (out.get("skills") or {}).values():
        for key in _VOLATILE_SKILL_FIELDS:
            assert key not in s, f"stable_projection leaked per-skill '{key}'"


def test_projection_keeps_the_skills_section_itself():
    """Over-stripping fence: the fix removes fields, not the section. If `skills` vanished the
    volatility tests above would all pass and the guard would be blind to every skill."""
    out = json.loads(_proj(load_committed()))
    skills = out.get("skills") or {}
    assert len(skills) == len(_skills(load_committed())), "projection dropped skill entries"
    assert any(s.get("cards_used") for s in skills.values()), "projection dropped cards_used wiring"


def test_projection_is_deterministic():
    graph = load_committed()
    assert _proj(graph) == _proj(copy.deepcopy(graph))
