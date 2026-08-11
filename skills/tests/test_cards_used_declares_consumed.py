"""Guard B — every card a skill CONSUMES must be DECLARED in its SKILL.md composition.cards_used.

Bug class: a skill grows a new consumed card (added to its run.py CARDS / SUBTYPE_CARDS constant)
but its SKILL.md under-declares it. Consequences: cited_by / coverage tooling undercounts the card
(so it looks unused and risks deprecation while a skill silently depends on it), and the
on_dependency_status map can't govern an undeclared card. The dispatcher docstring claims this drift
is "structurally impossible", but nothing enforced it — test_composition_declarations only checks
schema validity, not CARDS ⊆ cards_used. This test closes that gap.

Invariant: (run.py CARDS ∪ SUBTYPE_CARDS) ⊆ SKILL.md composition.cards_used, for every skill that
has a CARDS constant and a composition block. AST-parses run.py (no import); reads SKILL.md
front-matter. (cards_used MAY legitimately be a superset — e.g. it also declares subtype-only cards.)
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest
import yaml

SKILLS_DIR = Path(__file__).resolve().parent.parent


def _list_const(tree: ast.Module, name: str):
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name) and node.targets[0].id == name
                and isinstance(node.value, ast.List)):
            return [e.value for e in node.value.elts
                    if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return None


def _cards_used(skill_dir: Path):
    md = skill_dir / "SKILL.md"
    if not md.exists():
        return None
    m = re.match(r"^---\n(.*?)\n---", md.read_text(), re.S)
    if not m:
        return None
    try:
        doc = yaml.safe_load(m.group(1))
    except Exception:
        return None
    cu = ((doc or {}).get("composition") or {}).get("cards_used")
    if not isinstance(cu, list):
        return None
    out = []
    for c in cu:
        if isinstance(c, str):
            out.append(c)
        elif isinstance(c, dict):
            out.append(c.get("card_id") or c.get("id"))
    return {c for c in out if c}


def _cases():
    cases = []
    for d in sorted(SKILLS_DIR.iterdir()):
        if not d.is_dir() or d.name.startswith("_") or d.name == "tests":
            continue
        run = d / "scripts" / "run.py"
        if not run.exists():
            continue
        tree = ast.parse(run.read_text())
        cards = _list_const(tree, "CARDS")
        if not cards:
            continue
        declared = _cards_used(d)
        if declared is None:
            continue
        consumed = set(cards) | set(_list_const(tree, "SUBTYPE_CARDS") or [])
        cases.append((d.name, sorted(consumed), declared))
    return cases


_CASES = _cases()


def test_at_least_a_few_skills_discovered():
    # sanity: the discovery isn't silently empty (which would make the guard vacuous)
    assert len(_CASES) >= 8, f"only {len(_CASES)} skills discovered — CARDS/cards_used parsing changed?"


@pytest.mark.parametrize("name,consumed,declared", _CASES, ids=[c[0] for c in _CASES])
def test_consumed_cards_are_declared_in_skill_md(name, consumed, declared):
    undeclared = sorted(set(consumed) - declared)
    assert not undeclared, (
        f"{name}: run.py consumes card(s) {undeclared} not declared in SKILL.md "
        f"composition.cards_used. Add them there — an undeclared consumed card is undercounted "
        f"by cited_by/coverage tooling and can't be governed by on_dependency_status.")
