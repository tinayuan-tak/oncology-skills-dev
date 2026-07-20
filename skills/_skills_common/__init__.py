"""_skills_common — shared harness for compositional skills.

Skills answer a question by fetching a card set, running the axis
interpretation-rules over the summaries, optionally projecting fired rules
onto a modality lens, and emitting a decision artefact. This harness lets
each skill assemble a projection of the framework's machinery in ~30 lines.

Public API:
  1. `resolve_cards`     — pull live summaries for a card_id list, via
                            compose-dashboard's already-wired dispatchers.
  2. `fired_rules`       — apply the axis interpretation-rules to those
                            summaries, returning a flat biology-first list
                            of matched rules.
  3. `modality_lens`     — OPTIONAL projector from fired rules to a
                            modality (small_molecule / degrader / adc /
                            bite / antibody).
  4. `make_decision_json` / `write_decision` — emit decision.json.

Zero new dispatcher code, zero new rule content — skills are PROJECTIONS
over the same layers Macro (compose-dashboard) uses.

Design principles:
- Biology-first output. Modality is a post-hoc lens, not a native output
  attribute. Skills answering (target, indication) questions must produce
  valid output whether or not modality is specified.
- Rules are loaded via the canonical `rules_loader.load_interpretation_rules`
  function (this package). Skills do NOT reach into compose-dashboard's
  private `_synthesis._load_interpretation_rules` — decoupled since 2026-07-07.
- Dispatchers ARE still imported from compose-dashboard's `_live_readers`
  because the dispatcher registry is inherently Macro-side (cards need one
  canonical dispatch table across the framework).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .rules_loader import (
    TARGET_CONTRACTS,
    load_interpretation_rules,
    filter_rules_by_card_ids,
)
from .write_package import write_package
from .resolver import resolve_verdict, resolve_verdict_for_gate, load_resolver  # noqa: F401
from .composition_schema import (
    Composition,
    CompositionError,
    validate as validate_composition,
    validate_skill_md,
)
from .llm import synthesize_structured
from .placeholder import emit_placeholder
from .composite_panel import render_composite_panel


# --- environment discovery -------------------------------------------------

SKILLS_DIR = Path(__file__).resolve().parent.parent
COMPOSE_SCRIPTS = SKILLS_DIR / "compose-dashboard" / "scripts"


def _import_dispatcher():
    """Import compose-dashboard's live-reader dispatcher. Dispatch table is
    a framework-wide registry (16 wired cards); skills don't own it."""
    if str(COMPOSE_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(COMPOSE_SCRIPTS))
    from _live_readers import read_live_summary          # noqa: F401
    return read_live_summary


# --- Skill API -------------------------------------------------------------

def _primary_class_value(summary: dict):
    """The card's PRIMARY interpretation categorical — the same field
    resolve_cards lifts into `interpretation_call`. Only this field decides
    availability; a data-unavailable value in a secondary sub-field (e.g. a
    dual-layer card's protein sub-layer) must NOT mark the whole card missing.
    """
    return (summary.get("selectivity_class")
            or summary.get("class")
            or summary.get("interpretation_call"))


def _summary_is_unavailable(summary: dict) -> Optional[str]:
    """Return a short reason string if this dispatcher summary represents a
    NON-answer (error or data-unavailable) at the PRIMARY level, else None.

    A card is NOT genuinely available if the dispatcher:
      - raised and returned a `{"_live_read_error": ...}` sentinel, OR
      - the PRIMARY class field carries a data-unavailable marker
        (`data_unavailable` or `<topic>_data_unavailable`).

    Only the primary field is checked (NOT a scan of every summary key), so a
    partially-available card that reports a real primary verdict alongside an
    unavailable secondary sub-layer is still counted available. Counting a
    genuinely-errored/empty card as "available" would overstate coverage.
    """
    if not isinstance(summary, dict):
        return "non_dict_summary"
    if "_live_read_error" in summary:
        return f"live_read_error: {summary['_live_read_error']}"
    primary = _primary_class_value(summary)
    if isinstance(primary, str) and (
        primary == "data_unavailable" or primary.endswith("_data_unavailable")
    ):
        return f"primary_class={primary}"
    return None


def resolve_cards(card_ids: list[str], target: str, indication: str,
                  subgroup_context: Optional[dict] = None) -> list[dict]:
    """Fetch live summaries for a list of card_ids via the compose-dashboard
    dispatcher registry. Returns one card_output dict per card_id.

    Cards that are missing (dispatcher returns None), errored
    (`_live_read_error`), or explicitly data-unavailable are all tagged
    `_missing: True` with a `_missing_reason`, so `cards_available` reflects
    only cards that returned a real, usable signal. (Previously an errored
    dispatcher returned a dict and was silently counted as available —
    overstating coverage on every skill.)

    subgroup_context (optional): when provided, threaded to the dispatcher so
    panorama cards (subgroup-stratified-*) fan out across the resolved strata.
    Scalar cards ignore it. None → scalar-only (backward-compat).
    """
    read_live = _import_dispatcher()
    outputs: list[dict] = []
    for card_id in card_ids:
        if subgroup_context is not None:
            try:
                summary = read_live(card_id, target, indication,
                                    subgroup_context=subgroup_context)
            except TypeError:
                # Dispatcher predates the subgroup_context kwarg — scalar fallback.
                summary = read_live(card_id, target, indication)
        else:
            summary = read_live(card_id, target, indication)
        if summary is None:
            outputs.append({
                "card_id": card_id, "summary": {},
                "interpretation_call": "not_implemented",
                "_missing": True,
                "_missing_reason": "dispatcher_returned_none",
            })
            continue
        unavailable = _summary_is_unavailable(summary)
        if unavailable is not None:
            outputs.append({
                "card_id": card_id,
                "summary": summary,
                "interpretation_call": "data_unavailable",
                "_missing": True,
                "_missing_reason": unavailable,
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


def _rule_values_equal(actual, expected) -> bool:
    """Compare a card summary value against a rule's `equals`/`in` operand,
    tolerant ONLY of the bool-vs-string mismatch between readers and rule YAML.

    Readers emit native Python types (e.g. `True`); rule YAML encodes the
    operand as a string (`equals: 'true'`). A bare `==` makes `True == 'true'`
    False, silently killing every boolean-keyed rule. We bridge exactly that
    gap: when one side is a bool and the other its lowercase-string form.

    Everything else keeps strict semantics — in particular string-vs-string
    stays CASE-SENSITIVE (`equals: 'BRAF'` must not match `'braf'`), and
    numeric comparison is unchanged.
    """
    if actual == expected:
        return True

    def _bool_as_str(b: bool) -> str:
        return "true" if b else "false"

    # Bridge ONLY bool <-> its 'true'/'false' string spelling (case-insensitive
    # on the string side, since YAML may carry 'True'/'true'/'TRUE').
    if isinstance(actual, bool) and isinstance(expected, str):
        return _bool_as_str(actual) == expected.strip().lower()
    if isinstance(expected, bool) and isinstance(actual, str):
        return actual.strip().lower() == _bool_as_str(expected)
    return False


def _record_matches(record: dict, in_record: dict) -> bool:
    """True iff `record` satisfies EVERY key/value pair in an `in_record` predicate.

    Each predicate value is a scalar (exact match, via _rule_values_equal so the
    bool<->string bridge applies to subgroup_n_floor_met: true), an array (in-list),
    or an object {"in": [...]} (explicit in-list). A missing key never matches.
    This is the list-typed counterpart to the scalar equals/in path.
    """
    for key, expected in in_record.items():
        if key not in record:
            return False
        actual = record[key]
        if isinstance(expected, dict) and "in" in expected:
            if not any(_rule_values_equal(actual, opt) for opt in expected["in"]):
                return False
        elif isinstance(expected, list):
            if not any(_rule_values_equal(actual, opt) for opt in expected):
                return False
        else:
            if not _rule_values_equal(actual, expected):
                return False
    return True


def fired_rules(card_outputs: list[dict],
                axis: str,
                card_id_filter: Optional[list[str]] = None) -> list[dict]:
    """Return a FLAT list of {rule_id, card_id, field, value, signals} for
    each rule whose when: predicate matched some card_output. Signals kept
    as the raw dict from the rules file so downstream can either ignore
    them (biology-first skills) or project onto a modality lens.

    Matches on the same semantics compose-dashboard's rule engine uses:
    - when.card_id + when.field required
    - when.equals takes precedence; when.in falls back
    - field lookup checks summary[<field>], then card[<field>]; field name
      "interpretation_call" is lifted to the card root
    """
    rules = load_interpretation_rules(axis) or []
    rules = filter_rules_by_card_ids(rules, card_id_filter or [])

    card_by_id = {c["card_id"]: c for c in card_outputs
                  if c.get("card_id") and not c.get("_missing")}

    fired: list[dict] = []
    for rule in rules:
        when = rule.get("when") or {}
        card_id = when.get("card_id")
        field = when.get("field")
        equals = when.get("equals")
        in_list = when.get("in") or []
        in_record = when.get("in_record")
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

        if in_record is not None:
            # List-typed match: `actual` is a records list (e.g. per_subgroup_metrics).
            # Fire once per matching record, carrying the matched record so the
            # sub-verdict + provenance can name WHICH stratum drove the signal.
            records = actual if isinstance(actual, list) else []
            for rec in records:
                if isinstance(rec, dict) and _record_matches(rec, in_record):
                    fired.append({
                        "rule_id": rule.get("rule_id"),
                        "card_id": card_id,
                        "field": field,
                        "value": rec,                       # the matched record
                        "matched_stratum": rec.get("stratum"),
                        "signals": rule.get("signals") or {},
                        "tier": rule.get("tier"),
                        "dominant": bool(rule.get("dominant")),
                        "rationale": (rule.get("rationale") or "").strip(),
                    })
            continue

        matched = (equals is not None and _rule_values_equal(actual, equals)) \
                  or (equals is None and in_list
                      and any(_rule_values_equal(actual, opt) for opt in in_list))
        if not matched:
            continue
        fired.append({
            "rule_id": rule.get("rule_id"),
            "card_id": card_id,
            "field": field,
            "value": actual,
            "signals": rule.get("signals") or {},
            "tier": rule.get("tier"),
            "dominant": bool(rule.get("dominant")),
            "rationale": (rule.get("rationale") or "").strip(),
        })
    return fired


def modality_lens(fired: list[dict], modality: str) -> dict:
    """OPTIONAL second-pass projector: for a chosen modality, tally which
    fired rules read as {supportive, opposing, killer, neutral,
    insufficient} for that lens. Same categorical accounting Macro's fit-
    assessment uses; exposed as an add-on so a modality-agnostic skill can
    skip it entirely."""
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
    """Return the decision artefact.

    Shape: biology-first. `fired` is the flat list of matched rules.
    `modality_lenses` is optional — a skill that wants to surface a
    modality projection includes it, others omit it.
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
