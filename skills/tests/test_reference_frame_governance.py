"""Governance for the interpretation-encoding reference-frame rulers (Stage 2).

Lives skills-side (not target-contracts) because it cross-checks SALIENCE_SPECS — which are defined in
_skills_common — against the card contracts' `outputs.summary_fields` + `thresholds:`; target-contracts
cannot import skills. Fail-soft when the contracts checkout is absent (isolated CI) so it never red-fails
on environment, only on a real spec/contract drift.

Invariants:
  1. Every verdict-bearing measurement_type is GAUGEABLE — has a `direction` (numeric ruler) OR a
     non-empty `categorical` (the class IS the ruler). No un-gaugeable verdict type.
  2. Every `reference_frame` is well-formed: value_field + scale (no bare number) + direction (to orient).
  3. Every reference_frame field (value/distance/position + anchor fields) is a REAL summary_field of the
     naming card (sync check — a renamed contract field can't silently break the ruler).
  4. Every reference_frame cut single-sources to a REAL numeric key in the driving card's `thresholds:`
     (never re-hardcoded; never dangling).
"""
import sys
from functools import lru_cache
from pathlib import Path

import pytest
import yaml

SKILLS = Path(__file__).resolve().parents[1]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.evidence_salience import SALIENCE_SPECS, contract_threshold
from _skills_common.paths import target_contracts_root


@lru_cache(maxsize=256)
def _card_summary_fields(card_id: str):
    """The declared outputs.summary_fields of a card (or None when the contracts checkout is absent)."""
    p = target_contracts_root() / "cards" / f"{card_id}.card.yaml"
    if not p.exists():
        return None
    spec = yaml.safe_load(p.read_text()) or {}
    fields = ((spec.get("outputs") or {}).get("summary_fields")) or []
    return {f for f in fields if isinstance(f, str)}


def test_every_verdict_bearing_type_is_gaugeable():
    bad = [mt for mt, s in SALIENCE_SPECS.items() if not (s.get("direction") or s.get("categorical"))]
    assert not bad, f"measurement_types with neither a direction (numeric ruler) nor categorical: {bad}"


@pytest.mark.parametrize("mt", sorted(mt for mt, s in SALIENCE_SPECS.items() if s.get("reference_frame")))
def test_reference_frame_is_wellformed(mt):
    rf = SALIENCE_SPECS[mt]["reference_frame"]
    assert rf.get("value_field"), f"{mt}: reference_frame needs a value_field"
    assert rf.get("scale"), f"{mt}: reference_frame needs a scale (no bare number)"
    assert SALIENCE_SPECS[mt].get("direction"), f"{mt}: reference_frame needs a direction to orient the gauge"
    assert rf.get("kind") in ("percentile", "floor_cut_ceiling", "comparator_delta", "distance_to_cut"), \
        f"{mt}: unknown frame kind {rf.get('kind')!r}"


@pytest.mark.parametrize("mt", sorted(mt for mt, s in SALIENCE_SPECS.items() if s.get("reference_frame")))
def test_reference_frame_fields_are_real_summary_fields(mt):
    rf = SALIENCE_SPECS[mt]["reference_frame"]
    card_id = (rf.get("cut") or {}).get("card_id")
    if not card_id:
        pytest.skip(f"{mt}: no cut.card_id to anchor the summary-field sync check")
    sf = _card_summary_fields(card_id)
    if sf is None:
        pytest.skip("contracts checkout absent (set TARGET_CONTRACTS_ROOT)")
    named = [rf.get("value_field"), rf.get("distance_field"), rf.get("position_field")]
    named += [a.get("field") for a in (rf.get("anchors") or []) if isinstance(a, dict)]
    missing = sorted(f for f in named if f and f not in sf)
    assert not missing, f"{mt}: reference_frame fields not in {card_id} outputs.summary_fields: {missing}"


@pytest.mark.parametrize("mt", sorted(mt for mt, s in SALIENCE_SPECS.items()
                                      if (s.get("reference_frame") or {}).get("cut")))
def test_reference_frame_cut_resolves_to_a_real_threshold(mt):
    cut = SALIENCE_SPECS[mt]["reference_frame"]["cut"]
    if _card_summary_fields(cut.get("card_id")) is None:
        pytest.skip("contracts checkout absent (set TARGET_CONTRACTS_ROOT)")
    v = contract_threshold(cut.get("card_id"), cut.get("threshold"))
    assert v is not None, (f"{mt}: cut {cut.get('threshold')!r} does not resolve to a numeric key in "
                           f"{cut.get('card_id')} thresholds: (single-source it from the contract)")


def test_significance_field_added_for_mutation_stratified_is_real():
    # the Stage-2 coverage-gap fill must name a real summary_field
    sf = _card_summary_fields("mutation-stratified-dependency")
    if sf is None:
        pytest.skip("contracts checkout absent")
    assert "hotspot_mannwhitney_q" in sf
