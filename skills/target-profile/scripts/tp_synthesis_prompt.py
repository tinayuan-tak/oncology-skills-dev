"""target-profile — Tier-3 LLM synthesis prompt assembly: system prompt, forced structured tool,
and the deterministic user-prompt builder (card summaries + ordinal matrix slice)."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Optional


_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _skills_common import EVIDENCE_ONLY_DIRECTIVE as _EVIDENCE_ONLY_DIRECTIVE, ordinal_view
from _skills_common.signals_first import render_signal_summary




# --- LLM synthesis ----------------------------------------------------------

_SYSTEM_PROMPT = (
    "You are synthesizing a target-profile summary for a drug-discovery "
    "scientist at a major pharma. You will be given deterministic, rule-"
    "derived sub-verdicts from the evidence dimensions of the fan-out (expression, "
    "selectivity, dependency, synthetic-lethal partners, combinatorial dependency, "
    "mechanism, genomic alteration, differentiation, small-molecule tractability, "
    "surface/modality fit, safety, cis-coherence, and an indication-independent "
    "target-intrinsic dossier). Your job is to (a) "
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
    "lenses (expression, selectivity, dependency, mechanism, genomic alteration, safety) to a recommendation. "
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
            "exec_bullets", "executive_summary", "tension_analysis",
            "top_arguments_for", "top_arguments_against",
            "overall_recommendation", "confidence",
        ],
        "properties": {
            "exec_bullets": {
                "type": "array", "minItems": 1, "maxItems": 6,
                "description": (
                    "PRIMARY: <=6 crisp executive bullets reasoning ACROSS the sub-skills — each carrying "
                    "the SALIENT grounded datum from a sub-skill's KEY EVIDENCE (the indication/strongest "
                    "stratum effect WITH its q/p, the omnibus, the driving categorical) and weaving a "
                    "corroborating/contrasting literature citation where present. Connect >=2 signals per "
                    "bullet (corroboration, tension, or modality implication). Anchor each to real "
                    "card_id/rule_id tokens from the Per-verdict narrative block; <=~40 words; scientific voice."),
                "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["text", "polarity", "cites"],
                    "properties": {
                        "text": {"type": "string"},
                        "polarity": {"type": "string",
                                     "enum": ["supportive", "opposing", "neutral", "killer", "not_applicable"]},
                        "cites": {"type": "object", "additionalProperties": False,
                                  "properties": {
                                      "card_ids": {"type": "array", "items": {"type": "string"}},
                                      "question_ids": {"type": "array", "items": {"type": "string"}},
                                      "citation_ids": {"type": "array", "items": {"type": "string"}}}}}}},
            "executive_summary": {
                "type": "string",
                "description": (
                    "SECONDARY verbose prose (demoted below exec_bullets): 3-5 sentence synthesis of what "
                    "the (up to 10) sub-verdicts collectively imply for this (target, indication). CITE the "
                    "load-bearing driver(s) inline in square brackets — [rule_id] "
                    "and/or [card_id] — using ONLY anchors from the Per-verdict "
                    "narrative block."
                ),
            },
            "tension_analysis": {
                "type": "string",
                "description": (
                    "Where sub-verdicts disagree and why — e.g. tumor-"
                    "selectivity says discordant while functional-"
                    "requirement says lineage_selective. Ground each tension in "
                    "the specific dissenting / flip anchor inline in [brackets] "
                    "([rule_id]/[card_id]) from the Per-verdict narrative block. "
                    "If there's no meaningful tension, say so briefly (do not invent)."
                ),
            },
            "top_arguments_for": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
                "description": ("Up to 5 strongest positive arguments; each cites its "
                                "supporting [rule_id]/[card_id] anchor inline."),
            },
            "top_arguments_against": {
                "type": "array",
                "items": {"type": "string"},
                "maxItems": 5,
                "description": ("Up to 5 strongest negative arguments; each cites its "
                                "[rule_id]/[card_id] anchor inline (a dissenter, veto, or gap)."),
            },
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["claim", "anchors"],
                    "properties": {
                        "claim": {"type": "string",
                                  "description": "the argument / tension this supports"},
                        "anchors": {"type": "array", "items": {"type": "string"},
                                    "description": ("rule_id and/or card_id tokens (from the "
                                                    "Per-verdict narrative block) that back the claim")},
                    },
                },
                "description": (
                    "OPTIONAL structured backing for the load-bearing claims: each entry maps a "
                    "claim to the rule_id/card_id anchors that support it. Every anchor MUST appear "
                    "in the provided Per-verdict narrative block — never invent one."
                ),
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
    """The gate × modality ordinal matrix as prompt text: lets synthesis reason over
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


def _render_certainty_block(fragility: dict, sub_results: dict) -> list[str]:
    """Render the per-axis how-solid block from the ALREADY-computed fragility facet.

    Purely presentational + VERDICT-INERT: it reads the facet's `per_axis` (coverage +
    call-fragility) and `blind_decision_axes`, plus each sub-result's missing-card count, and
    renders them for the narration to calibrate confidence. It NEVER changes the recommendation,
    the gate, or the audited confidence tier.

    The framing keeps TWO signals explicitly DISTINCT (the Phase-0.5 fix, motivated by the MET/LUAD
    A/B, where the LLM read a high flip-fragility on a biologically-solid concordant negative as
    evidentiary doubt): COVERAGE is an EVIDENCE signal (did we measure it), while CALL-FRAGILITY is
    a STRUCTURAL property of the resolver ladder (how sensitive the verdict LABEL is to a single
    rule toggle) — NOT a measure of evidence strength. A fully-covered, independently-corroborated
    call can still be flip-fragile, and vice versa; flip-fragility must not be narrated as an
    'unresolved gap'. WEAKEST-LINK (do not average across axes) and the MNAR discipline (a blind
    axis is absence-of-evidence, not a negative) are stated so the LLM does not scalarize or
    mis-read a coverage gap as a finding."""
    per_axis = (fragility.get("per_axis") or {})
    if not per_axis:
        return []
    lines = [
        "",
        "### Per-axis how-solid facet (deterministic; a FACET, not a gate)",
        "TWO DISTINCT per-axis signals — do NOT conflate them, and do NOT average or sum either "
        "across axes (read WEAKEST-LINK):",
        "  (1) COVERAGE — did we measure this axis, and with what power (an EVIDENCE signal). "
        "`blind` / low coverage = ABSENCE OF EVIDENCE (we did not look), NOT evidence of absence; "
        "never narrate a blind or low-coverage axis as a negative finding.",
        "  (2) CALL-FRAGILITY — how sensitive the verdict LABEL is to toggling a single rule in the "
        "resolver ladder. This is a STRUCTURAL property of the scoring boundary, NOT a measure of "
        "evidence strength. A fully-covered, independently-corroborated call can still be "
        "flip-fragile, and vice versa. Do NOT read flip-fragility as evidentiary doubt or an "
        "'unresolved gap': a flip-fragile call whose underlying data is complete and concordant is a "
        "SOLID call sitting on a sensitive rule boundary — narrate it that way, not as 'we don't know'.",
        "| axis | call | coverage (evidence) | call-fragility (structural) | missing cards |",
        "|---|---|---|---|---|",
    ]
    for short in sorted(per_axis):
        pa = per_axis[short]
        r = sub_results.get(short) or {}
        cards = r.get("cards") or []
        n_missing = sum(1 for c in cards if c.get("_missing"))
        missing = f"{n_missing}/{len(cards)}" if cards else "—"
        call = pa.get("base_verdict") or "(blind — no evidenced verdict)"
        frag = pa.get("fragility")
        frag_s = "—" if frag is None else f"{frag}"
        lines.append(f"| {short} | `{call}` | {pa.get('coverage', 'blind')} | {frag_s} | {missing} |")
    ti = fragility.get("target_index")
    rfi = fragility.get("recommendation_fragility_index")
    contested = fragility.get("contested")
    lines.append(
        f"- worst call-fragility (target_index): {ti} ; worst GO/NO-GO fragility "
        f"(recommendation_fragility_index): {rfi} ; contested: {contested}. 0 = robust; None = no "
        "flippable/evidenced axis.")
    blind = fragility.get("blind_decision_axes") or []
    if blind:
        lines.append(
            f"- BLIND decision-relevant axes (measured GAP, not a negative — widen uncertainty and "
            f"say the evidence is thin here, do NOT read as a null result): {blind}")
    lines.append(
        "  NOTE: VERDICT-INERT — this facet does NOT move the recommendation, the gate, or the "
        "audited confidence tier. Use it ONLY to calibrate how confident the executive_summary / "
        "tension_analysis should read, and name the two failure modes DISTINCTLY: a THIN-COVERAGE "
        "axis = 'evidence is limited here' (go measure more); a FLIP-FRAGILE axis with complete "
        "coverage = 'the call is solid but rests on a sensitive rule boundary' (a scoring caveat, "
        "not an evidence gap). Fragility is a structural sensitivity measure, NOT a probability the "
        "target succeeds and NOT a statement about evidence strength; never sum/average it.")
    return lines


# Per-mode narration EMPHASIS steer (actionability_mode facet). EMPHASIS-ONLY: it reorders what the
# narration LEADS with and frames off-mode negatives as expected — it NEVER changes the verdict,
# recommendation, gate, or audited confidence tier (all clamped deterministically in run.main).
_MODE_STEER = {
    "cis_feature": ("Selection basis = a molecular FEATURE (a biomarker: mutation / fusion / amp+GoF / "
                    "pocket / neo-epitope). LEAD the narrative with the genomic-alteration + dependency + "
                    "tractability story. Treat a weak surface/abundance read as EXPECTED (a cis-feature "
                    "target need not be over-abundant) — NOT a disqualifier."),
    "abundance": ("Selection basis = selective OVER-ABUNDANCE (an expression/density cutoff). LEAD with "
                  "presence + selectivity + surface-modality + normal-tissue safety. Treat a `non_dependent` "
                  "read as EXPECTED (an ADC/TCE antigen need not be a genetic dependency); note that "
                  "declaring the biologics `--modality` lets the modality-scoped veto-suppression apply."),
    "mixed": ("BOTH modes fire — narrate the cis handle AND the abundance readout as MUTUALLY REINFORCING "
              "(e.g. amplification is simultaneously the biomarker and the density driver; EGFR/MET serve "
              "both SM and ADC). Do NOT bury either story."),
    "dependency_relational": ("No positive cis handle and not over-abundant — actioned via a PARTNER/CONTEXT "
                              "(LoF-driver → MDM2/synthetic-lethal; partner-conditional SL; lineage/paralog "
                              "co-dependency). LEAD with dependency + SL/combinatorial; patient-selection = "
                              "the partner/context biomarker, not the target's own lesion or abundance."),
    # `insufficient` deliberately has NO steer → emits no block → the prompt is unchanged from pre-Phase-2
    # (neutral == today). This is the common case for uncurated / signal-thin targets.
}


def format_mode_governance_block(mode_facet: Optional[dict]) -> str:
    """Render the actionability_mode profile as an EMPHASIS-ONLY governance block for the synthesis
    prompt (parallel to biology_axis's format_axis_governance_block). Reorders narrative emphasis;
    never touches the verdict. Returns '' when the facet is absent/insufficient (neutral = today)."""
    if not mode_facet:
        return ""
    dominant = mode_facet.get("dominant")
    steer = _MODE_STEER.get(dominant)
    if not steer:
        return ""
    arms = mode_facet.get("arms") or {}
    secondary = mode_facet.get("secondary")
    conf = mode_facet.get("confidence")
    parts = [
        "### Actionability mode (post-hoc, EMPHASIS ONLY — never changes the verdict)",
        f"dominant={dominant}" + (f", secondary={secondary}" if secondary else "")
        + f" (arm tiers: {arms}; confidence={conf}).",
        steer,
        "This is ORTHOGONAL to the biology_axis (where the drug acts) and never suppresses a fired "
        "KILLER/veto or a gating-axis (dependency/safety) verdict.",
    ]
    return "\n".join(parts)


def _render_narrative_block(narrative_by_axis: Optional[dict]) -> list[str]:
    """Per-verdict reasoning trace for the prompt (from nomination.json.narrative_by_axis): the rules
    that SET each verdict (movers), the fired rules that OPPOSED it and lost (dissenters), and the
    single rule-toggles that would FLIP it. This is the citeable anchor set — the model must ground its
    arguments in these rule_id / card_id tokens (inline [brackets]), not free-associate. VERDICT-INERT:
    it never moves the recommendation; it makes the narration TRACEABLE to the deterministic engine."""
    if not narrative_by_axis:
        return []
    out = ["", "### Per-verdict narrative — the CITEABLE reasoning trace (deterministic)",
           "For each axis below: what SET the verdict (movers), what fired AGAINST it and lost "
           "(dissenters), and the single rule-toggles that would FLIP it. When you write an argument "
           "for/against or a tension, CITE the specific driver inline in square brackets — [rule_id] "
           "and/or [card_id] — using ONLY anchors listed here. Do NOT cite anchors not listed."]
    for short, n in narrative_by_axis.items():
        if not isinstance(n, dict):
            continue
        v, drv = n.get("verdict"), n.get("driving_rule_id")
        out.append(f"- **{short}**: `{v}`" + (f" — set by [{drv}]" if drv else ""))
        for m in (n.get("movers") or []):
            if m.get("role") == "driver":
                continue
            out.append(f"    · also supports: [{m.get('rule_id')}] (card [{m.get('card_id')}])")
        by_rule: dict = {}
        for d in (n.get("dissenters") or []):
            by_rule.setdefault(d.get("rule_id"), {"channels": [], "sentence": d.get("sentence") or ""})
            by_rule[d.get("rule_id")]["channels"].append(d.get("channel"))
        for rid, info in by_rule.items():
            chans = ", ".join(c for c in info["channels"] if c)
            out.append(f"    · DESPITE (dissent on {chans}): [{rid}] — {info['sentence']}")
        for f in (n.get("flip_conditions") or []):
            cond = "drop" if f.get("present") else "add"
            rec = " [crosses GO/NO-GO]" if f.get("recommendation_flip") else ""
            out.append(f"    · flips to `{f.get('to_verdict')}` if you {cond} [{f.get('rule_id')}]{rec}")
        for g in (n.get("gaps") or []):
            if g.get("kind") == "acquire":
                cids = ", ".join(c.get("card_id") for c in (g.get("missing_cards") or []) if c.get("card_id"))
                out.append(f"    · GAP (acquire — held by ignorance, not a measured negative): {cids or 'missing data'}")
            elif g.get("kind") == "strengthen":
                out.append("    · GAP (strengthen — measured but underpowered)")
    return out


def _render_risk_6dim_block(risk_6dim: Optional[dict]) -> Optional[str]:
    """The deterministic 6-dimension governance risk roll-up (`target_report.risk_6dim`) as ANCHORED
    context for the narration (the ABSORB of the 6-dim risk into the advisory synthesis layer).

    VERDICT-INERT: `risk_6dim` is a pure spine PROJECTION — its bins are a deterministic function of the
    sub-verdicts, and (since the grounding demotion) literature never moves a bin — so the narration
    reasons about WHERE risk concentrates by governance category (AstraZeneca 5R), it does NOT set the
    call (`target_call` owns that). An `ENGINE-BLIND` dim is an honest coverage gap
    (`insufficient_evidence`), NOT low risk — the narration must not read absence as safety."""
    dims = risk_6dim.get("dims") if isinstance(risk_6dim, dict) and "dims" in risk_6dim else risk_6dim
    if not isinstance(dims, dict):
        return None
    order = ("biological", "druggability", "safety", "translational", "clinical", "commercial")
    rows = []
    for d in order:
        c = dims.get(d)
        if not isinstance(c, dict) or "bin" not in c:
            continue
        b = c.get("bin")
        label = "insufficient_evidence (engine-blind — a gap, not low risk)" if b == "ENGINE-BLIND" else b
        chain = c.get("chain") or []
        driver = (f"{chain[0][0]}: {chain[0][1]}" if chain and len(chain[0]) >= 2
                  else (c.get("pillar") or ""))
        disc = " ⚠ literature-discordant" if c.get("engine_literature_discordance") else ""
        rows.append(f"- **{d}**: `{label}`{disc} — {driver}")
    if not rows:
        return None
    return ("### 6-dimension risk roll-up (deterministic `risk_6dim`; a FACET, not a gate)\n"
            "Governance-category (AstraZeneca 5R) view of the SAME deterministic sub-verdicts, worst-case "
            "per category. VERDICT-INERT — use it to frame WHERE the residual risk concentrates and to "
            "structure the tension analysis; it NEVER moves the recommendation (`target_call` owns that). "
            "`insufficient_evidence` = no wired engine leg (an honest gap), NOT low risk.\n"
            + "\n".join(rows))


def _ke_oneliner(ke: dict) -> str:
    """Compact one-line render of a card's key_evidence (indication stratum effect + q, omnibus, driving
    categorical, subtype restriction) — the grounded datum a composed exec_bullet should LEAD with."""
    if not isinstance(ke, dict) or not ke:
        return ""

    def _n(v):
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return str(v)
        if isinstance(v, float) and v != 0 and abs(v) < 1e-3:
            return f"{v:.2e}"
        return f"{v:.4g}" if isinstance(v, float) else str(v)

    parts, strata = [], (ke.get("top_strata") or [])
    lead = next((s for s in strata if s.get("role") == "indication"), None) \
        or next((s for s in strata if s.get("role") == "strongest"), None)
    eff = ke.get("effect") or {}
    interp = ke.get("interpretation") or []
    if interp:
        # LEAD with the pre-gauged reference-frame reading so the composed bullet copies the framing
        from _skills_common import display_gloss
        gs = display_gloss.gauge_string(interp[0])
        if gs:
            parts.append(gs)
    elif lead:
        seg = f"{lead.get('label')} {eff.get('metric') or 'effect'}={_n(lead.get('value'))}"
        if lead.get("q") is not None:
            seg += f" (q={_n(lead.get('q'))})"
        parts.append(seg)
    elif eff.get("value") is not None:
        parts.append(f"{eff.get('metric')}={_n(eff.get('value'))}")
    om = ke.get("omnibus") or {}
    if om.get("value") is not None:
        parts.append(f"omnibus {om.get('stat')}={_n(om.get('value'))}")
    for cat in (ke.get("categorical") or [])[:1]:
        if cat.get("value") is not None:
            parts.append(str(cat.get("value")))
    sub = ke.get("subtype_axis") or {}
    if sub.get("restriction_class"):
        parts.append(f"subtype:{sub.get('restriction_class')}")
    return " · ".join(str(p) for p in parts if p)


def _render_subskill_key_evidence(sub_results: dict) -> str:
    """Per-sub-skill KEY EVIDENCE (from each carried evidence_graph, driving card first) — the decisive,
    indication-resolved data points the composed exec_bullets must ground in. Empty when no graphs carried."""
    lines = []
    for short, r in (sub_results or {}).items():
        eg = ((((r or {}).get("synthesis_facet") or {}).get("skill_report") or {}).get("evidence_graph"))
        if not isinstance(eg, dict):
            continue
        cards = [c for c in (eg.get("cards") or []) if isinstance(c, dict) and c.get("key_evidence")]
        cards.sort(key=lambda c: not (c.get("chain") or {}).get("is_driving"))  # driving first
        for c in cards[:2]:
            s = _ke_oneliner(c.get("key_evidence"))
            if s:
                lines.append(f"  · {short}/{c.get('id')}: {s}")
    if not lines:
        return ""
    return ("### KEY EVIDENCE (per sub-skill — the decisive grounded data points behind the sub-verdicts; "
            "LEAD each exec_bullet with these, carrying the effect WITH its q/p + the omnibus)\n" + "\n".join(lines))


def _render_presence_facet_block(pf: dict) -> list[str]:
    """Render the presence_facet block of the target-profile synthesis prompt (extracted
    from _build_user_prompt to match the sibling _render_*_block helpers; byte-identical)."""
    lines: list[str] = []
    lines.append("")
    lines.append("### Presence cross-modal reconciliation facet (deterministic; a FACET, not a gate)")
    lines.append("Per-(measurement, sample_context) presence sub-verdicts — the decomposition "
                 "BEHIND the one-word presence verdict. Read the DISAGREEMENTS across rows: an "
                 "RNA-high / protein-absent split, or a tumor-present / normal-tissue-present "
                 "split, is the decision-relevant tension (modality choice; therapeutic window).")
    pvm = pf.get("presence_verdict_by_modality") or {}
    if pvm:
        lines.append("| measurement / context | sub-verdict | evidence |")
        lines.append("|---|---|---|")
        for key, b in pvm.items():
            if not isinstance(b, dict):
                continue
            lines.append(f"| {key} | `{b.get('verdict')}` | {b.get('evidence_state')} |")
    # TYPED presence_state — the honest structured read; prefer it over parsing the collapsed word
    # (which can read `strongly_upregulated_in_tumor` for a contamination artifact or
    # `tumor_broadly_expressed` for a stromal-only signal). present/abundance/elevation/malignant + a
    # named protein↔RNA conflict.
    ps = pf.get("presence_state") or {}
    if isinstance(ps, dict) and ps.get("present"):
        lines.append(
            f"- TYPED presence_state (read THIS, not the one word): present=`{ps.get('present')}` "
            f"abundance=`{ps.get('abundance_level')}` elevated_vs_normal=`{ps.get('elevated_vs_normal')}` "
            f"malignant_intrinsic=`{ps.get('malignant_intrinsic')}` breadth=`{ps.get('breadth')}`"
            + ("  ⚠ protein↔RNA CONFLICT" if ps.get("conflict") else ""))
    lines.append(f"- collapsed presence verdict (compressed label): `{pf.get('presence_verdict')}` "
                 f"(headline lens: {pf.get('headline_lens')})")
    if pf.get("cell_line_vs_tumor_discordant"):
        lines.append(f"- ⚠ cell-line-vs-tumor DISCORDANT: {pf.get('presence_interpretation_note')}")
    # RNA-as-protein-proxy quality (both arms, side-by-side) — qualifies an RNA-only presence claim.
    lines.append(f"- RNA→protein proxy quality: `{pf.get('bulk_rna_proxy_quality')}` "
                 f"(source: {pf.get('bulk_rna_proxy_quality_source')}; cell-line arm "
                 f"{pf.get('rna_as_biomarker')} r={pf.get('rna_protein_r')}, tumor arm "
                 f"{pf.get('rna_as_biomarker_tumor')} r={pf.get('rna_protein_r_tumor')}). "
                 f"A poor/partial proxy means RNA presence needs protein confirmation before a "
                 f"biologics read.")
    # NORMAL-TISSUE comparators — window FRAMING (safety verdict owned by on-target-safety-liability).
    lines.append(f"- normal-tissue comparators (WINDOW framing, NOT the safety verdict): "
                 f"HPA-IHC breadth `{pf.get('normal_tissue_ihc_breadth_class')}` "
                 f"(essential-tissue flag: {pf.get('normal_tissue_ihc_essential_flag')}); "
                 f"scRNA-normal `{pf.get('sc_normal_expression_class')}` "
                 f"(max in {pf.get('sc_normal_max_det_cell_type')} @ "
                 f"{pf.get('sc_normal_max_det_fraction')}).")
    # Hierarchy-derived sub-group + per-question signal decomposition (the narrator-input contract's
    # structural signals, read from the SAME facet keys the single-lens presence narrator uses). Flows
    # STRUCTURALLY off presence_facet — no fields hand-picked here. VERDICT-INERT. Empty → skipped.
    _sig_summary = render_signal_summary(pf)
    if _sig_summary:
        lines.append("")
        lines.append("Presence signal decomposition (deterministic; hierarchy-derived sub-group "
                     "signals + per-question read behind the collapsed presence verdict — read it to "
                     "see WHICH sub-group/question carries or contradicts the presence call):")
        lines.append(_sig_summary)
    lines.append("  NOTE: presence is VERDICT-INERT to the nomination gate — this facet does NOT "
                 "move the recommendation. Its role is to surface cross-modal tension the "
                 "one-word presence verdict hides, and to frame tumor presence AGAINST the "
                 "normal-tissue window (the therapeutic-window verdict is owned by "
                 "on-target-safety-liability / tumor-selectivity, weighed via their sub-verdicts).")
    return lines


def _render_biomarker_facet_block(bf: dict) -> list[str]:
    """Render the biomarker_facet block of the target-profile synthesis prompt (extracted
    from _build_user_prompt to match the sibling _render_*_block helpers; byte-identical)."""
    lines: list[str] = []
    lines.append("")
    lines.append("### Biomarker convergence facet (deterministic; a FACET, not a gate)")
    lines.append(f"- facet verdict: `{bf.get('verdict')}`  |  preferred assay: "
                 f"`{bf.get('preferred_assay')}`")
    corr = {k: v for k, v in (bf.get("corroboration_role") or {}).items() if v is not None}
    strat = {k: v for k, v in (bf.get("stratification_role") or {}).items() if v is not None}
    lines.append(f"- corroboration (→ confidence in biology verdicts): "
                 f"{corr if corr else 'none reachable'}")
    lines.append(f"- stratification (→ patient selection): {strat if strat else 'none reachable'}")
    # surface the QUANTITATIVE strengths behind the classes (from the `quantitative` block)
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
    return lines


def _render_subtype_facet_block(sf: dict) -> list[str]:
    """Render the subtype_facet block of the target-profile synthesis prompt (extracted
    from _build_user_prompt to match the sibling _render_*_block helpers; byte-identical)."""
    lines: list[str] = []
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
    return lines




def _build_user_prompt(
    target: str,
    indication: str,
    sub_results: dict,
    modality: Optional[str] = None,
    therapeutic_hypothesis: Optional[str] = None,
    ordinal_matrix: Optional[dict] = None,
    biomarker_facet: Optional[dict] = None,
    subtype_facet: Optional[dict] = None,
    presence_facet: Optional[dict] = None,
    fragility: Optional[dict] = None,
    axis_info: Optional[dict] = None,
    actionability_mode: Optional[dict] = None,
    competitor_crossref: Optional[dict] = None,
    narrative_by_axis: Optional[dict] = None,
    risk_6dim: Optional[dict] = None,
) -> str:
    """Compose the user-message text: biology-axis governance + sub-verdicts + per-axis
    how-solid (certainty) block + modality-scoped matrix slice + biomarker convergence facet +
    card summaries + optional lens context.

    axis_info (from _skills_common.biology_axis.resolve_biology_axis) steers modality EMPHASIS:
    it foregrounds the plausible modalities for the target's curated axis so the narration does
    not over-weight surface-antigen framing for an intracellular target (or vice versa). It is a
    SLOT-2 emphasis steer only — the deterministic verdict + recommendation are untouched.

    fragility (the _fragility_facet emitted into nomination.json) supplies the per-axis
    how-solid block: coverage + single-rule call-fragility per decision-relevant axis, plus the
    blind (un-evidenced) axes. It calibrates HOW CONFIDENT the narration should read; it is
    VERDICT-INERT — it never moves the recommendation, the gate, or the audited confidence tier
    (which are clamped/floored deterministically in run.main), only the prose."""
    lines = [
        f"Target: {target}",
        f"Indication: {indication}",
    ]
    if axis_info is not None:
        from _skills_common.biology_axis import format_axis_governance_block
        lines.append("")
        lines.append(format_axis_governance_block(axis_info))
    _mode_block = format_mode_governance_block(actionability_mode)
    if _mode_block:
        lines.append("")
        lines.append(_mode_block)
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
    _ke_block = _render_subskill_key_evidence(sub_results)
    if _ke_block:
        lines.append(_ke_block)
        lines.append("")
    _risk_block = _render_risk_6dim_block(risk_6dim)
    if _risk_block:
        lines.append(_risk_block)
        lines.append("")
    if competitor_crossref is not None:
        cx = competitor_crossref
        lines.append("### Competitor cross-reference facet (deterministic; a FACET, not a gate)")
        lines.append("Open Targets competitor field vs the framework's OWN surface-modality-fit verdict. "
                     "VERDICT-INERT — it never moves the recommendation; use it to frame COMPETITIVE "
                     "POSITIONING and to sanity-check the framework's modality call against clinical precedent.")
        lines.append(f"- competition density: `{cx.get('competition_density')}` "
                     f"(competitor_class: {cx.get('competitor_class')}; "
                     f"{cx.get('n_competitor_programs')} program(s); scope: {cx.get('competitor_indication_scope')})")
        lines.append(f"- framework preferred surface modality: {cx.get('framework_preferred_modality')} "
                     f"(surface-modality-fit verdict: `{cx.get('surface_modality_verdict')}`); "
                     f"approved competitor modality/ies: {cx.get('competitor_modalities_approved')}")
        if cx.get("modality_contrarian"):
            lines.append("- ⚠ modality_contrarian=TRUE: the framework's preferred modality is NOT the "
                         "approved clinical modality here — treat the surface-modality-fit call as CONTESTED "
                         "by real-world precedent and weigh this in the recommendation narrative.")
        for hook in (cx.get("differentiation_hooks") or []):
            lines.append(f"  - hook: {hook}")
        lines.append("")
    if fragility is not None:
        lines.extend(_render_certainty_block(fragility, sub_results))
    if narrative_by_axis:
        lines.extend(_render_narrative_block(narrative_by_axis))
    if ordinal_matrix is not None:
        lines.extend(_render_matrix_slice_for_prompt(ordinal_matrix))
    if presence_facet is not None:
        lines.extend(_render_presence_facet_block(presence_facet))
    if biomarker_facet is not None:
        lines.extend(_render_biomarker_facet_block(biomarker_facet))
    if subtype_facet is not None:
        lines.extend(_render_subtype_facet_block(subtype_facet))
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


# --- Post-synthesis anchor validation (verdict-INERT audit) -----------------------------------------
# The synthesis prompt tells the model to cite load-bearing claims with inline [rule_id]/[card_id]
# anchors drawn ONLY from the Per-verdict narrative block, and to fill the optional structured
# `citations` with anchors present there — "never invent one." That was PROMPT-ONLY: nothing checked the
# emitted anchors against the legal set, so a hallucinated [rule_id] shipped silently into
# target_profile.md. This validator computes the legal anchor set deterministically (narrative_by_axis +
# every fired rule + every card_id across the fan-out) and records which bracketed anchors in the
# prose/citations are NOT in it. FLAG-ONLY (fail-visible, like _malformed_fields): it records the
# invented anchors and NEVER edits the prose, the verdict, or the recommendation.
_ANCHOR_TOKEN_RE = re.compile(r"\[([^\[\]]+)\]")
# a bracket token is an ID anchor only if it looks like a framework rule_id/card_id — KEBAB-case
# (>=1 hyphen, no spaces). This excludes numeric refs ([1]), UPPER_SNAKE stratum labels (MSI_H), and
# prose asides in brackets, which are not rule/card anchors and must not be mis-flagged.
_ID_LIKE_RE = re.compile(r"^[A-Za-z0-9]+(-[A-Za-z0-9]+)+$")
_PROSE_ANCHOR_FIELDS = ("executive_summary", "tension_analysis",
                        "top_arguments_for", "top_arguments_against")


def _uv_field(v):
    """Unwrap a provenance-stamped field ({'value':..., '_source':...}) to its value."""
    return v.get("value") if isinstance(v, dict) and "value" in v else v


def _allowed_anchor_set(narrative_by_axis: Optional[dict], sub_results: Optional[dict]) -> set:
    """The deterministic legal anchor set: every rule_id + card_id the narrative block, the fired
    rules, and the fan-out cards expose — i.e. exactly what the prompt told the model it may cite."""
    allowed: set = set()
    for n in (narrative_by_axis or {}).values():
        if not isinstance(n, dict):
            continue
        if n.get("driving_rule_id"):
            allowed.add(n["driving_rule_id"])
        for m in (n.get("movers") or []):
            allowed.update(x for x in (m.get("rule_id"), m.get("card_id")) if x)
        for d in (n.get("dissenters") or []):
            allowed.update(x for x in (d.get("rule_id"), d.get("card_id")) if x)
        for f in (n.get("flip_conditions") or []):
            if f.get("rule_id"):
                allowed.add(f["rule_id"])
        for rid, info in (n.get("rule_sentences") or {}).items():
            allowed.add(rid)
            if isinstance(info, dict) and info.get("card_id"):
                allowed.add(info["card_id"])
        for g in (n.get("gaps") or []):
            for mc in (g.get("missing_cards") or []):
                if mc.get("card_id"):
                    allowed.add(mc["card_id"])
    for r in (sub_results or {}).values():
        for f in (r.get("fired") or []):
            allowed.update(x for x in (f.get("rule_id"), f.get("card_id")) if x)
        for c in (r.get("cards") or []):
            if c.get("card_id"):
                allowed.add(c["card_id"])
    return allowed


def _extract_id_anchors(text: Any) -> set:
    """The kebab-case ID anchors inside [brackets] in a string (splitting a token on , or /)."""
    out: set = set()
    if not isinstance(text, str):
        return out
    for tok in _ANCHOR_TOKEN_RE.findall(text):
        for part in re.split(r"[,/]", tok):
            p = part.strip()
            if _ID_LIKE_RE.match(p):
                out.add(p)
    return out


def validate_synthesis_anchors(llm_output: Optional[dict], narrative_by_axis: Optional[dict],
                               sub_results: Optional[dict]) -> dict:
    """Verdict-INERT audit: flag bracketed [rule_id]/[card_id] anchors in the LLM prose + the structured
    `citations` that are NOT in the deterministic anchor set (possible hallucinated citations). Returns
    the audit block for the caller to attach; it never edits prose and never moves a verdict."""
    allowed = _allowed_anchor_set(narrative_by_axis, sub_results)
    cited: set = set()
    invented_by_field: dict = {}
    for field in _PROSE_ANCHOR_FIELDS:
        v = _uv_field((llm_output or {}).get(field))
        found: set = set()
        for t in (v if isinstance(v, list) else [v]):
            found |= _extract_id_anchors(t)
        cited |= found
        inv = sorted(a for a in found if a not in allowed)
        if inv:
            invented_by_field[field] = inv
    cit_found: set = set()
    for c in (_uv_field((llm_output or {}).get("citations")) or []):
        c = _uv_field(c)
        if isinstance(c, dict):
            for a in (_uv_field(c.get("anchors")) or []):
                if isinstance(a, str):
                    for part in re.split(r"[,/]", a):
                        p = part.strip()
                        if _ID_LIKE_RE.match(p):
                            cit_found.add(p)
    cited |= cit_found
    inv_cit = sorted(a for a in cit_found if a not in allowed)
    if inv_cit:
        invented_by_field["citations"] = inv_cit
    invented = sorted(a for a in cited if a not in allowed)
    return {
        "allowed_anchor_count": len(allowed),
        "n_cited": len(cited),
        "invented_anchors": invented,
        "n_invented": len(invented),
        "invented_by_field": invented_by_field,
        "_note": ("verdict-INERT audit: bracketed [rule_id]/[card_id] anchors in the LLM "
                  "prose/citations absent from the deterministic narrative block (possible "
                  "hallucinated citations). Does NOT alter the verdict, recommendation, or prose."),
    }


__all__ = [
    '_LOAD_BEARING_SUMMARY_KEY_PARTS',
    '_METRIC_LEGEND',
    '_PROMPT_CARD_CHAR_CAP',
    '_SYSTEM_PROMPT',
    '_build_synthesis_tool',
    '_build_user_prompt',
    '_format_card_summary_for_prompt',
    '_render_matrix_slice_for_prompt',
    'validate_synthesis_anchors',
]
