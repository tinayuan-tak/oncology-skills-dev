"""Guard: every summary field a skill READS must be a field the card DECLARES.

`get_card_field(cards, card_id, key)` returns None when `key` is absent from the card's summary —
so a mistyped / drifted field name is a SILENT None, not an error (the wrong-key bug class). This
statically checks every literal `get_card_field(cards, "<card_id>", "<key>")` call across the skills
against that card's declared `outputs.summary_fields` in target-contracts (96/96 cards declare one),
and asserts the read key is declared. It caught, e.g., tumor-presence reading
`cellline-rna-distribution.expression_call_class` (that card emits `expression_class`;
`expression_call_class` is tumor-rna-vs-adjacent's field) → a silent None.

AST-only (no imports, no live reads). Skips cleanly when target-contracts isn't checked out.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

import pytest
import yaml

SKILLS = Path(__file__).resolve().parent.parent


def _contracts_cards_dir():
    root = os.environ.get("TARGET_CONTRACTS_ROOT")
    candidates = []
    if root:
        candidates.append(Path(root) / "cards")
    # THIS checkout's own in-tree contracts/ (SK#2063). Was SKILLS.parent.parent/"rnd-...-target-
    # contracts" — one level above the repo root, i.e. the ARCHIVED pre-merge $HOME clone, so a local
    # run read STALE cards and CI (no such dir) fell through to None and skipped silently (SK#2196).
    candidates.append(SKILLS.parent / "contracts" / "cards")
    for c in candidates:
        if c.is_dir():
            return c
    return None


_CARDS_DIR = _contracts_cards_dir()


def _declared_fields(card_id: str):
    """The card's declared summary field names (outputs.summary_fields), or None if no such card."""
    f = _CARDS_DIR / f"{card_id}.card.yaml"
    if not f.exists():
        return None
    try:
        doc = yaml.safe_load(f.read_text()) or {}
    except Exception:
        return None
    sf = ((doc.get("outputs") or {}).get("summary_fields")) or []
    fields = set()
    for x in sf:  # 95 cards use a flat list of str; 1 (adc-tce) nests dicts
        if isinstance(x, str):
            fields.add(x)
        elif isinstance(x, dict):
            fields.update(k for k in x)
    return fields


def _literal_field_reads():
    """(skill, card_id, key, lineno) for every get_card_field(_, "<card_id>", "<key>") literal call."""
    reads = []
    for run in sorted(SKILLS.glob("*/scripts/run.py")):
        skill = run.relative_to(SKILLS).parts[0]
        tree = ast.parse(run.read_text())
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "get_card_field"
                and len(node.args) >= 3
                and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)
                and isinstance(node.args[2], ast.Constant)
                and isinstance(node.args[2].value, str)
            ):
                reads.append((skill, node.args[1].value, node.args[2].value, node.lineno))
    return reads


# Legitimate exceptions (a skill reads a field a card emits DYNAMICALLY / not in the declared list).
# Each MUST carry a why. Empty today — the one known drift was a real bug (fixed), not a waiver.
_WAIVERS: set[tuple[str, str]] = set()  # {(card_id, field), ...}


def test_field_read_discovery_is_not_vacuous():
    """Anti-vacuity floor for the conformance guard below. That guard iterates
    ``_literal_field_reads()`` — a ``SKILLS.glob("*/scripts/run.py")`` + AST scrape. If the glob
    matches nothing (skills relocated) or the scraper is refactored to return ``[]``, the loop asserts
    over zero reads and the guard passes GREEN having proven nothing (``collected`` stays 1, so the
    collapse is invisible). Pin the corpus to a member count so an emptied discovery goes RED here.
    ~357 reads today; 300 is a slack floor. Independent of target-contracts (reads come from this
    repo's run.py files), so this floor runs even when the conformance guard skips."""
    n = len(_literal_field_reads())
    assert n >= 300, (
        f"only {n} literal get_card_field reads discovered across skills/*/scripts/run.py — the glob "
        "or the AST scraper broke; test_skill_field_reads_are_declared_by_the_card would pass vacuously."
    )


@pytest.mark.skipif(_CARDS_DIR is None, reason="target-contracts cards/ not available")
def test_skill_field_reads_are_declared_by_the_card():
    unknown_card, undeclared = [], []
    for skill, card_id, key, lineno in _literal_field_reads():
        declared = _declared_fields(card_id)
        if declared is None:
            unknown_card.append((skill, card_id, lineno))
            continue
        if key not in declared and (card_id, key) not in _WAIVERS:
            undeclared.append((skill, card_id, key, lineno))
    assert not unknown_card, "get_card_field references a card_id with no card.yaml (typo?): " + "; ".join(
        f"{s}:{ln} -> {c}" for s, c, ln in unknown_card
    )
    assert not undeclared, (
        "get_card_field reads a field NOT in the card's outputs.summary_fields (silent-None drift). "
        "Fix the read, or add the field to the card, or waive with a reason:\n"
        + "\n".join(f"  {s}:{ln}  {c}.{k}" for s, c, k, ln in undeclared)
    )
