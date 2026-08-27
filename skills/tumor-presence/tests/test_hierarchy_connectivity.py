"""Question-hierarchy connectivity guard (signals-first hierarchy spec v0.1).

Encodes + ENFORCES the tree  skill > sub-group > question > card > data-signal  for tumor-presence:
every consumed CARD must bind to a question (by measurement_type), or be routed to another lens, or
be context — else it is a SAME-QUESTION ORPHAN (a card that measures a question this skill owns but
is used by nothing). Also: every question must have >=1 source card; every sub-group >=1 question.
This is what guarantees the cards are fully used toward the key questions.

Two tiers (mirrors the disposition-ledger test):
  - wellformed        — always runs (credential-less): the yaml parses, covers run.py CARDS' roles.
  - connectivity      — skipif target-contracts absent: the RATCHET — binds each card by its real
                        measurement_type and asserts orphan-free + every question sourced.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
HIER = SKILL_DIR / "question_hierarchy.yaml"
RUN_PY = SKILL_DIR / "scripts" / "run.py"


def _hier() -> dict:
    assert HIER.exists(), f"missing {HIER}"
    return yaml.safe_load(HIER.read_text()) or {}


def _cards() -> list[str]:
    spec = importlib.util.spec_from_file_location("_tp_cards", RUN_PY)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return list(m.CARDS)


def _contracts_root() -> Path | None:
    root = Path(os.environ.get(
        "TARGET_CONTRACTS_ROOT",
        "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))
    return root if (root / "cards").is_dir() else None


def _mt(card_id: str) -> str | None:
    root = _contracts_root()
    p = root / "cards" / f"{card_id}.card.yaml"
    if not p.exists():
        return None
    return (yaml.safe_load(p.read_text()) or {}).get("measurement_type")


def test_hierarchy_wellformed():
    """The yaml is well-formed: named skill, sub-groups each with >=1 question, questions declare
    measurement_types, other_lenses declare a lens."""
    h = _hier()
    assert h.get("skill")
    assert h.get("sub_groups"), "no sub_groups"
    for sg in h["sub_groups"]:
        assert sg.get("id"), "sub-group missing id"
        assert sg.get("questions"), f"sub-group {sg.get('id')} has no questions"
        for q in sg["questions"]:
            assert q.get("id") and q.get("measurement_types"), f"bad question in {sg['id']}"
    for e in h.get("other_lenses", []):
        assert e.get("lens") and e.get("measurement_types"), "other_lens missing lens/types"


@pytest.mark.skipif(_contracts_root() is None,
                    reason="target-contracts not resolvable (set TARGET_CONTRACTS_ROOT) — connectivity skipped")
def test_connectivity_no_orphans_every_question_sourced():
    """THE RATCHET: bind each consumed card by its real measurement_type. Every card must be a
    question SOURCE, context, or routed to another lens — no same-question orphan. And every question
    must have >=1 source card among the skill's CARDS."""
    h = _hier()
    q_types, ctx_types, sourced = {}, set(), {}
    for sg in h["sub_groups"]:
        for c in sg.get("context_types", []):
            ctx_types.add(c)
        for q in sg["questions"]:
            sourced[(sg["id"], q["id"])] = False
            for mt in q["measurement_types"]:
                q_types.setdefault(mt, []).append((sg["id"], q["id"]))
    lens_types = {mt for e in h.get("other_lenses", []) for mt in e["measurement_types"]}

    orphans = []
    for card in _cards():
        mt = _mt(card)
        if mt in q_types:
            for key in q_types[mt]:
                sourced[key] = True
        elif mt in ctx_types or mt in lens_types:
            continue
        else:
            orphans.append((card, mt))
    unsourced = [k for k, v in sourced.items() if not v]
    assert not orphans, ("same-question orphans (measure a presence question but bound to nothing — "
                         f"add to a question, route to a lens, or mark context): {orphans}")
    assert not unsourced, f"questions with no source card among CARDS: {unsourced}"
