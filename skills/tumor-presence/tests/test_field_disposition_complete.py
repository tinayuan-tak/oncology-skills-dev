"""Completeness guard for the field-disposition ledger (field_disposition.yaml).

The ledger makes "are we using all the extracted data?" machine-checkable: every emitted card
summary_field must carry an explicit disposition (signal | context | provenance | display), so a
field is never dropped SILENTLY. This test enforces COMPLETENESS + well-formedness, not tag
correctness (roles are a human judgement, editable by hand).

Two tiers, mirroring the freeze/replay split:
  - test_ledger_wellformed        — always runs (credential-less): valid roles + reasons, covers
                                     exactly run.py CARDS, no duplicate/empty entries.
  - test_ledger_matches_emitted   — skipif target-contracts absent: the RATCHET — the ledger's
                                     fields per card == the card's outputs.summary_fields, so a NEW
                                     emitted field with no disposition (orphan) or a STALE ledger
                                     entry fails CI.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
LEDGER = SKILL_DIR / "field_disposition.yaml"
RUN_PY = SKILL_DIR / "scripts" / "run.py"
VALID_ROLES = {"signal", "context", "provenance", "display"}


def _load_ledger() -> dict:
    assert LEDGER.exists(), f"missing field-disposition ledger at {LEDGER}"
    return yaml.safe_load(LEDGER.read_text()) or {}


def _cards() -> list[str]:
    spec = importlib.util.spec_from_file_location("_tp_run_cards", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return list(m.CARDS)


def _contracts_root() -> Path | None:
    root = Path(os.environ.get(
        "TARGET_CONTRACTS_ROOT",
        "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))
    return root if (root / "cards").is_dir() else None


def _emitted(cid: str) -> list[str]:
    root = _contracts_root()
    p = root / "cards" / f"{cid}.card.yaml"
    if not p.exists():
        return []
    y = yaml.safe_load(p.read_text()) or {}
    return [x for x in (((y.get("outputs") or {}).get("summary_fields")) or []) if isinstance(x, str)]


def test_ledger_wellformed():
    """Every entry has a valid role + non-empty reason; the ledger covers exactly run.py's CARDS."""
    doc = _load_ledger()
    cards = set(_cards())
    ledger_cards = {k for k in doc if not k.startswith("_")}
    assert ledger_cards == cards, (
        f"ledger cards != run.py CARDS. missing={sorted(cards - ledger_cards)} "
        f"extra={sorted(ledger_cards - cards)}")
    for cid in ledger_cards:
        entry = doc[cid]
        if entry.get("_no_contract_fields"):
            continue
        for field, spec in entry.items():
            assert isinstance(spec, dict), f"{cid}.{field}: expected a mapping, got {type(spec).__name__}"
            assert spec.get("role") in VALID_ROLES, f"{cid}.{field}: bad role {spec.get('role')!r}"
            assert str(spec.get("reason") or "").strip(), f"{cid}.{field}: empty reason"


@pytest.mark.skipif(_contracts_root() is None,
                    reason="target-contracts not resolvable (set TARGET_CONTRACTS_ROOT) — drift check skipped")
def test_ledger_matches_emitted_fields():
    """THE RATCHET: ledger fields per card == the card's emitted summary_fields. A new emitted field
    with no disposition (silent-drop risk) or a stale ledger entry fails here."""
    doc = _load_ledger()
    problems = []
    for cid in _cards():
        emitted = set(_emitted(cid))
        if not emitted:
            continue
        entry = {k: v for k, v in (doc.get(cid) or {}).items() if not k.startswith("_")}
        ledger_fields = set(entry)
        orphans = emitted - ledger_fields          # emitted, NO disposition → would be dropped silently
        stale = ledger_fields - emitted            # in ledger, no longer emitted
        if orphans:
            problems.append(f"{cid}: UNCLASSIFIED emitted fields (add a disposition): {sorted(orphans)}")
        if stale:
            problems.append(f"{cid}: STALE ledger fields (card no longer emits): {sorted(stale)}")
    assert not problems, "field-disposition ledger out of sync:\n  " + "\n  ".join(problems)
