"""Drift guard (2026-08-08): every field the headline reads via get_card_field(cards, <card>, <field>)
must be a field that card actually EMITS (declared in its target-contracts summary_fields).

Why: run.py's _headline had TWO silent field-name drift bugs — it read `dependency_class` on the RNAi
card (which emits `rnai_dependency_class`) and `lineage_selectivity_class` on the lineage card (which
emits `enrichment_class`). get_card_field returns None for an absent key, so both headline fields
rendered null on every run despite the cards classifying a live signal — the dossier looked
self-contradictory (verdict `lineage_selective` alongside `lineage_selectivity: None`) and under-
reported evidence. The VERDICT was unaffected (it reads the fired-rule list, not the headline), so
no existing verdict test caught it. This asserts the headline's card reads match the card contracts.

S3-free: parses run.py's get_card_field calls (AST-lite regex) + each card's summary_fields from the
target-contracts card YAML. Skips gracefully if target-contracts isn't checked out alongside.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

SKILL_DIR = Path(__file__).resolve().parent.parent
RUN_PY = SKILL_DIR / "scripts" / "run.py"
CONTRACTS = SKILL_DIR.parent.parent.parent / "rnd-computational-biology-oncology-target-contracts"
CARDS_DIR = CONTRACTS / "cards"


def _headline_reads() -> list[tuple[str, str]]:
    """(card_id, field) pairs the skill reads via get_card_field(cards, "<card>", "<field>")."""
    src = RUN_PY.read_text()
    return re.findall(r'get_card_field\(\s*cards,\s*["\']([a-z0-9-]+)["\'],\s*["\']([a-z0-9_]+)["\']', src)


def _summary_fields(card_id: str) -> set[str] | None:
    """The set of field names a card DECLARES it emits (summary_fields list). None if card absent."""
    spec = CARDS_DIR / f"{card_id}.card.yaml"
    if not spec.is_file():
        return None
    doc = yaml.safe_load(spec.read_text()) or {}
    # summary_fields lives under outputs: (list of scalars or {name: ...} dicts)
    outputs = doc.get("outputs") or {}
    fields = outputs.get("summary_fields") or doc.get("summary_fields") or []
    names = set()
    for f in fields:
        if isinstance(f, str):
            names.add(f)
        elif isinstance(f, dict):
            names.update(f.keys())
    return names


@pytest.mark.skipif(not CARDS_DIR.is_dir(), reason="target-contracts not checked out alongside")
@pytest.mark.parametrize("card_id,field", _headline_reads())
def test_headline_field_is_emitted_by_card(card_id, field):
    """Each headline get_card_field read must name a field the card declares in summary_fields —
    else it silently renders None (the rnai_dependency_class / enrichment_class drift bugs)."""
    declared = _summary_fields(card_id)
    if declared is None:
        pytest.skip(f"card spec {card_id} not found")
    assert field in declared, (
        f"_headline reads get_card_field(cards, {card_id!r}, {field!r}) but {card_id} does not "
        f"declare {field!r} in its summary_fields — it will silently render None. "
        f"Declared fields: {sorted(declared)}"
    )
