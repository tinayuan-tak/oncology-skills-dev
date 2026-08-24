"""claim_record.py — the shared factored-record ASSEMBLER (M1 of the factored-record migration;
target-contracts/docs/design/VERDICT_REPRESENTATION_MIGRATION.md).

The factored record (target-contracts/schemas/claim_record.schema.json) replaces the single
per-axis verdict TOKEN with a typed record that factors the four concerns the token conflated:
WHAT (finding), WHY (mechanism), FOR-WHAT (modality_scope), HOW-SURE (certainty). At M1 the record
is a SHADOW: each skill computes it in parallel and emits it into decision.json.claim_record_shadow,
and NOTHING consumes it (goldens untouched; the legacy verdict spine is still authoritative).

This module owns the parts that are IDENTICAL across all 10 axes:
  * record SHAPE (matches claim_record.schema.json),
  * the open-world INVARIANT (ignorance != negation): an open-world availability
    {not_wired, data_blocked, read_error} forces a non-committal finding
    (state='unknown', direction='neutral', magnitude flattened to none),
  * provenance assembly (fired_rule_ids MUST equal the resolver's actual fired set — the M1
    cross-check — and cards read).

Each skill supplies only the axis-SPECIFIC mapping (verdict token -> finding.state / direction /
availability / magnitude, mechanism role, modality_scope) via its own `_claim_record(...)` builder,
exactly as each skill already supplies its own `_strength_certainty(...)` certainty hook. The
per-axis certainty dict is passed straight through (it already conforms to CERTAINTY_MODEL.md).

Dependency-free by design (no jsonschema at runtime): schema conformance is guarded by unit tests,
not the hot path.

NOTE (carried to M3): the contracts validate_claim_record.py invariant D currently asserts
certainty.level == ordinal-min(coverage, corroboration) with strict equality; several skills
legitimately DOWNGRADE level below that on a none/absent verdict (a valid downgrade-only move).
When real records first hit the contracts validator (M3), invariant D should relax to
level <= ordinal-min(...) (downgrade-only). At M1 this is moot — the record is shadow-only.
"""
from __future__ import annotations

from typing import Optional

OPEN_WORLD_AVAILABILITY = frozenset({"not_wired", "data_blocked", "read_error"})
_NONE_MAGNITUDE = {"level": "none", "value": None, "scale": None, "distance_to_cut": None}

_VALID_AVAILABILITY = frozenset({
    "not_wired", "data_blocked", "read_error",
    "insufficient", "measured_negative", "measured_positive", "out_of_scope",
})
_VALID_DIRECTION = frozenset({"supports", "opposes", "neutral"})


def _rule_ids(fired) -> list[str]:
    """The resolver's fired set as sorted-unique rule_ids — the M1 provenance cross-check anchor."""
    return sorted({r["rule_id"] for r in (fired or []) if isinstance(r, dict) and r.get("rule_id")})


def _card_ids(cards) -> list[str]:
    return sorted({c["card_id"] for c in (cards or []) if isinstance(c, dict) and c.get("card_id")})


def assemble_claim_record(
    *,
    axis: str,
    state: str,
    direction: str,
    availability: str,
    certainty: dict,
    fired,
    cards,
    magnitude: Optional[dict] = None,
    mechanism: Optional[dict] = None,
    modality_scope: Optional[dict] = None,
    source_product_ids: Optional[list] = None,
    versions: Optional[dict] = None,
) -> dict:
    """Assemble a schema-shaped factored claim record from an axis's per-verdict mapping.

    Enforces the open-world invariant in one place so no per-axis builder can accidentally emit a
    directional finding under ignorance. `certainty` is passed through verbatim (already
    CERTAINTY_MODEL-shaped). `magnitude` defaults to the flattened none-magnitude.
    """
    if availability not in _VALID_AVAILABILITY:
        raise ValueError(f"claim_record[{axis}]: availability {availability!r} not in {sorted(_VALID_AVAILABILITY)}")

    mag = dict(magnitude) if magnitude else dict(_NONE_MAGNITUDE)
    # normalize optional magnitude keys so the shape is always complete
    for k, default in _NONE_MAGNITUDE.items():
        mag.setdefault(k, default)

    # OPEN-WORLD INVARIANT — ignorance != negation. A not_wired/data_blocked/read_error record
    # cannot carry a finding or a valence, and its magnitude collapses to none.
    if availability in OPEN_WORLD_AVAILABILITY:
        state, direction, mag = "unknown", "neutral", dict(_NONE_MAGNITUDE)

    if direction not in _VALID_DIRECTION:
        raise ValueError(f"claim_record[{axis}]: direction {direction!r} not in {sorted(_VALID_DIRECTION)}")
    if mag["value"] is not None and mag.get("scale") is None:
        raise ValueError(f"claim_record[{axis}]: magnitude.value set but scale is None (no bare numbers)")

    rec: dict = {
        "axis": axis,
        "finding": {
            "state": state,
            "direction": direction,
            "magnitude": mag,
            "availability": availability,
        },
        "certainty": certainty,
        "provenance": {
            "fired_rule_ids": _rule_ids(fired),
            "cards": _card_ids(cards),
        },
    }
    if mechanism:
        rec["mechanism"] = mechanism
    if modality_scope:
        rec["modality_scope"] = modality_scope
    if source_product_ids:
        rec["provenance"]["source_product_ids"] = sorted(set(source_product_ids))
    if versions:
        rec["provenance"]["versions"] = versions
    return rec
