"""surface-modality-fit --verdict-only lean-set safety.

The skill passes verdict_cards=sorted(verdict_relevant_cards("surface_modality")) to the dispatcher.
That set MUST be a non-empty SUBSET of the skill's declared CARDS — otherwise the dispatcher cannot
prove the lean is safe and falls back to reading ALL cards. This guards the subset invariant and
catches the drift where the resolver grows a rung keying a card the skill does not consume.
"""
from __future__ import annotations

import ast
import copy
import json
import os
import runpy
import sys
import tempfile
from pathlib import Path

import pytest
import yaml

_SK = Path(__file__).resolve().parent.parent.parent   # .../claude-oncology-skills/skills
sys.path.insert(0, str(_SK))
os.environ.setdefault(
    "TARGET_CONTRACTS_ROOT",
    str(_SK.parent.parent / "rnd-computational-biology-oncology-target-contracts"),
)

from _skills_common.reachability import verdict_relevant_cards  # noqa: E402

SKILL_DIR = Path(__file__).resolve().parent.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
FIXTURES = SKILL_DIR / "tests" / "fixtures"


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


def _real_summary(s) -> bool:
    return (isinstance(s, dict) and bool(s)
            and not s.get("_freeze_error") and not s.get("_dispatcher_returned_none"))


def test_verdict_only_run_does_not_crash_and_populates_verdict(monkeypatch):
    """RUNTIME lean guard (was AST-only): run run.py --verdict-only end-to-end through the REAL
    dispatcher with only the live reader monkeypatched (mirrors the replay test). In lean mode the
    dispatcher reads ONLY the ~5 verdict-relevant cards, but _headline reads enrichment cards
    (surface-topology-and-ptm, ...) via get_card_field, which RAISES on an absent card_id. This
    reproduces the KeyError crash (abort before decision.json) and asserts exit 0 + a populated,
    non-collapsed surface_modality_verdict."""
    fx = FIXTURES / "ceacam5_coadread.yaml"
    if not fx.exists():
        pytest.skip(f"no frozen fixture at {fx} — run freeze_fixture.py against live S3")
    frozen = yaml.safe_load(fx.read_text()) or {}

    import _skills_common as skc

    def _fake_dispatcher_factory():
        def _read_live(card_id, target_, indication_, *args, **kwargs):
            s = frozen.get(card_id)
            if not _real_summary(s):
                return None
            return copy.deepcopy(s)
        return _read_live

    out_dir = Path(tempfile.mkdtemp(prefix="smf-lean-"))
    monkeypatch.delenv("FRAMEWORK_HEALTH_SMOKE", raising=False)
    monkeypatch.setattr(skc, "_import_dispatcher", _fake_dispatcher_factory)
    monkeypatch.setattr(sys, "argv", ["run.py", "--target", "CEACAM5", "--indication", "COADREAD",
                                      "--verdict-only", "--out", str(out_dir)])
    try:
        runpy.run_path(str(RUN_PY), run_name="__main__")
    except SystemExit as e:
        assert e.code in (0, None), f"run.py --verdict-only exited non-zero ({e.code}) — lean crash"

    decision_path = out_dir / "decision.json"
    assert decision_path.exists(), "run.py --verdict-only wrote no decision.json (crashed before emit)"
    d = json.loads(decision_path.read_text())
    h = d.get("headline") or {}
    v = h.get("surface_modality_verdict")
    assert v not in (None, "", "insufficient", "modality_ambiguous"), (
        f"lean-mode surface_modality_verdict={v!r} collapsed — the verdict spine did not resolve.")
    assert h.get("driving_rule_id"), "lean run resolved a verdict but driving_rule_id is empty."
