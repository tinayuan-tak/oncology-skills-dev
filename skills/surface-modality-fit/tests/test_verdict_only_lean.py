"""surface-modality-fit --verdict-only lean-set safety.

The skill passes verdict_cards=sorted(verdict_relevant_cards("surface_modality")) to the dispatcher.
That set MUST be a non-empty SUBSET of the skill's declared CARDS — otherwise the dispatcher cannot
prove the lean is safe and falls back to reading ALL cards. This guards the subset invariant and
catches the drift where the resolver grows a rung keying a card the skill does not consume.
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

_SK = Path(__file__).resolve().parent.parent.parent   # .../claude-oncology-skills/skills
sys.path.insert(0, str(_SK))
os.environ.setdefault(
    "TARGET_CONTRACTS_ROOT",
    str(_SK.parent.parent / "rnd-computational-biology-oncology-target-contracts"),
)

from _skills_common.reachability import verdict_relevant_cards  # noqa: E402

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"


def _cards_const() -> set:
    for node in ast.parse(RUN_PY.read_text()).body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and getattr(node.targets[0], "id", None) == "CARDS"
                and isinstance(node.value, ast.List)):
            return {e.value for e in node.value.elts if isinstance(e, ast.Constant)}
    return set()


def test_surface_lean_set_is_nonempty_subset_of_cards():
    cards = _cards_const()
    assert cards, "CARDS list not found in surface-modality-fit run.py"
    lean = verdict_relevant_cards("surface_modality")
    assert lean, "empty lean set — dispatcher would fall back to reading ALL cards (lean disabled)"
    missing = lean - cards
    assert not missing, (
        f"surface_modality resolver references card(s) not in surface-modality-fit CARDS: {missing} "
        f"— add them to CARDS (the skill must consume every verdict-relevant card).")
