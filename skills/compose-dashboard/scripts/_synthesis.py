"""compose-dashboard phase-3 synthesis helpers.

Phase-3 reads:
  - run_plan.synthesis_directives (synthesis_prompts + per_modality_emphasis)
  - run_plan.loaded_modality_modules (for headline_decision_question lookup)
  - phase-2 card outputs (interpretation_calls per card)

And produces the evidence_package.synthesis block:
  - headline (string)
  - caveats_summary (string)
  - modality_fit_assessment (list of per-modality fit calls)

Iter-1b synthesis is RULE-BASED, not LLM-driven. Per the layer-distinction discipline,
synthesis must be deterministic (same inputs → byte-identical synthesis output) for
iter-1b acceptance. LLM-based narrative wrappers are iter-2+ work.

Synthesis algorithm:
  1. Build card_call_map: {card_id → interpretation_call} from phase-2 outputs
  2. For each loaded modality module:
     a. Check modality_killer_conditions (substring-match against card_call_map for iter-1b)
     b. Compute primary_card_score: count of primary_cards with positive calls
     c. Compute fit_level: strong | moderate | weak | not_viable
  3. Sort modalities by fit_level descending; pick the headline modality
  4. Build the headline string
  5. Aggregate caveats: collect modality_specific_caveats from all loaded modules
"""

from __future__ import annotations

from typing import Optional


# Interpretation calls considered "positive" — supports the modality fit
POSITIVE_CALLS = {
    "strong upregulation",
    "modest upregulation",
    "strong selective dependency",
    "modest selective dependency",
    "frequently mutated; characterized hotspot landscape",
    "occasionally mutated",
    "strong tumor selectivity",
    "modest tumor selectivity",
    "strong protein surface evidence",
    "modest protein surface evidence",
    "broad patient population at high expression",
    "targeted patient population (selection biomarker required)",
    "broad normal-tissue expression — modality-dependent caveats",
    "low normal-tissue liability",
    "validated target with approved agents",
    "late-stage clinical validation",
    "early clinical validation",
    "subgroup-specific expression pattern",
    "uniform expression across subgroups",
    "meaningful cross-stratum variation",
    "resolved cleanly with curated biology axis",
}

# Interpretation calls considered "negative" or "refusal" signals
NOT_INFORMATIVE_CALLS = {
    "not informative",
    "not informative for surface-modality programs",
    "no characterized hotspot landscape",
    "no published clinical precedent",
    "preclinical / early discovery only",
    "narrow patient population — patient-selection strategy critical",
    "no meaningful cross-stratum variation",
    "ESSENTIAL TISSUE LIABILITY — strict-modality programs likely not viable",
}


def synthesize(
    run_plan: dict,
    card_outputs: list[dict],
    contracts_root: "Path | None" = None,
) -> dict:
    """Produce the synthesis block for an evidence_package.

    Returns dict with keys:
      headline: str
      caveats_summary: str
      modality_fit_assessment: list[dict]

    EG4 (iter-2): when contracts_root is supplied, the synthesis layer reads each card_spec's
    interpretation_hints to identify DOMINANT calls (interpretation_hints[i].dominant: true).
    The fit_level scoring rule then becomes: "dominant signal + non-contradiction" wins strong
    BEFORE falling back to ratio-based scoring (current iter-1b behavior). Backward-compatible:
    contracts_root=None falls back to pure ratio-based scoring; cards without dominant_calls
    declarations land in the same ratio bucket they did pre-EG4.
    """
    # Special cases: axis unresolved or no loaded modules → minimal synthesis
    axis_status = run_plan.get("axis_resolution", {}).get("status")
    loaded_modules = run_plan.get("loaded_modality_modules", []) or []

    if axis_status != "resolved":
        return _synthesize_unresolved(run_plan)
    if not loaded_modules:
        return _synthesize_no_modules(run_plan)

    # EG4: build dominant_calls map per card_id (call set declared as dominant in interpretation_hints)
    dominant_calls_by_card = _build_dominant_calls_map(card_outputs, contracts_root)

    # Build card_call_map from non-excluded card outputs (used for fit scoring + rationale)
    card_call_map = {
        c["card_id"]: c.get("interpretation_call", "uninterpreted")
        for c in card_outputs
        if not c.get("excluded_by_applies_when", False)
    }

    # Build excluded set (for killer-condition checking against exclusions)
    excluded_cards = {
        c["card_id"]
        for c in card_outputs
        if c.get("excluded_by_applies_when", False)
    }

    # Build full card_outputs_by_id (includes BOTH present and excluded cards;
    # killer-condition evaluator needs both to check warning_id / validation_state
    # on present cards AND excluded_by_applies_when on excluded ones).
    # C1 fix (post-adversarial-review): killer_conditions now consume structured
    # predicates over the full card output, not just substring-match against calls.
    card_outputs_by_id = {c["card_id"]: c for c in card_outputs}

    # Per-modality fit assessment
    fit_assessment = []
    for module in loaded_modules:
        modality = module["modality"]
        emphasis = module.get("synthesis_emphasis", {}) or {}
        primary_cards = emphasis.get("primary_cards", []) or []
        secondary_cards = emphasis.get("secondary_cards", []) or []
        killer_conditions = emphasis.get("modality_killer_conditions", []) or []

        # Check killer conditions first (C1 fix: structured predicate evaluator)
        killers_hit = _check_killer_conditions(killer_conditions, card_outputs_by_id, excluded_cards)

        # Score primary cards
        primary_positive = sum(
            1 for c in primary_cards
            if card_call_map.get(c, "") in POSITIVE_CALLS
        )
        primary_excluded = sum(1 for c in primary_cards if c in excluded_cards)
        primary_total_in_scope = len(primary_cards) - primary_excluded

        # Determine fit_level
        # L7 fix (post-adversarial-review): score against ORIGINAL primary card count
        # (excluded cards count as negative, not as denominator reduction). Also require
        # min_primary_in_scope >= 2 for "strong" to prevent 1/1-card squeak-bys from
        # producing high-confidence calls on sparse evidence. Without this discipline
        # the framework would rate "strong fit" when 3 of 4 primary cards are excluded
        # and the 1 remaining card is positive.
        primary_total_original = len(primary_cards)
        MIN_IN_SCOPE_FOR_STRONG = 2
        positive_ratio_vs_original = primary_positive / max(primary_total_original, 1)

        # EG4 (iter-2): check for dominant-signal pattern. If ANY primary card emits a
        # call declared as dominant in its card_spec, AND no primary card emits a
        # NOT_INFORMATIVE call (contradiction), the modality rates strong even when
        # the ratio is below 0.75. This matches the historical discovery pattern where
        # one decisive evidence type carries the signal (e.g., DLL3's lineage-restriction,
        # KRAS-G12C's structural-druggability) and other cards confirm rather than vote.
        dominant_hits = []
        primary_contradictions = []
        for card_id in primary_cards:
            call = card_call_map.get(card_id, "")
            dominant_set = dominant_calls_by_card.get(card_id, set())
            if call in dominant_set:
                dominant_hits.append((card_id, call))
            elif call in NOT_INFORMATIVE_CALLS:
                primary_contradictions.append((card_id, call))

        if killers_hit:
            fit_level = "not_viable"
        elif dominant_hits and not primary_contradictions:
            # Dominant-signal-plus-confirmation rule: at least one primary card emitted a
            # decisive call AND no primary card actively contradicts. Strong fit regardless
            # of ratio. This is the core EG4 behavior change.
            fit_level = "strong"
        elif primary_total_in_scope == 0:
            fit_level = "insufficient_evidence"
        elif primary_total_in_scope < MIN_IN_SCOPE_FOR_STRONG:
            # Single-card-in-scope cases cannot rate higher than "moderate" regardless
            # of positive ratio. Forces synthesis to be honest about evidence sparsity.
            fit_level = "moderate" if primary_positive >= 1 else "weak"
        elif positive_ratio_vs_original >= 0.75:
            fit_level = "strong"
        elif positive_ratio_vs_original >= 0.50:
            fit_level = "moderate"
        else:
            fit_level = "weak"

        # Build rationale
        rationale_parts = []
        if killers_hit:
            rationale_parts.append("killer condition(s) hit: " + "; ".join(killers_hit))
        else:
            rationale_parts.append(
                f"{primary_positive}/{primary_total_in_scope} primary cards positive "
                f"({primary_excluded} excluded)"
            )
        # Cite the strongest and weakest primary card calls
        primary_calls = [(c, card_call_map.get(c, "excluded_or_failed")) for c in primary_cards]
        rationale_parts.append(
            "primary cards: " + ", ".join(f"{c}={call}" for c, call in primary_calls)
        )

        fit_assessment.append({
            "modality": modality,
            "fit_level": fit_level,
            "headline_decision_question": module.get("headline_decision_question", ""),
            "primary_cards_positive_count": primary_positive,
            "primary_cards_in_scope": primary_total_in_scope,
            "primary_cards_total": primary_total_original,
            "dominant_hits": [{"card_id": cid, "call": call} for cid, call in dominant_hits],
            "killer_conditions_hit": killers_hit,
            "rationale": "; ".join(rationale_parts),
        })

    # Sort by fit_level: strong > moderate > weak > insufficient_evidence > not_viable
    fit_priority = {"strong": 0, "moderate": 1, "weak": 2, "insufficient_evidence": 3, "not_viable": 4}
    fit_assessment.sort(key=lambda x: fit_priority.get(x["fit_level"], 99))

    # Build headline
    target = run_plan["input_context"]["target_symbol"]
    indication = run_plan["input_context"]["indication"]
    headline = _build_headline(target, indication, fit_assessment, card_outputs)

    # Aggregate caveats
    caveats_summary = _build_caveats_summary(run_plan, card_outputs, contracts_root)

    return {
        "headline": headline,
        "caveats_summary": caveats_summary,
        "modality_fit_assessment": fit_assessment,
    }


def _check_killer_conditions(
    killer_conditions: list,
    card_outputs_by_id: dict,
    excluded_cards: set,
) -> list[str]:
    """Check each killer_condition predicate against card outputs.

    Iter-1b post-adversarial-review (C1): structured DSL replaces free-prose strings.
    Each condition is a dict with required keys {card_id, predicate_type, message}
    and an optional predicate_value. Phase-3 evaluates each predicate deterministically
    against the card's emitted output.

    Supported predicate_types:
      - interpretation_call_equals: card's interpretation_call == predicate_value (str)
      - interpretation_call_in:     card's interpretation_call in predicate_value (list[str])
      - excluded_by_applies_when:   card is in excluded_cards set
      - warning_id_fires:           predicate_value (str) is in card's warning_ids
      - warning_id_in:              any element of predicate_value (list[str]) in warning_ids
      - validation_state_equals:    card's validation_state == predicate_value (str)

    Backward-compat: if a condition is a plain string (legacy format), best-effort
    substring match for graceful degradation — but emit a warning to surface the drift.

    Returns: list of message strings (one per fired condition) — surfaced in synthesis output.
    """
    triggered_messages = []

    for cond in killer_conditions:
        # Backward-compat: legacy free-prose string format
        if isinstance(cond, str):
            triggered_messages.append(
                f"[LEGACY-PROSE-FORMAT — NOT EVALUATABLE] {cond}"
            )
            continue

        card_id = cond.get("card_id")
        predicate_type = cond.get("predicate_type")
        predicate_value = cond.get("predicate_value")
        message = cond.get("message", "<no message>")

        if not card_id or not predicate_type:
            continue  # malformed entry; skip silently (schema validation catches this)

        card = card_outputs_by_id.get(card_id)

        # Evaluate based on predicate_type
        fired = False

        if predicate_type == "excluded_by_applies_when":
            fired = (card_id in excluded_cards) == bool(predicate_value)
        elif card is None:
            # Card not in outputs at all (neither present nor excluded) → predicate cannot fire
            fired = False
        elif card.get("excluded_by_applies_when"):
            # Card was excluded; only excluded_by_applies_when predicate can fire (handled above)
            fired = False
        elif predicate_type == "interpretation_call_equals":
            fired = card.get("interpretation_call") == predicate_value
        elif predicate_type == "interpretation_call_in":
            fired = card.get("interpretation_call") in (predicate_value or [])
        elif predicate_type == "warning_id_fires":
            fired = predicate_value in (card.get("warning_ids") or [])
        elif predicate_type == "warning_id_in":
            warning_ids = set(card.get("warning_ids") or [])
            fired = bool(warning_ids & set(predicate_value or []))
        elif predicate_type == "validation_state_equals":
            fired = card.get("validation_state") == predicate_value

        if fired:
            triggered_messages.append(message)

    return triggered_messages


def _build_headline(target: str, indication: str, fit_assessment: list[dict],
                     card_outputs: list[dict]) -> str:
    """Compose the headline string.

    Discipline:
      - If 3+ cards return 'not informative' or are excluded: emit "Insufficient evidence"
      - Otherwise: name the strongest-fit modality + cite primary cards
    """
    n_not_informative_or_excluded = sum(
        1 for c in card_outputs
        if c.get("excluded_by_applies_when")
        or c.get("interpretation_call", "") in NOT_INFORMATIVE_CALLS
    )
    if n_not_informative_or_excluded >= 3:
        return (
            f"Insufficient evidence for evaluation of {target} in {indication}; "
            f"{n_not_informative_or_excluded} cards excluded or returned non-informative calls."
        )

    if not fit_assessment:
        return f"No modality fit assessment available for {target} in {indication}."

    best = fit_assessment[0]
    if best["fit_level"] == "not_viable":
        n_viable = sum(1 for f in fit_assessment if f["fit_level"] != "not_viable")
        if n_viable == 0:
            return (
                f"No viable modality identified for {target} in {indication}; "
                f"all {len(fit_assessment)} evaluated modalities hit killer conditions."
            )

    # Strongest-evidence text: cite the actual finding(s) that drove the fit_level,
    # not the dashboard's decision-question label. For "strong" via dominant signal,
    # name the card + its interpretation_call. For ratio-based wins, summarize the
    # primary-positive count using human-friendly framing.
    evidence_text = _format_strongest_evidence(best, card_outputs)
    return (
        f"For {target} in {indication}, {best['modality']} fit is {best['fit_level']}. "
        f"{evidence_text}"
    )


def _format_strongest_evidence(best: dict, card_outputs: list[dict]) -> str:
    """Compose a stakeholder-readable 'strongest evidence' sentence for the headline.

    Three modes (in priority order):
      1. Dominant signal: cite each card_id + its interpretation_call (the EG4 path).
      2. Ratio-based strong/moderate: report dominant-positive count framed as
         "X dominant positive (sufficient)" so a "1/3" doesn't read as failure.
      3. Killer / insufficient: cite the limiting condition.
    """
    if best["fit_level"] == "not_viable":
        killers = best.get("killer_conditions_hit", [])
        return f"Killer condition(s) hit: {'; '.join(killers)}." if killers else "Killer condition(s) hit."
    if best["fit_level"] == "insufficient_evidence":
        return "Insufficient primary-card coverage in scope."

    dominant_hits = best.get("dominant_hits", []) or []
    if dominant_hits:
        call_map = {c["card_id"]: c.get("interpretation_call", "") for c in card_outputs}
        cites = [f"{h['card_id']}: {call_map.get(h['card_id'], h['call'])!r}" for h in dominant_hits]
        return f"Dominant signal — {'; '.join(cites)}."

    positive = best.get("primary_cards_positive_count", 0)
    in_scope = best.get("primary_cards_in_scope", 0)
    total = best.get("primary_cards_total", in_scope)
    if positive >= 1 and in_scope >= 1:
        sufficient_text = " (sufficient)" if best["fit_level"] in ("strong", "moderate") else ""
        return (
            f"{positive} primary card{'s' if positive != 1 else ''} positive of "
            f"{in_scope} in scope ({total} total){sufficient_text}."
        )
    return f"{positive}/{in_scope} primary positive."


def _build_caveats_summary(run_plan: dict, card_outputs: list[dict],
                            contracts_root=None) -> str:
    """Aggregate modality_specific_caveats from loaded modules + card-level caveats common
    across multiple cards. Iter-1b: deterministic concatenation; LLM dedup is iter-2."""
    caveats_parts = []

    # Modality-specific caveats from each loaded module
    for module in run_plan.get("loaded_modality_modules", []) or []:
        pass

    # Data-blocked cards
    data_blocked = [
        c["card_id"] for c in card_outputs
        if c.get("excluded_by_applies_when")
        and "data_blocked" in c.get("exclusion_reason", "").lower()
    ]
    if data_blocked:
        caveats_parts.append(
            f"Data-blocked cards in iter-1b (not yet evaluable): {', '.join(data_blocked)}."
        )

    # Sample-count divergence: when two cards both report indication-cohort sample counts
    # (e.g. expression's n_tumor, mutation-hotspot's n_samples_in_indication) but the
    # values differ, surface the divergence so a stakeholder doesn't read 624 vs 559
    # as a contradiction. Both numbers are legitimate; they index different data-availability
    # subsets of the same TCGA cohort (RNA-seq vs MAF-with-variant-calls).
    counts_observed = {}
    SAMPLE_COUNT_FIELDS = ("n_tumor", "n_samples_in_indication", "n_cell_lines_panel",
                            "n_indication_samples", "n_lineage_cell_lines")
    for c in card_outputs:
        if c.get("excluded_by_applies_when"):
            continue
        summ = c.get("summary") or {}
        for field in SAMPLE_COUNT_FIELDS:
            v = summ.get(field)
            if isinstance(v, int) and v > 0:
                counts_observed.setdefault(field, set()).add(v)
    indication_cohort_values = []
    for field in ("n_tumor", "n_samples_in_indication", "n_indication_samples"):
        for v in counts_observed.get(field, set()):
            indication_cohort_values.append((field, v))
    if len(set(v for _, v in indication_cohort_values)) > 1:
        details = ", ".join(f"{field}={v}" for field, v in indication_cohort_values)
        caveats_parts.append(
            f"Indication-cohort sample counts differ across cards ({details}); "
            f"both legitimate — different data-availability subsets of the same indication cohort."
        )

    # Warning IDs surface — prefer the card_spec's warning_predicate.message text
    # (stakeholder-readable) over the bare warning_id (framework-internal). Falls
    # back to "Warning '{id}' fired on: {card_id}." when contracts_root is None
    # or the card_spec isn't loadable.
    warning_messages_per_card = {}
    if contracts_root is not None:
        from ._resolution import load_card_spec
        for c in card_outputs:
            if c.get("excluded_by_applies_when"):
                continue
            if not c.get("warning_ids"):
                continue
            try:
                card_spec, _ = load_card_spec(c["card_id"], contracts_root=contracts_root)
            except Exception:
                continue
            predicates = {p["warning_id"]: p.get("message", "")
                          for p in card_spec.get("warning_predicates", []) or []
                          if "warning_id" in p}
            for w in c["warning_ids"]:
                msg = predicates.get(w, "")
                if msg:
                    warning_messages_per_card.setdefault((c["card_id"], w), msg)

    if warning_messages_per_card:
        for (card_id, warning_id), msg in warning_messages_per_card.items():
            caveats_parts.append(f"{card_id}: {msg}")
    else:
        warning_summary: dict[str, list[str]] = {}
        for c in card_outputs:
            if c.get("excluded_by_applies_when"):
                continue
            for w in c.get("warning_ids", []) or []:
                warning_summary.setdefault(w, []).append(c["card_id"])
        for w, cards in warning_summary.items():
            caveats_parts.append(f"Warning '{w}' fired on: {', '.join(cards)}.")

    if not caveats_parts:
        return "No cross-card caveats surfaced."
    return " ".join(caveats_parts)


def _build_dominant_calls_map(card_outputs: list[dict], contracts_root) -> dict:
    """EG4 (iter-2): build {card_id → set(dominant_call_strings)} from card_specs.

    For each non-excluded card in card_outputs, load its card_spec and collect
    interpretation_hints[i].call values where interpretation_hints[i].dominant == True.
    These are the calls the card-author has opted in as discovery-driving signals.

    Returns empty dict when contracts_root is None or when any card_spec lookup fails
    — fit_level scoring then falls back to ratio-based logic (backward-compat).
    """
    if contracts_root is None:
        return {}
    try:
        from ._resolution import load_card_spec
    except ImportError:
        return {}

    dominant_map = {}
    for card in card_outputs:
        card_id = card.get("card_id")
        if not card_id or card.get("excluded_by_applies_when"):
            continue
        try:
            spec, _ = load_card_spec(card_id, contracts_root=contracts_root)
        except Exception:
            continue
        dominant_calls = {
            hint["call"]
            for hint in (spec.get("interpretation_hints") or [])
            if hint.get("dominant") is True and hint.get("call")
        }
        if dominant_calls:
            dominant_map[card_id] = dominant_calls
    return dominant_map


def _synthesize_unresolved(run_plan: dict) -> dict:
    """Synthesis output when axis is unknown/incompatible — minimal, honest."""
    target = run_plan["input_context"]["target_symbol"]
    indication = run_plan["input_context"]["indication"]
    axis = run_plan["axis_resolution"]
    reason = axis.get("fallback_reason", "no reason provided")
    return {
        "headline": (
            f"Framework cannot evaluate {target} in {indication}: axis_resolution.status="
            f"{axis['status']!r}. {reason}"
        ),
        "caveats_summary": (
            f"Target {target!r} is not in target_biology_axis_lookup.yaml. Add a curated "
            f"axis assignment before re-running."
        ),
        "modality_fit_assessment": [],
    }


def _synthesize_no_modules(run_plan: dict) -> dict:
    """Synthesis output when no modality modules loaded — typically incompatible_modality."""
    target = run_plan["input_context"]["target_symbol"]
    indication = run_plan["input_context"]["indication"]
    mr = run_plan["modality_resolution"]
    reason = mr.get("incompatibility_reason", "no compatible modality modules loaded")
    return {
        "headline": f"Framework cannot evaluate {target} in {indication}: {reason}",
        "caveats_summary": reason,
        "modality_fit_assessment": [],
    }
