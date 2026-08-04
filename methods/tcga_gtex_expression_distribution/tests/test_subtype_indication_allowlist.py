"""Guard: the subtype-assignment allowlist (layer 4) covers the verified indications and stays in
lockstep with the card's applies_when (layer 5).

Extending subtype-stratified presence to a new indication is a 2-layer change — the reader map
(INDICATION_TO_TUMOR_ASSIGNMENT_MANIFEST) AND the card's applies_when — and they MUST agree, or the
card fires for an indication the reader can't serve (or vice versa). This pins both. S3-free (parses
the literals only)."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.tcga_gtex_expression_distribution.read import (  # noqa: E402
    INDICATION_TO_TUMOR_ASSIGNMENT_MANIFEST as MAP,
)

# the 6 indication FAMILIES verified 2026-08-04 (each with >=1 powered stratum in its emitted shard).
_VERIFIED_SHARDS = {
    "tcga-subgroup-assignments-coadread-v1",
    "tcga-subgroup-assignments-hnsc-v1",
    "tcga-subgroup-assignments-stad-v1",
    "tcga-subgroup-assignments-nsclc-v1",
    "tcga-subgroup-assignments-esca-v1",
    "tcga-subgroup-assignments-paad-v1",
}


def test_allowlist_covers_the_verified_shards():
    assert set(MAP.values()) == _VERIFIED_SHARDS


def test_alias_indications_map_to_the_same_shard():
    # NSCLC family shares one shard (histology split); COADREAD + STAD + PAAD aliases likewise.
    assert MAP["NSCLC"] == MAP["LUAD"] == MAP["LUSC"] == "tcga-subgroup-assignments-nsclc-v1"
    assert MAP["COADREAD"] == MAP["COAD"] == MAP["READ"] == "tcga-subgroup-assignments-coadread-v1"
    assert MAP["STAD"] == MAP["GC"] == "tcga-subgroup-assignments-stad-v1"
    assert MAP["PAAD"] == MAP["PDAC"] == "tcga-subgroup-assignments-paad-v1"


def test_card_applies_when_matches_the_reader_allowlist():
    """Layer 4 (reader map) and layer 5 (card applies_when) must list the SAME indications — a
    cross-repo lockstep guard. Skips gracefully if target-contracts isn't checked out alongside."""
    card = REPO.parent / "rnd-computational-biology-oncology-target-contracts" / "cards" / \
        "tumor-rna-distribution-by-subtype.card.yaml"
    if not card.exists():
        pytest.skip("target-contracts not checked out alongside")
    text = card.read_text()
    for ind in MAP:
        assert f"'{ind}'" in text, (
            f"indication {ind!r} is in the reader allowlist but NOT in the card's applies_when — "
            f"layers 4 and 5 are out of lockstep")
