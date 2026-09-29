"""Every committed card must validate against card.schema.json (2026-09-12).

card.schema.json is the structural contract for all 148 cards, and validate_cards' Layer 1
(`_structural_check`) enforces it — but NOTHING in this suite ran that layer over the committed
corpus. `schemas/card.schema.json` was loaded by exactly one test module
(tests/schemas/test_phase4_extensions.py), and only to validate hand-built in-test fixtures.

The consequence: the only executor of the structural layer against real cards was
`validators/architecture_dashboard/living/build_living_doc.py`, i.e. `make atlas-check` — a
LOCAL drift-guard that is not a CI job and takes minutes to run. So a card edit could violate the
schema, pass the full 594-test suite AND pass CI, and only surface as an `error`-severity gap in a
dashboard feed somebody regenerates later.

Found the honest way: the v1.2.0 edit to paralog-buffering.card.yaml in this PR broke BOTH
maxLength ceilings (caveats 500, warning_predicates[].message 300) and the entire suite stayed
green. Only the atlas noticed. The corpus is otherwise clean (0/148 violations), so this guard
lands green — it is a ratchet, not a backlog.

Anti-vacuity note: `iter_errors` on a card that passes yields nothing, so a per-card
parametrization that silently found no cards would also be green. The count assertions below make
the discovery itself part of the contract.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from jsonschema import Draft202012Validator

REPO = Path(__file__).resolve().parents[2]
CARDS_DIR = REPO / "cards"
CARD_FILES = sorted(CARDS_DIR.glob("*.card.yaml"))
_SCHEMA = json.loads((REPO / "schemas" / "card.schema.json").read_text())
_VALIDATOR = Draft202012Validator(_SCHEMA)


def test_cards_were_discovered():
    """The parametrization below is vacuous if the glob misses; pin a floor."""
    assert len(CARD_FILES) >= 140, (
        f"only {len(CARD_FILES)} cards found under {CARDS_DIR} — the corpus is ~148. A bad glob "
        "makes every parametrized case below disappear rather than fail."
    )


@pytest.mark.parametrize("card_path", CARD_FILES, ids=lambda p: p.name[: -len(".card.yaml")])
def test_card_validates_against_card_schema(card_path: Path):
    spec = yaml.safe_load(card_path.read_text())
    errors = sorted(_VALIDATOR.iter_errors(spec), key=lambda e: list(e.absolute_path))
    if not errors:
        return
    detail = "\n".join(
        f"  [{'.'.join(str(p) for p in e.absolute_path) or '<root>'}] {e.validator}"
        f"={e.validator_value if not isinstance(e.validator_value, (dict, list)) else '...'}: "
        f"{e.message[:200]}"
        for e in errors
    )
    pytest.fail(
        f"{card_path.name} violates schemas/card.schema.json ({len(errors)} error(s)):\n{detail}\n"
        "This is validate_cards' Layer 1 (_structural_check) — an `error`-severity atlas gap, not a "
        "style nit. Prose ceilings are the usual cause: caveats maxLength 500, "
        "warning_predicates[].message maxLength 300."
    )
