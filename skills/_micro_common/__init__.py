"""_micro_common — thin reusable harness for Micro-tier decision skills.

Micro skills answer a single narrow question over 1-3 cards. This harness lets
each Micro skill assemble a projection of the Macro machinery in ~20 lines:

  1. `resolve_cards`  — pull live summaries for a specified card_id list,
                        via compose-dashboard's already-wired dispatchers.
  2. `fired_rules`    — run the axis interpretation-rules against those
                        summaries, returning a flat list of rules that
                        matched — a BIOLOGY-first view (which rule + which
                        card+field triggered it).
  3. `modality_lens`  — OPTIONAL second pass that projects fired rules onto
                        a modality (small_molecule / degrader / adc / bite /
                        antibody), returning the {supportive, opposing,
                        killer, neutral} tallies for that lens.
  4. `make_decision_json` / `write_decision` — emit the artefact.

Zero new dispatcher code, zero new rule content — Micro is a PROJECTION over
the same layers Macro uses.

Design note: modality is NOT a native part of the Micro output; it is a lens
applied on top. A rule's `signals:` block in the rules file still names
modalities (that's how Macro drives its fit assessment), but Micro treats
those as post-hoc lens targets rather than as first-class output structure.
This keeps Micro biology-first and lets modality-agnostic Micros omit the
lens entirely.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# --- environment discovery -------------------------------------------------

SKILLS_DIR = Path(__file__).resolve().parent.parent
COMPOSE_SCRIPTS = SKILLS_DIR / "compose-dashboard" / "scripts"
TARGET_CONTRACTS = SKILLS_DIR.parent.parent / "rnd-computational-biology-oncology-target-contracts"


def _import_from_compose():
    """Piggyback on compose-dashboard's runtime code paths so Micro reads and
    rule-matches stay bit-for-bit consistent with Macro."""
    if str(COMPOSE_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(COMPOSE_SCRIPTS))
    from _live_readers import read_live_summary          # noqa: F401
    from _synthesis import _load_interpretation_rules    # noqa: F401
    return read_live_summary, _load_interpretation_rules


# --- Micro API -------------------------------------------------------------

def resolve_cards(card_ids: list[str], target: str, indication: str) -> list[dict]:
    """Fetch live summaries for a list of card_ids via compose-dashboard
    dispatchers. Returns a card_output dict per card_id."""
    read_live, _ = _import_from_compose()
    outputs: list[dict] = []
    for card_id in card_ids:
        summary = read_live(card_id, target, indication)
        if summary is None:
            outputs.append({
                "card_id": card_id, "summary": {},
                "interpretation_call": "not_implemented",
                "_missing": True,
            })
            continue
        outputs.append({
            "card_id": card_id,
            "summary": summary,
            "interpretation_call": summary.get("selectivity_class")
                or summary.get("class")
                or summary.get("interpretation_call"),
        })
    return outputs


def fired_rules(card_outputs: list[dict],
                axis: str,
                card_id_filter: Optional[list[str]] = None) -> list[dict]:
    """Return a FLAT list of {rule_id, card_id, field, value, signals} for
    each rule whose when: predicate matched some card_output. Signals are
    kept as the raw dict from the rules file so downstream can either
    ignore them (biology-first Micros) or project onto a modality lens.

    Rules file matching semantics identical to _synthesis._build_signal_matrix:
    - when.card_id + when.field required
    - when.equals takes precedence; when.in falls back
    - field lookup checks summary[<field>], then card[<field>], with
      interpretation_call lifted to the card root
    """
    _, load_rules = _import_from_compose()
    rules = load_rules(TARGET_CONTRACTS, axis) or []
    if card_id_filter:
        rules = [r for r in rules
                 if (r.get("when") or {}).get("card_id") in card_id_filter]

    card_by_id = {c["card_id"]: c for c in card_outputs
                  if c.get("card_id") and not c.get("_missing")}

    fired: list[dict] = []
    for rule in rules:
        when = rule.get("when") or {}
        card_id = when.get("card_id")
        field = when.get("field")
        equals = when.get("equals")
        in_list = when.get("in") or []
        if not card_id or not field:
            continue
        card = card_by_id.get(card_id)
        if card is None:
            continue
        summary = card.get("summary") or {}
        if field == "interpretation_call":
            actual = card.get("interpretation_call")
        else:
            actual = summary.get(field) if field in summary else card.get(field)
        matched = (equals is not None and actual == equals) \
                  or (equals is None and in_list and actual in in_list)
        if not matched:
            continue
        fired.append({
            "rule_id": rule.get("rule_id"),
            "card_id": card_id,
            "field": field,
            "value": actual,
            "signals": rule.get("signals") or {},
            "dominant": bool(rule.get("dominant")),
            "rationale": (rule.get("rationale") or "").strip(),
        })
    return fired


def modality_lens(fired: list[dict], modality: str) -> dict:
    """OPTIONAL second-pass projector: for a chosen modality, tally which
    fired rules read as {supportive, opposing, killer, neutral, insufficient}
    for that lens. This is the same categorical accounting Macro's fit-
    assessment uses; Micro exposes it as an add-on so a modality-agnostic
    skill can skip it entirely."""
    tally = {"supportive": [], "opposing": [], "killer": [],
             "neutral": [], "insufficient": []}
    for rule in fired:
        signal = (rule["signals"] or {}).get(modality)
        if signal in tally:
            tally[signal].append({"rule_id": rule["rule_id"],
                                  "card_id": rule["card_id"],
                                  "dominant": rule["dominant"]})
    return tally


def make_decision_json(
    skill_name: str,
    target: str,
    indication: str,
    question: str,
    card_outputs: list[dict],
    fired: list[dict],
    headline: dict,
    modality_lenses: Optional[dict] = None,
) -> dict:
    """Return the Micro decision artefact.

    Shape: biology-first. `fired` is the flat list of matched rules.
    `modality_lenses` is optional — a Micro that wants to surface a modality
    projection includes it, others omit it.
    """
    return {
        "skill": skill_name,
        "target": target,
        "indication": indication,
        "question": question,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "headline": headline,
        "cards": [{"card_id": c["card_id"],
                   "summary": c["summary"],
                   "missing": c.get("_missing", False)}
                  for c in card_outputs],
        "fired_rules": [{"rule_id": r["rule_id"],
                         "card_id": r["card_id"],
                         "field": r["field"],
                         "value": r["value"],
                         "dominant": r["dominant"],
                         "rationale_summary": r["rationale"].split("\n", 1)[0][:200]}
                        for r in fired],
        **({"modality_lenses": modality_lenses} if modality_lenses else {}),
    }


def write_decision(decision: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "decision.json"
    p.write_text(json.dumps(decision, indent=2, default=str))
    return p
