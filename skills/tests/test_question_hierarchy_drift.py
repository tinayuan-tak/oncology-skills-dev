"""Drift-CI for the consolidated question hierarchies (signals-first step 7).

The sub-group/question decomposition is the single source of truth in target-contracts
(vocabularies/target_profiling_axes.yaml `question_hierarchies`); each skill's question_hierarchy.yaml
is a generated MIRROR (skills/tools/sync_question_hierarchies.py). This test fails if any committed
mirror diverges from the governed source — so the hierarchy is edited in ONE place and can never
silently drift. skipif target-contracts absent (the source lives there)."""

from __future__ import annotations

from pathlib import Path

import pytest

from _test_support import load_module

SKILLS_DIR = Path(__file__).resolve().parents[1]
TOOL = SKILLS_DIR / "tools" / "sync_question_hierarchies.py"

_sync = load_module(TOOL, "_sync_qh")


@pytest.mark.skipif(
    not _sync.contracts_available(), reason="target-contracts absent (question_hierarchies source lives there)"
)
def test_mirrors_match_contracts_source():
    drift = _sync.check()
    assert drift == [], (
        "question_hierarchy.yaml mirror(s) diverge from the governed contracts source:\n"
        + "\n".join(f"  - {d}" for d in drift)
        + "\nEdit vocabularies/target_profiling_axes.yaml (question_hierarchies) then run "
        "`python skills/tools/sync_question_hierarchies.py --write`."
    )


@pytest.mark.skipif(not _sync.contracts_available(), reason="target-contracts absent")
def test_source_covers_every_skill_with_a_hierarchy():
    """Every skill that ships a question_hierarchy.yaml must have a governed source entry."""
    source_skills = set(_sync.load_source())
    committed = {p.parent.name for p in SKILLS_DIR.glob("*/question_hierarchy.yaml")}
    missing = committed - source_skills
    assert not missing, f"skills with a hierarchy but NO contracts source (would silently un-govern): {missing}"
