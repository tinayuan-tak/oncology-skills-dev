#!/usr/bin/env python3
"""render-evidence-package — Stage-1 markdown renderer for evidence_package.json.

Consumes an evidence_package matching evidence_package.schema.json and produces a
human-readable Stage-1 markdown rendering. This is the only renderer that ships
now; HTML (Stage 2), PowerPoint (Stage 3), decision memo (Stage 3+), and
interactive UI (Stage 4) are deferred.

The renderer is intentionally simple: it walks the evidence_package's top-level
sections and emits each as a markdown block. NO new synthesis, NO new interpretation,
NO new computation — the renderer is a pure formatter of upstream artifacts. Per
the layer-distinction discipline, the renderer adds nothing to the dashboard,
interpretation, or inference layers; it surfaces what they produced.

Usage:
    python -m scripts.render_markdown \
        --evidence-package /path/to/evidence_package.json \
        --out /path/to/dashboard.md

Library:
    from scripts.render_markdown import render_evidence_package
    md = render_evidence_package(ep_dict)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click


def render_evidence_package(ep: dict) -> str:
    """Render an evidence_package dict to a markdown string.

    The renderer dispatches on axis_resolution status (via dashboard_spec_ref) to
    produce either a full dashboard (resolved case) or a refusal page (unresolved).
    """
    target_symbol = ep["context"]["target"]["symbol"]
    indication = ep["context"]["indication"]["oncotree_code"]

    sections = []

    # ===== Title =====
    sections.append(f"# Evidence Package: {target_symbol} in {indication}")
    sections.append("")
    sections.append(f"_Package ID: `{ep['package_id']}` · Framework version: {ep['framework_version']}_")
    sections.append("")

    # ===== Refusal case — empty cards array means axis was unresolved =====
    if not ep.get("cards"):
        sections.extend(_render_refusal_page(ep))
        return "\n".join(sections) + "\n"

    # ===== Executive summary (synthesis headline) =====
    syn = ep.get("synthesis", {}) or {}
    sections.append("## Executive Summary")
    sections.append("")
    sections.append(f"**{syn.get('headline', '(no headline produced)')}**")
    sections.append("")
    if syn.get("caveats_summary"):
        sections.append(f"_Caveats_: {syn['caveats_summary']}")
        sections.append("")

    # ===== Per-skill canonical HEADLINE block (verdict · confidence · top tension) =====
    # The distilled one-line headline each sub-skill emits (headline_core.build_headline), carried into
    # synthesis.claim_vectors[short].headline_block. Leads the dashboard so the reader sees every lens's
    # call + confidence + sharpest tension before the detail. Verdict-inert; absent for un-migrated skills.
    sections.extend(_render_skill_headlines(syn))

    # ===== PRIMARY resolver gate-verdict (Stage 2) =====
    # The declarative resolver's gate verdict is the headline row; the per-modality
    # fit_level below is a demoted secondary LENS. A verdict-only synthesis block (no
    # modality_fit_assessment) must not crash — the fit section is gated on `fit`.
    primary_gate = syn.get("primary_gate_verdict")
    additional_gates = syn.get("additional_gate_verdicts", []) or []
    if primary_gate:
        sections.extend(_render_gate_verdicts(primary_gate, additional_gates))

    # ===== Per-modality fit assessment (SECONDARY lens) =====
    fit = syn.get("modality_fit_assessment", []) or []
    if fit:
        sections.extend(_render_modality_fit_table(fit))

    # ===== Table of contents =====
    sections.extend(_render_toc(ep, fit))

    # ===== Governance block =====
    sections.extend(_render_governance(ep))

    # ===== Per-card panels =====
    sections.append("## Card Evidence")
    sections.append("")
    for card in ep["cards"]:
        sections.extend(_render_card_panel(card))

    # ===== Failed-cards section (explicit accounting for n_cards_failed) =====
    sections.extend(_render_failed_cards_section(ep))

    # ===== Provenance footer =====
    sections.extend(_render_provenance_footer(ep))

    return "\n".join(sections) + "\n"


# ============================================================================
# Sub-renderers
# ============================================================================

def _render_skill_headlines(syn: dict) -> list[str]:
    """Leading table of each sub-skill's canonical headline block: call · confidence · top tension.
    Reads synthesis.claim_vectors[short].headline_block; returns [] when none carry one (byte-stable
    for un-migrated packages)."""
    cvs = syn.get("claim_vectors") or {}
    rows = []
    for short in sorted(cvs):
        blk = (cvs[short] or {}).get("headline_block")
        if not isinstance(blk, dict):
            continue
        verdict = (blk.get("verdict") or {}).get("phrase") or (blk.get("verdict") or {}).get("call") or "—"
        conf = (blk.get("confidence") or {}).get("level", "—")
        tension = (blk.get("top_tension") or {}).get("text", "") if blk.get("top_tension") else ""
        rows.append((short, str(verdict), str(conf), str(tension).replace("|", "\\|")))
    if not rows:
        return []
    out = ["## Skill Headlines", "",
           "_Each lens's canonical call, confidence, and sharpest tension (verdict-inert)._", "",
           "| Skill | Verdict | Confidence | Top tension |",
           "|---|---|---|---|"]
    for short, verdict, conf, tension in rows:
        out.append(f"| {short} | {verdict} | {conf} | {tension or '—'} |")
    out.append("")
    return out


def _render_refusal_page(ep: dict) -> list[str]:
    """Render the refusal page when the framework cannot proceed (axis unresolved,
    modality incompatible, etc.). This is the negative-control discipline rendered
    user-facing."""
    syn = ep.get("synthesis", {}) or {}
    sections = []
    sections.append("## ⚠️ Framework Refused to Evaluate")
    sections.append("")
    sections.append(syn.get("headline", "The framework could not produce evidence for this target/indication."))
    sections.append("")
    if syn.get("caveats_summary"):
        sections.append("### Next Steps")
        sections.append("")
        sections.append(syn["caveats_summary"])
        sections.append("")

    # Governance still useful in refusal case (shows data_mode, release_pin)
    sections.extend(_render_governance(ep))

    # Provenance shows what WAS attempted
    sections.append("## Provenance")
    sections.append("")
    sections.append(f"- **Generated at**: `{ep.get('generated_at', 'unknown')}`")
    sections.append(f"- **Generated by**: `{ep.get('generated_by', 'unknown')}`")
    sections.append(f"- **Dashboard spec referenced**: `{ep.get('dashboard_spec_ref', 'unresolved')}`")
    sections.append("")
    return sections


FIT_ICONS = {"strong": "🟢", "moderate": "🟡", "weak": "🟠",
              "insufficient_evidence": "⚪", "not_viable": "🔴",
              # A killer-veto card could not be read (read_error / not_wired), so the
              # safety veto is neither confirmed-fired nor confirmed-clear. The modality is
              # un-assessable — a data-blocked ⚪, NOT a green pass, even if primaries are positive.
              "non_concludable": "⚪"}

# Resolver-verdict vocabulary → icon (Stage 2). Covers the surface_modality,
# tractability_small_molecule, dependency, genomic_alteration and selectivity gate
# verdicts. A verdict absent from the map renders with a neutral marker (never crashes).
VERDICT_ICONS = {
    # --- positive / supported ---
    "both_viable": "🟢", "adc_preferred": "🟢", "tce_preferred": "🟢", "pmhc_tce_supported": "🟢",
    "well_covered": "🟢", "chemically_confirmed_genetic": "🟢",
    "concordant_dependent": "🟢", "chemical_genetic_confirmed_dependent": "🟢",
    "lineage_selective": "🟢", "selective_dependent": "🟢",
    "biomarker_stratified_dependency": "🟢", "confirmed_driver": "🟢",
    "multi_class_driver": "🟢", "strong_tumor_selective": "🟢",
    "chemically_active": "🟢", "measured_potent_ligand": "🟢",
    # --- moderate / caveated ---
    "confirmed_lof_driver": "🟡", "multi_class_lof_driver": "🟡",   # real TSG driver, not an inhibitor green-light
    "moderate_biomarker_dependency": "🟡", "modest_tumor_selective": "🟡",
    "field_effect_tumor_selective": "🟡", "partner_conditional_dependent": "🟡",
    "clinical_precedent_only": "🟡", "structurally_ligandable": "🟡",
    "surface_viable_density_caveated": "🟡", "shed_dominant_opposed": "🟡",
    "adc_preferred_tce_unsafe": "🟡", "drug_response_biomarker": "🟡",
    "recurrent_amplification_driver": "🟡", "recurrent_deletion_driver": "🟡",
    "recurrent_fusion_driver": "🟡", "lof_dominant_pattern": "🟡",
    "missense_dominant_pattern": "🟡", "tool_compound_only": "🟡",
    "weakly_active": "🟠", "broadly_dependent": "🟡", "non_dependent_paralog_buffered": "🟡",
    # --- opposing / ambiguous / abstain ---
    "modality_ambiguous": "⚪", "isoform_dependent_undefined": "⚪",
    "discordant": "🟠", "discordant_across_comparators": "🟠",
    "mixed_pattern": "⚪", "passenger_pattern": "⚪",
    "not_selective": "🟠", "not_informative": "⚪", "data_unavailable": "⚪",
    "insufficient": "⚪", "insufficient_underpowered": "⚪",
    "insufficient_underpowered_pan_essential": "⚪",
    "structurally_intractable": "🟠", "chemically_unhit": "🟠",
    # --- foreclosure / killer ---
    "neither_viable": "🔴", "tce_unsafe_normal_liability": "🔴",
    "pan_essential_killer": "🔴", "non_dependent": "🔴",
}


def _render_gate_verdicts(primary: dict, additional: list[dict]) -> list[str]:
    """Render the PRIMARY resolver gate-verdict as the headline row + any additional gate
    verdicts (Stage 2). This is the VERDICT; the modality-fit table that follows is a
    demoted lens."""
    sections = ["## Verdict", ""]

    def _row(block: dict, primary_row: bool) -> str:
        gate = block.get("gate", "?")
        verdict = block.get("verdict", "?")
        icon = VERDICT_ICONS.get(verdict, "•")
        driver = block.get("driving_rule_id")
        driver_cell = f"`{driver}`" if driver else "_default (no rule fired)_"
        label = "**Primary**" if primary_row else gate
        return f"| {label} | `{gate}` | {icon} **{verdict}** | {driver_cell} |"

    sections.append("| Role | Gate | Verdict | Driving rule |")
    sections.append("|---|---|---|---|")
    sections.append(_row(primary, True))
    for blk in additional:
        sections.append(_row(blk, False))
    sections.append("")
    # Surface the fired-rule set once (shared across the gates resolved from one axis).
    fired = primary.get("fired_rule_ids") or []
    if fired:
        sections.append(
            "_Resolved from fired rules: " + ", ".join(f"`{r}`" for r in fired) + "._"
        )
        sections.append("")
    return sections


def _fmt_evidence_cell(entry: dict) -> str:
    """Render the 'Primary Evidence' cell of the modality-fit table.

    Distinguishes the dominant-signal path (worth the loudest cell) from the
    ratio-based path. Avoids the misleading 'X/N primary positive' phrasing when
    the dominant rule fired — the underlying decision logic is 'one dominant call
    is sufficient', so the cell should reflect that.
    """
    dominant = entry.get("dominant_hits", []) or []
    positive = entry.get("primary_cards_positive_count", 0)
    in_scope = entry.get("primary_cards_in_scope", 0)
    total = entry.get("primary_cards_total", in_scope)
    # A non_concludable modality's safety veto could not be assessed (killer-veto card
    # read_error / not_wired). This MUST short-circuit BEFORE the dominant/positive branches —
    # otherwise a non_concludable modality with positive primaries renders "N dominant positive
    # (sufficient)" green, silently defeating the fail-open safety fix in the human-facing table.
    if entry.get("fit_level") == "non_concludable":
        reasons = entry.get("non_concludable_reasons", []) or []
        detail = f" ({'; '.join(str(r) for r in reasons)})" if reasons else ""
        return f"Non-concludable — killer-veto card unavailable{detail}"
    if dominant:
        n = len(dominant)
        return f"**{n} dominant positive** (sufficient) — {positive}/{in_scope} of {total} total"
    if entry.get("fit_level") == "not_viable":
        return "—"
    if entry.get("fit_level") == "insufficient_evidence":
        return f"0/{in_scope} in scope ({total} total)"
    return f"{positive}/{in_scope} primary positive ({total} total)"


def _render_modality_fit_table(fit: list[dict]) -> list[str]:
    sections = []
    sections.append("## Modality Fit Assessment")
    sections.append("")
    sections.append("_Per-modality fit is a secondary lens on the resolver verdict above, "
                    "not the verdict itself._")
    sections.append("")

    # Collapse 1-modality table to an inline summary line.
    if len(fit) == 1:
        entry = fit[0]
        modality = entry.get("modality", "?")
        fit_level = entry.get("fit_level", "?")
        fit_icon = FIT_ICONS.get(fit_level, "")
        ev = _fmt_evidence_cell(entry)
        killers = entry.get("killer_conditions_hit", []) or []
        killer_line = (
            f" Killer conditions: {'; '.join(killers)}." if killers else ""
        )
        question = entry.get("headline_decision_question", "")
        sections.append(
            f"**{modality}** fit: {fit_icon} **{fit_level}**. "
            f"Evidence: {ev}.{killer_line}"
        )
        if question:
            sections.append("")
            sections.append(f"_Decision question: {question}_")
        sections.append("")
        return sections

    # >=2 modalities: render the table as usual
    sections.append("| Modality | Fit | Primary Evidence | Killer Conditions Hit |")
    sections.append("|---|---|---|---|")
    for entry in fit:
        modality = entry.get("modality", "?")
        fit_level = entry.get("fit_level", "?")
        killers = entry.get("killer_conditions_hit", []) or []
        killers_cell = "none" if not killers else f"{len(killers)} hit"
        fit_icon = FIT_ICONS.get(fit_level, "")
        sections.append(
            f"| **{modality}** | {fit_icon} {fit_level} | {_fmt_evidence_cell(entry)} | {killers_cell} |"
        )
    sections.append("")

    sections.append("### Decision Questions Asked")
    sections.append("")
    for entry in fit:
        modality = entry.get("modality", "?")
        question = entry.get("headline_decision_question", "")
        sections.append(f"- **{modality}**: _{question}_")
    sections.append("")
    return sections


def _render_toc(ep: dict, fit: list[dict]) -> list[str]:
    """Render a table of contents linking to each non-excluded card section + standard blocks."""
    sections = ["## Contents", ""]
    # Link the resolver Verdict section only when it renders (gated on primary_gate_verdict).
    if (ep.get("synthesis", {}) or {}).get("primary_gate_verdict"):
        sections.append("- [Verdict](#verdict)")
    # Only link the Modality Fit section when it actually renders (render_evidence_package gates it
    # on a non-empty `fit`); otherwise this was a dangling anchor for targets with no assessment.
    if fit:
        sections.append("- [Modality Fit Assessment](#modality-fit-assessment)")
    sections.append("- [Governance](#governance)")
    sections.append("- [Card Evidence](#card-evidence)")
    for card in ep.get("cards", []):
        # Excluded + unavailable cards render their own stub panels but are not TOC-linked as
        # evidence (they carry no interpretation_call); the Cards-Without-Evidence section
        # accounts for the unavailable ones.
        if card.get("excluded_by_applies_when") or card.get("availability_state"):
            continue
        cid = card.get("card_id", "")
        anchor = cid.replace("_", "-")
        interp = card.get("interpretation_call", "")
        sections.append(f"  - [`{cid}`](#-{anchor}--{interp.lower().replace(' ', '-').replace('—', '').replace('--', '-')[:40]}) — _{interp}_")
    # Link the Cards-Without-Evidence section only when it renders. _render_failed_cards_section
    # returns [] unless n_cards_failed is truthy, so gating on availability_state alone produced a
    # dangling anchor for a package with a reasoned-absence card but n_cards_failed == 0. (Those
    # cards still render their own panels above, so nothing is lost from the TOC change.)
    if ((ep.get("governance", {}) or {}).get("validation_summary", {}) or {}).get("n_cards_failed"):
        sections.append("- [Cards Without Evidence](#cards-without-evidence)")
    sections.append("- [Provenance Footer](#provenance-footer)")
    sections.append("")
    return sections


def _render_failed_cards_section(ep: dict) -> list[str]:
    """Reconcile the n_cards_failed count with the reasoned-absence panels (2026-07-20).

    Cards whose reader returned None are now emitted as card_unavailable entries (rendered
    as their own reasoned panels above), so the failure count is auditable BY NAME. This
    section reconciles the count: it points at the reasoned panels and only speculates for
    any RESIDUAL that has no card_unavailable entry (a genuine drop, e.g. a validation
    failure that never reached the availability path)."""
    gov = ep.get("governance", {}) or {}
    vs = gov.get("validation_summary", {}) or {}
    n_failed = vs.get("n_cards_failed", 0)
    if not n_failed:
        return []

    unavailable = [c for c in ep.get("cards", []) if c.get("availability_state")]
    n_reasoned = len(unavailable)
    n_residual = n_failed - n_reasoned

    sections = ["## Cards Without Evidence", ""]
    if n_reasoned:
        sections.append(
            f"{n_reasoned} of {n_failed} card(s) that produced no evidence are shown above as "
            f"**reasoned-absence panels** (🚧/🔎) with a typed `availability_state` — "
            f""
            "`" + "`, `".join(sorted({c['availability_state'] for c in unavailable})) + "`. "
            "Those are coverage gaps (or, for `insufficient`, a measured absence), not results."
        )
        sections.append("")
    if n_residual > 0:
        sections.append(
            f"{n_residual} further card(s) were dropped without a reasoned-absence entry — a "
            f"genuine drop (e.g. a validation failure that never reached the availability path). "
            f"_Likely causes_: method not importable, or all input sources errored. "
            # 2026-08-10 fix: don't point at `validation_report.json` — that file is
            # never written. The validation errors surface on stderr of the current producer
            # (target-profile --emit / render-evidence-package), and a failed run's package is
            # written with the `.invalid.json` suffix.
            f"Validation errors are reported on stderr of the producing path (target-profile --emit / "
            f"render-evidence-package); a failed run's "
            f"package is written as `evidence_package.invalid.json`."
        )
        sections.append("")
    return sections


def _render_governance(ep: dict) -> list[str]:
    gov = ep.get("governance", {}) or {}
    vs = gov.get("validation_summary", {}) or {}
    sections = []
    sections.append("## Governance")
    sections.append("")
    sections.append(f"- **Data mode**: `{gov.get('data_mode', 'unknown')}`")
    sections.append(f"- **Release pin**: `{gov.get('release_pin', 'unpinned')}`")
    if gov.get("lockfile_ref"):
        sections.append(f"- **Lockfile**: `{gov['lockfile_ref']}`")

    concur = gov.get("concurrence")
    if concur:
        sections.append(
            f"- **Concurrence**: {concur.get('state', '?')} "
            f"(reviewer: `{concur.get('reviewer_id', '?')}`)"
        )
    else:
        sections.append("- **Concurrence**: _not recorded_ (exploratory grade only — NOT citable in nominations)")

    sections.append("")
    sections.append("### Validation Summary")
    sections.append("")
    sections.append(f"- Cards attempted: **{vs.get('n_cards_attempted', 0)}**")
    sections.append(f"- Passed: **{vs.get('n_cards_passed', 0)}**")
    sections.append(f"- Passed with warnings: **{vs.get('n_cards_passed_with_warnings', 0)}**")
    sections.append(f"- Failed: **{vs.get('n_cards_failed', 0)}**")
    sections.append(f"- Excluded by `applies_when`: **{vs.get('n_cards_excluded_by_applies_when', 0)}**")
    sections.append("")
    return sections


# Human-readable gloss per availability_state (2026-07-20). Keep in sync with
# target-contracts/vocabularies/availability_state.enum.yaml.
_AVAILABILITY_GLOSS = {
    "not_wired": "no live reader is registered for this card yet (framework-coverage gap — "
                 "the card is a contract/placeholder, not backed by a method). NOT a data finding.",
    "data_blocked": "the reader exists but its derived data product is not available yet "
                    "(coverage gap gated on data acquisition, not the target's biology).",
    "read_error": "the reader was invoked and errored (transient/operational — may resolve on retry).",
    "insufficient": "the reader ran and looked, but the target is genuinely absent from the dataset "
                    "or below the power floor — a MEASURED coverage gap, not a negative result.",
}


def _render_card_panel(card: dict) -> list[str]:
    """Render a single card_present, card_excluded, or card_unavailable entry."""
    sections = []
    card_id = card.get("card_id", "unknown-card")

    # Excluded card → render a stub with reason
    if card.get("excluded_by_applies_when"):
        sections.append(f"### ⏸️ `{card_id}` — excluded")
        sections.append("")
        sections.append("_Excluded by `applies_when` at compose time._")
        sections.append("")
        sections.append(f"**Reason**: {card.get('exclusion_reason', '(no reason provided)')}")
        sections.append("")
        sections.append("---")
        sections.append("")
        return sections

    # Unavailable card (2026-07-20) → a reasoned absence, NOT a present card. Surfaces the
    # typed availability_state so a reader can tell "not built yet" from a measured absence
    # (previously such a card fell through to the present-card path and rendered as
    # "? uninterpreted", losing the reason entirely).
    state = card.get("availability_state")
    if state:
        measured = state == "insufficient"
        icon = "🔎" if measured else "🚧"
        sections.append(f"### {icon} `{card_id}` — unavailable (`{state}`)")
        sections.append("")
        sections.append(f"_{_AVAILABILITY_GLOSS.get(state, 'no signal produced.')}_")
        sections.append("")
        sections.append(f"**Reason**: {card.get('availability_reason', '(no reason provided)')}")
        sections.append("")
        if not measured:
            sections.append("> This is a **coverage gap, not evidence** — do not read the absence "
                            "as a negative result for the target.")
            sections.append("")
        sections.append("---")
        sections.append("")
        return sections

    # Present card
    interp = card.get("interpretation_call", "uninterpreted")
    val_state = card.get("validation_state", "?")
    state_icon = {"pass": "✓", "passed_with_warnings": "⚠"}.get(val_state, "?")
    sections.append(f"### {state_icon} `{card_id}` — _{interp}_")
    sections.append("")

    # Figures block — embed each card.figures[] entry as a markdown image reference.
    # Primary figure rendered first; alternate figures collapsed into a <details> block.
    figures = card.get("figures", []) or []
    if figures:
        primary = [f for f in figures if f.get("primary")]
        alternates = [f for f in figures if not f.get("primary")]
        for f in primary:
            alt = f.get("type", f.get("id", "figure"))
            sections.append(f"![{alt}]({f['path']})")
            sections.append("")
        if alternates:
            sections.append("<details><summary>Alternate views</summary>")
            sections.append("")
            for f in alternates:
                alt = f.get("type", f.get("id", "figure"))
                sections.append(f"![{alt}]({f['path']})")
                sections.append("")
            sections.append("</details>")
            sections.append("")

    # Summary block — scalars in a YAML block, lists-of-dicts pulled out as markdown
    # tables for readability. Internal-state keys (underscore-prefixed) are hidden.
    summary = card.get("summary", {}) or {}
    if summary:
        scalars = {}
        tabular = []
        for k, v in summary.items():
            if k.startswith("_"):
                continue  # hide framework-internal keys
            if _is_tabular_list(v):
                tabular.append((k, v))
            else:
                scalars[k] = v

        if scalars:
            sections.append("**Summary**:")
            sections.append("")
            sections.append("```yaml")
            for k, v in scalars.items():
                sections.append(f"{k}: {_format_yaml_value(v)}")
            sections.append("```")
            sections.append("")
        for k, rows in tabular:
            sections.append(f"**{k}**:")
            sections.append("")
            if k in _PANORAMA_RECORD_FIELDS:
                # Subgroup panorama — render with evidence_state trichotomy so a
                # measured negative reads differently from an underpowered unknown.
                sections.extend(_render_subgroup_panorama_table(rows))
            else:
                sections.extend(_render_list_of_dicts_as_table(rows))
            sections.append("")

    # Warning IDs
    warnings = card.get("warning_ids", []) or []
    if warnings:
        sections.append(f"**Warnings**: {', '.join(f'`{w}`' for w in warnings)}")
        sections.append("")

    # Caveats
    caveats = card.get("caveats", []) or []
    if caveats:
        sections.append("**Caveats**:")
        sections.append("")
        for c in caveats:
            sections.append(f"- {c}")
        sections.append("")

    # Provenance
    prov = card.get("provenance", {}) or {}
    method_calls = prov.get("method_calls", []) or []
    input_manifests = prov.get("input_manifest_ids", []) or []
    if method_calls or input_manifests:
        sections.append("<details><summary>Provenance</summary>")
        sections.append("")
        if method_calls:
            sections.append("Method calls:")
            for mc in method_calls:
                sections.append(f"- `{mc.get('method', '?')}@{mc.get('git_sha', '?')}`")
        if input_manifests:
            sections.append("")
            sections.append(f"Input manifests: {', '.join(f'`{m}`' for m in input_manifests)}")
        sections.append("")
        sections.append("</details>")
        sections.append("")

    sections.append("---")
    sections.append("")
    return sections


_FLOAT_PRECISION = 3


def _format_yaml_value(v) -> str:
    """Format a summary value for inclusion in a markdown YAML-block.

    Floats rounded to _FLOAT_PRECISION decimal places — humans don't read at 15
    significant digits, and the precision suggests false confidence in numbers
    that are estimates from finite-sample statistics. Provenance / manifest.yaml
    still carries full-precision values for audit; this is the display layer.
    """
    if isinstance(v, float):
        return f"{v:.{_FLOAT_PRECISION}f}"
    if isinstance(v, list):
        return json.dumps(v, default=str)
    if isinstance(v, dict):
        return json.dumps(v, default=str)
    if isinstance(v, str):
        return v
    return str(v)


def _is_tabular_list(v) -> bool:
    """Return True iff v is a non-empty list of dicts. Used to lift verbose
    list-of-dicts summary fields (e.g. top_dependent_lineages, hotspot_frequencies)
    out of the YAML block into their own table."""
    if not isinstance(v, list) or not v:
        return False
    if not all(isinstance(item, dict) for item in v):
        return False
    return True


def _render_list_of_dicts_as_table(rows: list[dict]) -> list[str]:
    """Render a list of dicts as a markdown table. Columns are the union of all
    keys (preserving first-seen order). Float values rounded to _FLOAT_PRECISION."""
    cols = []
    seen = set()
    for r in rows:
        for k in r.keys():
            if k not in seen:
                cols.append(k)
                seen.add(k)
    lines = []
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("|" + "|".join(["---"] * len(cols)) + "|")
    for r in rows:
        cells = []
        for k in cols:
            v = r.get(k, "")
            if isinstance(v, float):
                cells.append(f"{v:.{_FLOAT_PRECISION}f}")
            elif isinstance(v, (list, dict)):
                cells.append(json.dumps(v, default=str))
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


# Subgroup-panorama record fields (2026-07-16). Rendered with evidence_state
# awareness rather than the generic list-of-dicts table. Both spellings in use.
_PANORAMA_RECORD_FIELDS = {"per_subgroup_metrics", "per_stratum_metrics"}

# evidence_state → (icon, label) for the descriptive trichotomy. A `measured`
# negative (real value on a floor-clearing cohort) is a trusted finding; an
# `underpowered` / `absent` row is an UNKNOWN and must read differently.
_EVIDENCE_STATE_BADGE = {
    "measured": ("●", "measured"),
    "underpowered": ("◐", "underpowered"),
    "absent": ("○", "absent"),
}
_SUBGROUP_N_FLOOR = 30  # mirrors methods/subgroup_common/panorama.py SUBGROUP_N_FLOOR


def _render_subgroup_panorama_table(rows: list[dict]) -> list[str]:
    """Render a per-subgroup panorama with the evidence_state trichotomy made legible.

    Descriptive-only: enumerates EVERY stratum row (positive AND negative). The
    evidence_state column distinguishes a trusted `measured` value (floor-cleared)
    from an `underpowered` / `absent` UNKNOWN. Underpowered rows are flagged
    inline with their n vs the floor so a reader never mistakes an unknown for a
    confirmed negative — and (per the admissibility rule) never lifts an
    underpowered number into a comparative claim.

    `stratum` and `evidence_state` are pinned as the first two columns; the rest
    follow first-seen order. Internal (underscore-prefixed) keys are hidden.
    """
    if not rows:
        return ["_(no subgroup rows)_"]

    # Column order: stratum, evidence_state, then the rest (first-seen), no _keys.
    lead = [c for c in ("stratum", "evidence_state") if any(c in r for r in rows)]
    cols = list(lead)
    for r in rows:
        for k in r.keys():
            if k.startswith("_") or k in cols:
                continue
            cols.append(k)

    lines = ["| " + " | ".join(cols) + " |",
             "|" + "|".join(["---"] * len(cols)) + "|"]
    for r in rows:
        state = r.get("evidence_state")
        cells = []
        for k in cols:
            if k == "evidence_state":
                icon, label = _EVIDENCE_STATE_BADGE.get(state, ("?", str(state)))
                # Flag underpowered rows inline with n vs floor.
                if state == "underpowered":
                    n = r.get("subgroup_n")
                    label = f"underpowered (n={n}<{_SUBGROUP_N_FLOOR})" if n is not None else "underpowered"
                cells.append(f"{icon} {label}")
                continue
            v = r.get(k, "")
            if isinstance(v, float):
                cells.append(f"{v:.{_FLOAT_PRECISION}f}")
            elif isinstance(v, (list, dict)):
                cells.append(json.dumps(v, default=str))
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")

    # Legend + admissibility note — the descriptive payoff made explicit.
    lines.append("")
    lines.append(
        "_● measured (n≥{floor}, trusted — a real negative is as informative as a "
        "positive) · ◐ underpowered (n<{floor}, UNKNOWN — inadmissible in comparative "
        "claims) · ○ absent (no samples in this stratum). Rows tagged by source_cohort "
        "are not merged across cohorts._".format(floor=_SUBGROUP_N_FLOOR)
    )
    return lines


def _render_provenance_footer(ep: dict) -> list[str]:
    sections = []
    sections.append("## Provenance Footer")
    sections.append("")
    sections.append(f"- **Generated at**: `{ep.get('generated_at', 'unknown')}`")
    sections.append(f"- **Generated by**: `{ep.get('generated_by', 'unknown')}`")
    sections.append(f"- **Dashboard spec**: `{ep.get('dashboard_spec_ref', 'unknown')}`")
    ctx = ep.get("context", {}) or {}
    if ctx.get("subgroup_spec"):
        sections.append(f"- **Subgroup spec**: `{ctx['subgroup_spec']}`")
    sections.append(f"- **Schema version**: {ep.get('schema_version', '?')}")
    sections.append("")
    return sections


# ============================================================================
# CLI
# ============================================================================

@click.command()
@click.option("--evidence-package", "ep_path", required=True,
              type=click.Path(exists=True, dir_okay=False, path_type=Path),
              help="Path to evidence_package.json (or evidence_package.yaml).")
@click.option("--out", required=True, type=click.Path(dir_okay=False, path_type=Path),
              help="Output markdown path (typically dashboard.md).")
def main(ep_path: Path, out: Path) -> int:
    """Render an evidence_package to Stage-1 markdown."""
    with ep_path.open() as f:
        if ep_path.suffix.lower() in (".yaml", ".yml"):
            import yaml as _yaml
            ep = _yaml.safe_load(f)
        else:
            ep = json.load(f)

    md = render_evidence_package(ep)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")

    target = ep.get("context", {}).get("target", {}).get("symbol", "?")
    indication = ep.get("context", {}).get("indication", {}).get("oncotree_code", "?")
    n_cards = len(ep.get("cards", []))
    click.echo("=== render_markdown ===")
    click.echo(f"  evidence_package: {ep_path}")
    click.echo(f"  target/indication: {target} / {indication}")
    click.echo(f"  cards rendered:    {n_cards}")
    click.echo(f"  → wrote:           {out} ({len(md)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
