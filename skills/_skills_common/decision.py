"""_skills_common.decision — decision-JSON assembly + card accessors.

Builds the biology-first `decision.json` payload from the resolved cards and
fired rules, plus the two per-card summary accessors (`get_card_field`,
`card_summary`).

Re-exported from the package root (`from _skills_common import make_decision_json`,
`get_card_field`, `card_summary`); import surface is unchanged by the 2026-10-01 split.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional


def make_decision_json(
    skill_name: str,
    target: str,
    indication: str,
    question: str,
    card_outputs: list[dict],
    fired: list[dict],
    headline: dict,
    modality_lenses: Optional[dict] = None,
    provenance: Optional[dict] = None,
) -> dict:
    """Return the decision artefact.

    Shape: biology-first. `fired` is the flat list of matched rules.
    `modality_lenses` is optional — a skill that wants to surface a
    modality projection includes it, others omit it.
    `provenance` (optional) — the run-level reproducibility block (skills git sha, data_mode,
    release_pin, resolved_release/content digests + per-family drift). Emitted as a top-level key so
    the subskill default output is auditable + reproducible, not only the opt-in evidence envelope.
    Each per-card entry also carries `input_manifest_ids` (the card_spec.required_inputs it read).
    """
    return {
        "skill": skill_name,
        "target": target,
        "indication": indication,
        "question": question,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "headline": headline,
        "cards": [
            {
                "card_id": c["card_id"],
                "summary": c["summary"],
                "_missing": c.get("_missing", False),
                "input_manifest_ids": (c.get("provenance") or {}).get("input_manifest_ids", []),
            }
            for c in card_outputs
        ],
        "fired_rules": [
            {
                "rule_id": r["rule_id"],
                "card_id": r["card_id"],
                "field": r["field"],
                "value": r["value"],
                "dominant": r["dominant"],
                "rationale_summary": r["rationale"].split("\n", 1)[0][:200],
            }
            for r in fired
        ],
        **({"provenance": provenance} if provenance else {}),
        **({"modality_lenses": modality_lenses} if modality_lenses else {}),
    }


def get_card_field(cards: list[dict], card_id: str, key: str):
    """Look up a summary field on a specific card by id.

    Raises KeyError if card_id is not in the cards list — a missing card_id
    is almost always a typo in the caller (previously silently returned None,
    making typos invisible). Returns None when the card exists but the key is
    absent from its summary.
    """
    card_by_id = {c["card_id"]: c for c in cards}
    if card_id not in card_by_id:
        raise KeyError(
            f"get_card_field: card_id {card_id!r} not found in cards list "
            f"(available: {sorted(card_by_id)}). Check for a typo in the caller."
        )
    return (card_by_id[card_id].get("summary") or {}).get(key)


def card_summary(cards: list[dict], card_id: str) -> dict:
    """Return a card's `summary` dict by card_id, or {} if the card is absent or has no
    summary. The graceful sibling of get_card_field: skills that tolerate a missing card
    (a card not resolved in this run) get an empty dict rather than a raise.
    """
    for c in cards:
        if c.get("card_id") == card_id:
            return c.get("summary") or {}
    return {}
