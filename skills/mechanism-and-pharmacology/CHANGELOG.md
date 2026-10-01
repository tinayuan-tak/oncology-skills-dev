# Changelog — mechanism-and-pharmacology


`SKILL_VERSION` in [scripts/run.py](scripts/run.py) is the current semver; the dated
development history below was migrated verbatim from the former inline `SKILL_VERSION`
comment. Newest first.

## 1.13.0 (2026-10-01): pathway-activity-context (PROGENy) promoted from pure display to a target-conditioned mechanism CONFIDENCE note (pathway_activation_confidence_note; SK#2314 B1) — member AND relatively_high (z>=+1) raises confidence language, member AND relatively_low (z<=-1) is the honest negative caution; follows the coessential-module confidence-facet precedent exactly. VERDICT-INERT (resolver keys only on network_class; mechanism_verdict byte-stable).

## 1.12.0 (2026-10-01): + driver-pathway-position card (pathway-context epic SK#2314 P1) — target+indication-conditioned POSITIONAL read (member/upstream/downstream of the indication's frequently-altered driver pathway); SOFT/VERDICT-INERT display facet (soft axis_fit rules only, no resolver — mechanism_verdict byte-stable, resolver keys only on network_class).

## 1.11.0 (2026-09-19): CASE-027-D1 — VERDICT-INERT mechanism_verdict_currency note: names that mechanism_verdict measures signaling-network ANNOTATION-DENSITY currency, so a partial/sparse verdict on a non-signaling mechanism class (surface antigen / neomorphic-metabolic enzyme / structural protein / synthetic-lethal partner) is expected by construction, NOT a poorly-characterized target. Constant scale-disclaimer (no over-call risk), complements curation_gap_note; cannot assert the class (points to target-profile mechanism_mismatch). Spine byte-stable (resolver keys only on network_class; replay guard asserts verdict + driving_rule_id).

## 1.10.2 (2026-09-12): curation_gap_note signal-specificity split (20-target lit-panel) — target-specific (phospho/co-essentiality) vs indication/expression-level (PROGENy/tahoe) signals; context-level-only thin targets get thin_network_context_level_signal_only (no curation-gap over-call for surface antigens like CEACAM5/MSLN). Verdict-inert.

## 1.10.1 (2026-09-12): mapped-MoA guard note — has_actionable_moa/has_pd_marker now require a MAPPED MoA class (method fix); confirmation-caveat note text + docs updated (31-class ontology, Reactome=context). Verdict-inert; spine byte-stable.

## 1.10.0 (2026-09-04): VERDICT-INERT prediction_lane_caveat MATERIALITY gate — fires only when the non-curated (kinome-prediction + co-essentiality) lanes are at least as large as the curated network, so it goes quiet on curated-dominant hubs (MYC/TP53) where firing on ~every target was noise. Spine byte-stable.

## 1.9.0 (2026-09-04): --literature lane (run_wired_skill make_literature_fn(MECHANISM_PHARMACOLOGY)) + VERDICT-INERT actionable-MoA INFLATION surfacing (mechanism_confirmation_caveat = has_actionable_moa off a CONTEXT-FREE curated edge without indication-operative validation, clinically-precedented false-demote guard; prediction_lane_caveat = kinome-atlas/co-essentiality lanes carried alongside but never merged; curation_gap_note; mechanism_provenance quorum summary; MECHANISM_PHARMACOLOGY thesis + polarity_note). Spine byte-stable (resolver keys only on network_class).

## 1.8.0 (2026-08-28): capsule-driven narrator via generic engine. Verdict-INERT.

## 1.7.0 (2026-08-27): tuned signals-first sub-group reader. Verdict-INERT.                       # stamped into provenance.yaml — MUST equal SKILL.md metadata.version
