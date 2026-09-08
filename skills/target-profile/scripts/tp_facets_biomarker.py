"""tp_facets — biomarker facet cluster (split out of tp_facets.py for readability; byte-identical).
Re-exported by tp_facets, so `from tp_facets import *` and existing imports are unaffected."""

from __future__ import annotations

from tp_common import _first_card_summary_field

_BIOMARKER_INPUTS = {
    # short (sub-skill) : list of (summary_field, role) it contributes
    "genomic_alteration": [
        ("alteration_role", "corroboration"),  # predictive_biomarker value
        ("mutation_stratification_class", "stratification"),
    ],  # mutant-stratified dependency
    "dependency": [
        ("abundance_dependency_class", "corroboration"),  # Q7 protein abundance→dep
        ("correlation_class", "corroboration"),  # RNA arm expression→dep
        ("correspondence_class", "corroboration"),
    ],  # Q4 model-backed dependency
    # (the recommended-models CARD key;
    #  NOT the functional-requirement
    #  headline alias model_correspondence_class,
    #  which _first_card_summary_field never sees)
    "expression": [
        ("rna_as_biomarker", "stratification"),  # Q5 preferred-assay input
        ("subtype_stratification_class", "stratification"),  # subtype patient-selection (2026-08-04)
        ("purity_confound_class", "corroboration"),
    ],  # Q9 signal-is-tumor-intrinsic
    # phospho_activity_class RE-HOMED 2026-08-05: it now surfaces under the mechanism sub-result
    # (phospho card moved tumor-presence → mechanism-and-pharmacology), so read it from there — else
    # the biomarker facet would silently drop the Q8 pathway-active corroboration signal.
    "mechanism": [("phospho_activity_class", "corroboration")],  # Q8 pathway-active (phospho)
    "differentiation": [("survival_association_class", "stratification")],  # Q11 prognostic stratifier
}


_BIOMARKER_QUANT = {
    # short (sub-skill) : list of numeric summary_fields to re-surface if present
    "genomic_alteration": [
        "hotspot_mannwhitney_q",
        "hotspot_effect_size",
        "delta_chronos_hotspot_mut_vs_wt",
        "median_chronos_hotspot_mutant",
        "median_chronos_hotspot_wildtype",
        # (2026-08-09): dependency-classification PERFORMANCE — the
        # biomarker as a classifier for the DepMap-dependency phenotype. PPV-lift
        # separates rare-sharp (BRAF ~9.6x) from common-dep high-PPV-low-lift (KRAS
        # ~2.2x) markers the coarse class hides. DEPENDENCY performance, NOT clinical.
        "hotspot_dependency_ppv",
        "hotspot_dependency_sensitivity",
        "hotspot_dependency_specificity",
        "hotspot_dependency_base_rate",
        "hotspot_dependency_ppv_lift",
    ],
    "dependency": [
        "pearson_r",
        "pearson_p",
        "spearman_r",
        "delta_chronos_top_vs_bottom_quartile",
        "protein_dependency_pearson_r",
        "protein_dependency_pearson_p",
        "n_cell_lines_evaluated",
        "n_paired_models",
        "fraction_agree",
        "fraction_dependent_in_both",
    ],
    "expression": ["rna_protein_r", "rna_protein_spearman", "n_paired_tumors"],
    "differentiation": ["logrank_p", "logrank_chi2", "n_patients", "n_events", "high_expr_hazard_direction"],
}


def _biomarker_quantitative(sub_results: dict) -> dict:
    """Re-surface the raw statistics behind the biomarker categorical classes. Returns a
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


def _classify_biomarker_best_roles(corroboration: dict, stratification: dict, quantitative: dict = None) -> list:
    """Type the assembled biomarker signals into a LIST of {intended_use, basis, evidence_strength}
    hypotheses (BEST-role). Pure fn — deterministic, no I/O; roles are NON-exclusive. A field that
    is null / data_unavailable / not_informative contributes nothing (honest — never fabricates a role).

    When `quantitative` carries the genomic dependency-classification performance, the
    genomic predictive hypothesis is annotated with the computed dependency-PPV + PPV-lift — a real
    metric on the DepMap-dependency ground truth (NOT drug-response / clinical PPV)."""
    quantitative = quantitative or {}

    def _live(v):
        return v not in (
            None,
            "data_unavailable",
            "not_informative",
            "insufficient_survival_data",
            "insufficient_mutation_rate",
            "insufficient_paired_models",
        )

    # Dependency-classification performance for the genomic stratifier, if present.
    _gq = quantitative.get("genomic_alteration", {}) or {}
    _dep_ppv = _gq.get("hotspot_dependency_ppv")
    _dep_lift = _gq.get("hotspot_dependency_ppv_lift")

    def _ppv_perf():
        """A compact dependency-performance dict to attach to a genomic predictive hypothesis."""
        if _dep_ppv is None:
            return None
        return {
            "dependency_ppv": _dep_ppv,
            "dependency_ppv_lift": _dep_lift,
            "dependency_sensitivity": _gq.get("hotspot_dependency_sensitivity"),
            "dependency_specificity": _gq.get("hotspot_dependency_specificity"),
            "dependency_base_rate": _gq.get("hotspot_dependency_base_rate"),
            "_metric_scope": "DepMap genetic-dependency phenotype (Chronos<=-0.5), NOT drug-response/clinical",
        }

    hyps: list = []
    mut_strat = stratification.get("mutation_stratification_class")
    alt_role = corroboration.get("alteration_role")
    surv = stratification.get("survival_association_class")
    subtype = stratification.get("subtype_stratification_class")
    phospho = corroboration.get("phospho_activity_class")
    # the dependency-correlation corroborators (support a predictive-dependency hypothesis, not roles of their own)
    corr_support = [
        corroboration.get(f) for f in ("abundance_dependency_class", "correlation_class", "correspondence_class")
    ]

    # PREDICTIVE — genomic stratifier (the strongest, most actionable). Two sub-bases:
    if alt_role == "predictive_biomarker":
        hyps.append(
            {
                "intended_use": "predictive",
                "basis": "alteration_role=predictive_biomarker",
                "evidence_strength": "strong",
                "_note": "genotype→drug-response predictive hypothesis (OncoKB/IntOGen-classed).",
            }
        )
    if mut_strat in ("mutant_strongly_dependent", "mutant_moderately_dependent"):
        strength = "strong" if mut_strat == "mutant_strongly_dependent" else "moderate"
        hyp = {
            "intended_use": "predictive",
            "basis": f"mutation_stratification_class={mut_strat}",
            "evidence_strength": strength,
            "_note": "mutation-stratified DEPENDENCY (CRISPR) — a dependency-predictive "
            "hypothesis; NOT auto an inhibitor biomarker (KO removes noncatalytic "
            "functions). Confirm with a pharmacologic (PRISM) arm before clinical framing.",
        }
        # attach the computed dependency-classification performance. PPV-lift is the
        # informativeness above the panel base-rate — it separates a rare-sharp predictor (high lift)
        # from a common-dependency high-PPV-low-lift marker (the coarse strength label hides this).
        perf = _ppv_perf()
        if perf is not None:
            hyp["dependency_performance"] = perf
        hyps.append(hyp)
    # a dependency-correlation signal WITHOUT a genotype stratifier = a weaker predictive-dependency hypothesis
    if not any(h["intended_use"] == "predictive" for h in hyps) and any(
        v
        in (
            "strong_negative",
            "moderate_negative",
            "protein_predicts_dependency",
            "well_modeled_in_lineage",
            "well_modeled_off_lineage",
        )
        for v in corr_support
    ):
        hyps.append(
            {
                "intended_use": "predictive",
                "basis": "expression/abundance↔dependency correlation",
                "evidence_strength": "weak",
                "_note": "abundance/expression correlates with dependency but no genotype stratifier "
                "— a continuous-biomarker HYPOTHESIS, weakest predictive tier.",
            }
        )

    # PROGNOSTIC — expression↔survival. STRICTLY distinct from predictive.
    if surv in ("expression_high_worse_survival", "expression_high_better_survival"):
        hyps.append(
            {
                "intended_use": "prognostic",
                "basis": f"survival_association_class={surv}",
                "evidence_strength": "weak",
                "_note": "univariate median-split OS association (stage-UNADJUSTED, hypothesis-"
                "generating) — a PROGNOSTIC hypothesis, says nothing about drug response.",
            }
        )

    # DIAGNOSTIC_SUBTYPING — a driver alteration that defines a class, or a restricted subtype.
    if alt_role in ("direct_driver_lof", "direct_driver_gof"):
        hyps.append(
            {
                "intended_use": "diagnostic_subtyping",
                "basis": f"alteration_role={alt_role}",
                "evidence_strength": "moderate",
                "_note": "driver alteration defines a molecular class/subtype; subtyping ≠ predictive "
                "(a class-defining event need not predict a specific drug's response).",
            }
        )
    if subtype in ("subtype_restricted", "subtype_enriched"):
        hyps.append(
            {
                "intended_use": "diagnostic_subtyping",
                "basis": f"subtype_stratification_class={subtype}",
                "evidence_strength": "moderate" if subtype == "subtype_restricted" else "weak",
                "_note": "expression restricted to / enriched in a molecular subtype — a subtyping/"
                "patient-selection axis.",
            }
        )

    # PHARMACODYNAMIC — a pathway-activity readout usable as a PD marker (not patient-selection).
    if _live(phospho) and phospho not in ("not_phosphoprotein",):
        hyps.append(
            {
                "intended_use": "pharmacodynamic",
                "basis": f"phospho_activity_class={phospho}",
                "evidence_strength": "weak",
                "_note": "phospho/pathway-activity readout — candidate PD (target-engagement) "
                "marker, forward-looking; NOT a patient-selection biomarker.",
            }
        )

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
    genomic_stratifier = (
        mut_strat in ("mutant_strongly_dependent", "mutant_moderately_dependent") or alt_role == "predictive_biomarker"
    )
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
    has_corroboration = any(v not in (None, "data_unavailable", "not_informative") for v in corroboration.values())
    if genomic_stratifier:
        verdict = "strong_selection_biomarker"
    elif preferred_assay == "protein" and not has_corroboration:
        verdict = "inadequate"
    elif has_corroboration or preferred_assay in ("RNA", "protein"):
        verdict = "corroborating_only"
    else:
        verdict = "none"

    # re-surface the raw statistics behind the categorical classes (strength, not just bucket).
    quantitative = _biomarker_quantitative(sub_results)

    # BEST-role classification: type the assembled signals into a LIST of non-exclusive
    # hypotheses, each naming its intended_use. Kept SEPARATE from the facet verdict (which is a
    # confidence/patient-selection summary) — this answers "what KIND of biomarker(s)", the verdict
    # answers "how strong a selector". Verdict-inert, additive. `quantitative` is passed so a
    # predictive hypothesis can carry the computed dependency-PPV performance.
    biomarker_hypotheses = _classify_biomarker_best_roles(corroboration, stratification, quantitative)
    intended_uses = sorted({h["intended_use"] for h in biomarker_hypotheses})

    return {
        "corroboration_role": corroboration,
        "stratification_role": stratification,
        "quantitative": quantitative,  # raw stats behind the classes (verdict-inert)
        "preferred_assay": preferred_assay,
        "verdict": verdict,
        "biomarker_hypotheses": biomarker_hypotheses,  # BEST-role: typed, non-exclusive
        "intended_uses": intended_uses,  # rollup of distinct roles present
        "_disclaimer": (
            "Biomarker is a FACET, not a gate: it corroborates other gates' verdicts "
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
            "negative."
        ),
    }
