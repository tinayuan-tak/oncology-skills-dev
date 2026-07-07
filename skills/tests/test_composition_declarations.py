"""Framework-level test: every compositional skill's SKILL.md must carry a
valid `composition:` front-matter block.

This test enforces the discipline that skills declare their shape
(cards_used, rules_scope, synthesis, output_shape, phase, steps_covered,
optional_lenses, status). Skills without valid front-matter should NOT
ship — the test fails so a reviewer catches the drift in PR.

Skills exempt from this check:
  - `_skills_common/` — internal package, not a skill
  - `tests/` — this directory
  - Non-compositional skills (workflow-target-evaluation-onc, query-target-
    evidence, compose-dashboard, render-evidence-package) are exempted by
    the SKILLS_TO_CHECK explicit inclusion list — extend when a skill is
    refactored to declare composition.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SKILLS_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SKILLS_DIR))

from _skills_common.composition_schema import (
    CompositionError,
    validate_skill_md,
)


# Compositional skills — every SKILL.md in this list MUST have a valid
# composition block. Discovered dynamically to catch new additions.
def _discover_compositional_skills() -> list[str]:
    """Auto-discover skills that declare a composition block.

    A skill counts as "compositional" if its SKILL.md contains a top-level
    `composition:` YAML key. Legacy skills without composition are ignored.
    """
    compositional: list[str] = []
    for skill_dir in sorted(SKILLS_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue
        if skill_dir.name.startswith("_") or skill_dir.name == "tests":
            continue
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.exists():
            continue
        # Cheap peek: does the front-matter mention 'composition:'?
        text = skill_md.read_text()
        if "\ncomposition:" in text or text.startswith("composition:"):
            compositional.append(skill_dir.name)
    return compositional


@pytest.mark.parametrize("skill_name", _discover_compositional_skills())
def test_composition_declaration_valid(skill_name: str):
    """Every compositional skill's SKILL.md validates against the schema.

    Failures point to the specific field + skill so debug is fast.
    """
    skill_md = SKILLS_DIR / skill_name / "SKILL.md"
    try:
        composition = validate_skill_md(skill_md)
    except CompositionError as e:
        pytest.fail(
            f"skill {skill_name!r} composition invalid: {e}\n"
            f"file: {skill_md}\n"
            f"Fix the front-matter block per _skills_common/composition_schema.py."
        )
    # Sanity: composition object was populated
    assert composition.data_mode
    assert composition.phase
    assert composition.synthesis
    assert composition.output_shape
    assert composition.steps_covered


def test_at_least_one_wired_skill_per_phase():
    """Coverage regression: for each phase A-K, ensure at least one skill
    declares that phase (wired OR placeholder). Un-covered phases would
    be invisible to users, defeating the transparency invariant.

    Placeholders count. This test asserts the skill catalog is *complete*
    at the phase-declaration level; whether the wiring is real is a
    separate check via `status` field on each skill.
    """
    phase_coverage: dict[str, list[str]] = {p: [] for p in "ABCDEFGHIJK"}
    for skill_name in _discover_compositional_skills():
        skill_md = SKILLS_DIR / skill_name / "SKILL.md"
        try:
            composition = validate_skill_md(skill_md)
        except CompositionError:
            continue  # earlier test covers this
        for p in composition.phase:
            if p in phase_coverage:
                phase_coverage[p].append(skill_name)

    uncovered = [p for p, skills in phase_coverage.items() if not skills]
    assert not uncovered, (
        f"Phases {uncovered} have NO skills declaring them. "
        f"Add a wired skill OR a placeholder (see _skills_common.emit_placeholder). "
        f"Phase coverage: {phase_coverage}"
    )
