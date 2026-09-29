"""Roster-driven question-hierarchy connectivity guard.

Consolidates the 13 byte-identical `skills/<skill>/tests/test_hierarchy_connectivity.py` copies into
one cross-skill test that iterates the LIVE skill roster — every skill that ships a
`question_hierarchy.yaml`. Adding the hierarchy file to a new skill automatically extends coverage
here; there is no per-skill test file to copy.

Enforces the tree  skill > sub-group > question > card > data-signal: every consumed CARD must bind
to a question (by measurement_type), be routed to another lens, or be context — else it is a
SAME-QUESTION ORPHAN; and every question must have >=1 source card. The shared checks live in
skills/conftest.py (the `hierarchy_connectivity` fixture)."""

from __future__ import annotations

from pathlib import Path

import pytest

SKILLS_ROOT = Path(__file__).resolve().parents[1]
# The live roster: every skill that declares a question_hierarchy.yaml (13 today).
SKILL_DIRS = sorted((p.parent for p in SKILLS_ROOT.glob("*/question_hierarchy.yaml")), key=lambda d: d.name)
_IDS = [d.name for d in SKILL_DIRS]


def test_roster_is_not_vacuous():
    """Anti-vacuity floor: the glob must find the roster it parametrizes over. If it matched NOTHING
    (hierarchy files relocated/renamed) the parametrized guards below would collect ZERO cases and
    pass by absence — a false green. Pin the roster to the known count."""
    assert len(SKILL_DIRS) >= 13, (
        f"expected >=13 skills with question_hierarchy.yaml, found {_IDS} — the roster glob broke and "
        "the connectivity guards would be vacuous."
    )


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=_IDS)
def test_hierarchy_wellformed(skill_dir, hierarchy_connectivity):
    hierarchy_connectivity.wellformed(skill_dir)


@pytest.mark.parametrize("skill_dir", SKILL_DIRS, ids=_IDS)
def test_connectivity_no_orphans_every_question_sourced(skill_dir, hierarchy_connectivity):
    hierarchy_connectivity.connectivity(skill_dir)
