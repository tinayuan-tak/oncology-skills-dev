"""The network_class edge-count cutoffs live in THREE places. Pin them together (skills #1806).

`network_class` (the SOLE verdict axis of signaling-network-mechanism) is derived from two coarse
annotation-DENSITY cutoffs (``>= 3`` edges per arm → well_characterized; ``<= 1`` total → sparse).
Those two numbers historically existed as bare inline literals in THREE independent spots with no
linkage:

  1. cards/signaling-network-mechanism.card.yaml `thresholds:`  CANONICAL / governed source
     (target-contracts): ``min_edges_well_characterized`` / ``max_edges_sparse``.
  2. methods/signor_mechanism_network/read.py                   AM authority: module constants
     MIN_EDGES_WELL_CHARACTERIZED / MAX_EDGES_SPARSE, mirroring the card.
  3. methods/mechanism_composed/read.py                         the COMPOSED classifier — now
     single-sourced by importing (2), so it cannot fork.

The trap this guards: editing the cut in one spot (e.g. retuning the card, or one reader) while the
others keep the old number. Because the composed reader re-classifies the deduped union with its own
ladder, a signor-only edit would leave the composed verdict on the stale cut, and a card-only edit
would change the reviewable contract while every emitted network_class stayed exactly as before.

These are text/YAML + import checks — no live S3, green on a credential-less runner.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from methods.mechanism_composed import read as composed
from methods.signor_mechanism_network import read as signor

REPO = Path(__file__).resolve().parents[3]
# TARGET_CONTRACTS_ROOT first (CI sets it; a /tmp worktree's REPO.parent is /tmp, so the sibling
# fallback alone would make this file skip silently outside the primary checkout), then the sibling.
_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT") or REPO.parent / "rnd-computational-biology-oncology-target-contracts"
)
CARD = _CONTRACTS / "cards" / "signaling-network-mechanism.card.yaml"

# card `thresholds:` key -> the AUTHORITATIVE AM constant name (methods/signor_mechanism_network/read.py).
_CARD_KEY_TO_CONST = {
    "min_edges_well_characterized": "MIN_EDGES_WELL_CHARACTERIZED",
    "max_edges_sparse": "MAX_EDGES_SPARSE",
}


def _card_thresholds() -> dict | None:
    """The card's `thresholds:` block, or None when the sibling contracts repo is not checked out."""
    if not CARD.exists():
        return None
    try:
        import yaml
    except ImportError:
        return None
    doc = yaml.safe_load(CARD.read_text()) or {}
    return doc.get("thresholds")


# --- (2) vs (3): the composed classifier must single-source the SIGNOR reader's constants ----------


def test_composed_reader_shares_the_signor_constants():
    """Unconditional (both modules are in THIS repo) — no skip, so this always asserts something.

    The composed reader ``import``s these names from the signor reader; if it ever re-declares its own
    literal ladder, the composed verdict can drift from the per-source one."""
    for name in _CARD_KEY_TO_CONST.values():
        auth = getattr(signor, name)
        comp = getattr(composed, name)
        assert comp == auth, (
            f"{name}: mechanism_composed/read.py holds {comp!r} but the authoritative "
            f"signor_mechanism_network/read.py holds {auth!r}. The composed classifier has forked from "
            f"the per-source one — re-import it from signor_mechanism_network.read."
        )


# --- (1) vs (2): the AM constants must equal the CANONICAL card thresholds --------------------------


def test_am_constants_match_the_card_thresholds():
    thresholds = _card_thresholds()
    if thresholds is None:
        pytest.skip("sibling target-contracts signaling-network-mechanism card not readable")
    mismatched = {}
    for card_key, const_name in _CARD_KEY_TO_CONST.items():
        assert card_key in thresholds, (
            f"card `thresholds:` no longer declares {card_key!r} — the canonical governed contract has "
            f"stopped stating the cut the AM readers apply ({const_name})."
        )
        auth = getattr(signor, const_name)
        if thresholds[card_key] != auth:
            mismatched[card_key] = (thresholds[card_key], auth)
    assert not mismatched, (
        "AM network_class constants disagree with the CANONICAL card `thresholds:` "
        f"{{key: (card, code)}} = {mismatched}. cards/signaling-network-mechanism.card.yaml is the "
        "single source of truth; either correct the card or the mirroring constants in "
        "methods/signor_mechanism_network/read.py so both state the same cut. (Re-valuing the cut is "
        "tracked in target-contracts #971 — not a silent edit here.)"
    )


def test_card_declares_no_network_class_threshold_the_code_lacks():
    """The reverse drift: a card advertising a cut no reader applies promises a knob that does nothing."""
    thresholds = _card_thresholds()
    if thresholds is None:
        pytest.skip("sibling target-contracts signaling-network-mechanism card not readable")
    undeclared = sorted(set(thresholds) - set(_CARD_KEY_TO_CONST))
    assert not undeclared, (
        f"card `thresholds:` declares {undeclared}, which this guard does not map to an AM constant. "
        f"Either add the mapping (if a reader applies it) or drop the key (if it is a knob no code reads)."
    )
