"""compose-dashboard phase-1 composition helpers.

Given resolved axis + modality(ies) + dashboard_spec + modality_modules + subgroup catalog,
assemble the card_run_plan: which cards run, which are excluded at compose, what threshold
overlays apply, and what method invocations phase-2 will execute.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from ._resolution import load_card_spec, load_modality_module, TARGET_CONTRACTS


def compose_card_run_plan(
    dashboard_spec: dict,
    loaded_modules: list[dict],
    subgroup_spec: object,
    subgroup_resolution: dict,
    contracts_root: Path = TARGET_CONTRACTS,
) -> dict:
    """Build the card_run_plan block: to_run, excluded_at_compose, failed_at_compose.

    Discipline (per plan § Dashboard, Interpretation, Inference Layers):
      - DASHBOARD LAYER: this function decides selection (to_run vs excluded)
      - INTERPRETATION LAYER: threshold overlays merged here become inputs to phase-2's
        interpretation_hints application
      - INFERENCE LAYER: this function does NOT consult synthesis_emphasis to bias selection;
        synthesis directives flow to a separate block (synthesis_directives) for phase-3
    """
    to_run: list[dict] = []
    excluded: list[dict] = []
    failed: list[dict] = []

    # 1. Base required_cards
    for card_ref in dashboard_spec.get("required_cards", []):
        entry = _try_compose_card(
            card_ref=card_ref,
            source="base_required",
            source_detail=f"required by {dashboard_spec['dashboard_id']}",
            loaded_modules=loaded_modules,
            subgroup_resolution=subgroup_resolution,
            contracts_root=contracts_root,
        )
        if entry["status"] == "ok":
            to_run.append(entry["plan_entry"])
        elif entry["status"] == "excluded":
            excluded.append(entry["exclusion_entry"])
        else:
            failed.append(entry["failure_entry"])

    # 2. Base optional_cards (gated by `when:`)
    for card_ref in dashboard_spec.get("optional_cards", []):
        when_predicate = card_ref.get("when")
        admitted = _evaluate_dashboard_when(when_predicate, subgroup_spec)
        if not admitted:
            excluded.append({
                "card_id": card_ref["card_id"],
                "exclusion_source": "base_optional_when_predicate_false",
                "exclusion_reason": f"dashboard_spec optional_card.when predicate false: {when_predicate!r}",
            })
            continue
        entry = _try_compose_card(
            card_ref=card_ref,
            source="base_optional",
            source_detail=f"admitted by when: {when_predicate}",
            loaded_modules=loaded_modules,
            subgroup_resolution=subgroup_resolution,
            contracts_root=contracts_root,
        )
        if entry["status"] == "ok":
            to_run.append(entry["plan_entry"])
        elif entry["status"] == "excluded":
            excluded.append(entry["exclusion_entry"])
        else:
            failed.append(entry["failure_entry"])

    # 3. Placeholder cards: declared-but-not-yet-wired cards (card.status
    #    placeholder_not_wired / dormant_pending_data). Surfaced in excluded_at_compose for roadmap
    #    transparency — visible in the plan/package but never run (no method/product). NOT gated by
    #    when: (they never run regardless of context). Reuses the standard exclusion_entry shape so
    #    downstream (envelope writer, _card_ids_excluded) treats them exactly like data_blocked cards.
    for card_ref in dashboard_spec.get("placeholder_cards", []):
        # Reuse the existing `data_blocked_at_compose` exclusion_source (a placeholder card IS
        # method/data-blocked — no method/product) so no run_plan.schema enum change is needed
        # (skills-only); the reason text disambiguates dashboard placeholder_card vs module additional_card.
        excluded.append({
            "card_id": card_ref["card_id"],
            "exclusion_source": "data_blocked_at_compose",
            "exclusion_reason": (
                "dashboard_spec placeholder_card — card.status placeholder_not_wired/dormant_pending_data; "
                "declared for roadmap transparency, not wired (no method/product yet)."
            ),
        })

    # 4. Modality module additional_cards
    for module in loaded_modules:
        modality_name = module.get("modality_module")
        for card_ref in module.get("additional_cards") or []:
            entry = _try_compose_card(
                card_ref=card_ref,
                source="modality_module_additional",
                source_detail=f"added by modality module: {modality_name}",
                loaded_modules=loaded_modules,
                subgroup_resolution=subgroup_resolution,
                contracts_root=contracts_root,
                modality_module_source=modality_name,
            )
            if entry["status"] == "ok":
                to_run.append(entry["plan_entry"])
            elif entry["status"] == "excluded":
                excluded.append(entry["exclusion_entry"])
            else:
                failed.append(entry["failure_entry"])

    return {
        "to_run": to_run,
        "excluded_at_compose": excluded,
        "failed_at_compose": failed,
    }


def _try_compose_card(
    card_ref: dict,
    source: str,
    source_detail: str,
    loaded_modules: list[dict],
    subgroup_resolution: dict,
    contracts_root: Path,
    modality_module_source: Optional[str] = None,
) -> dict:
    """Try to compose a single card into the run plan.

    Returns one of:
      {"status": "ok", "plan_entry": {...}}
      {"status": "excluded", "exclusion_entry": {...}}
      {"status": "failed", "failure_entry": {...}}
    """
    card_id = card_ref["card_id"]
    version_range = card_ref.get("version", "")

    # CHECK data_status FIRST — before attempting to load the card_spec.
    # Cards with data_status: data_blocked or method_pending are intentionally paper-only;
    # their card_spec may not exist on disk. Treat as excluded, not failed.
    data_status = card_ref.get("data_status")
    if data_status in ("data_blocked", "method_pending"):
        return {
            "status": "excluded",
            "exclusion_entry": {
                "card_id": card_id,
                "exclusion_source": "data_blocked_at_compose",
                "exclusion_reason": (
                    f"card data_status={data_status!r}: "
                    f"{card_ref.get('data_status_note', 'no further detail provided')}"
                ),
            },
        }

    # Try to load the card_spec
    try:
        card_spec, card_path = load_card_spec(card_id, contracts_root=contracts_root)
    except FileNotFoundError as e:
        return {
            "status": "failed",
            "failure_entry": {
                "card_id": card_id,
                "failure_reason": f"card_spec not found: {e}",
            },
        }

    # Check subgroup-dependence: card_spec.applies_when references context.subgroup_spec
    if _card_requires_subgroup_spec(card_spec) and subgroup_resolution.get("catalog_status") in (
        "not_requested", "not_available_for_indication", "uncurated"
    ):
        return {
            "status": "excluded",
            "exclusion_entry": {
                "card_id": card_id,
                "exclusion_source": "subgroup_spec_not_supplied",
                "exclusion_reason": (
                    f"card requires subgroup_spec but subgroup_resolution.catalog_status="
                    f"{subgroup_resolution.get('catalog_status')!r}"
                ),
            },
        }

    # Merge threshold overlays from all loaded modality modules that target this card
    applied_overlays, contributing_modalities = _merge_threshold_overlays(
        card_spec=card_spec,
        card_id=card_id,
        loaded_modules=loaded_modules,
    )

    # Resolve method invocations
    method_invocations = _resolve_method_invocations(card_spec)

    plan_entry = {
        "card_id": card_id,
        "card_version": card_spec.get("version", "unknown"),
        "card_spec_path": str(card_path.relative_to(contracts_root.parent)),
        "source": source,
        "source_detail": source_detail,
        "applied_threshold_overlays": applied_overlays,
        "overlay_contributing_modalities": contributing_modalities,
        "method_invocations": method_invocations,
    }

    return {"status": "ok", "plan_entry": plan_entry}


def _card_requires_subgroup_spec(card_spec: dict) -> bool:
    """Detect whether a card's applies_when references subgroup_spec context."""
    for predicate in card_spec.get("applies_when", []) or []:
        if "subgroup_spec" in predicate:
            return True
    return False


def _evaluate_dashboard_when(when_predicate: Optional[str], subgroup_spec: object) -> bool:
    """Evaluate a dashboard_spec optional_card `when:` predicate.

    Phase-1 supports a minimal predicate subset:
      - "subgroup_spec != null"  → True iff subgroup_spec is not None
      - 'indication in ["X","Y"]' → True iff (we don't have indication context; treat as true)
                                    Indication-gating is execution-session work.
    """
    if when_predicate is None:
        return True
    if "subgroup_spec != null" in when_predicate:
        return subgroup_spec is not None
    if "subgroup_spec is not null" in when_predicate:
        return subgroup_spec is not None
    if "indication in" in when_predicate:
        # Phase-1 stub: admit by default. Full indication-gating runs in execute phase.
        return True
    # Unrecognized predicate → admit conservatively but flag in run_plan (caller handles)
    return True


def _merge_threshold_overlays(
    card_spec: dict,
    card_id: str,
    loaded_modules: list[dict],
) -> tuple[dict, list[str]]:
    """Merge threshold overlays from loaded modality modules for this card_id.

    Conservative-merge with severity ordering.
    When multiple modules tune the same threshold key:
      - For SEVERITY_TIER keys (those ending in `_severity_tier`): pick the STRICTEST tier
        across all contributing modules. Ordering: strict > moderate > pathway_dependent.
        This errs toward false-negative (rejecting more) rather than false-positive — the
        right discipline for safety-critical modality differentiation.
      - For NUMERICAL keys: pick the most conservative value (smaller for thresholds that
        gate inclusion; this is fragile and the severity_tier pattern is preferred).
    Then resolve `_severity_tier` selections to their corresponding numerical thresholds
    (e.g., `essential_tissue_severity_tier: strict` → set `essential_tissue_active_threshold`
    to the value of `essential_tissue_strict_threshold` from the card_spec).

    Returns: (effective_thresholds_dict, list_of_contributing_modality_names)
    """
    SEVERITY_ORDER = {"strict": 0, "moderate": 1, "pathway_dependent": 2}

    effective = dict(card_spec.get("thresholds") or {})
    contributing: list[str] = []

    # Step 1: collect overlay contributions
    severity_tier_contributions: dict[str, list[tuple[str, str]]] = {}  # tier_key → [(modality, tier_value), ...]
    numerical_contributions: dict[str, list[tuple[str, object]]] = {}

    for module in loaded_modules:
        overlays = module.get("threshold_overlays") or {}
        if card_id not in overlays:
            continue
        contributing.append(module["modality_module"])
        for k, v in overlays[card_id].items():
            if k.endswith("_severity_tier") or k == "severity_threshold":
                severity_tier_contributions.setdefault(k, []).append((module["modality_module"], v))
            else:
                numerical_contributions.setdefault(k, []).append((module["modality_module"], v))

    # Step 2: resolve severity-tier keys via STRICTEST wins
    for tier_key, contribs in severity_tier_contributions.items():
        strictest = min(
            contribs,
            key=lambda mv: SEVERITY_ORDER.get(mv[1], 999),
        )
        effective[tier_key] = strictest[1]

    # Step 3: apply numerical overlays. Numerical overlays are rare (the severity_tier pattern is
    # preferred), but when >1 module tunes the same numerical key we must NOT silently resolve by
    # insertion order — that made the merged threshold depend on module LOAD ORDER (a
    # non-deterministic, invisible dependency). 2026-08-11: resolve
    # order-INDEPENDENTLY. Single contributor → use it. Multiple AGREEING → use the (shared) value.
    # Multiple DISAGREEING → pick the strictest (min) so composition stays deterministic and errs
    # toward false-negative (same discipline as the severity-tier strictest-wins rule), and emit a
    # diagnostic naming the conflict so the ambiguity is visible rather than silently order-decided.
    import sys as _sys
    for k, contribs in numerical_contributions.items():
        distinct_values = {v for _, v in contribs}
        if len(distinct_values) == 1:
            # Single value (one contributor, or several that agree) — no ambiguity.
            effective[k] = contribs[0][1]
            continue
        # Contributors disagree. For genuinely NUMERIC thresholds, resolve to the strictest
        # (min) — deterministic + order-independent (the previous last-wins depended on module
        # load order), erring toward false-negative like the severity-tier strictest-wins rule.
        # For NON-numeric overlays (e.g. a free-text `note`), there is no "strictest": keep the
        # historical last-wins (still a value, no spurious conflict noise) — these are display
        # annotations, not gates.
        numeric = [(m, v) for m, v in contribs if isinstance(v, (int, float)) and not isinstance(v, bool)]
        if len(numeric) == len(contribs):
            chosen = min(v for _, v in numeric)
            conflict = ", ".join(f"{m}={v!r}" for m, v in sorted(contribs, key=lambda mv: mv[0]))
            print(
                f"[compose-dashboard] numeric threshold-overlay CONFLICT on card {card_id!r} "
                f"key {k!r}: {conflict} → chose strictest {chosen!r} (order-independent). Prefer "
                f"the severity_tier pattern for multi-module numerical tuning.",
                file=_sys.stderr,
            )
            effective[k] = chosen
        else:
            # Mixed/non-numeric (notes, labels): last-wins, no conflict warning (not a gate).
            effective[k] = contribs[-1][1]

    # Step 4: resolve `essential_tissue_severity_tier` → `essential_tissue_active_threshold`
    # (and similar patterns for other cards) — bridge symbolic tier to numerical threshold
    if "essential_tissue_severity_tier" in effective:
        tier = effective["essential_tissue_severity_tier"]
        tier_threshold_key = f"essential_tissue_{tier}_threshold"
        if tier_threshold_key in effective:
            effective["essential_tissue_active_threshold"] = effective[tier_threshold_key]

    # Backward-compat: legacy `severity_threshold` (string) overlay support — used by
    # modality modules before tiered thresholds. Maps `moderate`/`strict` to
    # `essential_tissue_severity_tier` for the normal-tissue-liability card specifically.
    if "severity_threshold" in effective and card_id == "normal-tissue-liability":
        legacy_tier = effective["severity_threshold"]
        if legacy_tier in ("strict", "moderate", "pathway_dependent"):
            effective["essential_tissue_severity_tier"] = legacy_tier
            tier_threshold_key = f"essential_tissue_{legacy_tier}_threshold"
            if tier_threshold_key in effective:
                effective["essential_tissue_active_threshold"] = effective[tier_threshold_key]

    return effective, contributing


def _resolve_method_invocations(card_spec: dict) -> list[dict]:
    """Copy the card_spec's methods block verbatim. Template-string substitution
    (e.g., {target}, {indication}) happens in phase-2 when context is fully resolved."""
    return list(card_spec.get("methods") or [])
