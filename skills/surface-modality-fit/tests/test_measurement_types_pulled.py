"""surface-modality-fit gate-view PULL declaration (DATA_TO_SKILL_CONTRACT Rule 3).

The gate declares the measurement_type CLAIMS it pulls (composition.measurement_types_pulled),
independent of which datasets provide them. This test pins that the declaration exists, is
non-empty, and — when the sibling target-contracts repo is reachable — every pulled type resolves
to a key in vocabularies/measurement_types.yaml (a typo'd/removed type would make the gate pull a
claim no provider could ever satisfy). Graceful-skip when target-contracts is absent (isolated CI),
mirroring the figure-emitter registry check.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from _skills_common.paths import TARGET_CONTRACTS_ROOT_DEFAULT

yaml = pytest.importorskip("yaml")

SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"
TARGET_CONTRACTS = Path(os.environ.get("TARGET_CONTRACTS_ROOT", TARGET_CONTRACTS_ROOT_DEFAULT))
VOCAB = TARGET_CONTRACTS / "vocabularies" / "measurement_types.yaml"


def _skill_frontmatter() -> dict:
    """Parse the YAML frontmatter block (between the first two '---' lines) of SKILL.md."""
    text = SKILL_MD.read_text()
    parts = text.split("---")
    # frontmatter is parts[1] when the file starts with '---', else the first fenced block
    for chunk in parts[1:]:
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
    assert pulled, "surface-modality-fit must declare composition.measurement_types_pulled (Rule 3)"
    # the surface gate's biology: residency + topology + family + density + modality-fit
    assert "surface_confirmation" in pulled  # the CSPA/HPA claim (pulled even while data-blocked)
    assert "adc_tce_modality_fit" in pulled


def test_pulled_types_are_registered_in_the_vocab():
    """Every pulled type must be a real measurement_type key — else the gate pulls a claim no
    provider can satisfy. Skips if target-contracts isn't checked out alongside (isolated CI)."""
    if not VOCAB.exists():
        pytest.skip("target-contracts measurement_types.yaml not reachable")
    registered = set((yaml.safe_load(VOCAB.read_text()) or {}).get("measurement_types") or {})
    assert registered, "measurement_types.yaml present but yielded no types"
    unknown = [t for t in _pulled() if t not in registered]
    assert not unknown, f"pulled types not in measurement_types.yaml: {unknown}"


def test_cards_used_types_are_a_subset_of_pulled():
    """Sanity: every card the gate currently USES is a view of a type the gate PULLS (or is
    structure-features-static, which serves surface via surface_topology's derived neighbor). Guards
    against a card wired in that the pull-intent doesn't actually cover. Skips without the vocab."""
    if not VOCAB.exists():
        pytest.skip("target-contracts measurement_types.yaml not reachable")
    vocab = (yaml.safe_load(VOCAB.read_text()) or {}).get("measurement_types") or {}
    # card_id -> measurement_type (reverse index from the registry's cards: lists)
    card_to_type = {}
    for mtype, spec in vocab.items():
        for cid in spec.get("cards") or []:
            card_to_type[cid] = mtype
    pulled = set(_pulled())
    cards_used = _skill_frontmatter()["composition"].get("cards_used") or []
    # structure-features-static maps to structure_druggability, which feeds adc_tce_modality_fit
    # (a derived type the gate pulls) rather than being pulled directly — allow it.
    allowed_indirect = {"structure-features-static"}
    for cid in cards_used:
        if cid in allowed_indirect:
            continue
        mtype = card_to_type.get(cid)
        # a card with no registered type yet (un-migrated) is not asserted here
        if mtype is not None:
            assert mtype in pulled, f"card {cid} (type {mtype}) is used but not in measurement_types_pulled"
