"""display_gloss — plain-language readings for the evidence-graph card view + narrator.

The single registry that turns a bare summary field + number into a gauged, plain statement:

    median_chronos = -1.18   ->   "median CRISPR gene-effect (CHRONOS) = -1.18 (CHRONOS; lower = stronger)"

Three primitives, all pure + deterministic + DISPLAY-ONLY (feed no rule/resolver/gate):

  direction_phrase(direction)         3-value display hint -> a plain "lower = stronger" clause.
  gloss(field) -> (label, units)      METRIC_GLOSS for the ~50 salience-promoted metrics, a ~20-rule
                                      affix backstop for the raw L3 tail, else snake->space fallback.
  metric_reading(field, value, ...)   assembles "{label} = {value} ({units}; {direction_phrase})".

Plus the card DESCRIPTION join (the plain "what is this card"), which lives HERE (report_render), NOT the
pure evidence_graph builder:

  card_question(card_id)                        the raw card `question:` contract field (lru-cached).
  card_description(card_id, target, indication)  the same, with {target.symbol}/{indication.label} filled.

Consolidation target (Stage 2): the sandbox HELP map + tp_synthesis_prompt._METRIC_LEGEND both fold into
METRIC_GLOSS so the card view + the narrator bullets read one vocabulary.

Author budget kept small on purpose (contract in the CI coverage test test_display_gloss_coverage.py):
~50 metric entries (one per salience-promoted field) + ~20 affix rules + a handful of direction phrases.
"""

from __future__ import annotations

import functools
import re
from typing import Optional

import yaml

# ── direction phrases (3-value display hint -> plain clause) ─────────────────────────────────────────
# The graph carries `direction` on key_evidence.effect (24/30 salience specs). Normalize token variance
# (case / spacing / a few historical aliases) so a stray `higher_worse` still resolves — a prior organoid
# direction-inversion bug traces to un-normalized tokens.
_DIRECTION_PHRASE = {
    "lower_is_stronger": "lower = stronger",
    "higher_is_stronger": "higher = stronger",
    "higher_is_worse": "higher = worse (liability)",
    "lower_is_worse": "lower = worse (liability)",
    "near_zero_is_independent": "near zero = independent",
}
_DIRECTION_ALIASES = {
    "lower_stronger": "lower_is_stronger",
    "more_negative_is_stronger": "lower_is_stronger",
    "higher_stronger": "higher_is_stronger",
    "higher_is_better": "higher_is_stronger",
    "higher_worse": "higher_is_worse",
    "higher_bad": "higher_is_worse",
    "lower_worse": "lower_is_worse",
}


def _norm_direction(direction) -> Optional[str]:
    if not direction:
        return None
    tok = re.sub(r"\s+", "_", str(direction).strip().lower())
    return _DIRECTION_ALIASES.get(tok, tok)


def direction_phrase(direction) -> Optional[str]:
    """A plain-language reading of a `direction` display hint (None/unknown -> None)."""
    tok = _norm_direction(direction)
    return _DIRECTION_PHRASE.get(tok) if tok else None


# ── the metric registry: field -> (label, units/scale hint) ─────────────────────────────────────────
# ONE entry per salience-promoted field (evidence_salience.SALIENCE_SPECS effect/significance/omnibus/
# extra_scalars). `units` is a short scale token for the parenthetical ("CHRONOS", "log2FC", "%ile"); None
# when the number is already unitless (a fraction/flag). The q/p significance fields all share the one
# `(label, "q")`/`(label, "p")` shape (a lower=stronger convention documented in direction, not repeated
# per field). The CI coverage test asserts every salience field has an entry here.
METRIC_GLOSS: dict = {
    # ── effect metrics ──
    "median_chronos": ("median CRISPR gene-effect (CHRONOS)", "CHRONOS"),
    "median_chronos_panel": ("panel median CRISPR gene-effect (CHRONOS)", "CHRONOS"),
    "median_chronos_hotspot_mutant": ("median CHRONOS in hotspot-mutant lines", "CHRONOS"),
    "rnai_median_dep_score": ("median RNAi dependency score", "dep score"),
    "fraction_agree": ("CRISPR/RNAi agreement fraction", "fraction"),
    "spearman_r_crispr": ("CRISPR-PRISM concordance", "Spearman r"),
    "r2": ("dependency-predictability", "R2"),
    "loeuf_score": ("gnomAD LOEUF (LoF intolerance)", "LOEUF"),
    # s_het dominant-LoF selection (GeneBayes, Zeng 2024) — the continuous complement to LOEUF above.
    "shet_score": ("s_het dominant-LoF selection coefficient", "s_het"),
    "shet_lower_95": ("s_het 95% CI lower bound", "s_het"),
    "shet_upper_95": ("s_het 95% CI upper bound", "s_het"),
    "obs_lof_count": ("observed LoF variant count", "count"),
    "exp_lof_count": ("expected LoF variant count", "count"),
    # descriptor-coverage sweep, presence/spatial batch.
    "n_donors": ("spatial donors", "count"),
    "n_caf_subtypes_expressing": ("CAF subtypes expressing the target", "count"),
    "n_myeloid_subtypes_expressing": ("myeloid subtypes expressing the target", "count"),
    "n_phosphosites": ("phosphosites", "count"),
    # descriptor-coverage sweep, genomic-alteration-profile batch.
    "median_fraction_genome_altered": ("median fraction of genome altered (CIN)", "fraction"),
    "n_models_considered": ("models considered", "count"),
    "n_pathways_profiled": ("oncogenic pathways profiled", "count"),
    "n_score_sets": ("MAVE score sets", "count"),
    "n_variants_assayed": ("variants assayed", "count"),
    "n_splice_events": ("splice events", "count"),
    # descriptor-coverage sweep, cis + tractability batch.
    "n_drug_interactions": ("catalogued drug-gene interactions", "count"),
    "n_e3_ligases_literature": ("literature-reported E3 ligases", "count"),
    "n_models": ("cell-line models", "count"),
    "n_domains": ("annotated protein domains", "count"),
    "n_perturbing_drugs": ("perturbing drugs", "count"),
    # descriptor-coverage sweep, dependency/combination batch.
    "strongest_paralog_delta": ("strongest paralog dual-vs-single-KO buffering delta", "chronos delta"),
    "n_paralogs_annotated": ("annotated paralogs", "count"),
    "delta_chronos_deficient_vs_neutral": ("partner-deficient minus neutral CHRONOS", "chronos delta"),
    "partner_stratification_mannwhitney_q": ("partner-stratification Mann-Whitney q", "q-value"),
    "n_partner_deficient": ("partner-deficient cell lines", "count"),
    "n_consortia_corroborating": ("corroborating consortia", "count"),
    "n_partners": ("co-essential partners", "count"),
    "broad_n_lines": ("Broad DepMap cell lines", "count"),
    "n_positive_models": ("models expressing the target", "count"),
    # descriptor-coverage sweep, surface-modality-fit batch.
    "n_normal_tissues_presented": ("normal tissues presenting the peptide", "count"),
    "n_presented_peptides": ("presented peptides", "count"),
    "n_epitopes": ("catalogued epitopes", "count"),
    "n_exons": ("exons evaluated", "count"),
    "n_partners_tested": ("partner antigens tested", "count"),
    "n_partners_scanned": ("partner antigens scanned", "count"),
    "tm_pass_count": ("predicted transmembrane passes", "count"),
    "n_high": ("samples in the high stratum", "count"),
    # ClinGen dosage-sensitivity (dominant-loss dosage safety) + Open Targets gene-burden safety counts.
    "n_high_confidence": ("high-confidence ClinGen dosage rows", "count"),
    "n_total_rows": ("total curated rows for the gene", "count"),
    "n_autosomal_dominant": ("high-confidence autosomal-dominant rows", "count"),
    "n_autosomal_recessive": ("high-confidence autosomal-recessive rows", "count"),
    "min_pvalue": ("strongest gene-burden association p-value", "p-value"),
    "n_significant": ("significant gene-burden rows", "count"),
    "n_risk": ("significant risk-direction rows", "count"),
    "n_protect": ("significant protective-direction rows", "count"),
    # immune-context TIL (Saltz DL H&E) + surface-confirmation detection count.
    "median_til_percentage": ("median tumor-infiltrating-lymphocyte fraction", "%"),
    "median_number_of_clusters": ("median TIL spatial-cluster count", "count"),
    "n_samples": ("number of samples scored", "count"),
    "n_celllines_detected": ("cell lines with CSPA surface detection", "count"),
    "highest_tissue_median": ("highest normal-tissue median expression", "TPM"),
    # the PROTEIN counterparts of the two RNA normal-tissue levels above/below, kept adjacent to them so the
    # two arms of the same liability question stay in one vocabulary. Both say "protein" explicitly: an
    # unqualified "highest normal-tissue median" would be indistinguishable from the RNA arm in a bullet.
    "max_median_log2_abundance": ("highest normal-tissue median protein abundance", "log2 intensity"),
    "tphp_vital_organ_abundance": ("max protein abundance in a vital organ", "log2 intensity"),
    "log2fc_cell_a": ("tumor-vs-normal fold change", "log2FC"),
    "log2_fc": ("tumor-vs-adjacent fold change", "log2FC"),
    "protein_effect_size": ("tumor-vs-normal protein effect size", "effect size"),
    "malignant_detection_fraction": ("malignant-cell detection fraction", "fraction"),
    "fraction_tumor_above_normal_p95": ("tumor fraction above the normal 95th pct", "fraction"),
    "absolute_copies_per_cell": ("surface copies per cell", "copies/cell"),
    "max_detection_fraction": ("max normal cell-type detection fraction", "fraction"),
    "sc_normal_essential_max_detection_fraction": ("essential normal cell-type detection fraction", "fraction"),
    "max_mean_clr": ("peak normal-immune surface CLR-ADT", "CLR"),
    "rna_protein_r": ("RNA-protein correlation", "Pearson r"),
    "chembl_best_pchembl": ("best measured potency (ChEMBL)", "pChEMBL"),
    "median_log2auc": ("median PRISM compound activity", "log2 AUC"),
    "cd8_high_minus_low": ("CD8 infiltration delta (antigen high vs low)", "delta fraction"),
    # The label says "pan-cancer rank" because the cuts that band this value (0.084 / 0.113) are the Q1/Q3
    # of the CD8 share across the 33 TCGA studies — so `immune_hot` means top-quartile AMONG INDICATIONS,
    # not "heavily infiltrated", and it is not an ICI-response read (refractory PRAD 0.1312 lands hot while
    # ICI-approved BLCA/LUAD/LUSC land intermediate). Without that phrase a bare 0.11 beside a "hot" label
    # reads as an absolute density. Units stay "fraction": the number IS a leukocyte fraction; it is the
    # BAND around it that is rank-derived.
    "median_cd8_fraction": ("median CD8 share of leukocytes (banded by pan-cancer rank)", "fraction"),
    "log2_odds_ratio": ("co-mutation odds ratio", "log2 OR"),
    # ── ruler value_fields that predate the gloss-coverage fix (they were gauged but unglossed) ──
    "delta_chronos_hotspot_mut_vs_wt": ("dependency gap, hotspot-mutant vs wild-type", "delta CHRONOS"),
    "mut_fraction_missense": ("missense share of observed mutations", "fraction"),
    "mut_fraction_lof": ("loss-of-function share of observed mutations", "fraction"),
    "protein_effect_cohens_d": ("tumor-vs-normal protein effect (variance-standardized)", "Cohen's d"),
    "activity_z": ("pathway activity", "z-score"),
    "mean_gi": ("mean genetic interaction (dual-KO)", "GI score"),
    "mean_effect_shift": ("mean dependency shift under perturbation", "delta effect"),
    # ── significance metrics (shared q / p convention: lower = stronger) ──
    "q_value": ("FDR q-value", "q"),
    "q_value_cell_a": ("FDR q-value (tumor vs normal)", "q"),
    "bh_q_value": ("BH FDR q-value", "q"),
    "protein_bh_q_value": ("protein BH FDR q-value", "q"),
    "intogen_min_qvalue": ("IntOGen driver q-value", "q"),
    "gi_ttest_pvalue": ("dual-KO t-test p-value", "p"),
    "hotspot_mannwhitney_q": ("hotspot mutant-vs-WT Mann-Whitney q-value", "q"),
    "lineage_omnibus_p": ("cross-lineage omnibus p-value", "p"),
    "pli_score": ("gnomAD pLI (LoF-intolerance probability)", "pLI"),
    "frac_models_significant": ("fraction of models with a significant shift", "fraction"),
    # ── extra scalars ──
    "selectivity_index": ("dependency selectivity index", "index"),
    "mis_z_score": ("gnomAD missense z-score", "z-score"),
    "critical_organ_max": ("max expression in a critical organ", "TPM"),
    "tissue_breadth_fraction": ("normal-tissue breadth fraction", "fraction"),
    "best_spearman_r_crispr": ("best CRISPR concordance", "Spearman r"),
    "best_spearman_r_rnai": ("best RNAi concordance", "Spearman r"),
    "pearson_r_squared_rf": ("predictability (random forest)", "R2"),
    "median_chronos_hotspot_wildtype": ("median CHRONOS in wild-type lines", "CHRONOS"),
    "hotspot_dependency_base_rate": ("hotspot-mutant dependency base rate", "fraction"),
    "intogen_max_pct_samples": ("IntOGen max % samples mutated", "%"),
    "selectivity_allgene_percentile": ("selectivity percentile vs all genes", "%ile"),
    "allgene_percentile": ("pan-cancer expression rank vs all genes", "%ile"),
    "median_log2tpm": ("median tumor expression", "log2 TPM"),
    "median_log2tpm_panel": ("median cell-line expression (panel)", "log2 TPM"),
    "median_log2_abundance_panel": ("median cell-line protein abundance (panel)", "log2"),
    "fraction_elevated": ("fraction of cohorts with tumor elevation", "fraction"),
    "n_cohorts_elevated": ("cohorts with tumor elevation", "count"),
    "expression_purity_pearson_r": ("expression ↔ tumor-purity correlation", "Pearson r"),
    "fraction_moderate_strong": ("fraction of patients with moderate/strong IHC", "fraction"),
    "subtype_variance_explained": ("subtype variance explained (ε²)", "ε²"),
    "sig_all_cells": ("significant across all comparator cells", None),
    "normal_p95_log2tpm": ("normal-tissue 95th-percentile expression", "log2 TPM"),
    "distribution_overlap_tumor_normal": ("tumor-normal distribution overlap", "overlap"),
    "best_measured_potency_neglog_m": ("best measured potency", "-log10 M"),
    "alphafold_plddt_mean": ("AlphaFold mean pLDDT (model confidence)", "pLDDT"),
    "n_upstream_regulators": ("upstream regulators in the network", "count"),
    "n_downstream_effectors": ("downstream effectors in the network", "count"),
    "median_log2auc_across_compounds": ("median PRISM activity across compounds", "log2 AUC"),
    "strongest_partner_mean_gi": ("strongest partner mean genetic interaction", "GI score"),
    "strongest_co_target_shift": ("strongest co-target dependency shift", "delta effect"),
    "strongest_mediator_shift": ("strongest resistance-mediator shift", "delta effect"),
    # ── verdict-tail specs (2026-09-10) ──
    # genomic: stratified-dependency deltas + q, recurrence/drug-response
    "delta_chronos_amplified_vs_neutral": ("amplified − neutral CHRONOS delta", "CHRONOS"),
    "cn_stratification_mannwhitney_q": ("CN-stratified dependency Mann-Whitney q-value", "q"),
    "median_chronos_amplified": ("median CHRONOS in amplified lines", "CHRONOS"),
    "median_chronos_neutral": ("median CHRONOS in copy-neutral lines", "CHRONOS"),
    "cn_stratification_effect_size": ("CN-stratified dependency effect size", "effect size"),
    "delta_chronos_amp_expr_vs_rest": ("amp+overexpressed − rest CHRONOS delta", "CHRONOS"),
    "amp_expr_mannwhitney_q": ("amp-expr stratified dependency Mann-Whitney q-value", "q"),
    "median_chronos_amp_expr": ("median CHRONOS in amp+overexpressed lines", "CHRONOS"),
    "median_chronos_comparator": ("median CHRONOS in comparator lines", "CHRONOS"),
    "amp_expr_effect_size": ("amp-expr stratified dependency effect size", "effect size"),
    "delta_chronos_fusion_positive_vs_negative": ("fusion+ − fusion− CHRONOS delta", "CHRONOS"),
    "fusion_stratification_mannwhitney_q": ("fusion-stratified dependency Mann-Whitney q-value", "q"),
    "median_chronos_fusion_positive": ("median CHRONOS in fusion-positive lines", "CHRONOS"),
    "median_chronos_fusion_negative": ("median CHRONOS in fusion-negative lines", "CHRONOS"),
    "overall_mutation_frequency": ("overall mutation frequency", "fraction"),
    "pooled_driver_recurrence_percentile": ("pooled driver-recurrence percentile", "%ile"),
    "genie_mutation_frequency": ("GENIE mutation frequency", "fraction"),
    "n_mutated_pooled": ("pooled mutated samples", "count"),
    "delta_log2auc_mut_vs_wt": ("mutant − WT drug-response delta", "log2 AUC"),
    "drug_response_mannwhitney_q": ("mutant-vs-WT drug-response Mann-Whitney q-value", "q"),
    "drug_response_ppv": ("drug-response positive predictive value", "PPV"),
    "drug_response_effect_size": ("mutant-vs-WT drug-response effect size", "effect size"),
    "median_log2auc_mutant": ("median PRISM activity in mutant lines", "log2 AUC"),
    "fusion_frequency": ("fusion frequency in the indication", "fraction"),
    "genie_sv_frequency": ("GENIE structural-variant frequency", "fraction"),
    "genie_sv_recurrence_percentile": ("GENIE SV recurrence percentile", "%ile"),
    # ── genomic card-data rulers (2026-09-12): the three formerly spec-LESS verdict-bearing types ──
    # CN: the two arms of copy-number-distribution's classifier are NOT interchangeable (the deletion score
    # is shallow-inclusive and clears its cut for 60.1% of genes genome-wide vs 2.9% for amplification), so
    # each label says WHICH event and WHICH cohort — cell-line panel vs patient GISTIC — it is counting.
    "cn_recurrent_amplification_score": ("recurrent focal-amplification fraction (cell lines)", "fraction"),
    "cn_recurrent_deletion_score": ("recurrent deletion fraction, shallow-inclusive (cell lines)", "fraction"),
    "cn_fraction_high_amplification": ("cell-line fraction with high-level amplification", "fraction"),
    "cn_fraction_deep_deletion": ("cell-line fraction with deep (biallelic) deletion", "fraction"),
    "cn_median_panel": ("median relative copy number (panel)", "log2 ratio"),
    "patient_high_amp_fraction": ("patient fraction with high-level focal amplification (GISTIC +2)", "fraction"),
    "patient_homdel_fraction": ("patient fraction with homozygous deletion (GISTIC -2)", "fraction"),
    # variant-class spectrum: SHAPE of the somatic spectrum, not recurrence — the labels say "share of"
    # so a high value is not misread as evidence of selection (>=0.70 missense is the no-selection
    # expectation of the genetic code, and it fires for both negative controls).
    "mut_mutation_rate": ("share of panel cell lines mutated", "fraction"),
    "mut_n_cell_lines_total": ("cell lines evaluated for mutations", "count"),
    "mut_total_mutations": ("total mutations observed across the panel", "count"),
    # clonality
    "clonal_fraction": ("share of mutant samples with a clonal mutation", "fraction"),
    "median_ccf": ("median cancer-cell fraction of the mutation", "CCF"),
    # n_fields of the three new specs. The coverage test above checks effect/significance/omnibus/
    # extra_scalars but NOT n_field, so these are glossed by hand: the affix backstop turns the two
    # prefixed ones into "cn n cell lines evaluated" / "mut n cell lines mutated", which is worse than the
    # unprefixed fleet n_fields it handles acceptably (n_lethal -> "n lethal").
    "cn_n_cell_lines_evaluated": ("cell lines with copy-number data", "count"),
    "mut_n_cell_lines_mutated": ("cell lines carrying a mutation", "count"),
    "n_mutant_samples": ("mutant patient samples", "count"),
    # differentiation: survival log-rank + medians
    "logrank_p": ("survival log-rank p-value", "p"),
    "logrank_chi2": ("survival log-rank χ²", "χ²"),
    "logrank_df": ("survival log-rank degrees of freedom", "df"),
    "median_ostime_days": ("median overall survival", "days"),
    "median_ostime_high_days": ("median OS, high-expression arm", "days"),
    "median_ostime_low_days": ("median OS, low-expression arm", "days"),
    "median_ostime_mutated_days": ("median OS, mutated arm", "days"),
    "median_ostime_wildtype_days": ("median OS, wild-type arm", "days"),
    "n_admissible_strata": ("admissible survival strata", "count"),
    # combination: chemical synergy
    "strongest_synergy_delta_emax": ("strongest Bliss-excess synergy (ΔEmax)", "ΔEmax"),
    "strongest_synergy_partner_drug": ("strongest synergy partner drug", None),
    "strongest_synergy_partner_target": ("strongest synergy partner target", None),
    # cis-coherence: correlation r + p + slopes/deltas
    "methyl_expr_spearman_r": ("methylation ↔ expression correlation", "Spearman r"),
    "methyl_expr_spearman_p": ("methylation ↔ expression p-value", "p"),
    "subset_median_delta_log2tpm": ("hyper- vs unmethylated expression delta", "log2 TPM"),
    "methyl_expr_slope_log2tpm_per_methyl": ("methylation → expression slope", "log2 TPM/methyl"),
    "cn_expr_spearman_r": ("copy-number ↔ expression correlation", "Spearman r"),
    "cn_expr_spearman_p": ("copy-number ↔ expression p-value", "p"),
    "delta_log2tpm_amplified_vs_neutral": ("amplified − neutral expression delta", "log2 TPM"),
    "delta_log2tpm_methylated_vs_unmethylated": ("methylated − unmethylated expression delta", "log2 TPM"),
    "cn_prot_spearman_r": ("copy-number ↔ protein correlation", "Spearman r"),
    "cn_prot_spearman_p": ("copy-number ↔ protein p-value", "p"),
    "delta_log2abundance_amplified_vs_neutral": ("amplified − neutral protein delta", "log2"),
    "cn_prot_slope_log2abundance_per_cn": ("copy-number → protein slope", "log2/CN"),
    "pearson_r": ("expression ↔ dependency correlation", "Pearson r"),
    "pearson_p": ("expression ↔ dependency p-value", "p"),
    "delta_chronos_top_vs_bottom_quartile": ("top − bottom expression-quartile CHRONOS delta", "CHRONOS"),
    "chronos_at_high_expression": ("CHRONOS at high expression", "CHRONOS"),
    "chronos_at_low_expression": ("CHRONOS at low expression", "CHRONOS"),
    "protein_dependency_pearson_r": ("protein abundance ↔ dependency correlation", "Pearson r"),
    "protein_dependency_pearson_p": ("protein abundance ↔ dependency p-value", "p"),
    "n_dependent_models": ("dependent models", "count"),
    "protein_dependency_spearman_r": ("protein abundance ↔ dependency (Spearman)", "Spearman r"),
    # surface: therapeutic window + shedding
    "window_ratio_essential": ("tumor / worst essential-normal expression ratio", "ratio"),
    "max_essential_normal_tpm": ("max essential-normal-tissue expression", "TPM"),
    "window_ratio_full_normal": ("tumor / worst full-normal expression ratio", "ratio"),
    "max_full_normal_tpm": ("max full-normal-tissue expression", "TPM"),
    "media_mean_npx": ("measured shed antigen (Olink conditioned media)", "NPX"),
    "media_panel_high_npx": ("shed-panel high NPX", "NPX"),
    "serum_marker": ("clinical serum shed marker", None),
    # ── fleet n_fields / denominators (2026-09-12) ───────────────────────────────────────────────────
    # `n_field` is the DENOMINATOR the card's effect is read against, and the affix backstop only ever
    # supplies its units ("count") — never the noun. Un-glossed, `n_paired_models` renders "n paired
    # models = 41", which does not say paired on WHAT, so a reader cannot tell whether 41 is the whole
    # panel or the sliver with both layers measured. Labels therefore name the arm/cohort/pairing. Where
    # one field name serves cards with different units of analysis (n_mutant is cell lines in
    # mutation-drug-response but patient samples in mutation-stratified-surface, n_cell_lines_evaluated
    # spans 12 cards of which only some are paired) the label stays deliberately arm-neutral rather than
    # asserting a pairing that does not hold everywhere.
    "n_paired_models": ("cell-line models with both layers measured", "count"),
    "n_paired_models_cn_protein": ("cell lines with both relative CN and protein measured", "count"),
    "n_paired_samples": ("tumors with both expression and purity measured", "count"),
    "n_paired_tumors": ("tumors with both RNA and protein measured", "count"),
    "n_patients": ("patients with survival follow-up", "count"),
    "n_patients_joined": ("patients in the antigen × T-cell join", "count"),
    "n_patients_cn_expr": ("patients with both copy number and expression", "count"),
    "n_patients_total": ("patients in the detection denominator", "count"),
    "n_cell_lines_evaluated": ("cell lines evaluated", "count"),
    "n_cell_lines_panel": ("cell lines in the dependency panel", "count"),
    "n_tumor_samples": ("tumor samples evaluated", "count"),
    "n_amplified": ("amplified cell lines (stratified arm)", "count"),
    "n_amplified_overexpressed": ("cell lines both amplified and overexpressing", "count"),
    "n_hotspot_mutant": ("cell lines carrying the target hotspot mutation", "count"),
    "n_fusion_positive": ("cell lines carrying a fusion of the target", "count"),
    "n_mutant": ("mutant cell lines or patient samples (stratified arm)", "count"),
    "n_samples_with_fusion": ("samples with the fusion detected", "count"),
    "n_covered_pooled": ("samples covered, pooled across cohorts", "count"),
    "n_depmap_carriers": ("DepMap cell lines carrying the event", "count"),
    "n_interpreted_variants": ("single-variant profiles with curated evidence", "count"),
    "n_pathogenic_germline": ("pathogenic / likely-pathogenic germline variants", "count"),
    "n_lethal": ("lethal-labelled knockout phenotype rows", "count"),
    "n_cohorts_tested": ("cohorts the target was quantified in", "count"),
    "n_tissues_detectable": ("normal tissues with detectable expression", "count"),
    # normal_tissue_protein_abundance (TPHP DIA-MS). Each label names the ARM (protein, not RNA) and the
    # COHORT (adult normal tissues vs vital organs), because the RNA arm counts tissues too and a bare
    # "tissues detected" cannot be told apart from it in a narrator bullet.
    "n_adult_tissues_detected": ("adult normal tissues with detected protein (TPHP DIA-MS)", "count"),
    "n_adult_tissues_above_abundance_floor": (
        "adult normal tissues whose median protein abundance clears the floor",
        "count",
    ),
    "n_vital_organs_above_abundance_floor": (
        "vital organs whose median protein abundance clears the floor",
        "count",
    ),
    "n_essential_tissues_with_expression": ("essential normal tissues with expression", "count"),
    "n_celltypes_surface_displaying": ("normal cell types displaying the target on the surface", "count"),
    "n_synergy_partners": ("partner drugs passing the synergy threshold", "count"),
    "sl_partner_count": ("synthetic-lethal partners passing threshold", "count"),
    "media_n_lines_detected": ("cell lines with a detected conditioned-media value", "count"),
}

# ── affix backstop for the raw L3 tail (fields NOT in the salience registry) ─────────────────────────
# Ordered (substr, units) rules, first match wins; the label is the humanized field, the units come from
# the matched affix. Keeps the long tail (~99 non-salience numeric_anchors) readable without a per-field
# author entry. Substring (not regex) for speed + legibility.
_AFFIX_RULES: list = [
    ("chronos", "CHRONOS"),
    ("log2fc", "log2FC"),
    ("log2_fc", "log2FC"),
    ("log2auc", "log2 AUC"),
    ("log2tpm", "log2 TPM"),
    ("percentile", "%ile"),
    ("pchembl", "pChEMBL"),
    ("neglog_m", "-log10 M"),
    ("loeuf", "LOEUF"),
    ("log2abundance", "log2"),
    ("log2_abundance", "log2"),
    ("odds_ratio", "log2 OR"),
    ("effect_size", "effect size"),
    ("_q_value", "q"),
    ("_qvalue", "q"),
    ("_pvalue", "p"),
    ("_p_value", "p"),
    ("fraction", "fraction"),
    ("_frac", "fraction"),
    ("r_squared", "R2"),
    ("z_score", "z-score"),
    ("_tpm", "TPM"),
]

# TOKEN rules: same idea, but matched against the `_`-split tokens instead of the raw string. Reserved for
# short affixes that occur INSIDE unrelated words — `pli` was a substring rule and so claimed pLI units for
# every field naming an am-PLI-fied arm or a s-PLI-ce event (20 real contract summary_fields, 20/20 wrong:
# n_amplified, patient_amplified_fraction, splice_exon_skip_class, modality_implication_basis, …). Audited
# the other 20 substring rules by hand at the same time; `pli` is the only one that mislabels.
_TOKEN_RULES: list = [
    ("pli", "pLI"),
]

# Fields whose VALUE is a class/label/prose, not a number: ANY units we attach is nonsense
# ("splicing_dysregulation_class = exon_skip_dominant (pLI)"). Checked BEFORE the affix rules, because the
# affix matches the numeric noun buried in a categorical name (`allgene_percentile_class` → '%ile',
# `subtype_effect_size_class` → 'effect size', `pan_essential_fraction_call` → 'fraction'). Grounded in the
# contracts, not guessed: every field a card declares in `summary_fields_vocabulary` (i.e. every field with
# an enumerated value set) ends in one of these, and test_display_gloss pins that none of them gets units.
# NOT a suffix list for counts — `n_enriched_lineages` is a real count and keeps its 'count'.
_CATEGORICAL_SUFFIXES = ("_class", "_basis", "_call", "_context")


def _affix_units(field: str) -> Optional[str]:
    f = field.lower()
    if f.endswith(_CATEGORICAL_SUFFIXES):
        return None
    tokens = set(f.split("_"))
    for tok, units in _TOKEN_RULES:
        if tok in tokens:
            return units
    for sub, units in _AFFIX_RULES:
        if sub in f:
            return units
    # suffix-only conventions (avoid the substring false-positives of "_p" / "_r" inside a word)
    if f.endswith("_q"):
        return "q"
    if f.endswith("_p"):
        return "p"
    if f.endswith("_r") or f.endswith("_rho"):
        return "correlation r"
    if f.startswith("n_") or f.endswith("_n") or "count" in f:
        return "count"
    if f.startswith("median_"):
        return None
    return None


def humanize(s) -> str:
    """snake_case / SCREAMING_CASE -> 'Sentence case' (the class-value reader for the 'Reads:' line)."""
    if s is None:
        return ""
    return re.sub(r"_+", " ", str(s)).strip().capitalize()


def gloss(field) -> tuple:
    """(label, units_hint) for a metric field. METRIC_GLOSS -> affix backstop -> snake->space fallback."""
    if not field:
        return ("", None)
    if field in METRIC_GLOSS:
        return METRIC_GLOSS[field]
    return (str(field).replace("_", " "), _affix_units(str(field)))


def _fmt_num(v):
    """Compact scalar display (sig-figs for tiny p/q, short decimal otherwise). Mirrors ir._fmt_num."""
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return "" if v is None else str(v)
    if isinstance(v, float) and v != 0 and abs(v) < 1e-3:
        return f"{v:.2e}"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def _anchor_by_role(gv: dict) -> dict:
    out = {}
    for a in (gv.get("frame") or {}).get("anchors") or []:
        if isinstance(a, dict) and a.get("role"):
            out[a["role"]] = a
    return out


def _past_or_short(x, cut, direction) -> Optional[str]:
    """'past' when x is on the STRONGER/worse side of the cut (per direction), else 'short of'. None when
    either value is missing/non-numeric."""
    if (
        not isinstance(x, (int, float))
        or isinstance(x, bool)
        or not isinstance(cut, (int, float))
        or isinstance(cut, bool)
    ):
        return None
    d = _norm_direction(direction)
    if d in ("lower_is_stronger", "lower_is_worse"):
        return "past" if x <= cut else "short of"
    if d in ("higher_is_stronger", "higher_is_worse"):
        return "past" if x >= cut else "short of"
    return None


def _anchor_label(a: dict) -> str:
    return str(a.get("label") or a.get("role") or "").replace("_", " ")


def gauge_string(gv: dict) -> str:
    """A plain-language, PRE-GAUGED reading of one interpretation ruler (a gauged_value), e.g.
    'median CHRONOS in hotspot-mutant lines -1.73 vs hotspot wildtype -0.59 (Δ-1.14, past the -0.5 cut)'
    or 'between controls — median CRISPR gene-effect (CHRONOS) -0.46 between non essential floor -0.04 and
    pan essential ceiling -1.50, short of the -0.5 cut'. The words backend for text/md/pptx + the narrator;
    the HTML backend draws the visual ruler. '' when gv is empty."""
    if not isinstance(gv, dict) or gv.get("value") is None:
        return ""
    label, _units = gloss(gv.get("metric"))
    value = gv.get("value")
    head = f"{label} {_fmt_num(value)}" if label else _fmt_num(value)
    frame = gv.get("frame") or {}
    kind = frame.get("kind")
    anchors = _anchor_by_role(gv)
    direction = gv.get("direction")
    cut = anchors.get("cut") or {}

    if kind == "comparator_delta":
        seg = head
        comp = anchors.get("comparator") or {}
        if comp.get("value") is not None:
            seg += f" vs {_anchor_label(comp)} {_fmt_num(comp['value'])}"
        dtc = gv.get("distance_to_cut")
        tail = []
        if dtc is not None:
            tail.append(f"Δ{_fmt_num(dtc)}")
        ps = _past_or_short(dtc, cut.get("value"), direction)  # the cut is on the DELTA here
        if ps and cut.get("value") is not None:
            tail.append(f"{ps} the {_fmt_num(cut['value'])} cut")
        if tail:
            seg += f" ({', '.join(tail)})"
        return seg

    if kind == "floor_cut_ceiling":
        seg = head
        fc = []
        for role in ("floor", "ceiling"):
            a = anchors.get(role) or {}
            if a.get("value") is not None:
                fc.append(f"{_anchor_label(a)} {_fmt_num(a['value'])}")
        if fc:
            seg += " between " + " and ".join(fc)
        ps = _past_or_short(value, cut.get("value"), direction)
        if ps and cut.get("value") is not None:
            seg += f", {ps} the {_fmt_num(cut['value'])} cut"
        pos = gv.get("position")
        return f"{humanize(pos).lower()} — {seg}" if pos else seg

    if kind == "distance_to_cut":
        seg = head
        ps = _past_or_short(value, cut.get("value"), direction)
        if ps and cut.get("value") is not None:
            seg += f", {ps} the {_fmt_num(cut['value'])} cut"
        pos = gv.get("position")  # lead with the banded call when present (mirrors floor_cut_ceiling)
        return f"{humanize(pos).lower()} — {seg}" if pos else seg

    if kind == "graded_band":
        # value read against a ladder of >=2 cut anchors: name the STRONGEST cut it clears (e.g. "past the
        # 1.5 strong cut"), else the nearest one it falls short of ("short of the 0.5 modest cut").
        seg = head
        cuts = [
            a
            for a in (frame.get("anchors") or [])
            if a.get("role") == "cut"
            and isinstance(a.get("value"), (int, float))
            and not isinstance(a.get("value"), bool)
        ]
        stronger_first = _norm_direction(direction) in ("lower_is_stronger", "lower_is_worse")
        cuts.sort(key=lambda a: a["value"], reverse=stronger_first)  # weakest → strongest cut
        passed = [a for a in cuts if _past_or_short(value, a["value"], direction) == "past"]
        if passed:
            top = passed[-1]
            seg += f", past the {_fmt_num(top['value'])} {_anchor_label(top)} cut"
        elif cuts:
            seg += f", short of the {_fmt_num(cuts[0]['value'])} {_anchor_label(cuts[0])} cut"
        pos = gv.get("position")
        return f"{humanize(pos).lower()} — {seg}" if pos else seg

    if kind == "count_of_total":
        total = anchors.get("total") or {}
        seg = f"{_fmt_num(value)} of {_fmt_num(total['value'])}" if total.get("value") is not None else _fmt_num(value)
        if gv.get("scale"):
            seg += f" {gv['scale']}"
        ps = _past_or_short(value, cut.get("value"), direction)
        if ps and cut.get("value") is not None:
            seg += f", {ps} the {_fmt_num(cut['value'])} cut"
        pos = gv.get("position")
        return f"{humanize(pos).lower()} — {seg}" if pos else seg

    if kind == "percentile":
        return f"{_fmt_num(value)}th percentile ({label})" if label else f"{_fmt_num(value)}th percentile"

    if kind == "cohort_percentile":
        # "{value} {scale} — stronger than 82% of 210 known targets" (position pre-composed by _project_frame)
        seg = f"{_fmt_num(value)}"
        if gv.get("scale"):
            seg += f" {gv['scale']}"
        pos = gv.get("position")
        return f"{seg} — {pos}" if pos else seg

    # no / unknown frame → the glossed reading alone
    return metric_reading(gv.get("metric"), value, direction)


def metric_reading(field, value, direction=None, include_direction: bool = True) -> str:
    """A plain-language reading of one metric: '{label} = {value} ({units}; {direction_phrase})'.
    Omits the parenthetical parts that are absent, so a unitless flag still reads cleanly."""
    label, units = gloss(field)
    out = f"{label} = {_fmt_num(value)}" if label else _fmt_num(value)
    extras = []
    if units:
        extras.append(units)
    dp = direction_phrase(direction) if include_direction else None
    if dp:
        extras.append(dp)
    if extras:
        out += f" ({'; '.join(extras)})"
    return out


# ── card DESCRIPTION join (report_render-side; the builder stays pure) ───────────────────────────────
@functools.lru_cache(maxsize=1024)
def card_question(card_id: str) -> Optional[str]:
    """The raw `question:` contract field for a card (the plain 'what is this card'). None when the card
    is absent/unreadable or carries no question. Fail-soft (a description is display sugar; never break a
    render). Mirrors _skills_common.card_input_manifest_ids' cached card.yaml read."""
    try:
        from _skills_common.paths import target_contracts_root

        p = target_contracts_root() / "cards" / f"{card_id}.card.yaml"
        if not p.exists():
            return None
        spec = yaml.safe_load(p.read_text()) or {}
        q = spec.get("question")
        return q if isinstance(q, str) and q.strip() else None
    except Exception:  # noqa: BLE001 — display-only; never break the render
        return None


@functools.lru_cache(maxsize=256)
def indication_label(indication: Optional[str]) -> Optional[str]:
    """A human display label for an indication code (crosswalk display_name), else the code itself."""
    if not indication:
        return None
    ind = indication.upper()
    try:
        from _skills_common.evidence_salience import _crosswalk_entries

        for e in _crosswalk_entries():
            codes = {str(e.get("canonical_code") or "").upper(), str(e.get("oncotree_code") or "").upper()}
            if ind in codes and isinstance(e.get("display_name"), str):
                return e["display_name"]
    except Exception:  # noqa: BLE001
        pass
    return indication


def fill_placeholders(text: Optional[str], target: Optional[str] = None, indication: Optional[str] = None):
    """Substitute the request into a corpus-authored template — `{target.symbol}` / `{indication.label}`
    (plus the historical `{target}` / `{indication}` spellings) — collapsing the whitespace an empty
    substitution leaves behind. None/empty in → None out.

    Authored prose in this fleet is templated in TWO places: the 148 card contracts carrying a
    `question:` (read by `card_description`) and the per-skill `questions.yaml` registry (read by
    `evidence_graph.build_evidence_graph`). Only the card path ever substituted, so the skill path
    shipped the literal `{target.symbol}` all the way to the dashboard, `target_profile.md` and
    `nomination.json`. Both paths now share this one helper, so a placeholder can only be missed by a
    caller that never interpolates at all — and `test_no_unresolved_placeholders` asserts the absence of
    that failure across the whole corpus rather than the presence of the fix in one path.

    Deliberately an exact-token replace, not `str.format`: the prose contains unrelated braces (units,
    ranges, set notation) that `format` would raise on."""
    if not text:
        return None
    tsym = target or ""
    ilab = indication_label(indication) or (indication or "")
    text = text.replace("{target.symbol}", tsym).replace("{indication.label}", ilab)
    text = text.replace("{target}", tsym).replace("{indication}", ilab)
    return re.sub(r"\s{2,}", " ", text).strip() or None


def card_description(card_id: str, target: Optional[str] = None, indication: Optional[str] = None) -> Optional[str]:
    """The card `question:` with {target.symbol} / {indication.label} filled in (never left as a raw
    placeholder — an un-interpolated description reads broken). None when the card carries no question."""
    return fill_placeholders(card_question(card_id), target, indication)


__all__ = [
    "direction_phrase",
    "gloss",
    "metric_reading",
    "gauge_string",
    "humanize",
    "METRIC_GLOSS",
    "card_question",
    "card_description",
    "fill_placeholders",
    "indication_label",
]
