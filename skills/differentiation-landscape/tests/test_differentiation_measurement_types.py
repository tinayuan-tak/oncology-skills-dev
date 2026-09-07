"""differentiation-landscape gate-view PULL declaration (DATA_TO_SKILL_CONTRACT Rule 3).

Before the 2026-08-14 review the stemness-context card (Malta 2018, added 2026-08-10) was in cards_used
but its type (stemness_context) was omitted from measurement_types_pulled. This test pins the declaration:
every pulled type resolves to a key in vocabularies/measurement_types.yaml, and — the anti-drift guard —
every card the gate USES maps to a type it DECLARES it pulls. (clinical_precedent is a documented
data-blocked future-intent whose card is licensing-blocked and NOT in cards_used, so it is intentionally
declared without a consuming card; the anti-drift check only verifies the forward direction.)
Graceful-skip when target-contracts is absent. Mirror of surface-modality-fit / genomic-alteration-profile.
"""

from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"
TARGET_CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
VOCAB = TARGET_CONTRACTS / "vocabularies" / "measurement_types.yaml"


def _skill_frontmatter() -> dict:
    text = SKILL_MD.read_text()
    for chunk in text.split("---")[1:]:
        try:
            doc = yaml.safe_load(chunk)
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict) and "composition" in doc:
            return doc
    raise AssertionError("no composition frontmatter found in SKILL.md")


def _pulled() -> list:
    return _skill_frontmatter()["composition"].get("measurement_types_pulled") or []


def test_gate_declares_measurement_types_pulled():
    pulled = _pulled()
    assert pulled, "differentiation-landscape must declare composition.measurement_types_pulled (Rule 3)"
    assert "mutation_cooccurrence" in pulled  # the verdict-driving type
    assert "stemness_context" in pulled  # regression: the omitted stemness type must stay declared


def test_pulled_types_are_registered_in_the_vocab():
    if not VOCAB.exists():
        pytest.skip("target-contracts measurement_types.yaml not reachable")
    registered = set((yaml.safe_load(VOCAB.read_text()) or {}).get("measurement_types") or {})
    assert registered, "measurement_types.yaml present but yielded no types"
    unknown = [t for t in _pulled() if t not in registered]
    assert not unknown, f"pulled types not in measurement_types.yaml: {unknown}"


def test_every_used_card_maps_to_a_pulled_type():
    """THE ANTI-DRIFT GUARD (the check missing when stemness_context was omitted): every card in
    cards_used whose type is registered must map to a type the gate DECLARES it pulls."""
    if not VOCAB.exists():
        pytest.skip("target-contracts measurement_types.yaml not reachable")
    vocab = (yaml.safe_load(VOCAB.read_text()) or {}).get("measurement_types") or {}
    card_to_type = {}
    for mtype, spec in vocab.items():
        for cid in (spec or {}).get("cards") or []:
            card_to_type[cid] = mtype
    pulled = set(_pulled())
    cards_used = _skill_frontmatter()["composition"].get("cards_used") or []
    undeclared = [
        (cid, card_to_type[cid])
        for cid in cards_used
        if card_to_type.get(cid) is not None and card_to_type[cid] not in pulled
    ]
    assert not undeclared, f"cards used but whose measurement_type is not in measurement_types_pulled: {undeclared}"
