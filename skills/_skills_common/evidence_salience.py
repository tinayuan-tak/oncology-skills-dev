"""evidence_salience — per-measurement_type salience specs + indication→stratum resolution.

Drives the capsule's `_top_k_strata` selector and the evidence_graph's `key_evidence` promotion so the
DECISIVE data point per card (the indication stratum's effect + its q, the cross-stratum omnibus, the
load-bearing categorical verdict) is carried, not a generic pan-panel scalar. Seeded from the Stage-0
audit (docs/EVIDENCE_GRAPH_SALIENCE.md §3), one spec per ~20 verdict-bearing measurement_types (NOT per
149 cards). A measurement_type with no spec falls back to the existing list-of-dicts heuristic + no
omnibus/pinned-significance — graceful degradation, never an error.

A SALIENCE_SPEC is a dict with (all optional):
  strata_array         summary field holding the per-stratum list-of-dicts (the significance-bearing one)
  effect_field         the row's (or a scalar's) load-bearing effect metric
  significance_field   the row's q/p field, or a scalar significance field (q_value / mannwhitney_q / pli_score)
  omnibus_field        a scalar cross-stratum test (lineage_omnibus_p / subtype_omnibus_p); pinned EXPLICITLY
                       because these fail the _ANCHOR_HINTS p_value substring heuristic
  n_field              a scalar sample-size field
  direction            display hint: lower_is_stronger | higher_is_stronger | higher_is_worse | ...
  categorical          decisive STRING fields the numeric selectors can't carry (fit_class, constraint_class)
  extra_scalars        additional decisive scalars to surface when there is no strata array

Additive, deterministic, VERDICT-INERT. Mirrors the reader_spec precedent in subgroup_derivation.
"""
from __future__ import annotations

import functools
import math
from pathlib import Path


def sig_round(v, figs: int = 4):
    """Round a float to `figs` SIGNIFICANT figures (byte-stable). Unlike a fixed-decimal round, this
    preserves tiny significance values — round(3.8e-16, 4) == 0.0 would destroy a q-value, whereas
    sig_round(3.8e-16) == 3.8e-16. Non-floats / 0 / non-finite pass through unchanged."""
    if not isinstance(v, float) or v == 0 or not math.isfinite(v):
        return v
    return float(f"{v:.{figs}g}")

# ── per-measurement_type salience specs (seeded from Stage-0 §3; grow as new types are audited) ──────
SALIENCE_SPECS: dict = {
    # functional-requirement (§3.1) — the worked anchor
    "crispr_lof_dependency": {
        "strata_array": "enriched_lineages", "effect_field": "median_chronos", "significance_field": "q_value",
        "omnibus_field": "lineage_omnibus_p", "n_field": "n_cell_lines_panel", "direction": "lower_is_stronger",
        "categorical": ["dep_control_position_class"], "extra_scalars": ["selectivity_index"],
        # STAGE-2 PILOT ruler: floor_cut_ceiling. The gauged value is the PANEL median (median_chronos_panel)
        # — the field dep_control_position_class was banded on — NOT the effect_field stratum value
        # (median_chronos), so the read-verbatim position never contradicts a recomputed band.
        "reference_frame": {
            "kind": "floor_cut_ceiling", "value_field": "median_chronos_panel", "scale": "chronos",
            "position_field": "dep_control_position_class",
            "anchors": [{"role": "floor", "field": "dep_control_non_essential_floor", "label": "non_essential_floor"},
                        {"role": "ceiling", "field": "dep_control_pan_essential_ceiling", "label": "pan_essential_ceiling"}],
            "cut": {"card_id": "pan-cancer-crispr-dependency-distribution",
                    "threshold": "moderately_dependent_threshold_chronos", "label": "dependency_cut"}}},
    "rnai_lof_dependency": {
        "effect_field": "rnai_median_dep_score", "direction": "lower_is_stronger",
        "categorical": ["rnai_dependency_class"]},
    "crispr_rnai_concordance": {
        "effect_field": "fraction_agree", "direction": "higher_is_stronger"},
    "chemical_genetic_concordance": {
        "strata_array": "per_compound_concordance", "effect_field": "spearman_r_crispr", "label_field": "drug_name",
        "direction": "higher_is_stronger", "categorical": ["crispr_prism_concordance_class"],
        "extra_scalars": ["best_spearman_r_crispr", "best_spearman_r_rnai"]},
    "dependency_predictability": {
        "strata_array": "per_lineage_predictability", "effect_field": "r2", "direction": "higher_is_stronger",
        "categorical": ["predictability_class", "pred_dominant_feature_class"], "extra_scalars": ["pearson_r_squared_rf"]},

    # on-target-safety-liability (§3.2) — the liability anchor (scalar-effect, count-driven)
    "gnomad_lof_constraint": {
        "effect_field": "loeuf_score", "significance_field": "pli_score", "direction": "lower_is_stronger",
        "categorical": ["constraint_class"], "extra_scalars": ["mis_z_score"],
        # STAGE-2 ruler: distance_to_cut on LOEUF (LOWER = more LoF-constrained). value + position READ
        # VERBATIM (constraint_class), cut single-sourced from the card's high_loeuf threshold (0.45,
        # gnomAD v4-recommended) — no contracts round-trip needed (the named threshold already exists).
        # First SAFETY-axis reference_frame; the scalar loeuf now reads gauged ("LOEUF 0.32, past the 0.45
        # constraint cut") instead of bare. DISPLAY-ONLY / verdict-INERT.
        "reference_frame": {
            "kind": "distance_to_cut", "value_field": "loeuf_score", "scale": "loeuf",
            "position_field": "constraint_class",
            "cut": {"card_id": "gnomad-lof-constraint", "threshold": "high_loeuf",
                    "label": "loeuf_constraint_cut"}}},
    "normal_tissue_rna_breadth": {
        "effect_field": "highest_tissue_median", "n_field": "n_tissues_detectable", "direction": "higher_is_worse",
        "categorical": ["liability_class", "highest_tissue", "critical_organ_argmax"],
        "extra_scalars": ["critical_organ_max", "tissue_breadth_fraction"]},
    "normal_tissue_protein_breadth": {
        "categorical": ["normal_tissue_breadth_class", "hpa_tissue_specificity"],
        "n_field": "n_essential_tissues_with_expression"},
    "clinvar_germline_pathogenicity_safety": {
        "n_field": "n_pathogenic_germline", "categorical": ["clinvar_pathogenicity_class"]},
    "mouse_ko_phenotype_safety": {
        "n_field": "n_lethal", "categorical": ["ko_phenotype_class", "impc_ko_phenotype_class", "evidence_tier"]},
    "alteration_role": {
        "significance_field": "intogen_min_qvalue", "categorical": ["alteration_role"],
        "extra_scalars": ["intogen_max_pct_samples"]},
    "mutation_stratified_dependency": {
        "effect_field": "median_chronos_hotspot_mutant", "n_field": "n_hotspot_mutant",
        "significance_field": "hotspot_mannwhitney_q",   # coverage gap fill (q exists in summary_fields)
        "direction": "lower_is_stronger",
        "categorical": ["mutation_stratification_class", "stratification_direction"],
        "extra_scalars": ["median_chronos_hotspot_wildtype", "hotspot_dependency_base_rate"],
        # STAGE-2 PILOT ruler: comparator_delta — mutant median vs WT baseline, delta gauged against the
        # strong-effect delta cut. value/comparator/distance all NAME summary fields (never recomputed).
        "reference_frame": {
            "kind": "comparator_delta", "value_field": "median_chronos_hotspot_mutant", "scale": "chronos",
            "distance_field": "delta_chronos_hotspot_mut_vs_wt",
            "anchors": [{"role": "comparator", "field": "median_chronos_hotspot_wildtype",
                         "label": "hotspot_wildtype"}],
            "cut": {"card_id": "mutation-stratified-dependency", "threshold": "strong_effect_delta",
                    "label": "strong_effect_delta", "on": "distance"}}},

    # tumor-selectivity (§3.5)
    "tumor_vs_normal_selectivity": {
        "effect_field": "log2fc_cell_a", "significance_field": "q_value_cell_a", "direction": "higher_is_stronger",
        "categorical": ["selectivity_class", "comparator_concordance"],
        "extra_scalars": ["selectivity_allgene_percentile", "sig_all_cells"]},
    "surface_density": {
        "effect_field": "absolute_copies_per_cell", "direction": "higher_is_stronger",
        "categorical": ["surface_density_class", "density_floor_verdict", "is_tce_viable", "is_adc_high_payload_viable"]},
    "tumor_vs_normal_percentile_crossing": {
        "effect_field": "fraction_tumor_above_normal_p95", "direction": "higher_is_stronger",
        "extra_scalars": ["normal_p95_log2tpm", "distribution_overlap_tumor_normal"]},

    # tumor-presence (§3.4)
    "sc_tumor_celltype_expression": {
        "effect_field": "malignant_detection_fraction", "direction": "higher_is_stronger",
        "categorical": ["sc_expression_class", "stromal_confound_class", "caf_vs_malignant_class", "tce_antigen_escape_class"]},
    "tumor_vs_adjacent_expression": {
        "effect_field": "log2_fc", "significance_field": "q_value", "direction": "higher_is_stronger",
        "categorical": ["expression_call_class"],
        # STAGE-2 PILOT ruler #3 (first distance_to_cut consumer): tumor-vs-adjacent log2FC gauged against
        # the elevated-call cut (modest_upregulation_log2fc = 0.5, the flat→elevated boundary — mirrors the
        # crispr pilot gauging the PRIMARY call threshold). value NAMES log2_fc; the band
        # (expression_call_class) is READ VERBATIM as the position so the ordinal never contradicts the
        # marker; the cut single-sources from the card thresholds (contracts-first: b47f5d4).
        "reference_frame": {
            "kind": "distance_to_cut", "value_field": "log2_fc", "scale": "log2FC",
            "position_field": "expression_call_class",
            "cut": {"card_id": "tumor-rna-vs-adjacent", "threshold": "modest_upregulation_log2fc",
                    "label": "elevated_cut"}}},
    "tumor_protein_abundance": {
        "effect_field": "protein_effect_size", "significance_field": "protein_bh_q_value", "direction": "higher_is_stronger",
        "categorical": ["protein_expression_class"]},

    # surface-modality-fit (§3.6)
    "sc_normal_surface_protein": {
        "effect_field": "max_detection_fraction", "n_field": "n_cell_types_above_20pct", "direction": "higher_is_worse",
        "categorical": ["sc_normal_safety_essential_class"]},
    "rna_protein_concordance": {
        "effect_field": "rna_protein_r", "n_field": "n_paired_tumors", "direction": "higher_is_stronger"},

    # tractability-small-molecule (§3.7)
    "prism_compound_activity": {
        "strata_array": "top_compounds", "effect_field": "median_log2auc", "label_field": "drug_name",
        "direction": "lower_is_stronger", "categorical": ["prism_activity_class"]},
    "measured_potency_tractability": {
        "effect_field": "chembl_best_pchembl", "direction": "higher_is_stronger",
        "categorical": ["measured_bioactivity_class", "chembl_clinical_phase_class"],
        "extra_scalars": ["best_measured_potency_neglog_m"]},
    "structure_druggability": {
        "categorical": ["structural_ligandability_class", "hotspot_pocket_adjacency_call", "alphafold_confidence_class"],
        "extra_scalars": ["alphafold_plddt_mean"]},

    # mechanism-and-pharmacology (§3.8)
    "signaling_network_mechanism": {
        "categorical": ["network_class"], "extra_scalars": ["n_upstream_regulators", "n_downstream_effectors"]},
    "pathway_activity_context": {
        "strata_array": "per_pathway", "effect_field": "activity_z", "label_field": "pathway",
        "direction": "higher_is_stronger", "categorical": ["pathway_activity_class"]},

    # combination-and-vulnerability (§3.9)
    "combinatorial_ko_dependency": {
        "strata_array": "ranked_partner_table", "effect_field": "mean_gi", "significance_field": "gi_ttest_pvalue",
        "label_field": "partner_gene", "direction": "lower_is_stronger", "categorical": ["combinatorial_dependency_class"]},
    "drug_anchored_combination": {
        "strata_array": "top_co_targets", "effect_field": "mean_effect_shift", "significance_field": "frac_models_significant",
        "label_field": "co_target_gene", "direction": "lower_is_stronger", "categorical": ["combination_opportunity_class"]},
    "drug_anchored_resistance": {
        "strata_array": "top_resistance_mediators", "effect_field": "mean_effect_shift", "significance_field": "frac_models_significant",
        "label_field": "rescuer_gene", "direction": "higher_is_stronger", "categorical": ["resistance_emergence_class"]},

    # immune-context (§3.10)
    "immune_context": {
        "effect_field": "cd8_high_minus_low", "n_field": "n_patients_joined", "direction": "higher_is_stronger",
        "categorical": ["immune_context_class", "antigen_conditioned_call", "antigen_high_immune_context_class"]},

    # differentiation-landscape (§3.11)
    "mutation_cooccurrence": {
        "strata_array": "top_cooccurring", "effect_field": "log2_odds_ratio", "significance_field": "bh_q_value",
        "label_field": "partner_gene", "direction": "higher_is_stronger", "categorical": ["cooccurrence_class"]},
}

# ── subtype-axis salience (§3.16): the parallel omnibus-per-axis / per-subgroup shapes ───────────────
# Keyed loosely by the summary fields a subtype-stratified card carries; the key_evidence builder tries
# each in order and uses the first present. Verdict-inert; null when the subtype axis is absent.
SUBTYPE_SPECS: dict = {
    # presence: subtype_omnibus_by_axis (multi-axis omnibus) + per_subgroup_metrics
    "subtype_omnibus_by_axis": {
        "axis_array": "subtype_omnibus_by_axis", "axis_field": "axis", "omnibus_field": "subtype_omnibus_p",
        "which_separate_field": "which_subtypes_separate", "driving_axis_field": "subtype_omnibus_driving_axis",
        "restriction_class_field": "subtype_stratification_class",
        "subgroup_array": "per_subgroup_metrics", "subgroup_label_field": "stratum_id",
        "subgroup_effect_field": "median_log2tpm", "subgroup_n_field": "n_tumor_samples"},
    # dependency: per_subgroup_metrics with median_chronos + a cross-subgroup delta
    "per_subgroup_metrics": {
        "subgroup_array": "per_subgroup_metrics", "subgroup_label_field": "stratum",
        "subgroup_effect_field": "median_chronos", "subgroup_n_field": "subgroup_n",
        "restriction_class_field": "subgroup_stratification_class"},
    # survival: per_axis_association with logrank_p
    "per_axis_association": {
        "axis_array": "per_axis_association", "axis_field": "axis", "omnibus_field": "logrank_p",
        "restriction_class_field": "subtype_survival_association_class"},
}


def spec_for(measurement_type):
    return SALIENCE_SPECS.get(measurement_type) if measurement_type else None


# ── Stage-2 interpretation rulers (key_evidence.interpretation[]) ─────────────────────────────────────
# build_interpretation projects a spec's `reference_frame` into a list of gauged_value rulers. It NAMES
# summary fields (never recomputes), reads ordinal position VERBATIM from a resolver *_class field, and
# single-sources the cut from the driving card's `thresholds:` block. This is the ONLY card.yaml read
# behind interpretation and it lives HERE (the salience/authoring layer) — evidence_graph.build_evidence_
# graph stays a pure projection that DELEGATES to this function, so the builder does zero card.yaml reads.
def _inum(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _read_num_field(field, summary, cap):
    """A named NUMERIC field: summary first, then the capsule (numeric_anchors, then n_basis)."""
    if not field:
        return None
    if isinstance(summary, dict) and _inum(summary.get(field)) is not None:
        return summary[field]
    cap = cap or {}
    for a in (cap.get("numeric_anchors") or []):
        if isinstance(a, dict) and a.get("metric") == field and _inum(a.get("value")) is not None:
            return a["value"]
    nb = cap.get("n_basis")
    if isinstance(nb, dict) and _inum(nb.get(field)) is not None:
        return nb[field]
    return None


def _read_str_field(field, summary, cap):
    """A named STRING field (e.g. a resolver *_class): summary first, then capsule categorical_anchors."""
    if not field:
        return None
    if isinstance(summary, dict) and isinstance(summary.get(field), str):
        return summary[field]
    for a in ((cap or {}).get("categorical_anchors") or []):
        if isinstance(a, dict) and a.get("field") == field and isinstance(a.get("value"), str):
            return a["value"]
    return None


@functools.lru_cache(maxsize=512)
def contract_threshold(card_id, key, contracts_repo: str | None = None):
    """A single numeric value from a card's `thresholds:` block (the single-sourced cut). Cached; fail-soft
    → None (a missing cut just drops the cut anchor — never breaks the graph)."""
    if not card_id or not key:
        return None
    try:
        import yaml
        from _skills_common.paths import target_contracts_root
        base = Path(contracts_repo) if contracts_repo else target_contracts_root()
        p = Path(base) / "cards" / f"{card_id}.card.yaml"
        if not p.exists():
            return None
        spec = yaml.safe_load(p.read_text()) or {}
        return _inum((spec.get("thresholds") or {}).get(key))
    except Exception:  # noqa: BLE001 — display-only; never break the graph
        return None


def build_interpretation(cap: dict, summary: dict, spec: dict | None = None,
                         card_id: str | None = None, contracts_repo: str | None = None) -> list:
    """Project spec['reference_frame'] → key_evidence.interpretation[] (list of gauged_value). Deterministic
    (sig_round every number; absent layer omitted, never null-filled); [] when no frame or no value present.
    Enforces 'no bare number': a value is emitted only with a non-null scale."""
    cap = cap or {}
    summary = summary or {}
    spec = spec or {}
    rf = spec.get("reference_frame")
    if not isinstance(rf, dict):
        return []
    value = _read_num_field(rf.get("value_field"), summary, cap)
    scale = rf.get("scale")
    if value is None or not scale:            # no bare frame without a value+scale
        return []
    gv = {"metric": rf.get("value_field"), "value": sig_round(value), "scale": scale,
          "direction": spec.get("direction"), "frame": {"kind": rf.get("kind"), "anchors": []}}
    pos = _read_str_field(rf.get("position_field"), summary, cap)   # READ VERBATIM (never recomputed)
    if pos is not None:
        gv["position"] = pos
        gv["position_source"] = rf.get("position_field")
    dist = _read_num_field(rf.get("distance_field"), summary, cap)  # PREFER the summary's own delta
    if dist is not None:
        gv["distance_to_cut"] = sig_round(dist)
    anchors = []
    for a in (rf.get("anchors") or []):
        if not isinstance(a, dict):
            continue
        av = _read_num_field(a.get("field"), summary, cap)
        if av is not None:
            anchors.append({"role": a.get("role"), "label": a.get("label"), "value": sig_round(av)})
    cut = rf.get("cut")
    if isinstance(cut, dict):
        cv = contract_threshold(cut.get("card_id") or card_id, cut.get("threshold"), contracts_repo)
        if cv is not None:
            anchors.append({"role": "cut", "label": cut.get("label") or cut.get("threshold"),
                            "value": sig_round(cv)})
    gv["frame"]["anchors"] = anchors
    return [gv]


# ── indication → acceptable stratum labels (the canonical INDICATION_TO_* crosswalk) ─────────────────
# Resolves the INDICATION strata row by the framework's own vocabulary instead of the substring match
# that silently drops it (COADREAD ⊄ lineage "Bowel"; LUAD ⊄ "Lung"). Reads the canonical
# target-contracts/vocabularies/indication_crosswalk.yaml (the same file scope.py loads) — depmap_lineage,
# depmap_oncotree_lineage, oncotree_code, gtex_normal_tissue, tcga_studies (+ TCGA study bare codes).
# Fail-soft: crosswalk missing/unreadable → just the indication code itself (the substring fallback still
# applies downstream), so this NEVER breaks the capsule.
@functools.lru_cache(maxsize=None)
def _crosswalk_entries(contracts_repo: str | None = None) -> tuple:
    try:
        import yaml
        if contracts_repo:
            base = Path(contracts_repo)
        else:
            from _skills_common.scope import DEFAULT_CONTRACTS_REPO
            base = DEFAULT_CONTRACTS_REPO
        path = Path(base) / "vocabularies" / "indication_crosswalk.yaml"
        if not path.exists():
            return ()
        data = yaml.safe_load(path.read_text()) or {}
        return tuple(e for e in (data.get("indications") or []) if isinstance(e, dict))
    except Exception:  # noqa: BLE001 — display-only; never break the capsule
        return ()


@functools.lru_cache(maxsize=None)
def indication_stratum_aliases(indication: str | None, contracts_repo: str | None = None) -> frozenset:
    """The set of stratum labels that count as THIS indication's row (upper-cased), from the crosswalk."""
    if not indication:
        return frozenset()
    ind = indication.upper()
    out = {ind}
    for e in _crosswalk_entries(contracts_repo):
        codes = {str(e.get("canonical_code") or "").upper(), str(e.get("oncotree_code") or "").upper()}
        if ind not in codes:
            continue
        for key in ("canonical_code", "oncotree_code", "depmap_lineage", "depmap_oncotree_lineage",
                    "gtex_normal_tissue"):
            v = e.get(key)
            if isinstance(v, str) and v:
                out.add(v.upper())
        for study in (e.get("tcga_studies") or []):
            if isinstance(study, str) and study:
                out.add(study.upper())                      # TCGA-COAD
                out.add(study.upper().replace("TCGA-", ""))  # COAD
    return frozenset(out)


__all__ = ["SALIENCE_SPECS", "SUBTYPE_SPECS", "spec_for", "indication_stratum_aliases", "sig_round",
           "build_interpretation", "contract_threshold"]
