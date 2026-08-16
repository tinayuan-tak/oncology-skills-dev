"""target-profile — Tier-3 LLM synthesis prompt assembly: system prompt, forced structured tool,
and the deterministic user-prompt builder (card summaries + ordinal matrix slice)."""
from __future__ import annotations

import argparse
import concurrent.futures
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import yaml

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _skills_common import EVIDENCE_ONLY_DIRECTIVE as _EVIDENCE_ONLY_DIRECTIVE, resolve_cards, fired_rules, ordinal_view




# --- LLM synthesis ----------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are synthesizing a target-profile summary for a drug-discovery "
    "scientist at a major pharma. You will be given deterministic, rule-"
    "derived sub-verdicts from up to 10 evidence dimensions (expression, "
    "selectivity, dependency, mechanism, mutation, differentiation, "
    "tractability, safety, population, cohort_rank). Your job is to (a) "
    "write a concise executive summary, (b) surface any tension across "
    "the sub-verdicts, (c) list top arguments for and against pursuing "
    "this target, and (d) recommend a nomination action. Base every "
    "claim on the provided evidence. Do NOT invent biology. If evidence "
    "is thin or missing for a dimension, say so explicitly rather than "
    "filling with generalities. Note (arch A2): the tractability sub-"
    "verdict emits letter grades (adc_grade, tce_grade) ONLY when the "
    "modality lens was invoked at runtime — if those fields are absent, "
    "reason from the biology-agnostic fit_class categorical instead. "
    "Note (arch A3): the mechanism sub-verdict flags isoform-selective "
    "targets (e.g., ERBB2/p95HER2, AR/AR-V7, MET/exon14, EGFR/vIII); if "
    "isoform_selective_warning is true, gene-level modality claims should "
    "be qualified with isoform-resolution caveats. "
    "Note (matrix view): you are also given a modality-scoped evidence matrix "
    "(gate x modality). It is a REPROJECTION of the same signals, NOT new "
    "evidence and NOT a score — use it to reason about WHICH MODALITY each gate "
    "favors (e.g. a degrader-preferred vs small-molecule split) and to ground the "
    "modality framing of your recommendation. The ordinals are order-preserving, "
    "NOT calibrated: never sum or average them, and treat off-scale cells "
    "(insufficient/not_applicable) as coverage gaps, not low scores. When a matrix "
    "cell disagrees with a gate's resolved verdict, the VERDICT is the decision — "
    "the cell is the raw per-modality signal behind it. "
    "Note (altitude): your PRIMARY job is the INTEGRATED relevance case — reason across the biology "
    "lenses (expression, selectivity, dependency, mechanism, mutation, safety) to a recommendation. "
    "Modality is a SECONDARY, supporting dimension: discuss it AFTER the relevance case has been made, "
    "not as the headline. "
    "Note (register): write to scientific-publication standard — the voice of a methods/results "
    "section. Declarative, precise, factual; complete sentences; active voice. Report each number with "
    "its scale and direction, never bare. Do NOT use promotional or editorialising language (avoid "
    "'promising', 'exciting', 'compelling', 'robustly', 'clearly'); let the evidence carry the claim. "
    "Concise but readable — a domain biologist who is not a statistician must follow it without a "
    "glossary. On FIRST use of a technical metric, add a short plain-language parenthetical gloss (e.g. "
    "Chronos knockout fitness score ~ -1 = a typically essential gene; ε² = fraction of variation a "
    "grouping explains, ~0.14 large; log2 fold-change +1 = 2x). A deterministic metric_legend is also "
    "attached to the output for reference. "
    "Note (biology-axis governance): you may be given a MODALITY-EMPHASIS GOVERNANCE block stating the "
    "target's curated biology_axis (intracellular vs surface) and its plausible modalities. WHEN you "
    "discuss modality, RESPECT it — do not propose ADC/T-cell-engager/CAR for an intracellular target "
    "(or small-molecule-occupancy for a purely surface antigen) unless a fired rule overrides the axis. "
    "The block keeps modality talk biologically honest; it does NOT make modality the lead, and it never "
    "changes the deterministic verdict or recommendation (the gate owns those)."
    + _EVIDENCE_ONLY_DIRECTIVE
)

# Cross-cutting plain-language legend for the metrics the COMPOSED synthesis may cite across lenses.
# Attached to the LLM output as a sibling key (metric_legend) so a non-computational reader has an
# accurate, byte-stable reference independent of the LLM's inline glosses. Superset of the per-lens
# METRIC_LEGENDs in _skills_common/synthesis_*.py (this composed view spans all lenses).
_METRIC_LEGEND = {
    "chronos_score": ("CRISPR knockout fitness score (dependency lens). 0 = knockout does not affect "
                      "growth; ~ -1 = a typically essential gene; more negative = stronger dependency. "
                      "A pan-essential-level score is a broad-toxicity liability, not a target win."),
    "log2_fold_change": ("log2 of a ratio (e.g. tumour vs normal expression). +1 = 2x higher, 0 = no "
                         "difference. Used by the expression/selectivity lenses."),
    "allgene_percentile": ("Where a target ranks among ALL genes in the same cohort (0-100) — the "
                           "'relative to what?' frame for abundance (presence) or fold-change "
                           "(selectivity)."),
    "epsilon_squared": ("ε² (epsilon-squared): the fraction of a signal's variation across a grouping "
                        "(molecular subtype, or lineage for dependency) that the grouping explains, "
                        "0-1. ~0.06 moderate, ~0.14 large. Large = concentrated in a subgroup."),
    "driver_recurrence_percentile": ("Where a gene's mutation recurrence ranks among all mutated genes "
                                     "in the indication (mutation lens). High = recurrent beyond the "
                                     "passenger background; frequency is not function."),
    "alteration_role": ("Curated functional call (OncoKB x IntOGen): GoF (activating oncogene), LoF "
                        "(tumour suppressor), predictive_biomarker, or passenger."),
    "fit_class": ("Surface-modality-fit verdict: ADC_preferred / TCE_preferred / both_viable / "
                  "neither_viable — whether surface biology (topology, family) supports a biologics "
                  "modality. Distinct from the small-molecule tractability call."),
    "ordinal_matrix": ("A gate x modality reprojection of the same signals into order-preserving "
                       "ordinals — NOT a calibrated score; never summed or averaged. Off-scale cells "
                       "(insufficient / not_applicable) are coverage gaps, not low scores."),
    "verdict_fragility": ("Flip-stability (fragility facet): re-runs the deterministic resolver over "
                          "single-rule-perturbed fired sets. target_index = worst-case fraction of a "
                          "gate's verdict-movable rules whose toggle changes the DECISION ROLE (how "
                          "solid each axis's CALL is). recommendation_fragility_index = worst-case whose "
                          "toggle crosses the KILL boundary (how solid the GO/NO-GO is) — this drives "
                          "the `contested` banner. 0 = robust. Blind (un-evidenced) axes are a coverage "
                          "gap tracked separately, not folded in. A structural sensitivity measure — NOT "
                          "a probability the target succeeds, never summed/averaged, never moves the "
                          "recommendation."),
}


def _build_synthesis_tool() -> dict:
    """Tool schema for the LLM synthesis call. Enums are the audit-critical
    fields — LLM cannot free-form the recommendation."""
    return {
        "description": (
            "Emit a structured target-profile summary composed of one "
            "executive summary paragraph, tension analysis, top "
            "arguments for/against, and an overall recommendation."
        ),
        "type": "object",
        "required": [
            "executive_summary", "tension_analysis",
            "top_arguments_for", "top_arguments_against",
            "overall_recommendation", "confidence",
        ],
        "properties": {
            "executive_summary": {
                "type": "string",
                "description": (
                    "3-5 sentence synthesis of what the (up to 10) sub-verdicts "
                    "collectively imply for this (target, indication)."
                ),
            },
            "tension_analysis": {
                "type": "string",
                "description": (
                    "Where sub-verdicts disagree and why — e.g. tumor-"
                    "selectivity says discordant while functional-"
                    "requirement says lineage_selective. If there's no "
                    "meaningful tension, say so briefly (do not invent)."
                ),
            },
            "top_arguments_for": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
                "description": "Up to 5 strongest positive arguments.",
            },
            "top_arguments_against": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
                "description": "Up to 5 strongest negative arguments.",
            },
            "overall_recommendation": {
                "type": "string",
                "enum": ["nominate", "hold", "veto", "insufficient_evidence"],
                "description": (
                    "Nomination action: nominate = pursue; hold = "
                    "revisit after specific evidence gaps close; veto = "
                    "do not pursue; insufficient_evidence = cannot call."
                ),
            },
            "confidence": {
                "type": "string",
                "enum": ["high", "medium", "low", "insufficient"],
                "description": (
                    "Analyst-facing confidence in the recommendation. "
                    "'insufficient' iff overall_recommendation is "
                    "insufficient_evidence."
                ),
            },
        },
    }


def _render_matrix_slice_for_prompt(ordinal_matrix: dict) -> list[str]:
    """The gate × modality ordinal matrix as prompt text (gap #4b): lets synthesis reason over
    the MATRIX-SLICE (which modality does each gate favor?) instead of only the flat verdict list.
    Emphatically labeled a REPROJECTION of the same signals — not new evidence, not a score."""
    cols = ordinal_matrix["axes"]["columns"]
    leg = ordinal_matrix["legend"]
    lines = [
        "### Modality-scoped evidence matrix (a VIEW — reprojection, NOT new evidence)",
        "Each cell is the STRONGEST signal a gate emits for that modality, on an ORDER-PRESERVING "
        "ordinal scale (NOT calibrated — gaps are not metric). Use it to see WHICH MODALITY each "
        "gate favors (e.g. a degrader-preferred vs small-molecule-opposing split) — a nuance the "
        "flat verdict list flattens. A cell can differ from the resolved verdict (the cell is the "
        "raw signal; the verdict is the ordered-precedence decision). The verdict is the decision; "
        "the matrix is for modality reasoning only. Do NOT sum or average the ordinals.",
        "Scale: " + ", ".join(f"{k}={v:+d}" for k, v in sorted(leg["on_scale"].items(),
                                                               key=lambda t: -t[1]))
        + f"; off-scale (coverage, not a low score): {', '.join(leg['off_scale'])}; `·` = no signal.",
        "",
        "| gate | " + " | ".join(cols) + " |",
        "|" + "---|" * (len(cols) + 1),
    ]
    for row in ordinal_matrix["rows"]:
        cells = row["cells"]
        glyphs = " | ".join(ordinal_view._cell_glyph(cells[m]) for m in cols)
        lines.append(f"| {row['short']} | {glyphs} |")
    lines.append("")
    return lines


# Distribution-evidence field patterns that MUST survive to the LLM prompt intact (the Audit-B /
# 12-question-spec extraction layer emits these; the old blind truncation loop collapsed lists>5 and
# hard-capped at 1200 chars/card, destroying exactly the per-sample distribution signal the spec is
# about). Substring-matched against summary keys. Scalars always survive; only genuinely-oversized
# UNKNOWN lists get sampled.
_LOAD_BEARING_SUMMARY_KEY_PARTS = (
    "median", "percentile", "_pct", "p95", "p99", "p5", "p25", "p75",
    "fraction", "frac_", "coefficient_of_variation", "cov", "distribution_pattern",
    "log2fc", "log2_fc", "effect_size", "q_value", "bh_q", "class", "n_tumor", "n_normal",
    "n_cohorts", "n_indications", "concordance", "correlation", "enrich", "above_normal",
    "tumor_median", "normal_median", "detectable", "expressed",
    # per-entity evidence TABLES (the rows ARE the decision evidence — keep top-N, don't drop):
    "lineage", "per_", "stats", "models", "elevated", "tissues", "cohorts", "indications",
    "subtype", "recommended",
)
_PROMPT_CARD_CHAR_CAP = 3000   # raised from 1200; only bites on pathological output


def _format_card_summary_for_prompt(summary: dict) -> str:
    """Render a card summary for the LLM prompt, GUARANTEEING load-bearing distribution fields
    survive (the old loop dropped `_`-prefixed keys, sampled lists>5 to 3, and hard-capped 1200
    chars — destroying the per-sample distribution stats the extraction layer produces). Policy:
      - scalars (str/num/bool/None) always kept in full;
      - a list whose key matches a load-bearing pattern (e.g. per_lineage_stats, most_elevated_*)
        is kept as its top-8 rows (not dropped to a `_len`), since these ARE the decision evidence;
      - other/unknown lists >8 are summarized as {_len, _sample:3} (the old behavior, for genuine
        noise only);
      - `_`-prefixed provenance keys are still dropped (not decision evidence);
      - a generous per-card cap (3000) only trims pathological output."""
    def _is_scalar(v):
        return v is None or isinstance(v, (str, int, float, bool))

    def _load_bearing(key: str) -> bool:
        kl = key.lower()
        return any(part in kl for part in _LOAD_BEARING_SUMMARY_KEY_PARTS)

    out = {}
    for k, v in summary.items():
        if k.startswith("_"):
            continue
        if _is_scalar(v):
            out[k] = v
        elif isinstance(v, list):
            if _load_bearing(k):
                out[k] = v[:8]                      # keep the decision rows
            elif len(v) > 8:
                out[f"{k}_len"] = len(v)
                out[f"{k}_sample"] = v[:3]
            else:
                out[k] = v
        else:  # dict / nested
            out[k] = v
    return json.dumps(out, default=str)[:_PROMPT_CARD_CHAR_CAP]


def _build_user_prompt(
    target: str,
    indication: str,
    sub_results: dict,
    modality: Optional[str] = None,
    therapeutic_hypothesis: Optional[str] = None,
    ordinal_matrix: Optional[dict] = None,
    biomarker_facet: Optional[dict] = None,
    subtype_facet: Optional[dict] = None,
    axis_info: Optional[dict] = None,
) -> str:
    """Compose the user-message text: biology-axis governance + sub-verdicts + modality-scoped
    matrix slice + biomarker convergence facet + card summaries + optional lens context.

    axis_info (from _skills_common.biology_axis.resolve_biology_axis) steers modality EMPHASIS:
    it foregrounds the plausible modalities for the target's curated axis so the narration does
    not over-weight surface-antigen framing for an intracellular target (or vice versa). It is a
    SLOT-2 emphasis steer only — the deterministic verdict + recommendation are untouched."""
    lines = [
        f"Target: {target}",
        f"Indication: {indication}",
    ]
    if axis_info is not None:
        from _skills_common.biology_axis import format_axis_governance_block
        lines.append("")
        lines.append(format_axis_governance_block(axis_info))
    if modality:
        lines.append(f"Modality lens (post-hoc, reweight narrative): {modality}")
    if therapeutic_hypothesis:
        lines.append(f"Therapeutic hypothesis (post-hoc, reweight narrative): "
                     f"{therapeutic_hypothesis}")
    lines.append("")
    lines.append("### Sub-verdicts (deterministic, rule-fired)")
    for short, r in sub_results.items():
        v = r["verdict"]
        if v is None:
            lines.append(f"- **{short}** ({r['skill_dir']}): "
                         f"no rule-fired verdict (skill relies on raw metrics)")
        else:
            verdict_str, driving_rule = v
            lines.append(f"- **{short}** ({r['skill_dir']}): "
                         f"`{verdict_str}` (driving rule: {driving_rule})")
    lines.append("")
    if ordinal_matrix is not None:
        lines.extend(_render_matrix_slice_for_prompt(ordinal_matrix))
    if biomarker_facet is not None:
        bf = biomarker_facet
        lines.append("")
        lines.append("### Biomarker convergence facet (deterministic; a FACET, not a gate)")
        lines.append(f"- facet verdict: `{bf.get('verdict')}`  |  preferred assay: "
                     f"`{bf.get('preferred_assay')}`")
        corr = {k: v for k, v in (bf.get("corroboration_role") or {}).items() if v is not None}
        strat = {k: v for k, v in (bf.get("stratification_role") or {}).items() if v is not None}
        lines.append(f"- corroboration (→ confidence in biology verdicts): "
                     f"{corr if corr else 'none reachable'}")
        lines.append(f"- stratification (→ patient selection): {strat if strat else 'none reachable'}")
        # A2c: surface the QUANTITATIVE strengths behind the classes (from A2a's `quantitative` block)
        # so the narration reports HOW STRONG each biomarker signal is, not just its bucket. Each stat
        # is glossed in plain language for a non-computational reader (publication-register discipline).
        quant = {k: v for k, v in (bf.get("quantitative") or {}).items() if v}
        if quant:
            lines.append(f"- quantitative strength (raw statistics behind the classes above): {quant}")
            lines.append("  METRIC GLOSS (interpret in plain language; report with scale + direction): "
                         "hotspot_mannwhitney_q = FDR-adjusted p that mutant vs WT Chronos differ (lower "
                         "= more separated); hotspot_effect_size = rank-biserial (0-1, higher = cleaner "
                         "mutant-vs-WT dependency split); delta_chronos_* = mutant-minus-WT median "
                         "Chronos (more negative = mutant lines more dependent); pearson_r/spearman = "
                         "expression↔dependency correlation (negative = higher expression, more "
                         "dependent); fraction_agree = CRISPR/RNAi concordance rate; rna_protein_r = "
                         "how well RNA proxies protein (higher = RNA is an adequate assay); logrank_p = "
                         "expression↔survival separation. These quantify the STRATIFICATION / "
                         "CORROBORATION strength; they predict DEPENDENCY, not proven drug response.")
        lines.append("  NOTE: this facet may RAISE CONFIDENCE (corroboration) or define the "
                     "patient-selection population (stratification); it must NEVER by itself justify "
                     "a `nominate` — the deterministic gate owns the recommendation.")
    if subtype_facet is not None:
        sf = subtype_facet
        lines.append("")
        lines.append("### Subtype convergence facet (deterministic; a FACET, not a gate)")
        lines.append(f"- facet verdict: `{sf.get('verdict')}`  |  axes available: "
                     f"{sf.get('axes_available') or 'none'}  |  subtypes evaluated: "
                     f"{sf.get('n_subtypes_evaluated')}")
        conv = sf.get("convergent_subtypes") or []
        if conv:
            lines.append(f"- CONVERGENT subtypes (>=2 measured axes → cross-axis patient-selection "
                         f"strata): {conv}")
            for st in conv:
                b = (sf.get("per_subtype") or {}).get(st, {})
                lines.append(f"    - {st}: measured on {b.get('axes_measured')} "
                             f"(metrics: {b.get('metrics')})")
        else:
            lines.append("- no subtype converges >=2 measured axes on the SAME id this run")
        assoc = sf.get("associated_subtypes") or []
        if assoc:
            lines.append("- ASSOCIATED strata (different strata, each measured on its own axis, linked "
                         "by a subtype-registry association — RELATED, not the same stratum):")
            for a in assoc:
                bridge = " [CROSS-COHORT bridge: DepMap↔TCGA — interpret cautiously]" if a.get("cohort_bridge") else ""
                lines.append(f"    - {a['from']} {a['relationship']} {a['to']} "
                             f"({a['from_axes_measured']} ↔ {a['to_axes_measured']}){bridge}")
        lines.append("  NOTE: subtype convergence/association defines a PATIENT-SELECTION population + may "
                     "raise confidence; it must NEVER by itself justify a `nominate`. An ASSOCIATED pair "
                     "is a WEAK, registry-bridged link (e.g. MSI_H-dependency ↔ CMS1-expression) — the two "
                     "strata are biologically related, NOT identical; a cohort_bridge crosses DepMap↔TCGA. "
                     "subtype_axis_unavailable = no subtype shard for this indication (a P2 coverage gap), "
                     "not a measured negative.")
    lines.append("### Card summaries (raw, per-card)")
    for short, r in sub_results.items():
        lines.append(f"\n#### {short} ({r['skill_dir']})")
        for c in r["cards"]:
            cid = c["card_id"]
            # Distinguish the TWO _missing kinds (both are tagged _missing=True by resolve_cards,
            # but they mean opposite things to a reviewer):
            #   dispatcher_returned_none → the card is NOT WIRED (no reader) → truly absent.
            #   <anything else>          → the card WAS READ and returned data_unavailable → this is
            #     a MEASURED gap (coverage/proxy/underpowering), and resolve_cards RETAINED the real
            #     summary. Forwarding it (with its reason) is the difference between "we looked and
            #     found nothing" and "we never looked" — the measured-negative-vs-data_unavailable
            #     doctrine, applied inside the prompt so the LLM does not conflate them.
            if c.get("_missing"):
                reason = c.get("_missing_reason")
                if reason == "dispatcher_returned_none":
                    lines.append(f"- {cid}: NOT WIRED (no dispatcher)")
                    continue
                summary = c.get("summary") or {}
                detail = _format_card_summary_for_prompt(summary) if summary else "no summary fields"
                lines.append(f"- {cid}: DATA_UNAVAILABLE ({reason or 'measured gap'}) — {detail}")
                continue
            summary = c.get("summary") or {}
            lines.append(f"- {cid}: {_format_card_summary_for_prompt(summary)}")
    lines.append("")
    lines.append("### Fired rules (across all sub-skills, biology-first)")
    # Pass rule COLOR (rationale / signals / killer_message) — these are already computed on every
    # fired rule (_skills_common.fired_rules) but were previously dropped from the prompt, so the LLM
    # saw THAT a rule fired, never WHY. Surfacing them lets the model reason about significance +
    # modality direction, not just state. (Verdict spine unchanged — this is prompt-only enrichment.)
    for short, r in sub_results.items():
        for f in r["fired"]:
            line = f"- [{short}] {f['rule_id']} on {f['card_id']}.{f['field']} = {f['value']}"
            signals = f.get("signals") or {}
            if signals:
                line += "  | signals: " + ", ".join(f"{k}={v}" for k, v in signals.items())
            killer = f.get("killer_message")
            if killer:
                line += f"  | KILLER: {killer.strip()}"
            rationale = (f.get("rationale") or "").strip()
            if rationale:
                # one-line the rationale + cap so a verbose block-scalar can't blow the prompt
                one_line = " ".join(rationale.split())
                line += f"  | why: {one_line[:240]}"
            lines.append(line)
    return "\n".join(lines)


__all__ = [
    '_LOAD_BEARING_SUMMARY_KEY_PARTS',
    '_METRIC_LEGEND',
    '_PROMPT_CARD_CHAR_CAP',
    '_SYSTEM_PROMPT',
    '_build_synthesis_tool',
    '_build_user_prompt',
    '_format_card_summary_for_prompt',
    '_render_matrix_slice_for_prompt',
]
