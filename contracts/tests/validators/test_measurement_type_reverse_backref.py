"""Tests for the bidirectional measurement_type <-> card back-reference check (C4, 2026-08-15).

The one-way check (a type's `cards:` back-ref names an EXISTING card) let registry drift pass. The
reverse adds:
  Arm 1 (card -> registry): every card whose measurement_type is a registered type MUST appear in that
    type's `cards:` list (un-migrated cards with no measurement_type are skipped).
  Arm 2 (registry -> card): every `name.cards` entry that resolves to a real card MUST declare
    measurement_type == name (a listed card declaring None or a different type is a one-sided drift).

Hermetic: synthetic vocab + cards dirs written to tmp. Two integration tests assert the real tree.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _load(mod_name: str):
    spec = importlib.util.spec_from_file_location(mod_name, REPO / "validators" / f"{mod_name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


VMT = _load("validate_measurement_types")


def _card(cid: str, **overrides) -> dict:
    c = {
        "card_id": cid,
        "version": "1.0.0",
        "question": "Question for {target.symbol}?",
        "applies_when": ["true"],
        "required_inputs": [{"product_id": "some-product-v1"}],
        "methods": [{"call": "some-method"}],
        "outputs": {"summary_fields": ["some_field"]},
        "caveats": ["A caveat long enough to satisfy the minLength."],
        "schema_version": 1,
    }
    c.update(overrides)
    return c


def _vocab(cards_list, grains=("target",)) -> dict:
    return {
        "entity_grain_vocabulary": {g: {} for g in grains},
        "measurement_types": {
            "type_a": {
                "claim": "a claim",
                "entity_grains": list(grains),
                "cards": list(cards_list),
                "providers": [{"kind": "dataset", "source": "s", "evidence_tier": "measured"}],
            }
        },
    }


def _run(tmp_path: Path, vocab: dict, cards: list[dict]):
    vd = tmp_path / "vocab"
    vd.mkdir()
    cd = tmp_path / "cards"
    cd.mkdir()
    (vd / "measurement_types.yaml").write_text(yaml.safe_dump(vocab))
    for c in cards:
        (cd / f"{c['card_id']}.card.yaml").write_text(yaml.safe_dump(c))
    return VMT.validate(vd / "measurement_types.yaml", cd)


def test_arm2_listed_card_declaring_none_errors(tmp_path):
    r = _run(tmp_path, _vocab(["card-a"]), [_card("card-a")])  # no measurement_type
    assert not r.ok
    assert any("declares measurement_type=None" in e for e in r.errors), r.errors


def test_arm2_listed_card_declaring_wrong_type_errors(tmp_path):
    r = _run(tmp_path, _vocab(["card-a"]), [_card("card-a", measurement_type="type_b")])
    assert not r.ok
    assert any("declares measurement_type='type_b'" in e for e in r.errors), r.errors


def test_arm1_migrated_card_missing_from_backref_errors(tmp_path):
    # card declares type_a but the type's cards list is empty
    r = _run(tmp_path, _vocab([]), [_card("card-a", measurement_type="type_a")])
    assert not r.ok
    assert any("is NOT in" in e and "type_a.cards" in e for e in r.errors), r.errors


def test_arm1_unmigrated_card_is_skipped(tmp_path):
    # a card with NO measurement_type is un-migrated -> not flagged for membership
    r = _run(tmp_path, _vocab([]), [_card("card-a")])
    assert r.ok, r.errors


def test_concordant_backref_is_clean(tmp_path):
    r = _run(tmp_path, _vocab(["card-a"]), [_card("card-a", measurement_type="type_a")])
    assert r.ok, r.errors


# ---------- regression guards on the real tree (would have caught the fixed drifts) ----------


def test_real_vocab_reverse_backref_is_consistent():
    r = VMT.validate(REPO / "vocabularies" / "measurement_types.yaml", REPO / "cards")
    assert r.ok, "\n".join(r.errors)


def test_target_clonality_declares_mutation_clonality():
    doc = yaml.safe_load((REPO / "cards" / "target-clonality.card.yaml").read_text())
    assert doc.get("measurement_type") == "mutation_clonality"


def test_tumor_rna_distribution_by_subtype_backreffed():
    vocab = yaml.safe_load((REPO / "vocabularies" / "measurement_types.yaml").read_text())
    cards = vocab["measurement_types"]["tumor_expression_distribution"]["cards"]
    assert "tumor-rna-distribution-by-subtype" in cards
