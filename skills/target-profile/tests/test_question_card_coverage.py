"""REVERSE-COVERAGE GUARD — every card a skill actually consumes (run.py CARDS) must be anchored in at
least one of that skill's question sets (target_profiling_axes.yaml skill_objectives[].questions[].answered_by).

Why this exists: the ontology already guards the FORWARD direction (test_skill_question_sets — every
answered_by resolves to a real card, so `drift` is 0). But nothing guarded the REVERSE — a card added to
a skill's run.py CARDS without a matching answered_by is silently STRANDED (unanswered by any question).
The 2026-08-19 revive/cross-wire PRs stranded 6 cards exactly this way (found by a manual multi-agent
audit, fixed in target-contracts). This test makes "every consumed card answers a question" a CI
invariant so that class of ontology-lag can't recur — a future card-wiring PR fails here until the
ontology is updated too.

Cross-repo: reads the ontology from TARGET_CONTRACTS_ROOT. Graceful-skip only if the contracts checkout
is absent (isolated CI); otherwise it ENFORCES.
"""
from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
import yaml

_SKILLS = Path(__file__).resolve().parents[2]                       # .../skills
_CONTRACTS = Path(os.environ.get(
    "TARGET_CONTRACTS_ROOT",
    "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))
_AXES = _CONTRACTS / "vocabularies" / "target_profiling_axes.yaml"

# Skills exempt from reverse-coverage: target-intrinsic DISPLAYS cards homed in sibling skills (its
# questions cover only its 7 exclusive cards, by design — see the ontology H2 note). Add a skill here
# ONLY with a documented reason.
_EXEMPT_SKILLS = frozenset({"target-intrinsic"})


def _run_py_cards(skill: str) -> set[str]:
    """The card_ids a skill's run.py declares (CARDS + SUBTYPE_CARDS), via AST (no import/exec)."""
    rp = _SKILLS / skill / "scripts" / "run.py"
    if not rp.exists():
        return set()
    out: set[str] = set()
    for node in ast.walk(ast.parse(rp.read_text())):
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in ("CARDS", "SUBTYPE_CARDS"):
                    try:
                        out |= {e for e in ast.literal_eval(node.value) if isinstance(e, str)}
                    except (ValueError, SyntaxError):
                        pass
    return out


def _answered_by(skill_obj: dict) -> set[str]:
    return {c for q in (skill_obj.get("questions") or []) for c in (q.get("answered_by") or [])}


def _skill_objectives() -> list[dict]:
    doc = yaml.safe_load(_AXES.read_text()) or {}
    return doc.get("skill_objectives") or []


@pytest.mark.skipif(not _AXES.exists(), reason="target-contracts ontology not present (isolated CI)")
def test_every_consumed_card_is_anchored_in_a_question():
    """For every skill with a question set, each card it consumes (run.py CARDS) must appear in some
    question's answered_by. Stranded cards (consumed but unanswered) fail here."""
    stranded: dict[str, list[str]] = {}
    checked = 0
    for s in _skill_objectives():
        skill = s.get("skill")
        if not skill or skill in _EXEMPT_SKILLS or not s.get("questions"):
            continue
        cards = _run_py_cards(skill)
        if not cards:                                  # skill dir absent / no CARDS → nothing to check
            continue
        checked += 1
        missing = sorted(cards - _answered_by(s))
        if missing:
            stranded[skill] = missing
    assert checked >= 6, f"expected to check the core question-bearing skills, only checked {checked}"
    assert not stranded, (
        "reverse-coverage: run.py CARDS not anchored in any question answered_by "
        f"(add them to target_profiling_axes.yaml skill_objectives[].questions): {stranded}"
    )


@pytest.mark.skipif(not _AXES.exists(), reason="target-contracts ontology not present")
def test_exempt_skills_are_deliberate():
    """target-intrinsic is exempt because it displays sibling-homed cards; keep the exemption list tight."""
    skills = {s.get("skill") for s in _skill_objectives()}
    assert _EXEMPT_SKILLS <= skills, f"exempt skills not in ontology: {_EXEMPT_SKILLS - skills}"
