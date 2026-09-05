"""Tests for the tractability-small-molecule druggability ladder.

B3a (2026-08-06): the ladder LOGIC was moved into a declarative resolver
(target-contracts/resolvers/tractability_small_molecule.resolver.yaml); the skill's `_snapshot` now
DELEGATES to it. These tests exercise `_snapshot_legacy_oracle` — the retained if-chain that is the
GOLDEN ORACLE the resolver was proven byte-identical to (resolver_golden_snapshots.json's
tractability_small_molecule table was generated from THIS function over all 1024 combos). They keep the
ladder's behavioral coverage independent of the resolver, and guard the oracle from silent edits.

Focus: the E8 structure/forward-ligandability rung added 2026-07-17. A druggable
pocket must raise `structurally_ligandable` (ranked below a real chemical hit,
above chemically_unhit) — the fix for the KRAS-G12C switch-II pocket being
invisible to gate E1 pre-sotorasib. Pure-helper tests (no Bedrock, no I/O)."""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tsm_run")


def _fired(*rule_ids):
    return [{"rule_id": r} for r in rule_ids]


# --- chemical-genetic tier unchanged (regression) ---

def test_triangulated_still_top():
    v, drv = tp._snapshot_legacy_oracle(_fired("e7-triangulated-target-engaged-supportive"))
    assert v == "well_covered"


def test_chemically_active():
    v, drv = tp._snapshot_legacy_oracle(_fired("prism-clinically-active-supportive-sm"))
    assert v == "chemically_active"


# --- E8: structural forward ligandability ---

def test_druggable_pocket_is_structurally_ligandable():
    """KRAS-G12C archetype: a hotspot in a druggable pocket, no compound in PRISM."""
    v, drv = tp._snapshot_legacy_oracle(_fired("hotspot-in-druggable-pocket-sm-supportive-e8"))
    assert v == "structurally_ligandable"
    assert drv == "hotspot-in-druggable-pocket-sm-supportive-e8"


def test_pocket_adjacent_is_structurally_ligandable():
    v, drv = tp._snapshot_legacy_oracle(_fired("structure-pocket-adjacent-sm-supportive"))
    assert v == "structurally_ligandable"


def test_chemical_hit_outranks_structure():
    """A real chemical hit (retrospective) must outrank a mere pocket (forward)."""
    v, drv = tp._snapshot_legacy_oracle(_fired(
        "prism-clinically-active-supportive-sm",
        "hotspot-in-druggable-pocket-sm-supportive-e8"))
    assert v == "chemically_active"


def test_structure_outranks_chemically_unhit():
    """The whole point: a druggable pocket with no compound is BETTER than
    chemically_unhit — the KRAS-G12C-pre-sotorasib case must not read unhit."""
    v, drv = tp._snapshot_legacy_oracle(_fired(
        "prism-no-compounds-found-neutral",
        "hotspot-in-druggable-pocket-sm-supportive-e8"))
    assert v == "structurally_ligandable", "a druggable pocket must beat chemically_unhit"


def test_low_confidence_structure_is_intractable_not_killer():
    v, drv = tp._snapshot_legacy_oracle(_fired("structure-low-confidence-sm-opposing"))
    assert v == "structurally_intractable"


def test_chemically_unhit_when_only_negative():
    v, drv = tp._snapshot_legacy_oracle(_fired("prism-no-compounds-found-neutral"))
    assert v == "chemically_unhit"


def test_insufficient_when_nothing_fires():
    v, drv = tp._snapshot_legacy_oracle(_fired())
    assert v == "insufficient" and drv is None
