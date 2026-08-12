"""Tests for the resolver-reachability primitive (verdict_relevant_cards).

The lean / --verdict-only read path rests on ONE invariant: resolve_verdict_for_gate depends only on
the resolver's REFERENCED rule_ids, so dropping cards whose rules are non-referenced leaves the
verdict byte-identical. These pin that invariant + the derivation, including the 2026-08-09 v1.1.0
surface_modality safety-mover catch that motivated deriving (not hand-listing) the lean set.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_SK = Path(__file__).resolve().parent.parent.parent   # .../claude-oncology-skills/skills
sys.path.insert(0, str(_SK))
os.environ.setdefault(
    "TARGET_CONTRACTS_ROOT",
    str(_SK.parent.parent / "rnd-computational-biology-oncology-target-contracts"),
)

from _skills_common.reachability import (  # noqa: E402
    verdict_relevant_cards,
    resolver_referenced_rule_ids,
)
from _skills_common.resolver import resolve_verdict_for_gate  # noqa: E402


def test_surface_modality_lean_set_includes_the_v1_1_0_safety_movers():
    """The v1.1.0 resolver made the safety/density/shed cards VERDICT-MOVING via when_all_fired
    combination rungs. The DERIVED lean set must include them — a naive [adc-tce-modality-fit] lean
    would silently drop the safety downgrades (the exact bug this primitive prevents)."""
    got = verdict_relevant_cards("surface_modality")
    assert "adc-tce-modality-fit" in got
    for mover in ("normal-tissue-liability", "sc-normal-celltype-expression",
                  "surface-abundance-density", "shed-ectodomain-liability"):
        assert mover in got, f"{mover} is a v1.1.0 verdict-mover but is missing from the lean set"


def test_absent_gate_returns_empty_so_caller_reads_all():
    # SAFETY CONTRACT: empty ⇒ "cannot prove a lean set" ⇒ caller must read ALL cards.
    assert verdict_relevant_cards("no_such_gate_xyz") == set()


def test_resolve_verdict_ignores_non_referenced_fired_rules():
    """CORE lean invariant: the verdict depends ONLY on referenced rule_ids. Adding NON-referenced
    fired rules never changes it — so dropping verdict-inert cards (whose rules are all
    non-referenced) yields a byte-identical verdict."""
    gate = "surface_modality"
    ref = resolver_referenced_rule_ids(gate)
    assert ref, "resolver referenced no rules?"
    a_ref_rule = "adc-preferred-supportive"
    assert a_ref_rule in ref
    base = resolve_verdict_for_gate([{"rule_id": a_ref_rule}], gate)
    assert base is not None
    inert = [{"rule_id": "totally-inert-enrichment-rule-xyz"},
             {"rule_id": "another-non-referenced-rule"}]
    assert resolve_verdict_for_gate([{"rule_id": a_ref_rule}] + inert, gate) == base
