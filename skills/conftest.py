"""Repo-level pytest fixtures shared across all skill test suites.

pytest auto-discovers this conftest from any test collected under `skills/` — both the per-skill
suites (`skills/<skill>/tests/`, each run in its own process by CI) and the cross-skill guard suite
(`skills/tests/`). Shared test scaffolding therefore lives here in ONE place instead of being
copy-pasted into every skill's tests/. Fixtures ONLY — no autouse fixtures and no collection hooks —
so merely adding this file changes the behavior of no existing test; a test opts in by naming a
fixture in its signature.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


def _contracts_root() -> Path | None:
    root = Path(os.environ.get(
        "TARGET_CONTRACTS_ROOT",
        "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))
    return root if (root / "cards").is_dir() else None


def _skill_cards(skill_dir: Path) -> list[str]:
    """The skill's consumed CARDS, read from its scripts/run.py. Loaded under a throwaway module
    name and NOT registered in sys.modules — one run.py per (isolated per-skill) process, so no
    cross-run.py import collision."""
    run_py = skill_dir / "scripts" / "run.py"
    spec = importlib.util.spec_from_file_location("_skill_cards_probe", run_py)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return list(m.CARDS)


def _card_measurement_type(card_id: str) -> str | None:
    root = _contracts_root()
    if root is None:
        return None
    p = root / "cards" / f"{card_id}.card.yaml"
    if not p.exists():
        return None
    return (yaml.safe_load(p.read_text()) or {}).get("measurement_type")


def _check_hierarchy_wellformed(skill_dir: Path) -> None:
    """The yaml is well-formed: named skill, sub-groups each with >=1 question, questions declare
    measurement_types, other_lenses declare a lens. Always runs (credential-less)."""
    hier_path = skill_dir / "question_hierarchy.yaml"
    assert hier_path.exists(), f"missing {hier_path}"
    h = yaml.safe_load(hier_path.read_text()) or {}
    assert h.get("skill")
    assert h.get("sub_groups"), "no sub_groups"
    for sg in h["sub_groups"]:
        assert sg.get("id"), "sub-group missing id"
        assert sg.get("questions"), f"sub-group {sg.get('id')} has no questions"
        for q in sg["questions"]:
            assert q.get("id") and q.get("measurement_types"), f"bad question in {sg['id']}"
    for e in h.get("other_lenses", []):
        assert e.get("lens") and e.get("measurement_types"), "other_lens missing lens/types"


def _check_hierarchy_connectivity(skill_dir: Path) -> None:
    """THE RATCHET: bind each consumed card by its real measurement_type. Every card must be a
    question SOURCE, context, or routed to another lens — no same-question orphan. And every question
    must have >=1 source card among the skill's CARDS. Self-skips when target-contracts is absent."""
    if _contracts_root() is None:
        pytest.skip("target-contracts not resolvable (set TARGET_CONTRACTS_ROOT) — connectivity skipped")
    h = yaml.safe_load((skill_dir / "question_hierarchy.yaml").read_text()) or {}
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
    for card in _skill_cards(skill_dir):
        mt = _card_measurement_type(card)
        if mt is None:
            continue  # no measurement_type => not a per-target claim (e.g. population ranking); exempt
        if mt in q_types:
            for key in q_types[mt]:
                sourced[key] = True
        elif mt in ctx_types or mt in lens_types:
            continue
        else:
            orphans.append((card, mt))
    unsourced = [k for k, v in sourced.items() if not v]
    assert not orphans, ("same-question orphans (measure a question this skill owns but bound to "
                         f"nothing — add to a question, route to a lens, or mark context): {orphans}")
    assert not unsourced, f"questions with no source card among CARDS: {unsourced}"


@pytest.fixture
def hierarchy_connectivity():
    """Shared question-hierarchy connectivity guard — the body that was copy-pasted byte-identically
    into 13 skills' test_hierarchy_connectivity.py.

    Returns a namespace with two checks, each taking the skill dir:
      - .wellformed(skill_dir)   — always runs; the question_hierarchy.yaml is structurally valid.
      - .connectivity(skill_dir) — the RATCHET; skipif target-contracts absent. Binds each CARD by its
                                   real measurement_type and asserts orphan-free + every question sourced.
    Each per-skill shim passes its own SKILL_DIR, so the run.py CARDS load stays one-run.py-per-process
    inside that skill's isolated suite.
    """
    return SimpleNamespace(
        wellformed=_check_hierarchy_wellformed,
        connectivity=_check_hierarchy_connectivity,
    )
