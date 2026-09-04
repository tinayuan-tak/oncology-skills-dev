"""Synthetic nomination fixtures matching the documented spine shapes (docs/UNIFIED_OUTPUT_CONTRACT.md).

Shipped in-package (rather than under tests/) so the CI-collected suite in _skills_common/tests/ can
import it. Two builders: a fully-populated nomination (exercises every block kind) and a null-heavy one
(the fail-soft stressor — empty/None slots, a gateless call=None skill). Pure data; no imports.
"""
from __future__ import annotations


def _skill(*, call, role, polarity, honest_phrase="phrase", with_evidence=False,
           confidence=None, tension=None):
    r = {
        "call": call,
        "role": role,
        "polarity": polarity,
        "honest_phrase": honest_phrase,
        "confidence": confidence,
        "top_tension": tension,
        "claim_chips": [],
        "question_table": [],
        "per_phase_metrics": [],
        "figures": [],
        "provenance": {"driving_rule_id": None, "fired_rule_ids": [],
                       "cards_used": [], "cards_missing": []},
        "_contract": "docs/UNIFIED_OUTPUT_CONTRACT.md",
    }
    if with_evidence:
        r["confidence"] = confidence or {"level": "moderate", "basis": "2 concordant assays",
                                         "coverage": {"n_measured": 4, "n_axes": 5, "n_critical_measured": 2}}
        r["claim_chips"] = [
            {"key": "A", "label": "constraint", "signal": "supportive",
             "corroboration": "high", "conflict": None, "evidence": "pLI 0.99",
             "cites": [{"role": "signal", "card_id": "gnomad-constraint"}], "cite": {"card_id": "gnomad-constraint"}},
            {"key": "B", "label": "burden", "signal": "opposing", "corroboration": "weak",
             "conflict": None, "evidence": "no burden signal",
             "cites": [{"role": "signal", "card_id": "ot-burden"}], "cite": {"card_id": "ot-burden"}},
        ]
        # REAL question-table shape (question_table_core.row/conf): signal + confidence are DICTS
        # ({tier, fill/dots, polarity, label}), NOT strings. The renderer must surface their `label`.
        r["question_table"] = [
            {"id": "Q1", "question": "LoF-constrained?", "primary": "pLI 0.99", "support": "",
             "signal": {"tier": "strong", "fill": 5, "polarity": "supports", "label": "constrained"},
             "confidence": {"tier": "high", "dots": 3, "label": "gnomAD v4: high"}},
            {"id": "Q2", "question": "population burden?", "primary": "no enrichment", "support": "",
             "signal": {"tier": "absent", "fill": 1, "polarity": "opposes", "label": "absent"},
             "confidence": {"tier": "moderate", "dots": 2, "label": "moderate"}},
        ]
        r["per_phase_metrics"] = [
            {"metric": "pLI", "value": 0.99, "sample_context": "gnomAD v4 (n=807k)"},
        ]
        r["figures"] = [
            {"slot": "hero", "kind": "hero_svg", "path": "figures/safety_hero.svg",
             "caption": "gnomAD constraint vs tolerance percentile"},
        ]
        r["provenance"] = {"driving_rule_id": "SAF-LOF-01",
                           "fired_rule_ids": ["SAF-LOF-01", "SAF-DOSAGE-02"],
                           "cards_used": ["gnomad-constraint", "ot-burden"],
                           "cards_missing": ["clinvar-path"]}
    return r


def make_nomination() -> dict:
    """A populated nomination — one killer gating skill (full evidence), one supportive gating skill,
    one gateless descriptive skill (call=None)."""
    return {
        "target": "USP8",
        "indication": "COADREAD",
        "llm_synthesis": {
            # inline [rule-id] citations mirror the real synthesis prompt output — the renderer must
            # lift them OUT of the prose into the `citations` provenance affordance.
            "executive_summary": ("USP8 is a selective MSI-high dependency "
                                  "[dependency-mutant-strongly-dependent-supportive] but highly "
                                  "LoF-constrained [SAF-LOF-01, SAF-DOSAGE-02]."),
            "tension_analysis": ("Supportive dependency vs a killer safety constraint "
                                 "[safety-lof-constrained-killer]."),
            "top_arguments": [{"claim": "Selective dependency in MSI-high lines "
                                        "[lineage-selective-supportive]"},
                              {"claim": "Full-KO safety risk from LoF constraint"}],
        },
        "risk_assessment": {"dimensions": {
            "safety": {"risk_level": "HIGH", "interpretation": "gnomAD LoF-constrained",
                       "cited_pmids": ["12345678", "23456789"]},
            "clinical": {"risk_level": "MEDIUM", "interpretation": "no approved precedent"},
        }},
        # top-level sub_verdicts (the real nomination shape) — cards_used gives report_render the
        # card_id → owning-skill join. normal-tissue-liability composes under BOTH safety (gating) and
        # target_intrinsic (descriptive) → the figure join must route it to safety (gating-lister wins),
        # never duplicate it under both.
        "sub_verdicts": {
            "dependency": {"skill_dir": "functional-requirement", "verdict": "genetic_dependency",
                           "driving_rule_id": "strongly-selective-supportive",
                           "fired_rule_ids": ["strongly-selective-supportive"],
                           "cards_used": ["pan-cancer-crispr-dependency-distribution",
                                          "dependency-lineage-selectivity"], "cards_missing": []},
            "safety": {"skill_dir": "on-target-safety-liability", "verdict": "lof_constrained",
                       "driving_rule_id": "gnomad-lof-constrained-veto",
                       "fired_rule_ids": ["gnomad-lof-constrained-veto"],
                       "cards_used": ["gnomad-lof-constraint", "normal-tissue-liability"],
                       "cards_missing": []},
            "target_intrinsic": {"skill_dir": "target-intrinsic", "verdict": None,
                                 "driving_rule_id": None, "fired_rule_ids": [],
                                 "cards_used": ["normal-tissue-liability", "functional-gene-state"],
                                 "cards_missing": []},
        },
        # per-card figures produced this run (descriptor shape from _figure_emitters: id/path/type/
        # primary/dynamic; path relative to figures/). A plotly.json sibling (dynamic:True) is carried
        # as dynamic_ref, never its own image block.
        "card_figures": {
            "pan-cancer-crispr-dependency-distribution": [
                {"id": "chronos_density",
                 "path": "cards/pan-cancer-crispr-dependency-distribution/figure_chronos_density.svg",
                 "type": "chronos_dependency_density", "primary": True, "dynamic": None},
                {"id": "chronos_lineage",
                 "path": "cards/pan-cancer-crispr-dependency-distribution/figure_chronos_lineage.svg",
                 "type": "per_lineage_strip_plot", "primary": False, "dynamic": None},
                {"id": "chronos_density",
                 "path": "cards/pan-cancer-crispr-dependency-distribution/figure_chronos_density.plotly.json",
                 "type": "plotly", "primary": None, "dynamic": True},
            ],
            "gnomad-lof-constraint": [
                {"id": "loeuf_vs_genome",
                 "path": "cards/gnomad-lof-constraint/figure_loeuf_vs_genome.svg",
                 "type": "loeuf_vs_genome_distribution", "primary": True, "dynamic": None},
            ],
            "normal-tissue-liability": [
                {"id": "normal_tissue_heatmap",
                 "path": "cards/normal-tissue-liability/figure_normal_tissue_expression_heatmap.svg",
                 "type": "normal_tissue_expression_heatmap", "primary": True, "dynamic": None},
            ],
            "functional-gene-state": [
                {"id": "gene_state",
                 "path": "cards/functional-gene-state/figure_functional_gene_state.svg",
                 "type": "functional_gene_state_bar", "primary": True, "dynamic": None},
            ],
        },
        "target_report": {
            "schema": "target_report.v1",
            "skill_reports": {
                # NOTE: emit order intentionally NOT role-first, so ordering logic is exercised.
                "dependency": _skill(call="genetic_dependency", role="gating", polarity="supportive",
                                     honest_phrase="Selective dependency in MSI-high lines",
                                     with_evidence=True),
                "safety": _skill(call="lof_constrained", role="gating", polarity="killer",
                                 honest_phrase="Highly LoF-constrained — full-KO risk",
                                 with_evidence=True,
                                 tension={"text": "constraint vs tumor selectivity",
                                          "source": "safety", "severity": "high"}),
                "target_intrinsic": _skill(call=None, role="descriptive", polarity="not_scored",
                                           honest_phrase="Deubiquitinase; druggable pocket present"),
            },
            "target_call": {
                "schema": "target_call.v1",
                "recommendation": "hold",
                "confidence": {"level": "moderate", "basis": "killer safety vs supportive dependency"},
                "deciding_axis": {"basis": "gate_fired", "coverage_source": "vocab",
                                  "deciding_axes": [{"short": "safety", "gate_name": "On-target safety",
                                                     "band": "necessity"}]},
                "dissent": [{"source": "dependency", "detail": "supportive signal overruled by safety",
                             "resolved_to": "hold"}],
                "gate": {"recommendation_gate": "hold"},
            },
            "risk_6dim": {
                "biological": {"bin": "LOW"}, "druggability": {"bin": "MED"},
                "safety": {"bin": "HIGH"}, "translational": {"bin": "LOW"},
                "clinical": {"bin": "MED"}, "commercial": {"bin": "ENGINE-BLIND"},
            },
            "thesis": {"schema": "target_coherence.v1",
                       "thesis": {"primary": "selective_dependency_with_safety_ceiling"},
                       # a NON-trivial coherence: a caveat present → the block emits (a bare "coherent"
                       # with no caveat is suppressed by _coherence_block as context-free).
                       "coherence": {"class": "coherent", "confirms": [],
                                     "caveats": ["dependency is MSI-context-conditional — confirm the "
                                                 "partner background"],
                                     "artifact_flags": []}},
            "evidence_matrix": {
                "axes": {"columns": ["small_molecule", "degrader", "adc", "bite_tce"]},
                "rows": [
                    {"short": "safety", "verdict": "lof_constrained",
                     "cells": {"small_molecule": {"signal": "opposing", "ordinal": -1, "on_scale": True},
                               "degrader": {"signal": "killer", "ordinal": -3, "on_scale": True},
                               "adc": {"signal": None, "ordinal": None, "on_scale": False},
                               "bite_tce": {"signal": "not_applicable", "ordinal": None, "on_scale": False}}},
                    {"short": "dependency", "verdict": "genetic_dependency",
                     "cells": {"small_molecule": {"signal": "supportive", "ordinal": 2, "on_scale": True},
                               "degrader": {"signal": "supportive", "ordinal": 2, "on_scale": True},
                               "adc": {"signal": None, "ordinal": None, "on_scale": False},
                               "bite_tce": {"signal": None, "ordinal": None, "on_scale": False}}},
                    # an all-off-scale row (no measured modality signal) — must be DROPPED from the
                    # display matrix (pure `·` noise), exercising _row_has_on_scale.
                    {"short": "translational_readiness", "verdict": None,
                     "cells": {"small_molecule": {"signal": None, "ordinal": None, "on_scale": False},
                               "degrader": {"signal": None, "ordinal": None, "on_scale": False},
                               "adc": {"signal": None, "ordinal": None, "on_scale": False},
                               "bite_tce": {"signal": "insufficient", "ordinal": None, "on_scale": False}}},
                ],
                "legend": {"on_scale": {"supportive": 2, "neutral": 0, "opposing": -1, "killer": -3},
                           "off_scale": ["insufficient", "not_applicable"]},
                "_disclaimer": "ORDINAL VIEW — display/ranking only, not calibrated measurement.",
            },
            # authoritative per-modality rollup (worst-case conjunction of each axis's RESOLVED
            # modality_scope) — the spine-safe source the "Modality fit" readout renders. MYC-like:
            # SM/degrader unfavorable (limited by safety); the surface channels are a category error.
            "modality_fit": {"by_channel": {
                "small_molecule": {"fit": "unfavorable", "limiting_axis": "safety",
                                   "by_axis": {"tractability_sm": "favorable", "safety": "unfavorable",
                                               "dependency": "conditional"}},
                "degrader": {"fit": "unfavorable", "limiting_axis": "safety",
                             "by_axis": {"tractability_sm": "favorable", "safety": "unfavorable",
                                         "dependency": "favorable"}},
                "biologics": {"fit": "not_applicable_by_axis", "limiting_axis": None, "by_axis": {},
                              "masked_by_axis": "intracellular_intrinsic"},
                "adc": {"fit": "not_applicable_by_axis", "by_axis": {},
                        "masked_by_axis": "intracellular_intrinsic"},
                "bite_tce": {"fit": "not_applicable_by_axis", "by_axis": {},
                             "masked_by_axis": "intracellular_intrinsic"},
            }},
            "skill_report_rollup": {
                "by_role": {"gating": [{"short": "safety", "call": "lof_constrained", "polarity": "killer"},
                                       {"short": "dependency", "call": "genetic_dependency",
                                        "polarity": "supportive"}]},
                "killer_axes": ["safety"], "recommendation": "hold",
            },
            # molecular-subtype stratification (real shape) — MSI_H is a convergent subtype here.
            "subtype_convergence": {
                "verdict": "single_axis_stratification", "n_subtypes_evaluated": 3,
                "axes_available": ["expression"], "convergent_subtypes": ["MSI_H"],
                "associated_subtypes": [],
                "per_subtype": {"MSI_H": {"metrics": {}}, "MSS": {"metrics": {}}, "CMS1": {"metrics": {}}},
                "_disclaimer": "subtype panorama — descriptive.",
            },
            # patient-selection biomarker facet (real shape) — the reader fields + a hypothesis whose
            # _note dev text + dependency_performance numbers must NOT leak into the block.
            "biomarker": {
                "verdict": "strong_selection_biomarker", "preferred_assay": "genomic",
                "corroboration_role": {"alteration_role": "direct_driver_gof"},
                "stratification_role": {"mutation_stratification_class": "mutant_strongly_dependent",
                                        "subtype_stratification_class": "msi_enriched",
                                        "survival_association_class": "expression_high_better_survival",
                                        "rna_as_biomarker": "poor_proxy"},
                "biomarker_hypotheses": [{"intended_use": "predictive",
                                          "basis": "mutation_stratification_class=mutant_strongly_dependent",
                                          "evidence_strength": "strong", "_note": "DEV NOTE must not leak",
                                          "dependency_performance": {"dependency_ppv": 1.0}}],
                "intended_uses": ["predictive", "diagnostic_subtyping"],
                "_disclaimer": "biomarker facet — descriptive.",
            },
        },
        # per-axis narrative w/ flip_conditions (real shape) — "what would change the call". Only the
        # recommendation_flip:True entries surface; the dev-note `sentence` is never rendered.
        # dependency emits the resolver's FULL reachable-verdict enumeration (a present=True load-bearing
        # rest-on + an adverse kill + several near-duplicate strengthen/neutralize) — the block must
        # CURATE this (dedupe by direction, present-first, cap per axis), not dump all of it.
        "narrative_by_axis": {
            "dependency": {"axis": "dependency", "flip_conditions": [
                {"rule_id": "non-dependent-killer", "present": True, "to_verdict": "insufficient",
                 "to_role": "neutral", "recommendation_flip": True,
                 "sentence": "H fix (2026-07-20): DEV NOTE — must not render."},   # rests-on (neutralize)
                {"rule_id": "pan-essential-killer", "present": False, "to_verdict": "pan_essential_killer",
                 "to_role": "kill:veto", "recommendation_flip": True, "sentence": "dev note"},   # kill
                {"rule_id": "would-be-lineage", "present": False, "to_verdict": "lineage_selective",
                 "to_role": "positive", "recommendation_flip": True, "sentence": "dev"},   # strengthen (capped out)
                {"rule_id": "would-be-selective", "present": False, "to_verdict": "selective_dependent",
                 "to_role": "positive", "recommendation_flip": True, "sentence": "dev"},   # strengthen dup dir
                {"rule_id": "would-be-insuff-up", "present": False, "to_verdict": "insufficient_underpowered",
                 "to_role": "neutral", "recommendation_flip": True, "sentence": "dev"},   # neutralize dup dir
                {"rule_id": "concordant-dependent-supportive", "present": True, "to_verdict": "concordant_dependent",
                 "to_role": "positive", "recommendation_flip": False,  # non-flip → must be filtered out
                 "sentence": "dev note"}]},
            "safety": {"axis": "safety", "flip_conditions": [
                {"rule_id": "clinvar-germline-pathogenic-safety-warning", "present": True,
                 "to_verdict": "moderately_constrained_safety", "to_role": "neutral",
                 "recommendation_flip": True, "sentence": "dev note"}]},
        },
    }


def make_decision_json(skill_name: str = "on-target-safety-liability", *, with_evidence: bool = True,
                       call: str = "lof_constrained", role: str = "gating",
                       polarity: str = "killer") -> dict:
    """A STANDALONE skill decision.json: skill_report lives at decision['headline']['skill_report']
    (the shared write_package path). Mirrors the real on-disk shape."""
    return {
        "skill": skill_name,
        "target": "USP8",
        "indication": "COADREAD",
        "headline": {
            "headline_text": "…",
            "skill_report": _skill(call=call, role=role, polarity=polarity,
                                   honest_phrase="Highly LoF-constrained — full-KO risk",
                                   with_evidence=with_evidence,
                                   tension=({"text": "constraint vs selectivity", "source": "safety",
                                             "severity": "high"} if with_evidence else None)),
        },
        "run_health": {"skill_name": skill_name, "status": "ok"},
    }


def make_null_heavy_nomination() -> dict:
    """The fail-soft stressor: gateless call=None, empty everything, a None honest_phrase."""
    return {
        "target": None,
        "indication": None,
        "target_report": {
            "schema": "target_report.v1",
            "skill_reports": {
                "combination_vulnerability": _skill(call=None, role="descriptive",
                                                    polarity="not_scored", honest_phrase=None),
                "cis_coherence": _skill(call=None, role="inert", polarity="not_scored",
                                        honest_phrase=None),
                # a gating skill with NOTHING — should surface unmeasured coverage at L2, never crash.
                "selectivity": _skill(call=None, role="gating", polarity=None, honest_phrase=None),
            },
            "target_call": {},  # no recommendation, no deciding axis, no dissent
        },
    }
