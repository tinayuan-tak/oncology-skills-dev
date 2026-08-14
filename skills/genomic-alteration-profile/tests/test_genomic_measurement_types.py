"""genomic-alteration-profile gate-view PULL declaration (DATA_TO_SKILL_CONTRACT Rule 3).

The gate declares the measurement_type CLAIMS it pulls (composition.measurement_types_pulled),
independent of which datasets provide them. Before the 2026-08-13 review this list had drifted to 8
entries while cards_used had grown to 17 cards spanning 17 distinct types — the 3 stratified-dependency
siblings (cn/fusion/amp-expr), the drug-response biomarker, and the 5 cohort-context/variant layers were
pulled but never declared. This test pins the declaration: it exists, is non-empty, every pulled type
resolves to a key in vocabularies/measurement_types.yaml, and — the anti-drift guard — every card the
gate USES maps to a type it DECLARES it pulls. Graceful-skip when target-contracts is absent (isolated
CI). Mirror of surface-modality-fit/tests/test_measurement_types_pulled.py.
"""
from __future__ import annotations

from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"
TARGET_CONTRACTS = Path("/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
VOCAB = TARGET_CONTRACTS / "vocabularies" / "measurement_types.yaml"


def _skill_frontmatter() -> dict:
    """Parse the YAML frontmatter block (between the first two '---' lines) of SKILL.md."""
    text = SKILL_MD.read_text()
    parts = text.split("---")
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
    assert pulled, "genomic-alteration-profile must declare composition.measurement_types_pulled (Rule 3)"
    # the verdict-driving spine: SNV spectrum + the stratified-dependency siblings + role
    for required in ("mutation_variant_class_spectrum", "cn_stratified_dependency",
                     "fusion_stratified_dependency", "amp_expr_stratified_dependency",
                     "alteration_role", "copy_number_alteration"):
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
    """THE ANTI-DRIFT GUARD (the check that was missing when this list fell to 8/17): every card in
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
    assert not undeclared, (
        f"cards used but whose measurement_type is not in measurement_types_pulled: {undeclared}")
