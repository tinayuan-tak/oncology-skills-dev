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
import os
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import yaml

from .rules_loader import (
    TARGET_CONTRACTS,
    load_interpretation_rules,
    filter_rules_by_card_ids,
)
from .write_package import write_package
from .resolver import resolve_verdict, resolve_verdict_for_gate, resolve_or_raise, load_resolver  # noqa: F401
from .composition_schema import (
    Composition,
    CompositionError,
    validate as validate_composition,
    validate_skill_md,
)
from .llm import synthesize_structured, EVIDENCE_ONLY_DIRECTIVE
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


@lru_cache(maxsize=512)
def card_input_manifest_ids(card_id: str) -> tuple[str, ...]:
    """The data-catalog manifest ids a card DECLARES as inputs — its `required_inputs[].product_id`
    from the card_spec (target-contracts). This is the SAME declarative card->manifest mapping the
    compose-dashboard path uses (_execution._provenance_input_manifests); reusing it here means the
    subskill default path (decision.json) records the same real manifest ids as the composed engine.

    Best-effort + fail-open: a missing/malformed card_spec or absent required_inputs → empty tuple
    (provenance must never block a run). Returns a tuple so the @lru_cache result is immutable.
    """
    try:
        path = TARGET_CONTRACTS / "cards" / f"{card_id}.card.yaml"
        spec = yaml.safe_load(path.read_text()) or {}
        return tuple(
            ri["product_id"] for ri in (spec.get("required_inputs") or [])
            if isinstance(ri, dict) and ri.get("product_id")
        )
    except Exception:  # noqa: BLE001 — provenance is best-effort; never break card resolution
        return ()


# --- Skill API -------------------------------------------------------------

def _is_data_unavailable(v) -> bool:
    """True if a summary value is the honest 'no data' sentinel."""
    return isinstance(v, str) and (v == "data_unavailable" or v.endswith("_data_unavailable"))


def _primary_class_value(summary: dict):
    """The card's PRIMARY interpretation categorical — the value resolve_cards lifts into
    `interpretation_call`. Legacy primaries (selectivity_class / class / interpretation_call)
    win; otherwise the card's primary answer lives in a topic-specific `*_class` field
    (dependency_class, fit_class, immune_context_class, copy_number_class, …), so return the
    first REAL (non-data_unavailable) `*_class` value — falling back to a data_unavailable one
    only when there is no real class answer anywhere.

    Only this PRIMARY decides availability; a data_unavailable value in a SECONDARY sub-field
    (a dual-layer card's protein sub-layer, copy-number's patient_* cross-check, gnomAD's
    human_ko_observed_class, …) must NOT mark the whole card missing.
    """
    if not isinstance(summary, dict):
        return None
    for f in ("selectivity_class", "class", "interpretation_call"):
        v = summary.get(f)
        if v is not None:
            return v
    class_vals = [summary[k] for k in summary
                  if k.endswith("_class") and isinstance(summary[k], str)]
    if not class_vals:
        return None
    real = [v for v in class_vals if not _is_data_unavailable(v)]
    return real[0] if real else class_vals[0]


def _data_unavailable_field(summary: dict) -> Optional[str]:
    """If this summary's PRIMARY answer is an honest `data_unavailable`, return the
    field name carrying it, else None.

    A card answers in a topic-specific `*_class` field (dependency_class, fit_class,
    immune_context_class, copy_number_class, …), not just the legacy three — so a genuinely
    no-data PRIMARY must be detected there too (M2, 2026-08-11). BUT a `data_unavailable` in a
    SECONDARY facet (antigen_high_immune_context_class, patient_copy_number_class,
    patient_focal_cn_class, human_ko_observed_class, dep_control_position_class, …) is a NORMAL
    partial-data state and must NOT flag the whole card. So:
      - if a legacy primary field is present, it ALONE decides;
      - otherwise the card is data_unavailable only when EVERY present `*_class` categorical is
        data_unavailable (i.e. there is no real class answer anywhere).
    This restores the invariant `_primary_class_value` documents; the previous "sentinel on ANY
    `*_class`" scan violated it and falsely degraded multi-class cards (immune-context on every
    run, genomic-instability-state / copy-number-distribution / gnomad-lof-constraint on common
    indications — real primary, data-less secondary).
    """
    if not isinstance(summary, dict):
        return None
    for f in ("selectivity_class", "class", "interpretation_call"):
        if f in summary:
            return f if _is_data_unavailable(summary.get(f)) else None
    class_fields = [k for k in summary
                    if k.endswith("_class") and isinstance(summary.get(k), str)]
    if class_fields and all(_is_data_unavailable(summary[k]) for k in class_fields):
        return class_fields[0]
    return None


def _summary_is_unavailable(summary: dict) -> Optional[str]:
    """Return a short reason string if this dispatcher summary represents a
    NON-answer (error or data-unavailable) at the PRIMARY level, else None.

    A card is NOT genuinely available if the dispatcher:
      - raised and returned a `{"_live_read_error": ...}` sentinel, OR
      - a PRIMARY class field carries a data-unavailable marker.

    2026-08-11 REVIEW FIX (M2): detection now spans any `*_class` field (see
    _data_unavailable_field), not the 3 hardcoded primaries. NOTE this flags the card
    for COVERAGE accounting (`_missing`), but resolve_cards separately marks it
    `_data_unavailable` so fired_rules still evaluates its dedicated data_unavailable
    rung — an honest no-data answer is a real, rule-fireable signal, not a silent drop.
    """
    if not isinstance(summary, dict):
        return "non_dict_summary"
    if "_live_read_error" in summary:
        return f"live_read_error: {summary['_live_read_error']}"
    field = _data_unavailable_field(summary)
    if field is not None:
        return f"{field}={summary.get(field)}"
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

    FRAMEWORK_HEALTH_SMOKE (env flag): when set, SKIP all live dispatcher reads and
    return a synthetic minimal card output per card_id. This lets the framework-health
    harness run each subskill's REAL run.py end-to-end (authentic axis/verdict/headline
    → run_health) DETERMINISTICALLY and OFFLINE — proving "does the compute path execute
    cleanly?" without any S3/network read. Off by default: unset → zero production impact
    (this branch is not entered). Not a data source — a liveness-of-the-pipeline probe.
    """
    if os.environ.get("FRAMEWORK_HEALTH_SMOKE"):
        # Synthetic stub per card — a well-formed but empty summary. Rules that need real
        # values simply don't fire (fired=[]); the point is that resolve→rules→verdict→
        # run_health executes without error, which is the "runs clean?" health signal.
        return [{"card_id": cid, "summary": {}, "_missing": False, "_smoke": True,
                 "provenance": {"input_manifest_ids": list(card_input_manifest_ids(cid))}}
                for cid in card_ids]

    read_live = _import_dispatcher()

    def _read_one(card_id: str) -> dict:
        """Read + classify ONE card into its card_output dict. Pure w.r.t. `outputs` (returns a fresh
        dict), so it is safe to run concurrently across card_ids — the only shared state it touches is
        the dispatcher's own (thread-safe) lru_caches. Read exceptions propagate to the caller exactly
        as in the sequential path (they surface out of resolve_cards)."""
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
            return {
                "card_id": card_id, "summary": {},
                "interpretation_call": "not_implemented",
                "_missing": True,
                "_missing_reason": "dispatcher_returned_none",
            }
        unavailable = _summary_is_unavailable(summary)
        if unavailable is not None:
            # Distinguish an HONEST data_unavailable answer (the card ran and reported
            # no data) from a genuine absence (dispatcher None / live_read_error). Both
            # count against COVERAGE (`_missing` → cards_missing / run_health unchanged),
            # but the honest-data_unavailable card is flagged `_data_unavailable` so
            # fired_rules still evaluates it and its dedicated `equals: data_unavailable`
            # resolver rung fires (real driving_rule_id) instead of the verdict silently
            # collapsing to the bare `insufficient` default. (M2, 2026-08-11.)
            is_honest_du = "_live_read_error" not in summary and _data_unavailable_field(summary) is not None
            return {
                "card_id": card_id,
                "summary": summary,
                "interpretation_call": "data_unavailable",
                "_missing": True,
                "_missing_reason": unavailable,
                "_data_unavailable": is_honest_du,
            }
        return {
            "card_id": card_id,
            "summary": summary,
            "interpretation_call": _primary_class_value(summary),
        }

    # PERF (2026-08-18): the per-card reads are INDEPENDENT and I/O-bound (S3 + pyarrow, both of which
    # release the GIL), so run them concurrently on a bounded thread pool instead of summing their
    # latencies. Measured on tumor-presence (14 cards): sequential read wall-clock ~59s (the SUM),
    # dominated by the two expression-distribution cards (~14.5s + ~10.4s); parallelized it collapses
    # toward the SLOWEST single read (~15s). Output is byte-identical: ThreadPoolExecutor.map preserves
    # input order, and _read_one returns a fresh dict per card (no shared mutable state). Sequential
    # fallback for a single card or when SKILLS_READ_WORKERS<=1 (a kill-switch for debugging / any
    # reader later found thread-unsafe) keeps the exact former code path.
    try:
        _max_workers = int(os.environ.get("SKILLS_READ_WORKERS", "8"))
    except ValueError:
        _max_workers = 8
    if len(card_ids) <= 1 or _max_workers <= 1:
        outputs = [_read_one(cid) for cid in card_ids]
    else:
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=min(_max_workers, len(card_ids))) as _ex:
            outputs = list(_ex.map(_read_one, card_ids))
    # PROVENANCE (2026-08-13): stamp each card_output with the manifest ids it DECLARES as inputs
    # (card_spec.required_inputs[].product_id), so the subskill default path carries the same real
    # per-card data provenance as the composed engine — the basis for the decision.json governance
    # block + the resolved_release_digest. Applied to available AND missing cards: the digest is the
    # run's DECLARED input set (stable across transient read misses), not only successful reads.
    for o in outputs:
        o["provenance"] = {"input_manifest_ids": list(card_input_manifest_ids(o["card_id"]))}
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
                card_id_filter: Optional[list[str]] = None,
                rules: Optional[list[dict]] = None) -> list[dict]:
    """Return a FLAT list of {rule_id, card_id, field, value, signals, dominant,
    killer_message, ...} for each rule whose when: predicate matched some card_output.
    Signals kept as the raw dict from the rules file so downstream can either ignore
    them (biology-first skills) or project onto a modality lens / signal matrix.

    THE ONE shared rule-`when` matcher (gap #5 step 5): target-profile calls it (→ per-gate
    verdict via the resolver) and compose-dashboard's _build_signal_matrix calls it (→ per-
    modality matrix via a pivot). Pass `rules=` to match against a PRE-LOADED rules list
    (compose-dashboard already resolves them with its own contracts_root); omit it to
    load-by-axis (target-profile's path). Either way the matching semantics are identical:
    - when.card_id + when.field required
    - when.equals takes precedence; when.in falls back; when.in_record for list fields
    - field lookup checks summary[<field>], then card[<field>]; field name
      "interpretation_call" is lifted to the card root
    """
    if rules is None:
        rules = load_interpretation_rules(axis) or []
    rules = filter_rules_by_card_ids(rules, card_id_filter or [])

    # Include cards that are either available OR an HONEST data_unavailable answer. A genuine
    # absence (_missing without _data_unavailable — dispatcher None / live_read_error) stays
    # excluded. An honest data_unavailable card IS available for rule-matching so its dedicated
    # `equals: data_unavailable` rung fires (M2, 2026-08-11): the card's interpretation_call is
    # "data_unavailable" and its summary carries the data_unavailable *_class value the rule keys on.
    card_by_id = {c["card_id"]: c for c in card_outputs
                  if c.get("card_id") and (not c.get("_missing") or c.get("_data_unavailable"))}

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
                        "killer_message": rule.get("killer_message"),
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
            "killer_message": rule.get("killer_message"),
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
        "cards": [{"card_id": c["card_id"],
                   "summary": c["summary"],
                   "_missing": c.get("_missing", False),
                   "input_manifest_ids": (c.get("provenance") or {}).get("input_manifest_ids", [])}
                  for c in card_outputs],
        "fired_rules": [{"rule_id": r["rule_id"],
                         "card_id": r["card_id"],
                         "field": r["field"],
                         "value": r["value"],
                         "dominant": r["dominant"],
                         "rationale_summary": r["rationale"].split("\n", 1)[0][:200]}
                        for r in fired],
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


def write_decision(decision: dict, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    p = out_dir / "decision.json"
    p.write_text(json.dumps(decision, indent=2, default=str))
    return p
