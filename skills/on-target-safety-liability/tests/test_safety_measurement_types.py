"""on-target-safety-liability gate-view PULL declaration (DATA_TO_SKILL_CONTRACT Rule 3).

Before the 2026-08-14 review this list had DRIFTED to 4 entries for an 8-card roster, and two of the
four were wrong: `normal_tissue_protein_breadth` (the GTEx card's real type is normal_tissue_rna_breadth
— GTEx is RNA) and `surface_confirmation` (spurious — that type belonged to protein-surface-evidence,
which was dropped from this skill and re-homed to surface-modality-fit). This test pins the declaration:
it exists, every pulled type resolves to a key in vocabularies/measurement_types.yaml, and — the
anti-drift guard — every card the gate USES maps to a type it DECLARES it pulls. Graceful-skip when
target-contracts is absent. Mirror of surface-modality-fit / genomic-alteration-profile.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

yaml = pytest.importorskip("yaml")

SKILL_MD = Path(__file__).resolve().parent.parent / "SKILL.md"
TARGET_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)
VOCAB = TARGET_CONTRACTS / "vocabularies" / "measurement_types.yaml"


def _skill_frontmatter() -> dict:
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
    assert pulled, "on-target-safety-liability must declare composition.measurement_types_pulled (Rule 3)"
    # the human-genetics safety spine + the mechanism-conditioning input + the two data-utilization
    # expansion legs (2026-08-21): DepMap pan-essentiality (crispr_lof_dependency) and the HPA-IHC
    # essential-tissue PROTEIN card (normal_tissue_protein_breadth — now legitimately composed here).
    for required in (
        "gnomad_lof_constraint",
        "human_genetic_safety",
        "alteration_role",
        "crispr_lof_dependency",
        "normal_tissue_protein_breadth",
    ):
        assert required in pulled, f"{required!r} missing from measurement_types_pulled"
    # normal_tissue_protein_breadth is NOW legitimate — the normal-tissue-liability (HPA-IHC protein)
    # card joined the roster in the data-utilization expansion. Its RNA sibling
    # (normal-tissue-liability-gtex) remains a SEPARATE normal_tissue_rna_breadth entry; both are pulled.
    assert "normal_tissue_rna_breadth" in pulled, (
        "normal_tissue_rna_breadth missing — the GTEx card (normal-tissue-liability-gtex) is RNA-breadth"
    )
    # regression: this spurious entry must NOT reappear (belonged to protein-surface-evidence, re-homed)
    assert "surface_confirmation" not in pulled, (
        "surface_confirmation is spurious — protein-surface-evidence was re-homed to surface-modality-fit"
    )


def test_pulled_types_are_registered_in_the_vocab():
    if not VOCAB.exists():
        pytest.skip("target-contracts measurement_types.yaml not reachable")
    registered = set((yaml.safe_load(VOCAB.read_text()) or {}).get("measurement_types") or {})
    assert registered, "measurement_types.yaml present but yielded no types"
    unknown = [t for t in _pulled() if t not in registered]
    assert not unknown, f"pulled types not in measurement_types.yaml: {unknown}"


def test_every_used_card_maps_to_a_pulled_type():
    """THE ANTI-DRIFT GUARD (the check missing when the list fell to 4/8): every card in cards_used whose
    type is registered must map to a type the gate DECLARES it pulls."""
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
