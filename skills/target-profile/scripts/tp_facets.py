"""target-profile — deterministic derived facets (verdict-inert render inputs + the deciding-axis
router): ordinal matrix, biomarker, subtype, fragility, heterogeneity, addressable-population."""
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

from _skills_common import ordinal_view
from _skills_common.flip_analysis import flip_analysis
from tp_common import _CONTRACTS_REPO, _first_card_summary_field
from tp_fanout import SUBTYPE_SHORT, _SHORT_TO_GATE
from tp_gates import _COVERAGE_RANK, _load_gate_coverage, _load_gate_verdicts, _load_positive_signals, _run_coverage_for_short, _sub_result_has_signal




def _deciding_axis(sub_results: dict, gate_action: Optional[str],
                   gate_hits: list[dict], positive_hits: list[dict],
                   contracts_repo: Path | None = None) -> dict:
    """Build the deciding_axis block (see module comment above). Deterministic; never predicts."""
    baseline, source = _load_gate_coverage(contracts_repo)

    def _row(short: str) -> dict:
        b = baseline.get(short, {})
        return {
            "short": short,
            "gate": b.get("gate"),
            "gate_name": b.get("gate_name"),
            "band": b.get("band"),
            "framework_can_evidence": _run_coverage_for_short(short, sub_results.get(short, {}), baseline),
        }

    # (1) A gate FIRED → the deciding axis is KNOWN (the firing gate). captured by definition.
    if gate_action and gate_hits:
        # Name the gate whose action actually WON (forced == max over action ranks), not merely
        # the first-iterated hit — otherwise the routing text could name a 'hold' gate while
        # reporting the 'veto' a different gate forced.
        _winning = next((h for h in gate_hits if h.get("action") == gate_action), gate_hits[0])
        top = _winning["short"]
        row = _row(top)
        row["framework_can_evidence"] = "captured"   # it fired → we evidenced it
        return {"basis": "gate_fired", "coverage_source": source,
                "deciding_axis": row,
                "routing": f"decided by gate {row.get('gate')} ({row.get('gate_name')}): "
                           f"{top} forced '{gate_action}'."}

    # (2) A positive tier exists → the load-bearing axis is the strongest positive dimension.
    if positive_hits:
        shorts = sorted({h["short"] for h in positive_hits})
        rows = [_row(s) for s in shorts]
        return {"basis": "positive_signal", "coverage_source": source,
                "deciding_axes": rows,
                "routing": f"supported by {', '.join(shorts)} (necessity biology evidenced)."}

    # (3) Abstaining → report the NECESSITY gates we could NOT evidence this run + their standing.
    # This is the routing instruction: "the decision lives in a gate we're blind on."
    unevidenced = []
    for short, r in sub_results.items():
        if short not in baseline:
            continue
        if not _sub_result_has_signal(r):
            unevidenced.append(_row(short))
    # necessity first, then by weakest coverage (blind before partial) — the gates most likely
    # to be the reason we can't decide.
    unevidenced.sort(key=lambda x: (x.get("band") != "necessity",
                                    _COVERAGE_RANK.get(x.get("framework_can_evidence"), 0)))
    return {"basis": "abstention_coverage_gaps", "coverage_source": source,
            "unevidenced_gates": unevidenced,
            "routing": ("cannot decide from framework evidence; unevidenced gates (necessity "
                        "first): " + ", ".join(
                            f"{g['short']}[{g.get('gate')}/{g.get('framework_can_evidence')}]"
                            for g in unevidenced) if unevidenced else
                        "cannot decide; no gate produced a signal and no coverage map available.")}


# --- Ordinal matrix VIEW (gap #3 "now" / gap #4 demo) ------------------------
#
# A gate × modality signal matrix, projected onto the ordinal scale for DISPLAY + RANKING.
# This is the "evidence matrix" made concrete for a single (target, indication) run: rows = the
# gates (sub-skills), columns = the 5 delivery modalities, cells = the strongest signal that
# gate's fired rules emit for that modality, shown as its ordinal.
#
# HONESTY (ordinal_view module contract): this is a labeled VIEW, NOT measurement and NOT a
# verdict input. It reads already-resolved fired-rule signals and never feeds back into any
# rule/resolver/gate. insufficient/not_applicable cells are off-scale (coverage), not low scores.
_MATRIX_MODALITIES = ("small_molecule", "degrader", "adc", "bite_tce", "antibody")


def _strongest_signal_for_modality(fired: list[dict], modality: str) -> Optional[str]:
    """The most-decisive signal a gate's fired rules emit for one modality channel. 'Most
    decisive' = lowest ordinal (killer < opposing < neutral < supportive); off-scale
    (insufficient/not_applicable) only when NO on-scale signal was emitted. Mirrors the
    display convention that a killer dominates a co-fired supportive in the same cell."""
    on_scale: list[tuple[int, str]] = []
    off_scale: Optional[str] = None
    for r in fired:
        sig = (r.get("signals") or {}).get(modality)
        if sig is None:
            continue
        o = ordinal_view.ordinal_of(sig)
        if o is None:
            off_scale = off_scale or sig      # remember an off-scale signal as a fallback
        else:
            on_scale.append((o, sig))
    if on_scale:
        return min(on_scale, key=lambda t: t[0])[1]   # most-negative wins the cell
    return off_scale                                   # else an off-scale coverage marker (or None)


def _ordinal_matrix(sub_results: dict) -> dict:
    """Build the gate × modality ordinal-view matrix for this run (see section comment).
    Returns {rows: [{short, gate signals+ordinals per modality}], legend, _disclaimer}."""
    rows = []
    for short, r in sub_results.items():
        fired = r.get("fired") or []
        by_mod = {m: _strongest_signal_for_modality(fired, m) for m in _MATRIX_MODALITIES}
        view = ordinal_view.project_signals(by_mod)
        rows.append({
            "short": short,
            "verdict": (r.get("verdict") or [None])[0],
            "cells": view["cells"],          # {modality: {signal, ordinal, on_scale}}
        })
    return {
        "axes": {"rows": "gate (sub-skill)", "columns": list(_MATRIX_MODALITIES),
                 "cell": "strongest signal for (gate, modality), ordinal-projected"},
        "rows": rows,
        "legend": ordinal_view.scale_legend(),
        "_disclaimer": ordinal_view.scale_legend()["_disclaimer"],
    }


# --- Biomarker convergence facet (Q12; master-sequencing Part 3c) -----------
#
# A FACET, not a gate: biomarker is always "a biomarker OF something" — it has no standalone verdict
# about the target, it MODIFIES other gates' verdicts. This assembles the scattered biomarker-relevant
# byproducts each extraction plan produces into ONE structured object with two jobs (Part 3c):
#   - corroboration_role  → raises CONFIDENCE in a biology-gate verdict
#   - stratification_role → defines the patient-selection population + preferred assay
# DETERMINISTIC + ADDITIVE + ONE-DIRECTIONAL (mirrors _ordinal_matrix): computed pre-prompt from the
# sub-verdicts, surfaced to the LLM + emitted in nomination.json, and it can raise confidence via the
# LLM's reasoning but NEVER mints a nominate (no verdict input; the deterministic gate is untouched).
# Pure convergence — no new extraction, no new card. Reads ONLY what the sub-skills already surface.
_BIOMARKER_INPUTS = {
    # short (sub-skill) : list of (summary_field, role) it contributes
    "genomic_alteration": [("alteration_role", "corroboration"),          # predictive_biomarker value
                           ("mutation_stratification_class", "stratification")],  # mutant-stratified dependency
    "dependency":        [("abundance_dependency_class", "corroboration"),   # Q7 protein abundance→dep
                          ("correlation_class", "corroboration"),            # RNA arm expression→dep
                          ("correspondence_class", "corroboration")],        # Q4 model-backed dependency
                                                                             # (the recommended-models CARD key;
                                                                             #  NOT the functional-requirement
                                                                             #  headline alias model_correspondence_class,
                                                                             #  which _first_card_summary_field never sees)
    "expression":        [("rna_as_biomarker", "stratification"),            # Q5 preferred-assay input
                          ("subtype_stratification_class", "stratification"), # subtype patient-selection (2026-08-04)
                          ("purity_confound_class", "corroboration")],       # Q9 signal-is-tumor-intrinsic
    # phospho_activity_class RE-HOMED 2026-08-05: it now surfaces under the mechanism sub-result
    # (phospho card moved tumor-presence → mechanism-and-pharmacology), so read it from there — else
    # the biomarker facet would silently drop the Q8 pathway-active corroboration signal.
    "mechanism":         [("phospho_activity_class", "corroboration")],      # Q8 pathway-active (phospho)
    "differentiation":   [("survival_association_class", "stratification")], # Q11 prognostic stratifier
}


# ── A2a: quantitative re-surfacing (biomarker-axis plan §A2a) ─────────────────────────────────
# The categorical *_class fields above are BUCKETED from raw statistics the cards already compute
# (pearson_r, effect sizes, Mann-Whitney q, delta-Chronos, agreement fractions) — but the facet
# collapses each card to its class and DISCARDS the numbers. This map names, per sub-skill, the
# companion NUMERIC summary fields to re-surface alongside the class, so the facet carries the
# strength of each signal, not just its bucket. Pulled with the SAME _first_card_summary_field
# accessor the categorical read uses (no new data, no computation). Verdict-inert: the numbers ride
# in a parallel `quantitative` block; the recommendation gate never reads the facet.
_BIOMARKER_QUANT = {
    # short (sub-skill) : list of numeric summary_fields to re-surface if present
    "genomic_alteration": ["hotspot_mannwhitney_q", "hotspot_effect_size",
                           "delta_chronos_hotspot_mut_vs_wt",
                           "median_chronos_hotspot_mutant", "median_chronos_hotspot_wildtype",
                           # Thread 3 (2026-08-09): dependency-classification PERFORMANCE — the
                           # biomarker as a classifier for the DepMap-dependency phenotype. PPV-lift
                           # separates rare-sharp (BRAF ~9.6x) from common-dep high-PPV-low-lift (KRAS
                           # ~2.2x) markers the coarse class hides. DEPENDENCY performance, NOT clinical.
                           "hotspot_dependency_ppv", "hotspot_dependency_sensitivity",
                           "hotspot_dependency_specificity", "hotspot_dependency_base_rate",
                           "hotspot_dependency_ppv_lift"],
    "dependency":        ["pearson_r", "pearson_p", "spearman_r",
                          "delta_chronos_top_vs_bottom_quartile",
                          "protein_dependency_pearson_r", "protein_dependency_pearson_p",
                          "n_cell_lines_evaluated", "n_paired_models",
                          "fraction_agree", "fraction_dependent_in_both"],
    "expression":        ["rna_protein_r", "rna_protein_spearman", "n_paired_tumors"],
    "differentiation":   ["logrank_p", "logrank_chi2", "n_patients", "n_events",
                          "high_expr_hazard_direction"],
}


def _biomarker_quantitative(sub_results: dict) -> dict:
    """Re-surface the raw statistics behind the biomarker categorical classes (A2a). Returns a
    {sub_skill: {field: value}} dict of the numeric companion fields that were present this run —
    reusing _first_card_summary_field (same accessor as the categorical read). Verdict-inert: this
    is display strength only; null/absent fields are simply omitted (honest coverage, not fabricated)."""
    quant: dict = {}
    for short, numeric_fields in _BIOMARKER_QUANT.items():
        r = sub_results.get(short)
        if not r:
            continue
        found = {}
        for field in numeric_fields:
            val = _first_card_summary_field(r, field)
            if val is not None:
                found[field] = val
        if found:
            quant[short] = found
    return quant


# ── BEST-role classification (biomarker-axis plan §1) ────────────────────────────────────────
# The facet's corroboration/stratification blocks answer "IS there a biomarker signal?" but NOT
# "what KIND?". A biomarker is always one of a fixed set of intended-uses, and they MUST stay
# separate — high target expression may be PROGNOSTIC but not PREDICTIVE; a driver LoF may define a
# diagnostic SUBTYPE but not predict inhibitor sensitivity. A single target can carry SEVERAL
# (KRAS: predictive; MLH1: subtyping + prognostic), so this emits a LIST of typed hypotheses, never
# one collapsed label. Pure classification over fields the facet already assembled — no new data,
# verdict-inert (each hypothesis names its intended_use + basis + a coarse evidence_strength).
#
# intended_use vocabulary (BEST framework subset the current inputs can support):
#   predictive           — a molecular state that predicts response to targeting (mutation-stratified
#                          dependency / predictive_biomarker alteration_role). Guardrail: a CRISPR-
#                          dependency biomarker is a DEPENDENCY-predictive hypothesis, NOT proven an
#                          inhibitor biomarker — labelled predictive_dependency, basis flagged.
#   prognostic           — associates with outcome irrespective of treatment (expression↔survival).
#                          Kept STRICTLY distinct from predictive (survival is stage-dominated).
#   diagnostic_subtyping — defines a molecular subtype/class (driver LoF/GoF or a restricted subtype).
#   pharmacodynamic      — a downstream activity readout usable to confirm target engagement (phospho).
# (predictive-performance PPV/NPV + deployability are the plan's NEXT layers — NOT computed here.)


def _classify_biomarker_best_roles(corroboration: dict, stratification: dict,
                                    quantitative: dict = None) -> list:
    """Type the assembled biomarker signals into a LIST of {intended_use, basis, evidence_strength}
    hypotheses (BEST-role §1). Pure fn — deterministic, no I/O; roles are NON-exclusive. A field that
    is null / data_unavailable / not_informative contributes nothing (honest — never fabricates a role).

    When `quantitative` carries the genomic dependency-classification performance (Thread 3), the
    genomic predictive hypothesis is annotated with the computed dependency-PPV + PPV-lift — a real
    metric on the DepMap-dependency ground truth (NOT drug-response / clinical PPV)."""
    quantitative = quantitative or {}

    def _live(v):
        return v not in (None, "data_unavailable", "not_informative", "insufficient_survival_data",
                         "insufficient_mutation_rate", "insufficient_paired_models")

    # Dependency-classification performance for the genomic stratifier (Thread 3), if present.
    _gq = quantitative.get("genomic_alteration", {}) or {}
    _dep_ppv = _gq.get("hotspot_dependency_ppv")
    _dep_lift = _gq.get("hotspot_dependency_ppv_lift")

    def _ppv_perf():
        """A compact dependency-performance dict to attach to a genomic predictive hypothesis."""
        if _dep_ppv is None:
            return None
        return {"dependency_ppv": _dep_ppv,
                "dependency_ppv_lift": _dep_lift,
                "dependency_sensitivity": _gq.get("hotspot_dependency_sensitivity"),
                "dependency_specificity": _gq.get("hotspot_dependency_specificity"),
                "dependency_base_rate": _gq.get("hotspot_dependency_base_rate"),
                "_metric_scope": "DepMap genetic-dependency phenotype (Chronos<=-0.5), NOT drug-response/clinical"}

    hyps: list = []
    mut_strat = stratification.get("mutation_stratification_class")
    alt_role = corroboration.get("alteration_role")
    surv = stratification.get("survival_association_class")
    subtype = stratification.get("subtype_stratification_class")
    phospho = corroboration.get("phospho_activity_class")
    # the dependency-correlation corroborators (support a predictive-dependency hypothesis, not roles of their own)
    corr_support = [corroboration.get(f) for f in
                    ("abundance_dependency_class", "correlation_class", "correspondence_class")]

    # PREDICTIVE — genomic stratifier (the strongest, most actionable). Two sub-bases:
    if alt_role == "predictive_biomarker":
        hyps.append({"intended_use": "predictive", "basis": "alteration_role=predictive_biomarker",
                     "evidence_strength": "strong",
                     "_note": "genotype→drug-response predictive hypothesis (OncoKB/IntOGen-classed)."})
    if mut_strat in ("mutant_strongly_dependent", "mutant_moderately_dependent"):
        strength = "strong" if mut_strat == "mutant_strongly_dependent" else "moderate"
        hyp = {"intended_use": "predictive", "basis": f"mutation_stratification_class={mut_strat}",
               "evidence_strength": strength,
               "_note": "mutation-stratified DEPENDENCY (CRISPR) — a dependency-predictive "
                        "hypothesis; NOT auto an inhibitor biomarker (KO removes noncatalytic "
                        "functions). Confirm with a pharmacologic (PRISM) arm before clinical framing."}
        # Thread 3: attach the computed dependency-classification performance. PPV-lift is the
        # informativeness above the panel base-rate — it separates a rare-sharp predictor (high lift)
        # from a common-dependency high-PPV-low-lift marker (the coarse strength label hides this).
        perf = _ppv_perf()
        if perf is not None:
            hyp["dependency_performance"] = perf
        hyps.append(hyp)
    # a dependency-correlation signal WITHOUT a genotype stratifier = a weaker predictive-dependency hypothesis
    if not any(h["intended_use"] == "predictive" for h in hyps) and any(
            v in ("strong_negative", "moderate_negative", "protein_predicts_dependency",
                  "well_modeled_in_lineage", "well_modeled_off_lineage") for v in corr_support):
        hyps.append({"intended_use": "predictive", "basis": "expression/abundance↔dependency correlation",
                     "evidence_strength": "weak",
                     "_note": "abundance/expression correlates with dependency but no genotype stratifier "
                              "— a continuous-biomarker HYPOTHESIS, weakest predictive tier."})

    # PROGNOSTIC — expression↔survival. STRICTLY distinct from predictive.
    if surv in ("expression_high_worse_survival", "expression_high_better_survival"):
        hyps.append({"intended_use": "prognostic", "basis": f"survival_association_class={surv}",
                     "evidence_strength": "weak",
                     "_note": "univariate median-split OS association (stage-UNADJUSTED, hypothesis-"
                              "generating) — a PROGNOSTIC hypothesis, says nothing about drug response."})

    # DIAGNOSTIC_SUBTYPING — a driver alteration that defines a class, or a restricted subtype.
    if alt_role in ("direct_driver_lof", "direct_driver_gof"):
        hyps.append({"intended_use": "diagnostic_subtyping", "basis": f"alteration_role={alt_role}",
                     "evidence_strength": "moderate",
                     "_note": "driver alteration defines a molecular class/subtype; subtyping ≠ predictive "
                              "(a class-defining event need not predict a specific drug's response)."})
    if subtype in ("subtype_restricted", "subtype_enriched"):
        hyps.append({"intended_use": "diagnostic_subtyping", "basis": f"subtype_stratification_class={subtype}",
                     "evidence_strength": "moderate" if subtype == "subtype_restricted" else "weak",
                     "_note": "expression restricted to / enriched in a molecular subtype — a subtyping/"
                              "patient-selection axis."})

    # PHARMACODYNAMIC — a pathway-activity readout usable as a PD marker (not patient-selection).
    if _live(phospho) and phospho not in ("not_phosphoprotein",):
        hyps.append({"intended_use": "pharmacodynamic", "basis": f"phospho_activity_class={phospho}",
                     "evidence_strength": "weak",
                     "_note": "phospho/pathway-activity readout — candidate PD (target-engagement) "
                              "marker, forward-looking; NOT a patient-selection biomarker."})

    return hyps


def _biomarker_facet(sub_results: dict) -> dict:
    """Assemble the biomarker-convergence facet (Q12). Deterministic; additive; verdict-inert.

    Pulls the biomarker-relevant fields each sub-skill surfaces into corroboration_role +
    stratification_role blocks, derives a preferred_assay (RNA | protein | genomic | neither) and a
    facet verdict. Fields not reachable (sub-skill absent, card not composed) are recorded as null —
    an HONEST coverage signal, never fabricated."""
    corroboration: dict = {}
    stratification: dict = {}
    for short, fields in _BIOMARKER_INPUTS.items():
        r = sub_results.get(short)
        if not r:
            continue
        for field, role in fields:
            val = _first_card_summary_field(r, field)
            target_block = corroboration if role == "corroboration" else stratification
            target_block[field] = val

    # preferred_assay: which layer is the trustworthy biomarker readout?
    #   genomic  — a mutant-stratified dependency or predictive_biomarker alteration_role (the
    #              strongest, most actionable stratifier; also the live veto-suppressor)
    #   protein  — RNA is a POOR proxy (Q5), so protein must be measured
    #   RNA      — RNA is an adequate proxy (Q5)
    #   neither  — no adequate stratifier surfaced
    rna_as_biomarker = stratification.get("rna_as_biomarker")
    mut_strat = stratification.get("mutation_stratification_class")
    alt_role = corroboration.get("alteration_role")
    genomic_stratifier = (mut_strat in ("mutant_strongly_dependent", "mutant_moderately_dependent")
                          or alt_role == "predictive_biomarker")
    if genomic_stratifier:
        preferred_assay = "genomic"
    elif rna_as_biomarker == "adequate_proxy":
        preferred_assay = "RNA"
    elif rna_as_biomarker in ("poor_proxy", "partial_proxy"):
        preferred_assay = "protein"
    else:
        preferred_assay = "neither"

    # facet verdict — a FACET summary (confidence/patient-selection role), never a target verdict.
    #   strong_selection_biomarker — a genomic stratifier (mutant-stratified dependency / predictive)
    #   corroborating_only          — corroboration signals present but no patient-selection stratifier
    #   inadequate                  — signals present but RNA is a poor proxy + no genomic stratifier
    #   none                        — nothing biomarker-relevant surfaced
    has_corroboration = any(v not in (None, "data_unavailable", "not_informative")
                            for v in corroboration.values())
    if genomic_stratifier:
        verdict = "strong_selection_biomarker"
    elif preferred_assay == "protein" and not has_corroboration:
        verdict = "inadequate"
    elif has_corroboration or preferred_assay in ("RNA", "protein"):
        verdict = "corroborating_only"
    else:
        verdict = "none"

    # A2a: re-surface the raw statistics behind the categorical classes (strength, not just bucket).
    quantitative = _biomarker_quantitative(sub_results)

    # BEST-role classification (§1): type the assembled signals into a LIST of non-exclusive
    # hypotheses, each naming its intended_use. Kept SEPARATE from the facet verdict (which is a
    # confidence/patient-selection summary) — this answers "what KIND of biomarker(s)", the verdict
    # answers "how strong a selector". Verdict-inert, additive. `quantitative` is passed so a
    # predictive hypothesis can carry the computed dependency-PPV performance (Thread 3).
    biomarker_hypotheses = _classify_biomarker_best_roles(corroboration, stratification, quantitative)
    intended_uses = sorted({h["intended_use"] for h in biomarker_hypotheses})

    return {
        "corroboration_role": corroboration,
        "stratification_role": stratification,
        "quantitative": quantitative,                   # A2a: raw stats behind the classes (verdict-inert)
        "preferred_assay": preferred_assay,
        "verdict": verdict,
        "biomarker_hypotheses": biomarker_hypotheses,   # BEST-role §1: typed, non-exclusive
        "intended_uses": intended_uses,                 # rollup of distinct roles present
        "_disclaimer": ("Biomarker is a FACET, not a gate: it corroborates other gates' verdicts "
                        "(→ confidence) and defines patient-selection (→ stratification); it never "
                        "mints a nomination. biomarker_hypotheses are BEST-role-typed (predictive / "
                        "prognostic / diagnostic_subtyping / pharmacodynamic) + NON-exclusive — a "
                        "target can carry several; predictive and prognostic are kept strictly "
                        "separate. `quantitative` re-surfaces the raw statistics (r / effect size / "
                        "Mann-Whitney q / delta-Chronos / agreement fraction) the cards already "
                        "computed behind each class — strength, not just a bucket. A genomic predictive "
                        "hypothesis now carries `dependency_performance` (PPV / sensitivity / specificity "
                        "/ base-rate / PPV-lift) — a COMPUTED metric on the DepMap genetic-dependency "
                        "phenotype, NOT drug-response or clinical PPV (clinical-PPV/NPV + deployability "
                        "remain uncomputed). null fields = input not reachable this run, not a measured "
                        "negative."),
    }


# --- PRESENCE cross-modal reconciliation facet -------------------------------------------------
# tumor-presence emits a per-(measurement, sample_context) sub-verdict MATRIX + proxy-quality +
# normal-tissue comparators via its `_synthesis_facet` (carried by the fan-out as
# sub_results['expression']['synthesis_facet']). This thin reader surfaces it as a first-class
# facet for the synthesis prompt + evidence package — parallel to _biomarker_facet / _subtype_facet.
# VERDICT-INERT: presence is deliberately absent from _SHORT_TO_GATE, so this never moves the
# nomination. Its value: the LLM reasons over the deterministic cross-modal reconciliation (where
# RNA / protein / single-cell / normal-comparator AGREE or CONFLICT) instead of re-deriving it from
# raw card numbers. Returns None when tumor-presence is absent / supplied no facet.
def _presence_facet(sub_results: dict) -> Optional[dict]:
    expr = (sub_results or {}).get("expression") or {}
    return expr.get("synthesis_facet")


# --- SUBTYPE convergence facet (capstone Part 3c integration layer) ----------------------------
# The cross-card per-molecular-subtype convergence the capstone owed. Where _biomarker_facet
# converges SCALAR biomarker roles, this converges the PER-STRATUM panoramas: the three
# subtype-grain cards each emit `per_subgroup_metrics` (one record per molecular subtype, carrying
# evidence_state measured/underpowered/absent + a metric), scattered across three sub-skills. Nothing
# assembled them BY SUBTYPE across cards. This facet does: for each molecular subtype, which axes
# (expression / dependency / mutation-frequency) carry a MEASURED signal, and which subtypes have
# ≥2 axes converge (the actionable patient-selection strata). Deterministic, additive, verdict-inert.
#
# (sub_skill_short, card_id, axis_label) — the three subtype-grain panorama cards + where they live.
_SUBTYPE_INPUTS = [
    ("expression",         "tumor-rna-distribution-by-subtype",        "expression"),
    ("dependency",         "subgroup-stratified-dependency",           "dependency"),
    ("genomic_alteration", "subgroup-stratified-mutation-frequency",   "mutation_frequency"),
]


def _first_card_per_subgroup(sub_result: dict, card_id: str) -> list:
    """Return the named card's per_subgroup_metrics list (records per molecular subtype), or []."""
    for c in sub_result.get("cards") or []:
        if c.get("card_id") == card_id:
            return (c.get("summary") or {}).get("per_subgroup_metrics") or []
    return []


def _subtype_stratum_key(rec: dict) -> str | None:
    """The molecular-subtype identity of a per_subgroup_metrics record. Panorama rows use `stratum`
    (subgroup_common.build_panorama); tolerate a few historical aliases. None if unidentifiable."""
    for k in ("stratum", "subgroup_id", "subgroup_label", "subgroup"):
        v = rec.get(k)
        if v:
            return str(v)
    return None


def _load_subtype_crosswalk(indication: str, contracts_repo: Path | None = None) -> dict:
    """Load the indication's block from vocabularies/subtype_crosswalk.yaml. Returns
    {associations: [...], axis_of: {stratum: axis}, cohorts_of: {stratum: [cohorts]}} or empty dicts
    when the registry / indication is absent (graceful — the facet degrades to exact-match only)."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "subtype_crosswalk.yaml"
    out = {"associations": [], "axis_of": {}, "cohorts_of": {}}
    if not path.exists():
        return out
    try:
        import yaml
        doc = yaml.safe_load(path.read_text()) or {}
    except Exception:  # noqa: BLE001
        return out
    for ind in doc.get("indications", []) or []:
        if ind.get("canonical_code") != indication:
            continue
        out["associations"] = ind.get("associations", []) or []
        for ax in ind.get("axes", []) or []:
            for s in ax.get("strata", []) or []:
                out["axis_of"][s] = ax.get("axis")
                out["cohorts_of"][s] = ax.get("cohorts", []) or []
        break
    return out


def _subtype_facet(sub_results: dict, indication: str = None,
                   contracts_repo: Path | None = None) -> dict:
    """Assemble the per-molecular-subtype CONVERGENCE facet (capstone Part 3c). Deterministic;
    additive; VERDICT-INERT (a synthesis facet, never a gate — informs patient-selection confidence,
    never mints a nominate). Converges the three subtype-grain panoramas BY SUBTYPE:

      per_subtype: {subtype: {axes_measured: [...], axes_present: [...], n_axes_measured, metrics:{}}}
      convergent_subtypes: subtypes with >= 2 MEASURED axes on the SAME stratum id (the strong claim)
      associated_subtypes: pairs of DIFFERENT strata (each measured on its own axis) linked by a
        subtype_crosswalk association (enriched_in / co_defining) — the WEAK, cohort-bridged claim
        that lets MSI_H(dependency, DepMap) relate to CMS1(expression, TCGA) WITHOUT claiming they
        are the same stratum. Each carries the relationship + a cohort_bridge flag when the two axes
        live on different cohorts (e.g. DepMap dependency vs TCGA expression).
      verdict:
        convergent_stratification  — >=1 subtype with >=2 measured axes on the SAME id (strongest)
        associated_stratification  — no same-id convergence, but >=1 registry-linked measured pair
        single_axis_stratification — measured subtype signal on only one axis, no association
        no_subtype_signal          — panoramas present but no measured stratum on any axis
        subtype_axis_unavailable   — no subtype shard reached for this indication (coverage gap)

    Absence is HONEST: a subtype/axis with no measured record contributes nothing (never fabricated).
    The association tier NEVER collapses two strata into one — it reports them as related, with the
    relationship type + cohort bridge explicit, so a CMS finding is never mislabeled an MSI finding."""
    xwalk = _load_subtype_crosswalk(indication, contracts_repo) if indication else \
        {"associations": [], "axis_of": {}, "cohorts_of": {}}
    per_subtype: dict = {}
    axes_seen: set = set()
    any_rows = False
    for short, card_id, axis in _SUBTYPE_INPUTS:
        # Production (_run_sub_skills) resolves the dependency + mutation-frequency subtype
        # cards under the single SUBTYPE_SHORT ('subtype_fit') result, NOT under their per-gate
        # short (the expression subtype card lives under 'expression' / tumor-presence). Search
        # the per-gate short first (matches the synthetic test fixtures), then fall back to
        # subtype_fit (matches production). Without the fallback the dependency + genomic axes
        # were always empty, so >=2-axis convergence was structurally unreachable.
        rows: list = []
        for _src in (short, SUBTYPE_SHORT):
            r = sub_results.get(_src)
            if r:
                rows = _first_card_per_subgroup(r, card_id)
                if rows:
                    break
        if rows:
            any_rows = True
            axes_seen.add(axis)
        for rec in rows:
            subtype = _subtype_stratum_key(rec)
            if not subtype:
                continue
            state = rec.get("evidence_state")
            block = per_subtype.setdefault(subtype, {"axes_measured": [], "axes_present": [],
                                                     "metrics": {}})
            block["axes_present"].append(axis)
            # carry the axis metric (whatever numeric/class the panorama row exposes beyond bookkeeping)
            metric = {k: v for k, v in rec.items()
                      if k not in ("stratum", "subgroup_id", "subgroup_label", "subgroup",
                                   "subgroup_n", "subgroup_n_floor_met", "evidence_state",
                                   "source_cohort") and v is not None}
            if metric:
                block["metrics"][axis] = metric
            if state == "measured":
                block["axes_measured"].append(axis)

    for block in per_subtype.values():
        block["axes_measured"] = sorted(set(block["axes_measured"]))
        block["axes_present"] = sorted(set(block["axes_present"]))
        block["n_axes_measured"] = len(block["axes_measured"])

    convergent = sorted(st for st, b in per_subtype.items() if b["n_axes_measured"] >= 2)
    any_measured = any(b["n_axes_measured"] >= 1 for b in per_subtype.values())

    # ── Association tier (registry-bridged, WEAK): different strata each measured on their own axis,
    # linked by a subtype_crosswalk enriched_in / co_defining association. This is what lets
    # MSI_H(dependency) relate to CMS1(expression) across the vocabulary/cohort gap WITHOUT claiming
    # they are the same stratum. Only strata that are actually MEASURED here participate.
    measured_axes_of = {st: set(b["axes_measured"]) for st, b in per_subtype.items()
                        if b["n_axes_measured"] >= 1}
    associated_pairs = []
    for assoc in xwalk["associations"]:
        a, b_, rel = assoc.get("from"), assoc.get("to"), assoc.get("relationship")
        if rel not in ("enriched_in", "co_defining"):
            continue
        # both endpoints must be measured, and on DIFFERENT axes (else it's not a cross-axis bridge)
        if a not in measured_axes_of or b_ not in measured_axes_of:
            continue
        axes_a, axes_b = measured_axes_of[a], measured_axes_of[b_]
        cross_axis = bool(axes_a - axes_b) or bool(axes_b - axes_a)
        if not cross_axis:
            continue
        # cohort bridge: the two strata's registry cohorts don't overlap (e.g. DepMap dep vs TCGA expr)
        coh_a, coh_b = set(xwalk["cohorts_of"].get(a, [])), set(xwalk["cohorts_of"].get(b_, []))
        cohort_bridge = bool(coh_a and coh_b and not (coh_a & coh_b))
        associated_pairs.append({
            "from": a, "to": b_, "relationship": rel,
            "from_axes_measured": sorted(axes_a), "to_axes_measured": sorted(axes_b),
            "cohort_bridge": cohort_bridge, "note": assoc.get("note", ""),
        })

    if not any_rows:
        verdict = "subtype_axis_unavailable"
    elif convergent:
        verdict = "convergent_stratification"
    elif associated_pairs:
        verdict = "associated_stratification"
    elif any_measured:
        verdict = "single_axis_stratification"
    else:
        verdict = "no_subtype_signal"

    return {
        "verdict": verdict,
        "convergent_subtypes": convergent,
        "associated_subtypes": associated_pairs,
        "n_subtypes_evaluated": len(per_subtype),
        "axes_available": sorted(axes_seen),
        "per_subtype": per_subtype,
        "_disclaimer": ("Subtype is a FACET, not a gate: it converges the per-molecular-subtype "
                        "panoramas (expression / dependency / mutation-frequency) BY SUBTYPE to "
                        "surface cross-axis patient-selection strata. It informs confidence + "
                        "patient-selection, never mints a nominate. convergent_subtypes = subtypes "
                        "with >=2 MEASURED axes on the SAME stratum id (strong). associated_subtypes "
                        "= DIFFERENT strata each measured on its own axis, linked by a "
                        "subtype_crosswalk enriched_in/co_defining association (weak, cohort-bridged) "
                        "— reported as RELATED, never as the same stratum (a CMS finding is never "
                        "relabeled an MSI finding); cohort_bridge=true flags a DepMap-vs-TCGA cross. "
                        "subtype_axis_unavailable = no shard for this indication (coverage gap), not "
                        "a measured negative."),
    }


# --- Fragility facet (verdict-inert flip-stability; the quantitative "how solid is this call?") ---
#
# Bounded uncertainty WITHOUT probability. For each DECISION-RELEVANT axis (an axis whose verdicts the
# nomination gate / positive tier / veto-suppressors actually read), run the single-rule flip scan
# (flip_analysis) on that axis's resolver and measure how easily the call moves. Three fragilities:
#   raw_flip_fragility            — fraction of verdict-movable rules whose toggle changes the STRING.
#   decision_flip_fragility       — fraction whose toggle changes the axis's DECISION ROLE (kill /
#                                   positive / contradiction / neutral). A lineage_selective ->
#                                   selective_dependent flip changes the string but both are `positive`,
#                                   so it is NOT a decision flip (the KRAS anchor).
#   recommendation_flip_fragility — fraction whose toggle CROSSES THE KILL BOUNDARY (enters/leaves a
#                                   gate action). These are the ONLY flips that can move
#                                   overall_recommendation; positive<->contradiction<->neutral flips
#                                   change CONFIDENCE, not the Go/No-Go.
# TWO target-level indices (both worst-case/max over axes, never a mean — mirroring the gate's
# max-over-action-ranks): target_index = worst CALL fragility (how solid each axis's call is;
# informative); recommendation_fragility_index = worst RECOMMENDATION fragility, and this is what DRIVES
# `contested`. An axis the framework could not evidence (no signal) is an EVIDENCE GAP not a fragile
# verdict — tracked separately in blind_decision_axes (fragility None), never folded into either index.
#
# STRICTLY VERDICT-INERT: reads sub_results, never calls _gate_recommendation, never writes
# overall_recommendation / confidence. Emitted as a nomination.json facet; it MAY set a categorical
# `contested` flag (from a declarative threshold) that a reader/banner surfaces — the flag NEVER
# changes the recommendation. `contested` is None when no threshold is configured (absence must not
# fabricate a flag); the numeric indices are emitted regardless.
_FRAGILITY_LEGEND = (
    "Verdict FRAGILITY (flip-stability): re-runs the deterministic resolver over single-rule-perturbed "
    "fired sets. target_index = worst-case fraction of a gate's verdict-movable rules whose toggle "
    "changes its DECISION ROLE (how solid each axis's CALL is). recommendation_fragility_index = worst "
    "case whose toggle crosses the KILL boundary (how solid the GO/NO-GO is) — this drives `contested`. "
    "0 = robust; higher = a call one plausible rule-change could flip. A structural sensitivity "
    "measure — NOT a probability the target succeeds, and never summed or averaged."
)


def _load_contested_threshold(contracts_repo: Path | None = None) -> Optional[dict]:
    """Load the optional `contested_threshold` stanza from the nomination-gate vocab, or None if
    absent/malformed. NEVER-FABRICATE contract: absence → None → the facet emits contested=None (no
    flag). A missing threshold can only make the facet emit LESS (no contested), never fabricate one;
    and the flag is verdict-inert either way, so this is safe."""
    repo = contracts_repo or _CONTRACTS_REPO
    path = repo / "vocabularies" / "nomination_verdict_gate.yaml"
    try:
        data = yaml.safe_load(path.read_text())
        ct = data.get("contested_threshold")
        if isinstance(ct, dict) and isinstance(ct.get("fragility_index_min"), (int, float)):
            return ct
        return None
    except Exception:  # noqa: BLE001 — absence/parse failure → no contested flag (verdict-inert)
        return None


def _decision_role(short: str, verdict: str,
                   gate_map: dict, pos_map: dict, contra_set: set) -> str:
    """The axis's role in the nomination decision for a given verdict: 'kill:<action>' /
    'positive:<weight>' / 'contradiction' / 'neutral'. Pure lookup over the loaded vocab maps."""
    if (short, verdict) in gate_map:
        return f"kill:{gate_map[(short, verdict)]}"
    if (short, verdict) in pos_map:
        return f"positive:{pos_map[(short, verdict)]}"
    if (short, verdict) in contra_set:
        return "contradiction"
    return "neutral"


def _subgroup_flip_view(sub_results: dict) -> dict:
    """Descriptive per-stratum heterogeneity view (only under --subtypes). Reports the POOLED
    dependency verdict alongside the subtype panorama's per-stratum rows, so a reader can see when a
    pooled call hides a stratified pattern ("pooled non_dependent, but stratum X shows a measured
    dependency"). DESCRIPTIVE, not a re-resolved per-stratum verdict: it surfaces the panorama's own
    per_subgroup_metrics (evidence_state + metric); the resolver-backed subtype call is
    subtype_fit_verdict. (A full per-stratum re-resolution is the deferred Tier-1 heterogeneity work.)"""
    dep = sub_results.get("dependency") or {}
    dep_v = dep.get("verdict")
    subtype_r = sub_results.get(SUBTYPE_SHORT) or {}
    subtype_v = subtype_r.get("verdict")
    rows = []
    for rec in _first_card_per_subgroup(subtype_r, "subgroup-stratified-dependency"):
        st = _subtype_stratum_key(rec)
        if not st:
            continue
        rows.append({
            "stratum": st,
            "evidence_state": rec.get("evidence_state"),
            "subgroup_n_floor_met": rec.get("subgroup_n_floor_met"),
            "metric": {k: v for k, v in rec.items()
                       if k not in ("stratum", "subgroup_id", "subgroup_label", "subgroup",
                                    "subgroup_n", "subgroup_n_floor_met", "evidence_state",
                                    "source_cohort") and v is not None},
        })
    return {
        "pooled_dependency_verdict": dep_v[0] if dep_v else None,
        "subtype_fit_verdict": subtype_v[0] if subtype_v else None,
        "per_stratum_dependency": rows,
        "_note": ("Descriptive per-stratum view (--subtypes): the subtype panorama's own "
                  "per_subgroup_metrics beside the POOLED dependency verdict, to expose a stratified "
                  "pattern the pooled call hides. NOT a re-resolved per-stratum verdict; the "
                  "resolver-backed subtype call is subtype_fit_verdict."),
    }


def _fragility_facet(sub_results: dict, subtypes: Optional[list[str]] = None,
                     contracts_repo: Path | None = None, modality: str | None = None) -> dict:
    """Verdict-inert flip-stability facet (see section header). Emitted in nomination.json; never
    touches the verdict / gate / recommendation. `modality` is threaded so the decision-relevant
    axis set includes modality-scoped surface positives under an explicit biologics modality —
    keeping the fragility scan consistent with what the gate/positive tier actually reads."""
    gate_map, _gsrc = _load_gate_verdicts(contracts_repo)
    pos_map, contra_set, _cfg, _psrc = _load_positive_signals(contracts_repo, modality=modality)
    baseline, _covsrc = _load_gate_coverage(contracts_repo)

    # Decision-relevant axes = every sub_skill short the gate / positive / contradiction vocab reads.
    decision_shorts = ({s for (s, _v) in gate_map} | {s for (s, _v) in pos_map}
                       | {s for (s, _v) in contra_set})

    per_axis: dict = {}
    fragilities: list[float] = []           # worst-case CALL fragility (any decision-role change)
    rec_fragilities: list[float] = []       # worst-case RECOMMENDATION fragility (kill-boundary crossing)
    blind_decision_axes: list[str] = []
    for short in sorted(decision_shorts):
        r = sub_results.get(short)
        if r is None:
            continue  # a decision-relevant axis not present this run (e.g. subtype_fit w/o --subtypes)
        has_signal = _sub_result_has_signal(r)
        coverage = _run_coverage_for_short(short, r, baseline)
        gate = _SHORT_TO_GATE.get(short)

        if not has_signal:
            # An un-evidenced axis is an EVIDENCE GAP, not a fragile verdict (measured-vs-null
            # discipline): it has no verdict to flip. Tracked separately, NOT folded into the flip
            # index — coverage/blindness is the deciding-axis router's responsibility, not fragility's.
            per_axis[short] = {"gate": gate, "flip_applicable": bool(gate), "has_signal": False,
                               "coverage": coverage, "fragility": None, "reason": "blind"}
            blind_decision_axes.append(short)
            continue

        if gate is None:
            # decision-relevant but no resolver to flip (e.g. `expression` presence positive): it has
            # signal but no flip scan, so it informs coverage, not the index.
            per_axis[short] = {"gate": None, "flip_applicable": False, "has_signal": True,
                               "coverage": coverage, "fragility": None, "reason": "no_resolver_gate"}
            continue

        fa = flip_analysis(r.get("fired") or [], gate, contracts_repo)
        if fa is None:
            per_axis[short] = {"gate": gate, "flip_applicable": False, "has_signal": True,
                               "coverage": coverage, "fragility": None, "reason": "resolver_absent"}
            continue

        base_role = _decision_role(short, fa["base_verdict"], gate_map, pos_map, contra_set)
        base_kill = base_role.startswith("kill:")   # base verdict maps to a gate action (veto/hold)
        decision_flips = []
        n_rec_flips = 0
        for f in fa["flips"]:
            to_role = _decision_role(short, f["to_verdict"], gate_map, pos_map, contra_set)
            if to_role == base_role:
                continue                              # raw flip but same decision role (e.g. lineage↔selective)
            # A RECOMMENDATION flip crosses the KILL boundary (enters/leaves a gate action) — the only
            # flips that can move overall_recommendation. Role changes AMONG positive/contradiction/
            # neutral change CONFIDENCE, not the Go/No-Go — so they are call-fragile, not recommendation-
            # fragile (this is why KRAS, fragile only on the selectivity CONTRADICTION, is not contested).
            rec = base_kill != to_role.startswith("kill:")
            if rec:
                n_rec_flips += 1
            decision_flips.append({"rule_id": f["rule_id"], "present": f["present"],
                                   "to_verdict": f["to_verdict"], "to_role": to_role,
                                   "recommendation_flip": rec})
        n_rel = fa["n_relevant"]
        decision_fragility = (len(decision_flips) / n_rel) if n_rel else 0.0
        rec_fragility = (n_rec_flips / n_rel) if n_rel else 0.0
        per_axis[short] = {
            "gate": gate, "flip_applicable": True, "has_signal": True, "coverage": coverage,
            "base_verdict": fa["base_verdict"], "base_driver": fa["base_driver"],
            "base_role": base_role, "n_relevant": n_rel,
            "raw_flip_fragility": round(fa["flip_fragility"], 4),
            "decision_flip_fragility": round(decision_fragility, 4),
            "recommendation_flip_fragility": round(rec_fragility, 4),
            "decision_flips": decision_flips,
            "fragility": round(decision_fragility, 4),
        }
        fragilities.append(decision_fragility)
        rec_fragilities.append(rec_fragility)

    # target_index = worst-case CALL fragility (how solid is each axis's own call — informative).
    # recommendation_fragility_index = worst-case fragility of the GO/NO-GO ACTION itself, and it is what
    # DRIVES `contested` — a call can be fragile (selectivity discordant) while the recommendation is rock
    # solid, and only the latter should raise a contested banner.
    target_index = round(max(fragilities), 4) if fragilities else None
    recommendation_fragility_index = round(max(rec_fragilities), 4) if rec_fragilities else None

    ct = _load_contested_threshold(contracts_repo)
    contested = None
    if ct is not None and recommendation_fragility_index is not None:
        contested = recommendation_fragility_index >= ct["fragility_index_min"]

    facet = {
        "target_index": target_index,
        "recommendation_fragility_index": recommendation_fragility_index,
        "contested": contested,
        "decision_relevant_axes": sorted(decision_shorts),
        "blind_decision_axes": blind_decision_axes,
        "per_axis": per_axis,
        "_basis": "target_index = worst-case DECISION-flip (any role change: how solid is each axis's "
                  "call). recommendation_fragility_index = worst-case KILL-boundary-crossing flip (how "
                  "solid the Go/No-Go ACTION is) and DRIVES `contested`. single-rule scan; blind axes "
                  "tracked separately (coverage != fragility), never folded into either index.",
        "_legend": _FRAGILITY_LEGEND,
        "_contested_threshold": ct,
    }
    if subtypes:
        facet["subgroup_flips"] = _subgroup_flip_view(sub_results)
    return facet


def _find_card_summary(sub_results: dict, card_id: str) -> dict:
    """First matching card's summary dict across all sub-results (source-short-agnostic), or {}."""
    for r in sub_results.values():
        for c in (r.get("cards") or []):
            if c.get("card_id") == card_id:
                return c.get("summary") or {}
    return {}


def _cv(vals: list) -> "Optional[float]":
    """Coefficient of variation (population stdev / |mean|) over >=2 numerics; None otherwise.

    Values are coerced to Python float: numpy.float64 passes isinstance(v, float) (it
    subclasses float) but breaks statistics.mean/pstdev in py3.12 with
    "'float' object has no attribute 'numerator'". bool and NaN are excluded.
    """
    import math
    xs = []
    for v in vals:
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            continue
        fv = float(v)
        if math.isnan(fv):
            continue
        xs.append(fv)
    if len(xs) < 2:
        return None
    import statistics
    m = statistics.mean(xs)
    return (statistics.pstdev(xs) / abs(m)) if m != 0 else None


def _norm_entropy(labels: list) -> "Optional[float]":
    """Shannon entropy of a label multiset, normalized to 0..1 by log(#distinct); None if <2 labels."""
    xs = [x for x in labels if x]
    if len(xs) < 2:
        return None
    import math
    from collections import Counter
    counts = Counter(xs)
    if len(counts) < 2:
        return 0.0
    n = len(xs)
    h = -sum((c / n) * math.log(c / n) for c in counts.values())
    return h / math.log(len(counts))


# --- Heterogeneity facet (verdict-inert; cross-stratum / -comparator / -modality DISPERSION) --------
#
# Companion to fragility: fragility asks "how easily does the CALL move?"; heterogeneity asks "does a
# single pooled verdict HIDE a split?" — a target strong in some strata/comparators/assays and absent
# in others. NARROW by design (round-2 review): dispersion is only computable where the underlying
# MULTI-VALUE data survives — the tumor-vs-normal four-cell (always), CRISPR-vs-RNAi fraction_agree
# (always), and the per-molecular-subtype dependency panorama (ONLY under --subtypes; not pulled
# otherwise). Most pooled cards carry no per-value array, so a GENERAL cross-cohort dispersion is
# deliberately NOT attempted (needs method-layer plumbing). heterogeneity_index = worst-case over the
# available NORMALIZED (0..1) signals. STRICTLY VERDICT-INERT: emitted in nomination.json; never
# touches overall_recommendation / confidence.
_HETEROGENEITY_LEGEND = (
    "Cross-context HETEROGENEITY (dispersion): does a pooled verdict hide a split? Worst-case over the "
    "available normalized signals — tumor-vs-normal comparator disagreement (four-cell), CRISPR-vs-RNAi "
    "modality disagreement (1-fraction_agree), and (only under --subtypes) per-subtype dependency "
    "spread (class entropy / metric CV over floor-cleared strata). 0 = uniform; higher = a stratified "
    "opportunity the pooled call hides. NOT a probability; never summed or averaged."
)


def _heterogeneity_facet(sub_results: dict, subtypes: "Optional[list[str]]" = None) -> dict:
    """Verdict-inert cross-context dispersion facet (see section header). Emitted in nomination.json;
    never touches the verdict / gate / recommendation."""
    sources: dict = {}
    signals: list = []

    # (1) tumor-vs-normal four-cell comparator dispersion
    sel = _find_card_summary(sub_results, "tumor-vs-normal-selectivity")
    ran, sup = sel.get("cells_ran"), sel.get("cells_supporting")
    if isinstance(ran, (int, float)) and ran and isinstance(sup, (int, float)):
        unsupported = 1.0 - (sup / ran)
        disc = bool(sel.get("discordant"))
        logs_cv = _cv([sel.get("log2fc_cell_a"), sel.get("log2fc_cell_b"), sel.get("log2fc_cell_c")])
        disp = 1.0 if disc else round(unsupported, 4)   # an explicit discordant read is maximal dispersion
        sources["selectivity_comparators"] = {
            "cells_ran": ran, "cells_supporting": sup, "unsupported_fraction": round(unsupported, 4),
            "discordant": disc, "log2fc_cv": round(logs_cv, 4) if logs_cv is not None else None,
            "dispersion": disp}
        signals.append(disp)

    # (2) CRISPR-vs-RNAi modality dispersion
    conc = _find_card_summary(sub_results, "crispr-rnai-dependency-concordance")
    fa = conc.get("fraction_agree")
    if isinstance(fa, (int, float)):
        disp = round(1.0 - fa, 4)
        sources["modality_crispr_rnai"] = {"fraction_agree": round(fa, 4), "dispersion": disp}
        signals.append(disp)

    # (3) per-molecular-subtype dependency spread — only when --subtypes scoped (panorama present)
    if subtypes:
        rows = _first_card_per_subgroup(sub_results.get(SUBTYPE_SHORT) or {},
                                        "subgroup-stratified-dependency")
        measured = [r for r in rows
                    if r.get("evidence_state") == "measured" and r.get("subgroup_n_floor_met")]
        if len(measured) >= 2:
            metric_cv = _cv([r.get("median_chronos") for r in measured])
            ent = _norm_entropy([r.get("dependency_class") or r.get("_dependency_class") for r in measured])
            disp = ent if ent is not None else (min(metric_cv, 1.0) if metric_cv is not None else None)
            sources["subtype_strata"] = {
                "n_measured_strata": len(measured),
                "class_entropy": round(ent, 4) if ent is not None else None,
                "metric_cv": round(metric_cv, 4) if metric_cv is not None else None,
                "dispersion": round(disp, 4) if disp is not None else None}
            if disp is not None:
                signals.append(disp)

    return {
        "heterogeneity_index": round(max(signals), 4) if signals else None,
        "sources": sources,
        "_basis": "worst_case over available normalized cross-context dispersion signals "
                  "(selectivity four-cell / crispr-rnai concordance / subtype strata [--subtypes only])",
        "_legend": _HETEROGENEITY_LEGEND,
    }


# --- Addressable-population facet (patient-population layer, reconstructed as composition) ----------
_ADDRESSABLE_POPULATION_LEGEND = (
    "Estimated fraction of the indication addressable by the target's SELECTION BASIS. For an "
    "alteration-stratified / mutation-driver target the addressable population is the in-indication "
    "PREVALENCE of the defining SNV/indel (coverage-correct GENIE preferred — ~35x the MC3 sample "
    "count; MC3 fallback); for a broad (unstratified) dependency it is biomarker_unrestricted (the "
    "indication itself); a CN/fusion-defined subgroup is not_estimated_this_axis (SNV frequency is the "
    "wrong denominator — CN/fusion prevalence is a v2 extension). VERDICT-INERT: population-sizing "
    "context beside the nomination, never a gate input."
)

# clinical addressable-population tiers by alteration prevalence
def _addressable_population_class(freq: "float | None") -> "str | None":
    if not isinstance(freq, (int, float)):
        return None
    if freq >= 0.20:
        return "broad"            # e.g. KRAS/TP53 in COADREAD (~40%)
    if freq >= 0.05:
        return "common"
    if freq >= 0.01:
        return "uncommon"
    if freq >= 0.001:
        return "rare"
    return "ultra_rare"

# genomic verdicts whose actionability is TIED TO AN SNV/indel ALTERATION → population = its prevalence
_SNV_SELECTION_VERDICTS = frozenset({
    "biomarker_stratified_dependency", "moderate_biomarker_dependency", "confirmed_driver",
    "multi_class_driver", "missense_dominant_pattern", "lof_dominant_pattern", "drug_response_biomarker",
})
_CN_FUSION_SELECTION_VERDICTS = frozenset({
    "recurrent_amplification_driver", "recurrent_deletion_driver", "recurrent_fusion_driver",
})
_NON_DEPENDENT = frozenset({"non_dependent", "insufficient", "data_unavailable", ""})


def _addressable_population_facet(sub_results: dict) -> dict:
    """VERDICT-INERT addressable-population facet — joins the target's SELECTION BASIS (what defines the
    treatable subgroup, from the genomic + dependency verdicts) to the in-indication PREVALENCE of that
    basis (from mutation-hotspot-frequency: genie_mutation_frequency preferred, overall_mutation_frequency
    fallback). Reconstructs the deleted patient-population-and-access layer as a composition over signals
    already on the fan-out. Emitted in nomination.json + the synthesis prompt; never touches the gate."""
    gen = (sub_results.get("genomic_alteration") or {}).get("verdict")
    gen_verdict = gen[0] if gen else None
    dep = (sub_results.get("dependency") or {}).get("verdict")
    dep_verdict = dep[0] if dep else None

    hf = _find_card_summary(sub_results, "mutation-hotspot-frequency")
    genie_freq = hf.get("genie_mutation_frequency")
    mc3_freq = hf.get("overall_mutation_frequency")
    n_samples = hf.get("n_samples_in_indication")
    freq, source = ((genie_freq, "genie") if isinstance(genie_freq, (int, float))
                    else (mc3_freq, "tcga_mc3") if isinstance(mc3_freq, (int, float))
                    else (None, None))

    if gen_verdict in _SNV_SELECTION_VERDICTS:
        basis = "snv_indel_stratified"
        pop_class = _addressable_population_class(freq)
        note = None
    elif gen_verdict in _CN_FUSION_SELECTION_VERDICTS:
        basis = "copy_number_or_fusion_stratified"
        pop_class, freq, source = "not_estimated_this_axis", None, None
        note = ("addressable population is defined by a CN/fusion event; SNV frequency is inapplicable "
                "— CN/fusion prevalence (copy-number-distribution / fusion cards) is a v2 extension")
    elif dep_verdict and dep_verdict not in _NON_DEPENDENT:
        basis = "biomarker_unrestricted"
        pop_class = "biomarker_unrestricted"
        note = ("a broad dependency with no alteration-defined selection biomarker; the addressable "
                "population is the indication itself")
    else:
        basis = "undetermined"
        pop_class = None
        note = ("no alteration-selection verdict and no positive dependency to anchor an "
                "addressable-population estimate")

    return {
        "addressable_population_class": pop_class,
        "selection_basis": basis,
        "biomarker_prevalence": round(freq, 4) if isinstance(freq, (int, float)) else None,
        "prevalence_source": source,
        "n_samples_in_indication": n_samples,
        "_note": note,
        "_legend": _ADDRESSABLE_POPULATION_LEGEND,
    }


__all__ = [
    '_ADDRESSABLE_POPULATION_LEGEND',
    '_BIOMARKER_INPUTS',
    '_BIOMARKER_QUANT',
    '_CN_FUSION_SELECTION_VERDICTS',
    '_FRAGILITY_LEGEND',
    '_HETEROGENEITY_LEGEND',
    '_MATRIX_MODALITIES',
    '_NON_DEPENDENT',
    '_SNV_SELECTION_VERDICTS',
    '_SUBTYPE_INPUTS',
    '_addressable_population_class',
    '_addressable_population_facet',
    '_biomarker_facet',
    '_presence_facet',
    '_biomarker_quantitative',
    '_classify_biomarker_best_roles',
    '_cv',
    '_deciding_axis',
    '_decision_role',
    '_find_card_summary',
    '_first_card_per_subgroup',
    '_fragility_facet',
    '_heterogeneity_facet',
    '_load_contested_threshold',
    '_load_subtype_crosswalk',
    '_norm_entropy',
    '_ordinal_matrix',
    '_strongest_signal_for_modality',
    '_subgroup_flip_view',
    '_subtype_facet',
    '_subtype_stratum_key',
]
