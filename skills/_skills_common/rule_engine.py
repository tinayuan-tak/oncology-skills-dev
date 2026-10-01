"""_skills_common.rule_engine — the axis rule-firing engine.

Applies the axis interpretation-rules to resolved card summaries, returning a
flat biology-first list of matched rules, plus the optional modality-lens
projector. THE ONE shared rule-`when` matcher used by both target-profile (→
per-gate verdict via the resolver) and the retired compose-dashboard's signal
matrix.

Re-exported from the package root (`from _skills_common import fired_rules`,
`modality_lens`); import surface is unchanged by the 2026-10-01 split.
"""

from __future__ import annotations

from typing import Optional

from .cards import _data_unavailable_field
from .rules_loader import filter_rules_by_card_ids, load_interpretation_rules


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


def fired_rules(
    card_outputs: list[dict], axis: str, card_id_filter: Optional[list[str]] = None, rules: Optional[list[dict]] = None
) -> list[dict]:
    """Return a FLAT list of {rule_id, card_id, field, value, signals, dominant,
    killer_message, ...} for each rule whose when: predicate matched some card_output.
    Signals kept as the raw dict from the rules file so downstream can either ignore
    them (biology-first skills) or project onto a modality lens / signal matrix.

    THE ONE shared rule-`when` matcher (gap #5 step 5): target-profile calls it (→ per-gate
    verdict via the resolver) and the retired compose-dashboard's _build_signal_matrix
    called it (→ per-modality matrix via a pivot). Pass `rules=` to match against a
    PRE-LOADED rules list (that path resolved them with its own contracts_root); omit it to
    load-by-axis (target-profile's path). Either way the matching semantics are identical:
    - when.card_id + when.field required
    - when.equals takes precedence; when.in falls back; when.in_record for list fields
    - field lookup checks summary[<field>], then card[<field>]; field name
      "interpretation_call" is lifted to the card root
    """
    if rules is None:
        rules = load_interpretation_rules(axis) or []
    rules = filter_rules_by_card_ids(rules, card_id_filter or [])

    # Include cards that are either available OR carry a data_unavailable *_class the dedicated
    # `equals: data_unavailable` rung keys on — so a coverage gap anchors its provenance rung instead of
    # falling through to the resolver default (null driving_rule). Two such cases: an HONEST
    # data_unavailable answer (`_data_unavailable`, M2 2026-08-11) AND a LIVE_READ_ERROR stub whose
    # summary still reports a data_unavailable class (the reader errored but stamped the class) — the
    # latter is NOT flagged `_data_unavailable` (that flag also drives dispatcher availability_state:
    # read_error vs insufficient, which must stay distinct), so we detect the class on the summary here.
    # A genuine EMPTY absence (dispatcher-None → summary {}, no class) stays excluded (nothing to fire).
    card_by_id = {
        c["card_id"]: c
        for c in card_outputs
        if c.get("card_id")
        and (
            not c.get("_missing")
            or c.get("_data_unavailable")
            or _data_unavailable_field(c.get("summary") or {}, c.get("card_id")) is not None
        )
    }

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
                    fired.append(
                        {
                            "rule_id": rule.get("rule_id"),
                            "card_id": card_id,
                            "field": field,
                            "value": rec,  # the matched record
                            "matched_stratum": rec.get("stratum"),
                            "signals": rule.get("signals") or {},
                            "tier": rule.get("tier"),
                            "dominant": bool(rule.get("dominant")),
                            "killer_message": rule.get("killer_message"),
                            "rationale": (rule.get("rationale") or "").strip(),
                        }
                    )
            continue

        matched = (equals is not None and _rule_values_equal(actual, equals)) or (
            equals is None and in_list and any(_rule_values_equal(actual, opt) for opt in in_list)
        )
        if not matched:
            continue
        fired.append(
            {
                "rule_id": rule.get("rule_id"),
                "card_id": card_id,
                "field": field,
                "value": actual,
                "signals": rule.get("signals") or {},
                "tier": rule.get("tier"),
                "dominant": bool(rule.get("dominant")),
                "killer_message": rule.get("killer_message"),
                "rationale": (rule.get("rationale") or "").strip(),
            }
        )
    return fired


def modality_lens(fired: list[dict], modality: str) -> dict:
    """OPTIONAL second-pass projector: for a chosen modality, tally which
    fired rules read as {supportive, opposing, killer, neutral,
    insufficient} for that lens. Same categorical accounting Macro's fit-
    assessment uses; exposed as an add-on so a modality-agnostic skill can
    skip it entirely."""
    tally = {"supportive": [], "opposing": [], "killer": [], "neutral": [], "insufficient": []}
    for rule in fired:
        signal = (rule["signals"] or {}).get(modality)
        if signal in tally:
            tally[signal].append({"rule_id": rule["rule_id"], "card_id": rule["card_id"], "dominant": rule["dominant"]})
    return tally
