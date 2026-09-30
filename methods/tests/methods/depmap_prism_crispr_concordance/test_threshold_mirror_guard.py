"""The PRISM×CRISPR concordance thresholds live in THREE places. Pin them together (2026-09-12).

`crispr_prism_concordance_class` is classified at PRECOMPUTE time and frozen into the parquet — the
reader (`depmap_prism_crispr_concordance.read`/`cli`) does `row.get("crispr_prism_concordance_class")`
and never re-derives it. So the same numbers exist three times with no linkage:

  1. methods/depmap_prism_precompute/cli.py            AUTHORITATIVE — classifies at build time.
  2. methods/depmap_prism_crispr_concordance/cli.py    DISPLAY MIRROR — plot reference lines + legend
                                                       text ("both ≥ 0.30") only. Editing it changes
                                                       the FIGURE and nothing else.
  3. cards/prism-crispr-concordance.card.yaml `thresholds:`  DOCUMENTATION MIRROR (target-contracts).
                                                       Read by no code at all.

The trap this guards: editing (2) or (3) to retune the call looks like it worked (the card is the
reviewable contract, the legend visibly changes) while every emitted class stays exactly as frozen.
Only a change to (1) plus a parquet rebuild moves a verdict. If these three ever disagree, the card
is advertising a cut the data was not classified at, and the figure's reference lines no longer mark
the boundary the classes were drawn on.

These are text/YAML checks — no live S3, green on a credential-less runner.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from onc_methods.depmap_prism_crispr_concordance import cli as reader
from onc_methods.depmap_prism_precompute import cli as precompute

REPO = Path(__file__).resolve().parents[3]
# TARGET_CONTRACTS_ROOT first (CI sets it; a /tmp worktree's REPO.parent is /tmp, so the sibling
# fallback alone would make this file skip silently outside the primary checkout), then the sibling.
_CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT") or REPO.parent / "rnd-computational-biology-oncology-target-contracts"
)
CARD = _CONTRACTS / "cards" / "prism-crispr-concordance.card.yaml"

# card `thresholds:` key -> the AUTHORITATIVE precompute constant name.
# `dual_responders_max_entries` is intentionally absent: it is a display cap on the top-K list, not a
# classification cut, and the precompute does not carry it.
_CARD_KEY_TO_PRECOMPUTE_CONST = {
    "min_lines_for_concordance": "MIN_LINES_FOR_CONCORDANCE",
    "concordance_strong_spearman": "CONCORDANCE_STRONG_SPEARMAN",
    "concordance_weak_spearman": "CONCORDANCE_WEAK_SPEARMAN",
    "dual_responder_chronos": "DUAL_RESPONDER_CHRONOS",
    "dual_responder_lfc": "DUAL_RESPONDER_LFC",
}

# The subset the reader re-declares for its figure. Must equal the precompute's, or the reference
# lines are drawn somewhere other than the boundary the frozen classes were cut at.
_READER_MIRRORED_CONSTS = ("CONCORDANCE_STRONG_SPEARMAN", "CONCORDANCE_WEAK_SPEARMAN")


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


# --- (1) vs (2): the display mirror must track the authoritative build-time constants -------------


def test_reader_display_constants_match_the_precompute():
    """Unconditional (both modules are in THIS repo) — no skip, so this always asserts something."""
    for name in _READER_MIRRORED_CONSTS:
        auth = getattr(precompute, name)
        disp = getattr(reader, name)
        assert disp == auth, (
            f"{name}: the display mirror in depmap_prism_crispr_concordance/cli.py is {disp!r} but the "
            f"AUTHORITATIVE build-time constant in depmap_prism_precompute/cli.py is {auth!r}. The "
            f"figure's reference lines would no longer mark the boundary the frozen "
            f"crispr_prism_concordance_class values were cut at."
        )


def test_classification_reads_the_authoritative_constant_not_the_reader_copy():
    """Guard the direction of the dependency: the classifier must be the precompute's. If
    `classify_crispr_prism_concordance` ever moves to the reader module, this file's premise (and the
    'editing the reader changes only the figure' comment above) is stale."""
    assert hasattr(precompute, "classify_crispr_prism_concordance"), (
        "classify_crispr_prism_concordance is no longer in depmap_prism_precompute — the "
        "authoritative/mirror split documented in this file needs re-deriving."
    )
    assert not hasattr(reader, "classify_crispr_prism_concordance"), (
        "the reader now defines classify_crispr_prism_concordance: the class may no longer be frozen "
        "at precompute time, so the card's thresholds may have become live. Re-derive this guard."
    )


# --- (1) vs (3): the card contract must advertise the cut the data was classified at --------------


def test_card_thresholds_match_the_precompute():
    thresholds = _card_thresholds()
    if thresholds is None:
        pytest.skip("sibling target-contracts prism-crispr-concordance card not readable")
    mismatched = {}
    for card_key, const_name in _CARD_KEY_TO_PRECOMPUTE_CONST.items():
        assert card_key in thresholds, (
            f"card `thresholds:` no longer declares {card_key!r} — the reviewable contract has stopped "
            f"stating a cut the precompute still applies ({const_name})."
        )
        auth = getattr(precompute, const_name)
        if thresholds[card_key] != auth:
            mismatched[card_key] = (thresholds[card_key], auth)
    assert not mismatched, (
        "card `thresholds:` disagrees with the AUTHORITATIVE precompute constants "
        f"{{key: (card, precompute)}} = {mismatched}. The card is a DOCUMENTATION mirror read by no "
        "code: crispr_prism_concordance_class is frozen in the parquet at precompute time, so editing "
        "the card cannot retune a call. Either correct the card to state the cut the data was actually "
        "classified at, or change depmap_prism_precompute AND rebuild the parquet."
    )


def test_card_declares_no_classification_threshold_the_precompute_lacks():
    """The reverse drift: a card advertising a cut no code applies promises a knob that does nothing."""
    thresholds = _card_thresholds()
    if thresholds is None:
        pytest.skip("sibling target-contracts prism-crispr-concordance card not readable")
    known = set(_CARD_KEY_TO_PRECOMPUTE_CONST) | {"dual_responders_max_entries"}
    undeclared = sorted(set(thresholds) - known)
    assert not undeclared, (
        f"card `thresholds:` declares {undeclared}, which this guard does not map to a precompute "
        f"constant. Either add the mapping (if the precompute applies it) or drop the key (if it is a "
        f"knob no code reads)."
    )
