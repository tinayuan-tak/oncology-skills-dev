"""Question-hierarchy connectivity guard — thin shim over the shared `hierarchy_connectivity`
fixture (skills/conftest.py).

Enforces the tree  skill > sub-group > question > card > data-signal: every consumed CARD must bind
to a question (by measurement_type), be routed to another lens, or be context — else it is a
SAME-QUESTION ORPHAN. Also: every question must have >=1 source card. The shared body lives in
skills/conftest.py (was copy-pasted byte-identically across 13 skills)."""
from __future__ import annotations

from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent


def test_hierarchy_wellformed(hierarchy_connectivity):
    hierarchy_connectivity.wellformed(SKILL_DIR)


def test_connectivity_no_orphans_every_question_sourced(hierarchy_connectivity):
    hierarchy_connectivity.connectivity(SKILL_DIR)
