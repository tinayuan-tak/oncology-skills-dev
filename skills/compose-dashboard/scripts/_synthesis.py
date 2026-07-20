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

    # EG4: build dominant_calls map per card_id (call set declared as dominant in interpretation_hints).
    # Legacy path — consumed when Tier-2 rules don't match (e.g. Card 2/4 still on the
    # interpretation_hints[].dominant pattern pre-refactor).
    dominant_calls_by_card = _build_dominant_calls_map(card_outputs, contracts_root)

    # Tier-2 signal matrix — the new normative layer. When a rules file exists for the
    # resolved axis AND its rules match against a card's emitted descriptive label, the
    # per-(card, modality) entry in the matrix carries {signal, rule_id, dominant flag}.
    # Empty when no rules file is found OR no rules match → legacy path takes precedence.
    axis = (run_plan.get("axis_resolution", {}) or {}).get("resolved_axis", "")
    tier2_rules = _load_interpretation_rules(contracts_root, axis)
    tier2_signal_matrix = _build_signal_matrix(card_outputs, tier2_rules)

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
        # the ratio is below 0.75.
        #
        # Tier-2 path (new): when the rules file is loaded, dominant/contradiction
        # determination consults the signal matrix instead of the card-embedded
        # dominant flag. The signal matrix is keyed on (card_id, modality), so
        # the same card may emit different signals for different modalities (e.g.,
        # expression-not-informative is a degrader killer but small_molecule neutral).
        #
        # Legacy path (fallback): for cards not yet refactored (e.g. Card 2 + Card 4
        # still emit normative interpretation_call strings), the dominant_calls_by_card
        # set + NOT_INFORMATIVE_CALLS set drive the decision.
        dominant_hits = []
        primary_contradictions = []
        tier2_killer_signals = []   # per-modality killer signals from Tier-2 rules
        fired_rule_ids = set()       # traceability: which rules contributed to this modality's fit

        for card_id in primary_cards:
            call = card_call_map.get(card_id, "")
            # --- Tier-2 path ---
            tier2_signals = _signals_for_card_modality(tier2_signal_matrix, card_id, modality)
            if tier2_signals:
                for entry in tier2_signals:
                    fired_rule_ids.add(entry["rule_id"])
                    sig = entry["signal"]
                    if sig == "killer":
                        tier2_killer_signals.append({
                            "card_id": card_id,
                            "rule_id": entry["rule_id"],
                            "message": entry.get("killer_message", ""),
                        })
                    elif sig == "supportive" and entry.get("dominant"):
                        dominant_hits.append((card_id, f"rule:{entry['rule_id']}"))
                    elif sig == "opposing":
                        primary_contradictions.append((card_id, f"rule:{entry['rule_id']}"))
                # When Tier-2 fires for this card, skip the legacy interpretation_call
                # check — the signal matrix is authoritative.
                continue
            # --- Legacy path (no Tier-2 match for this card) ---
            dominant_set = dominant_calls_by_card.get(card_id, set())
            if call in dominant_set:
                dominant_hits.append((card_id, call))
            elif call in NOT_INFORMATIVE_CALLS:
                primary_contradictions.append((card_id, call))

        # Merge Tier-2 killer signals into the killers_hit list (string messages)
        # so the existing fit_level → "not_viable" gate fires uniformly.
        if tier2_killer_signals:
            killers_hit = list(killers_hit) + [
                k["message"] or f"{k['card_id']} via rule {k['rule_id']}"
                for k in tier2_killer_signals
            ]

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
            # Tier-3 traceability — which Tier-2 rules contributed to this modality's
            # fit_level. Per the LLM-advisory protocol: a stakeholder disagreeing with
            # the call can pin the disagreement to a specific rule_id.
            "fired_rule_ids": sorted(fired_rule_ids),
            # Tier-2 killer-signal details (separate from the legacy killer_conditions_hit
            # string list because Tier-2 killers carry structured rule_id + card_id).
            "tier2_killer_signals": tier2_killer_signals,
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
        # Citation strategy:
        #   - When the hit came from a Tier-2 rule, the call string is "rule:<rule_id>".
        #     Cite that rule_id directly — it's the audit-grade source.
        #   - Otherwise cite the card's interpretation_call (legacy path).
        # The card_id is still shown either way so a reader can find the evidence.
        call_map = {c["card_id"]: c.get("interpretation_call", "") for c in card_outputs}
        cites = []
        for h in dominant_hits:
            call_str = h.get("call", "")
            if isinstance(call_str, str) and call_str.startswith("rule:"):
                # Tier-2 path
                rule_id = call_str[len("rule:"):]
                cites.append(f"{h['card_id']} (rule: {rule_id})")
            else:
                # Legacy path — fall back to interpretation_call lookup
                resolved = call_map.get(h["card_id"], call_str)
                cites.append(f"{h['card_id']}: {resolved!r}")
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


# ============================================================================
# Tier-2 signal-matrix readers
# ============================================================================
# The Tier-2 rules file (target-contracts/interpretation-rules/*.rules.yaml)
# is the single home for normative knowledge that previously lived scattered
# across card interpretation_hints[].dominant flags, modality killer_conditions,
# and the synthesis-layer NOT_INFORMATIVE_CALLS set. Per the warm-rolling-bunny
# plan's decoupling-design decisions:
#   - cards emit descriptive labels only (Tier-1)
#   - rules map (card_id, field, value) → {modality: signal} (Tier-2)
#   - synthesis reads the signal matrix to produce fit_level (Tier-3 deterministic)
#
# Backward-compat: when no rules file is found OR a card's emitted output doesn't
# match any rule, the synthesis layer falls back to the legacy
# _build_dominant_calls_map path (interpretation_hints[].dominant). Both paths
# coexist during the Cards 1+2+4 refactor.


def _load_interpretation_rules(contracts_root, axis: str) -> "list[dict] | None":
    """Load the Tier-2 rules file for a given axis. Thin shim delegating to
    the canonical loader in _skills_common/rules_loader.py — extracted
    2026-07-07 so Macro synthesis and compositional skills share one loader.

    Returns the list of rules, or None if the rules file is absent /
    unreadable / has the wrong axis. Returning None signals the synthesis
    caller to use the legacy _build_dominant_calls_map fallback.
    """
    if contracts_root is None or not axis:
        return None
    # Add skills/_skills_common to sys.path if not already there. Same pattern
    # compose-dashboard already uses to reach sibling scripts modules.
    import sys
    from pathlib import Path
    skills_dir = Path(__file__).resolve().parent.parent.parent
    if str(skills_dir) not in sys.path:
        sys.path.insert(0, str(skills_dir))
    from _skills_common.rules_loader import load_interpretation_rules
    return load_interpretation_rules(axis, contracts_root=contracts_root)


# The five delivery-modality channels compose-dashboard scores per-modality fit over.
# This engine is the PER-MODALITY consumer of the shared rule matcher, so it projects
# ONLY these channels into its signal matrix. The shared matcher (fired_rules) is
# deliberately channel-agnostic and also surfaces target-first / subtype_fit_* channels —
# those are consumed by target-profile's per-gate resolver, NOT by compose-dashboard's
# per-modality fit loop (whose `modality` key only ever takes one of these five values).
# Canonical source: target-contracts/schemas/interpretation_rules.schema.json `modality_id`.
_MODALITY_CHANNELS = frozenset(
    {"small_molecule", "degrader", "adc", "bite_tce", "antibody"})


def _build_signal_matrix(
    card_outputs: list[dict],
    rules: "list[dict] | None",
) -> dict:
    """Apply Tier-2 rules to card outputs; build a per-(card_id, modality) signal matrix.

    Returns dict keyed by (card_id, modality) → list of {signal, rule_id, dominant,
    killer_message} entries (a list because multiple rules may fire on the same
    (card_id, field) producing signals for different modalities, or even multiple
    rules matching the same card output). Only the five delivery-modality channels
    (_MODALITY_CHANNELS) are projected — non-modality channels (subtype_fit_*, target_*)
    the shared matcher may also emit belong to target-profile's resolver, not this
    per-modality fit loop, so they're filtered out here (keeps this matrix's
    (card_id, modality) contract exact and byte-identical to the pre-convergence path).

    When `rules` is None or empty: returns an empty dict (caller falls back to legacy).
    """
    if not rules:
        return {}
    # CONVERGENCE (gap #5 step 5, 2026-07-20): the rule-`when`-matching (card_id/field/
    # equals/in + the interpretation_call root-lift) is now done by the ONE shared matcher
    # `_skills_common.fired_rules` — the SAME matcher target-profile uses. This function no
    # longer re-implements it (that was the copied-not-shared duplication); it only PIVOTS
    # the shared matcher's flat output into compose-dashboard's per-(card_id, modality)
    # signal matrix (the compose-dashboard-specific shape target-profile doesn't need). One
    # matcher, two consumers: target-profile → per-gate verdict via the resolver; compose-
    # dashboard → per-modality matrix via this pivot.
    from _skills_common import fired_rules  # shared rule-when matcher

    # fired_rules keys off card.get("_missing"); compose-dashboard marks skipped cards with
    # `excluded_by_applies_when`. Normalize so an excluded card is not matched (same
    # exclusion the old inline matcher applied).
    normed = [dict(c, _missing=True) if c.get("excluded_by_applies_when") else c
              for c in card_outputs]
    surviving = [c["card_id"] for c in normed
                 if c.get("card_id") and not c.get("_missing")]

    matrix: dict[tuple[str, str], list[dict]] = {}
    # axis="" is unused when rules= is passed (fired_rules skips the axis-load); we pass the
    # caller's PRE-LOADED tier-2 rules so the rule set is identical to the old inline path.
    for fr in fired_rules(normed, axis="", card_id_filter=surviving, rules=rules):
        card_id = fr["card_id"]
        for modality, signal in (fr.get("signals") or {}).items():
            if modality not in _MODALITY_CHANNELS:
                continue   # non-modality channel → target-profile's resolver owns it, not this loop
            entry = {
                "signal": signal,
                "rule_id": fr.get("rule_id", "<no-id>"),
                "dominant": bool(fr.get("dominant")),
            }
            if signal == "killer" and fr.get("killer_message"):
                entry["killer_message"] = fr["killer_message"]
            matrix.setdefault((card_id, modality), []).append(entry)
    return matrix


def _signals_for_card_modality(
    matrix: dict, card_id: str, modality: str,
) -> list[dict]:
    """Convenience accessor: list of signal entries for (card_id, modality), or []."""
    return matrix.get((card_id, modality), [])


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
