"""genomic-alteration-profile PULL declaration (composition.measurement_types_pulled).

The skill declares the measurement_type CLAIMS it pulls, independent of which datasets provide them.
This test pins the declaration: it exists, is non-empty, every pulled type resolves to a key in
vocabularies/measurement_types.yaml, and — the anti-drift guard — every card the skill USES maps to a
type it DECLARES it pulls, so the list cannot silently drift out of sync with cards_used. Graceful-skip
when target-contracts is absent (isolated CI). Mirror of
surface-modality-fit/tests/test_measurement_types_pulled.py.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from _skills_common.composition_schema import parse_skill_md_frontmatter
from _skills_common.paths import TARGET_CONTRACTS_ROOT_DEFAULT

yaml = pytest.importorskip("yaml")

SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"
TARGET_CONTRACTS = Path(os.environ.get("TARGET_CONTRACTS_ROOT", TARGET_CONTRACTS_ROOT_DEFAULT))
VOCAB = TARGET_CONTRACTS / "vocabularies" / "measurement_types.yaml"


def _skill_frontmatter() -> dict:
    """The skill's composition frontmatter, via the canonical parser (skills#2142)."""
    doc = parse_skill_md_frontmatter(SKILL_MD)
    if isinstance(doc, dict) and "composition" in doc:
        return doc
    raise AssertionError("no composition frontmatter found in SKILL.md")


def _pulled() -> list:
    return _skill_frontmatter()["composition"].get("measurement_types_pulled") or []


def test_gate_declares_measurement_types_pulled():
    pulled = _pulled()
    assert pulled, "genomic-alteration-profile must declare composition.measurement_types_pulled"
    # the verdict-driving spine: SNV spectrum + the stratified-dependency siblings + role
    for required in (
        "mutation_variant_class_spectrum",
        "cn_stratified_dependency",
        "fusion_stratified_dependency",
        "amp_expr_stratified_dependency",
        "alteration_role",
        "copy_number_alteration",
    ):
        assert required in pulled, f"{required!r} missing from measurement_types_pulled"


def test_pulled_types_are_registered_in_the_vocab():
    """Every pulled type must be a real measurement_type key — else the gate pulls a claim no provider
    can satisfy. Skips if target-contracts isn't checked out alongside (isolated CI)."""
    if not VOCAB.exists():
        pytest.skip("target-contracts measurement_types.yaml not reachable")
    registered = set((yaml.safe_load(VOCAB.read_text()) or {}).get("measurement_types") or {})
    assert registered, "measurement_types.yaml present but yielded no types"
    unknown = [t for t in _pulled() if t not in registered]
    assert not unknown, f"pulled types not in measurement_types.yaml: {unknown}"


def test_every_used_card_maps_to_a_pulled_type():
    """THE ANTI-DRIFT GUARD: every card in
    cards_used (whole-cohort CARDS + the --subtypes-gated subgroup card) whose type is registered must
    map to a type the gate DECLARES it pulls. A card wired in without declaring its pull fails here."""
    if not VOCAB.exists():
        pytest.skip("target-contracts measurement_types.yaml not reachable")
    vocab = (yaml.safe_load(VOCAB.read_text()) or {}).get("measurement_types") or {}
    card_to_type = {}
    for mtype, spec in vocab.items():
        for cid in (spec or {}).get("cards") or []:
            card_to_type[cid] = mtype
    pulled = set(_pulled())
    cards_used = _skill_frontmatter()["composition"].get("cards_used") or []
    undeclared = []
    for cid in cards_used:
        mtype = card_to_type.get(cid)
        if mtype is not None and mtype not in pulled:
            undeclared.append((cid, mtype))
    assert not undeclared, f"cards used but whose measurement_type is not in measurement_types_pulled: {undeclared}"
