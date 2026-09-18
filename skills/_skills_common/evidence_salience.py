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


def round_keep_tiny(v, decimals: int = 4, figs: int = 4):
    """Fixed-decimal round that never ANNIHILATES a tiny-but-nonzero value.

    `round(v, 4)` is the right display rounding for effects, medians and counts, but it maps every
    |v| < 5e-5 to 0.0 — and a p/q-value is exactly that shape. Measured on 944 real decisions before this
    existed: **980 capsule `numeric_anchors` values across 10 measurement_types were sitting at 0.0 with a
    nonzero source field** (`intogen_min_qvalue` 8.33e-49 → 0.0, `min_pvalue` 1.77e-25 → 0.0,
    `hotspot_mannwhitney_q` 2.03e-07 → 0.0), so the number displayed as the card's decisive datum asserted
    "no effect / not significant" about the most significant results in the corpus.

    The obvious repair — swap in `sig_round` — is wrong in the OTHER direction, and that was measured too:
    `sig_round(12345.678, 4)` is 12350.0, which would have degraded 172 `surface_density`
    `estimated_copies_per_cell_*` anchors. Significant-figure rounding is only better for small magnitudes.

    So: take the fixed-decimal result, and fall back to significant figures ONLY where fixed-decimal
    destroyed the value. Consequences worth stating, because they are what makes this safe to land:
      * a GENUINE zero stays 0.0 (675 anchors in that corpus are correctly 0.0 — a real
        `patient_homdel_fraction` of 0 must not become a tiny float);
      * every value that already round-trips is returned BYTE-IDENTICALLY, so this is not a re-rounding of
        the corpus — it only repairs annihilated values;
      * still deterministic, so `_prompt_hash` stays reproducible for identical inputs (its contract is
        determinism, not any particular constant).
    """
    if not isinstance(v, float) or v == 0 or not math.isfinite(v):
        return v
    r = round(v, decimals)
    return sig_round(v, figs) if r == 0 else r


# ── REACH OF A `reference_frame` — read this before writing "DISPLAY-ONLY" on one ────────────────────
# This file annotated its frames "DISPLAY-ONLY / verdict-INERT" at 12 sites with no authority named at any
# of them. Measured 2026-09-14 against trunk, HALF of that label is backwards. A frame has FOUR consumers
# and exactly ONE of them is inert:
#
#   1. DISPLAY       build_interpretation() below projects every frame into key_evidence.interpretation[].
#   2. ATLAS  *LIVE* feature_vectoriser.numeric_feature_specs() mints `{mt}::num::{value_field}` from the
#                    PRIMARY frame (rf[0]) ONLY — 32 columns from 77 frames on 35 axes. Those columns are
#                    FROZEN in the target-archetype atlas, and every shipped cohort_percentile moves when
#                    they change.
#   3. CLAIM RECORD  claim_record.magnitude_from_interpretation() re-reads interp[0] as the record's
#                    {value, scale, distance_to_cut}, so the PRIMARY frame IS the record's magnitude.
#   4. GATES  *INERT* nothing: zero resolvers, zero vetoes, zero dispatcher reads. This half is TRUE.
#
# So "verdict-INERT" is right and "display-only" is FALSE for any primary frame on an atlas-live axis. What
# decides it is PRIMARY vs SECONDARY, which none of those 12 comments stated:
#   - rf[0] with no `atlas_numeric: False`  -> ATLAS-LIVE + CLAIM-LIVE. Never call it display-only.
#   - an APPENDED / secondary frame, rf[1:] -> display-only, genuinely. Say so, and say WHY (it is secondary).
#   - `atlas_numeric: False` on rf[0]       -> display-only, and that flag is the only honest way to say so.
#     ADDING it to a shipped axis DELETES a frozen column at the next re-freeze, silently: atlas_health
#     compares the artifact against itself, so a self-consistent narrowing reads as green.
#
# Frames are also injected by HELPERS further down, so "which frames does this axis carry" is NOT answerable
# by reading one spec block: _BATCH_DISTANCE_TO_CUT_METERS injects the PRIMARY for 4 axes (all 4 mint frozen
# columns), while _SECONDARY_FRAMES and the fleet cohort roll APPEND. A literal-string scan of these blocks
# therefore undercounts the framed axes — it read 31 against a live 35.
#
# AUTHORITY: skills/tests/test_reference_frame_governance.py, invariant 5 — a reader-role census pinned to
# EXACT equality (any new consumer of the key reds until it is classified), a fleet-wide display + claim-
# record projection assertion, and an `atlas_numeric: False` ratchet with a zero-residual population check.
# Verdict-inertness is not a safety argument by itself: see the note beside _UNRANKABLE_SCALES below, where
# a defect "survived because it was verdict-inert, so it still rendered — just wrong."
#
# ── per-measurement_type salience specs (seeded from Stage-0 §3; grow as new types are audited) ──────
SALIENCE_SPECS: dict = {
    # functional-requirement (§3.1) — the worked anchor
    "crispr_lof_dependency": {
        "strata_array": "enriched_lineages",
        "effect_field": "median_chronos",
        "significance_field": "q_value",
        "omnibus_field": "lineage_omnibus_p",
        "n_field": "n_cell_lines_panel",
        "direction": "lower_is_stronger",
        "categorical": ["dep_control_position_class"],
        "extra_scalars": ["selectivity_index"],
        # STAGE-2 PILOT ruler: floor_cut_ceiling. The gauged value is the PANEL median (median_chronos_panel)
        # — the field dep_control_position_class was banded on — NOT the effect_field stratum value
        # (median_chronos), so the read-verbatim position never contradicts a recomputed band.
        "reference_frame": [
            {
                "kind": "floor_cut_ceiling",
                "value_field": "median_chronos_panel",
                "scale": "chronos",
                "position_field": "dep_control_position_class",
                "anchors": [
                    {"role": "floor", "field": "dep_control_non_essential_floor", "label": "non_essential_floor"},
                    {"role": "ceiling", "field": "dep_control_pan_essential_ceiling", "label": "pan_essential_ceiling"},
                ],
                "cut": {
                    "card_id": "pan-cancer-crispr-dependency-distribution",
                    "threshold": "moderately_dependent_threshold_chronos",
                    "label": "dependency_cut",
                },
            },
            # + cohort ruler: panel-median dependency vs the 213 known targets.
            {
                "kind": "cohort_percentile",
                "value_field": "median_chronos_panel",
                "scale": "chronos",
                "cohort_key": "crispr_lof_dependency::num::median_chronos_panel",
            },
        ],
    },
    "rnai_lof_dependency": {
        "effect_field": "rnai_median_dep_score",
        "direction": "lower_is_stronger",
        "categorical": ["rnai_dependency_class"],
    },
    "crispr_rnai_concordance": {"effect_field": "fraction_agree", "direction": "higher_is_stronger"},
    "chemical_genetic_concordance": {
        "strata_array": "per_compound_concordance",
        "effect_field": "spearman_r_crispr",
        "label_field": "drug_name",
        "direction": "higher_is_stronger",
        "categorical": ["crispr_prism_concordance_class"],
        "extra_scalars": ["best_spearman_r_crispr", "best_spearman_r_rnai"],
        # gauge the BEST-compound CRISPR-PRISM concordance (top-level scalar) on a graded band (weak 0.10 /
        # strong 0.30). The per-compound rhos live in an array; best_spearman_r_crispr is the card-level max.
        "reference_frame": {
            "kind": "graded_band",
            "value_field": "best_spearman_r_crispr",
            "scale": "spearman_r",
            "position_field": "crispr_prism_concordance_class",
            "cuts": [
                {"card_id": "prism-crispr-concordance", "threshold": "concordance_weak_spearman", "label": "weak"},
                {"card_id": "prism-crispr-concordance", "threshold": "concordance_strong_spearman", "label": "strong"},
            ],
        },
    },
    "dependency_predictability": {
        "strata_array": "per_lineage_predictability",
        "effect_field": "r2",
        "direction": "higher_is_stronger",
        "categorical": ["predictability_class", "pred_dominant_feature_class"],
        "extra_scalars": ["pearson_r_squared_rf"],
        # gauge the DepMap-parity r² (top-level scalar) vs the high-confidence floor (0.16). position = the
        # predictability_class band READ VERBATIM.
        "reference_frame": {
            "kind": "distance_to_cut",
            "value_field": "pearson_r_squared_rf",
            "scale": "r2",
            "position_field": "predictability_class",
            "cut": {
                "card_id": "dependency-predictability",
                "threshold": "r2_depmap_high_conf",
                "label": "high_conf_cut",
            },
        },
    },
    # on-target-safety-liability (§3.2) — the liability anchor (scalar-effect, count-driven)
    "gnomad_lof_constraint": {
        "effect_field": "loeuf_score",
        "significance_field": "pli_score",
        "direction": "lower_is_stronger",
        "categorical": ["constraint_class"],
        "extra_scalars": ["mis_z_score"],
        # STAGE-2 ruler: distance_to_cut on LOEUF (LOWER = more LoF-constrained). value + position READ
        # VERBATIM (constraint_class), cut single-sourced from the card's high_loeuf threshold (0.45,
        # gnomAD v4-recommended) — no contracts round-trip needed (the named threshold already exists).
        # First SAFETY-axis reference_frame; the scalar loeuf now reads gauged ("LOEUF 0.32, past the 0.45
        # constraint cut") instead of bare. verdict-INERT (no gate reads it) but NOT display-only: rf[0] mints
        # the FROZEN atlas column gnomad_lof_constraint::num::loeuf_score. See REACH OF A `reference_frame`.
        "reference_frame": [
            {
                "kind": "distance_to_cut",
                "value_field": "loeuf_score",
                "scale": "loeuf",
                "position_field": "constraint_class",
                "cut": {"card_id": "gnomad-lof-constraint", "threshold": "high_loeuf", "label": "loeuf_constraint_cut"},
            },
            # + cohort ruler: where this LOEUF sits among the 210 known targets that carry it.
            {
                "kind": "cohort_percentile",
                "value_field": "loeuf_score",
                "scale": "loeuf",
                "cohort_key": "gnomad_lof_constraint::num::loeuf_score",
            },
        ],
    },
    "normal_tissue_rna_breadth": {
        "effect_field": "highest_tissue_median",
        "n_field": "n_tissues_detectable",
        "direction": "higher_is_worse",
        "categorical": ["liability_class", "highest_tissue", "critical_organ_argmax"],
        "extra_scalars": ["critical_organ_max", "tissue_breadth_fraction"],
    },
    # The TPHP DIA-MS PROTEIN arm of the same normal-tissue liability question normal_tissue_rna_breadth
    # answers on RNA, so it mirrors that spec field for field (peak level + tissue count + liability ladder)
    # — the two arms must read in ONE vocabulary or a reader cannot tell a protein liability from an RNA one.
    # Distinct from normal_tissue_protein_breadth below, which is the HPA antibody breadth card.
    #
    # VERDICT-BEARING as of target-contracts #767: the selectivity KILL ladder lives in the resolver's
    # `post_resolver_clamp`, a keypath the rule_role_partition generator never read, so this card's rules were
    # misfiled `display` (= verdict-inert) while resolver rungs minted verdicts from them. Un-misfiling them
    # promoted this measurement_type into the gating set, which is what obliges a spec here.
    #
    # NO reference_frame, DELIBERATELY — and not for want of a cut (the card carries a clean
    # moderate 10 / broad 35 tissue-count ladder). The fleet loop at the bottom of this module appends a
    # `cohort_percentile` frame to EVERY spec carrying a numeric frame, and numeric_feature_specs() mints an
    # atlas column from it, so authoring a frame here would silently register a new atlas feature that only
    # a re-freeze can populate. That belongs to the atlas workstream. The categorical liability ladder IS
    # the ruler meanwhile (gaugeable via `categorical`, per invariant 1).
    "normal_tissue_protein_abundance": {
        "effect_field": "max_median_log2_abundance",
        "n_field": "n_adult_tissues_detected",
        "direction": "higher_is_worse",
        "categorical": [
            "tphp_normal_protein_liability_class",
            "normal_protein_breadth_class",
            "tphp_vital_organ_liability_class",
            "highest_abundance_tissue",
            "highest_abundance_tissue_class",
        ],
        "extra_scalars": [
            "tphp_vital_organ_abundance",
            "n_adult_tissues_above_abundance_floor",
            "n_vital_organs_above_abundance_floor",
        ],
    },
    "normal_tissue_protein_breadth": {
        # essential_tissue_flag (Gap-A): rule-read by normal-tissue-essential-{bite-killer,adc-antibody-opposing}
        # + the safety warning — a {present, unknown, absent} class with no descriptor. Categorical.
        "categorical": ["normal_tissue_breadth_class", "hpa_tissue_specificity", "essential_tissue_flag"],
        "n_field": "n_essential_tissues_with_expression",
    },
    "clinvar_germline_pathogenicity_safety": {
        "n_field": "n_pathogenic_germline",
        "categorical": ["clinvar_pathogenicity_class"],
    },
    "mouse_ko_phenotype_safety": {
        "n_field": "n_lethal",
        "categorical": ["ko_phenotype_class", "impc_ko_phenotype_class", "evidence_tier"],
    },
    # human-genetics HOLD-axis safety cards (descriptor-coverage mint, 2026-09-18). Both were on the
    # _UNSPECCED_VERDICT_BEARING_DEBT allowlist in test_reference_frame_governance (gating cards whose
    # numbers reached no descriptor); this mint gives them one and REMOVES them from the debt (the ratchet
    # shrinks 9 -> 7). Neither has a `thresholds:` block, so there is no single-sourced numeric cut and the
    # CLASS is the ruler — categorical + n_field (+ significance for burden), no reference_frame / no atlas
    # column, mirroring clinvar_germline_pathogenicity_safety + mouse_ko_phenotype_safety above. Adding a
    # SALIENCE_SPEC is verdict-INERT (no gate reads salience), so the resolver golden stays byte-stable.
    "dosage_sensitivity_safety": {
        "n_field": "n_high_confidence",
        "categorical": ["dosage_sensitivity_class", "germline_inheritance_mode", "top_confidence"],
        "extra_scalars": ["n_total_rows", "n_autosomal_dominant", "n_autosomal_recessive"],
    },
    "human_genetic_safety": {
        "significance_field": "min_pvalue",
        "n_field": "n_significant",
        "categorical": ["burden_safety_class"],
        "extra_scalars": ["n_total_rows", "n_risk", "n_protect"],
    },
    # alteration-role had NO numeric anchor at all: no effect_field, no n_field, and its one number sat in
    # `significance_field`, which the capsule's numeric selectors do not promote — measured as class=None +
    # ZERO anchors on 26 of 26 genomic review-panel runs, for the card that supplies the driver ROLE the
    # resolver's role rungs key on. The ruler gauges IntOGen's best q against the card's own driver_qvalue
    # cut, which is the only numeric cut the contract declares.
    #
    # atlas_numeric: False — the value is degenerate as a phenotype coordinate. Every gene with a driver
    # call has q at or below 0.05 and most sit many orders of magnitude below it (KRAS 1e-30), while genes
    # WITHOUT one have no value at all, so the ::mask already carries the whole signal and the signed value
    # would contribute a near-constant column. Displayed as a ruler, kept out of the geometry.
    "alteration_role": {
        "significance_field": "intogen_min_qvalue",
        "direction": "lower_is_stronger",
        "categorical": ["alteration_role", "functional_direction", "oncokb_gene_type"],
        "extra_scalars": ["intogen_max_pct_samples"],
        "reference_frame": {
            "kind": "distance_to_cut",
            "value_field": "intogen_min_qvalue",
            "scale": "qvalue",
            "atlas_numeric": False,
            # no position_field ON PURPOSE: alteration_role is banded on the OncoKB x IntOGen role JOIN,
            # not on this q-value, so reading it as the gauge's ordinal position would assert a
            # correspondence the contract does not make.
            "cut": {"card_id": "alteration-role", "threshold": "driver_qvalue", "label": "driver_tier_cut"},
        },
    },
    "mutation_stratified_dependency": {
        "effect_field": "median_chronos_hotspot_mutant",
        "n_field": "n_hotspot_mutant",
        "significance_field": "hotspot_mannwhitney_q",  # coverage gap fill (q exists in summary_fields)
        "direction": "lower_is_stronger",
        "categorical": ["mutation_stratification_class", "stratification_direction"],
        "extra_scalars": ["median_chronos_hotspot_wildtype", "hotspot_dependency_base_rate"],
        # STAGE-2 PILOT ruler: comparator_delta — mutant median vs WT baseline, delta gauged against the
        # strong-effect delta cut. value/comparator/distance all NAME summary fields (never recomputed).
        "reference_frame": {
            "kind": "comparator_delta",
            "value_field": "median_chronos_hotspot_mutant",
            "scale": "chronos",
            "distance_field": "delta_chronos_hotspot_mut_vs_wt",
            "anchors": [
                {"role": "comparator", "field": "median_chronos_hotspot_wildtype", "label": "hotspot_wildtype"}
            ],
            "cut": {
                "card_id": "mutation-stratified-dependency",
                "threshold": "strong_effect_delta",
                "label": "strong_effect_delta",
                "on": "distance",
            },
        },
    },
    # tumor-selectivity (§3.5)
    "tumor_vs_normal_selectivity": {
        "effect_field": "log2fc_cell_a",
        "significance_field": "q_value_cell_a",
        "direction": "higher_is_stronger",
        # TC#780's two VOCABULARY-BEARING selectivity fields, gauged as categoricals. The 2-vs-4 split
        # of that contract's six new fields is DECLARED, not judged: exactly these two carry an
        # `outputs.summary_fields_vocabulary` entry (4 and 3 members respectively), and a field with no
        # vocabulary has nothing to be salient over — so a ruler is the right reader here and the wrong
        # one for the other four. Those four are display-only and their remedy is a contracts-side
        # `capsule:` declaration, NOT a second reader; see test_field_disposition.py's aperture block.
        # ★ Added as SCORING design, not to move the aperture counter. Both are also creditable by a
        # capsule declaration, so this earns no counter movement once that lands — which is the point:
        # wiring a ruler to move a number is the failure this file's own :479 warning names.
        "categorical": [
            "selectivity_class",
            "comparator_concordance",
            "selectivity_evidence_independence",
            "selectivity_substrate_basis",
        ],
        "extra_scalars": ["selectivity_allgene_percentile", "sig_all_cells"],
        # STAGE-2 ruler: distance_to_cut on the tumor-vs-normal window (HIGHER log2FC = more selective).
        # position = selectivity_class READ VERBATIM; cut single-sourced from the card's existing
        # modest_selectivity_log2fc threshold (0.5, the selective/not boundary). verdict-INERT (no gate reads
        # it) but NOT display-only: rf[0] mints the FROZEN atlas column
        # tumor_vs_normal_selectivity::num::log2fc_cell_a. See REACH OF A `reference_frame`.
        "reference_frame": {
            "kind": "distance_to_cut",
            "value_field": "log2fc_cell_a",
            "scale": "log2FC",
            "position_field": "selectivity_class",
            "cut": {
                "card_id": "tumor-vs-normal-selectivity",
                "threshold": "modest_selectivity_log2fc",
                "label": "selective_cut",
            },
        },
    },
    "surface_density": {
        "effect_field": "absolute_copies_per_cell",
        "direction": "higher_is_stronger",
        # is_tce_viable / is_adc_high_payload_viable dropped: contract #783 types them `boolean`; a *_class
        # (string) read yields None, so they were never in the categorical projection anyway.
        "categorical": [
            "surface_density_class",
            "density_floor_verdict",
        ],
        # STAGE-2 ruler: distance_to_cut on absolute surface density (HIGHER copies/cell = more modality-viable).
        # position = surface_density_class READ VERBATIM; cut = the card's tce_viability_copies_per_cell floor
        # (1000/cell, Slaga 2018). SPARSE field (grade-E often null) → the ruler simply omits when absent.
        "reference_frame": {
            "kind": "distance_to_cut",
            "value_field": "absolute_copies_per_cell",
            "scale": "copies_per_cell",
            "position_field": "surface_density_class",
            "cut": {
                "card_id": "surface-abundance-density",
                "threshold": "tce_viability_copies_per_cell",
                "label": "tce_viability_floor",
            },
        },
    },
    "tumor_vs_normal_percentile_crossing": {
        "effect_field": "fraction_tumor_above_normal_p95",
        "direction": "higher_is_stronger",
        "extra_scalars": ["normal_p95_log2tpm", "distribution_overlap_tumor_normal"],
        # STAGE-2 ruler: distance_to_cut on the population-separation fraction (HIGHER = more tumors clear the
        # normal p95). No categorical on this spec → value+cut only (still gaugeable via direction). Cut =
        # the card's strong_frac_p95 threshold (0.5). verdict-INERT (no gate reads it) but NOT display-only:
        # rf[0] mints the FROZEN atlas column
        # tumor_vs_normal_percentile_crossing::num::fraction_tumor_above_normal_p95. See REACH OF A
        # `reference_frame`.
        "reference_frame": {
            "kind": "distance_to_cut",
            "value_field": "fraction_tumor_above_normal_p95",
            "scale": "fraction",
            "cut": {
                "card_id": "tumor-vs-normal-percentile-crossing",
                "threshold": "strong_frac_p95",
                "label": "population_crossing_cut",
            },
        },
    },
    # tumor-presence (§3.4)
    "sc_tumor_celltype_expression": {
        "effect_field": "malignant_detection_fraction",
        "direction": "higher_is_stronger",
        "categorical": [
            "sc_expression_class",
            "stromal_confound_class",
            "caf_vs_malignant_class",
            "tce_antigen_escape_class",
        ],
        # STAGE-2 ruler: distance_to_cut on malignant-compartment detection (HIGHER = more malignant-intrinsic
        # presence). position = sc_expression_class READ VERBATIM; cut = the card's malignant_broadly_detected_min
        # (0.5 = detected in >=50% of malignant cells). verdict-INERT (no gate reads it) but NOT display-only:
        # rf[0] mints the FROZEN atlas column sc_tumor_celltype_expression::num::malignant_detection_fraction.
        # (The comparator_delta appended in _SECONDARY_FRAMES is rf[1] and IS display-only.) See REACH OF A
        # `reference_frame`.
        "reference_frame": {
            "kind": "distance_to_cut",
            "value_field": "malignant_detection_fraction",
            "scale": "detection_fraction",
            "position_field": "sc_expression_class",
            "cut": {
                "card_id": "tumor-scrna-celltype-expression",
                "threshold": "malignant_broadly_detected_min",
                "label": "broadly_detected_cut",
            },
        },
    },
    # tumor-presence NORMAL-SAFETY sc card (Gap-A mint, 2026-09-18): sc-normal-celltype-expression drove
    # the ONLY modality-varying edge in the whole run (sc_normal_safety_essential_class) yet had NO spec,
    # so its liability class + expression band shipped with no descriptor/label/direction. Mint one here.
    # DIRECTION higher_is_worse (mirrors sibling sc_normal_surface_protein): a NORMAL-tissue detection
    # fraction — higher normal-cell detection = MORE safety liability, the inverse of the tumor sibling
    # sc_tumor_celltype_expression (higher_is_stronger). Getting this sign wrong inverts the ruler on a
    # SAFETY axis, so it carries a sign test. graded_band: position = sc_normal_safety_essential_class READ
    # VERBATIM; the three ascending cuts (not_expressed 0.01 < moderate 0.2 < high 0.5) ARE the card's own
    # liability cutpoints, single-sourced from its thresholds — declaring this frame is simultaneously how
    # the derivation obligation is satisfied for this card, in a vocabulary (graded_band) that already
    # exists. verdict-INERT (no gate reads salience). See REACH OF A `reference_frame`.
    "sc_normal_celltype_expression": {
        "effect_field": "sc_normal_essential_max_detection_fraction",
        "direction": "higher_is_worse",
        "categorical": [
            "sc_normal_safety_essential_class",
            "sc_normal_expression_class",
            "sc_normal_abundance_class",
        ],
        "reference_frame": {
            "kind": "graded_band",
            # DISPLAY-ONLY: the atlas is deferred out of go-live, and a numeric PRIMARY frame otherwise
            # mints a frozen atlas column (a one-way door ratcheted in test_reference_frame_governance
            # invariant 5) + a cohort_percentile append. The Gap-A goal is a descriptor + a display ruler,
            # both delivered without an atlas feature. Flip this to omit the flag if/when the atlas returns.
            "atlas_numeric": False,
            "value_field": "sc_normal_essential_max_detection_fraction",
            "scale": "detection_fraction",
            "position_field": "sc_normal_safety_essential_class",
            "cuts": [
                {
                    "card_id": "sc-normal-celltype-expression",
                    "threshold": "not_expressed_ceiling",
                    "label": "not_expressed",
                },
                {
                    "card_id": "sc-normal-celltype-expression",
                    "threshold": "moderate_liability_median_det",
                    "label": "moderate",
                },
                {"card_id": "sc-normal-celltype-expression", "threshold": "high_liability_median_det", "label": "high"},
            ],
        },
    },
    # on-target-safety NORMAL-genetics s_het card (descriptor-coverage mint, 2026-09-18):
    # shet-lof-intolerance emits shet_class + a continuous s_het (GeneBayes, Zeng 2024) — the CONTINUOUS
    # complement to gnomad_lof_constraint's binary LOEUF/pLI — but had NO spec, so shet_score + its CI +
    # LoF counts landed unclassified with no label/units/direction. Mint one here.
    # DIRECTION higher_is_worse (mirrors gnomad_lof_constraint's liability framing + sc_normal): a HIGHER
    # s_het = MORE dominant-LoF-constrained = a full-KO (degrader / RNA-therapeutic) safety concern. The
    # card's own note says "Higher = more intolerant." Getting this sign wrong inverts a SAFETY ruler, so
    # it carries a sign test. graded_band: position = shet_class READ VERBATIM; the two ascending cuts
    # (moderate 0.01 < high 0.1) ARE the card's own intolerance cutpoints, single-sourced from its
    # thresholds. verdict-INERT (Phase 1: fires no rule, drives no safety rung — a corroboration of the
    # constraint call), so the resolver golden is byte-stable. See REACH OF A `reference_frame`.
    "shet_lof_selection": {
        "effect_field": "shet_score",
        "direction": "higher_is_worse",
        "categorical": ["shet_class"],
        "extra_scalars": ["shet_lower_95", "shet_upper_95", "obs_lof_count", "exp_lof_count"],
        "reference_frame": {
            "kind": "graded_band",
            # DISPLAY-ONLY: atlas deferred out of go-live (see sc_normal above); a numeric PRIMARY frame
            # otherwise mints a frozen atlas column. Descriptor + display ruler delivered without one.
            "atlas_numeric": False,
            "value_field": "shet_score",
            "scale": "shet",
            "position_field": "shet_class",
            "cuts": [
                {
                    "card_id": "shet-lof-intolerance",
                    "threshold": "moderate_intolerance_shet",
                    "label": "moderate_intolerance",
                },
                {
                    "card_id": "shet-lof-intolerance",
                    "threshold": "high_intolerance_shet",
                    "label": "high_intolerance",
                },
            ],
        },
    },
    # immune-context TIL card (descriptor-coverage mint, 2026-09-18): tcga-til-fraction-saltz emits
    # til_fraction_class + a continuous median_til_percentage (Saltz DL H&E TIL maps) with no spec, so the
    # fraction + its companions landed unclassified. DIRECTION higher_is_stronger (more infiltration = a
    # stronger immune/TCE-effector signal; the card calls til_high "strongly infiltrated") — carries a sign
    # test. graded_band: position = til_fraction_class READ VERBATIM; two ascending cuts (intermediate 2.0 <
    # high 5.0) single-sourced from the card's thresholds. atlas_numeric False AND an _ATLAS_NUMERIC_OPTOUT
    # entry because median_til_percentage is an INDICATION property (identical for every target in a cohort,
    # like immune_context) — a target atlas column would phrase an indication property as a target one.
    # verdict-INERT (no gating rule keys on it). See REACH OF A `reference_frame`.
    "spatial_til_fraction": {
        "effect_field": "median_til_percentage",
        "direction": "higher_is_stronger",
        "categorical": ["til_fraction_class"],
        "extra_scalars": ["median_number_of_clusters", "n_samples"],
        "reference_frame": {
            "kind": "graded_band",
            "atlas_numeric": False,
            "value_field": "median_til_percentage",
            "scale": "til_percentage",
            "position_field": "til_fraction_class",
            "cuts": [
                {
                    "card_id": "tcga-til-fraction-saltz",
                    "threshold": "til_intermediate_percentage",
                    "label": "til_intermediate",
                },
                {"card_id": "tcga-til-fraction-saltz", "threshold": "til_high_percentage", "label": "til_high"},
            ],
        },
    },
    # surface-confirmation card (descriptor-coverage mint, 2026-09-18): protein-surface-evidence emits
    # surface_confirmation_class + HPA/CSPA companion classes + a detection count, all unclassified. No
    # numeric value field carries a single-sourced cut (no thresholds:), so the CLASS is the ruler — a
    # categorical + n_field spec (no reference_frame, no atlas column), mirroring normal_tissue_protein_breadth.
    # verdict-INERT (no gating rule keys on it; the surface-intrinsic rules that read the class are context).
    "surface_confirmation": {
        "n_field": "n_celllines_detected",
        "categorical": [
            "surface_confirmation_class",
            "hpa_if_surface_class",
            "surface_multimodal_support",
            "cspa_category",
        ],
    },
    # ── descriptor-coverage sweep, surface-modality-fit batch (2026-09-18) ──────────────────────────
    # pmhc_presentation: GRADED on a COUNT — more normal tissues presenting the peptide = broader
    # on-target/off-tumor SAFETY liability for a pMHC TCE (higher_is_worse). cuts bin
    # n_normal_tissues_presented into pmhc_presentation_class (restricted <=3 .. broad >=19).
    # DEBT-CLEARING (removed from _UNSPECCED_VERDICT_BEARING_DEBT).
    "pmhc_presentation": {
        "effect_field": "n_normal_tissues_presented",
        "direction": "higher_is_worse",
        "categorical": ["pmhc_presentation_class"],
        "n_field": "n_presented_peptides",
        "reference_frame": {
            "kind": "graded_band",
            "atlas_numeric": False,
            "value_field": "n_normal_tissues_presented",
            "scale": "normal_tissue_count",
            "position_field": "pmhc_presentation_class",
            "cuts": [
                {
                    "card_id": "pmhc-presentation",
                    "threshold": "restricted_max_tissues",
                    "label": "restricted_presentation",
                },
                {"card_id": "pmhc-presentation", "threshold": "broad_min_tissues", "label": "broadly_presented_normal"},
            ],
        },
    },
    # categorical-only (the CLASS is the ruler; no single-sourced numeric cut) — surface family:
    "pmhc_epitope_evidence": {  # DEBT-CLEARING
        "n_field": "n_epitopes",
        "categorical": ["epitope_evidence_class"],
    },
    "exon_window": {  # DEBT-CLEARING (thresholds live method-side; no card cut to single-source)
        "n_field": "n_exons",
        "categorical": ["exon_window_class"],
    },
    "antigen_pair_coexpression": {
        "n_field": "n_partners_tested",
        "categorical": ["samecell_avidity_class", "window_verdict"],
    },
    "antigen_pair_selectivity": {
        "n_field": "n_partners_scanned",
        "categorical": ["best_and_call_class"],
    },
    "cd_antigen_backbone": {
        "categorical": ["cd_antigen_backbone_class"],
    },
    "surface_topology": {
        "n_field": "tm_pass_count",
        "categorical": [
            "topology_class",
            "ecd_engineerability_class",
            "ecd_orientation",
            "isoform_selective_warning",
        ],
    },
    "surfaceome_family": {
        "categorical": ["family_class", "surface_protein_family"],
    },
    "mutation_stratified_surface": {
        "significance_field": "q_value",
        "n_field": "n_mutant",
        "categorical": ["mutant_stratified_surface_class"],
    },
    "pathway_stratified_surface": {
        "significance_field": "q_value",
        "n_field": "n_high",
        "categorical": ["pathway_stratified_surface_class"],
    },
    # ── descriptor-coverage sweep, dependency/combination batch (2026-09-18) ────────────────────────
    # paralog_buffering: GRADED, higher_is_worse — a larger dual-vs-single-KO buffering delta means more
    # paralog compensation, so the single-KO dependency is UNDERSTATED and single-agent inhibition risks
    # paralog-mediated escape (the card's own warning). Sign is load-bearing (veto-suppressor on the
    # dependency call). DEBT-CLEARING.
    "paralog_buffering": {
        "effect_field": "strongest_paralog_delta",
        "direction": "higher_is_worse",
        "categorical": ["paralog_buffering_class"],
        "n_field": "n_paralogs_annotated",
        "reference_frame": {
            "kind": "graded_band",
            "atlas_numeric": False,
            "value_field": "strongest_paralog_delta",
            "scale": "chronos_delta",
            "position_field": "paralog_buffering_class",
            "cuts": [
                {"card_id": "paralog-buffering", "threshold": "partial_buffering_delta", "label": "partial"},
                {"card_id": "paralog-buffering", "threshold": "strong_buffering_delta", "label": "strong"},
            ],
        },
    },
    # partner_conditional_dependency: GRADED, lower_is_stronger — more-negative delta means partner-deficient
    # cells are MORE dependent = stronger synthetic-lethal signal. Mirrors the cn/fusion/amp_expr
    # stratified-dependency siblings exactly (same moderate -0.2 / strong -0.5 cut names + labels). DEBT-CLEARING.
    "partner_conditional_dependency": {
        "effect_field": "delta_chronos_deficient_vs_neutral",
        "significance_field": "partner_stratification_mannwhitney_q",
        "direction": "lower_is_stronger",
        "categorical": ["partner_stratification_class"],
        "n_field": "n_partner_deficient",
        "reference_frame": {
            "kind": "graded_band",
            "atlas_numeric": False,
            "value_field": "delta_chronos_deficient_vs_neutral",
            "scale": "chronos_delta",
            "position_field": "partner_stratification_class",
            "cuts": [
                {
                    "card_id": "partner-conditional-dependency",
                    "threshold": "moderate_effect_delta",
                    "label": "moderate",
                },
                {"card_id": "partner-conditional-dependency", "threshold": "strong_effect_delta", "label": "strong"},
            ],
        },
    },
    # categorical-only (the class is the ruler) — dependency-corroboration + model-correspondence:
    "cross_consortium_paralog_gi": {
        "n_field": "n_consortia_corroborating",
        "categorical": ["cross_consortium_paralog_class", "dede_class", "in4mer_class"],
    },
    "coessential_module": {
        "n_field": "n_partners",
        "categorical": ["coessential_module_class"],
    },
    "cross_consortium_dependency": {
        "n_field": "broad_n_lines",
        "categorical": ["cross_consortium_class"],
    },
    "patient_model_correspondence": {
        "n_field": "n_positive_models",
        "categorical": ["correspondence_class"],
    },
    "pathway_node_leverage": {
        "categorical": [
            "node_leverage_class",
            "evidence_scope",
            "single_ko_leverage_understated",
            "paralog_buffering_class",
        ],
    },
    "tumor_vs_adjacent_expression": {
        "effect_field": "log2_fc",
        "significance_field": "q_value",
        "direction": "higher_is_stronger",
        "categorical": ["expression_call_class"],
        # tumor-vs-adjacent log2FC on a GRADED BAND: the card has TWO named call cuts (modest 0.5 →
        # elevated, strong 1.5 → strongly elevated), so the ruler reads the ladder ("strongly elevated —
        # log2FC 2.1, past the 1.5 strong cut") instead of a single flat/elevated boundary. value NAMES
        # log2_fc; the band (expression_call_class) is READ VERBATIM as the position; both cuts single-source
        # from the card thresholds. A percentile companion is appended by _SECONDARY_FRAMES.
        "reference_frame": {
            "kind": "graded_band",
            "value_field": "log2_fc",
            "scale": "log2FC",
            "position_field": "expression_call_class",
            "cuts": [
                {"card_id": "tumor-rna-vs-adjacent", "threshold": "modest_upregulation_log2fc", "label": "modest"},
                {"card_id": "tumor-rna-vs-adjacent", "threshold": "strong_upregulation_log2fc", "label": "strong"},
            ],
        },
    },
    "tumor_protein_abundance": {
        "effect_field": "protein_effect_size",
        "significance_field": "protein_bh_q_value",
        "direction": "higher_is_stronger",
        "categorical": ["protein_expression_class"],
    },
    # ── tumor-presence DISTRIBUTION cards: pan-cancer allgene-percentile rulers (tranche #1) ──────────
    # These three measurement_types previously carried NO salience spec at all (key_evidence fell back to the
    # capsule heuristic + no ruler). Each distribution card independently carries the SAME decisive facet: a
    # pan-cancer rank of the target's panel/tumor median among ALL ~20k genes (allgene_percentile, 0-100) with
    # a named top-decile cut (allgene_top_decile = 90). That rank was emitted BARE; here it becomes a
    # distance_to_cut ruler ("top decile — pan-cancer expression rank 96 %ile, past the 90 cut"). value +
    # position (allgene_percentile_class) are READ VERBATIM; the cut single-sources the card threshold. The
    # spec also NAMES each card's median effect_field + resolver class band so key_evidence stops guessing.
    # verdict-INERT (no gate reads it) but NOT display-only: rf[0] mints the FROZEN atlas column
    # cell_line_rna_expression::num::allgene_percentile. See REACH OF A `reference_frame`.
    # (The by-subtype sibling shares tumor_expression_distribution but carries
    # no top-level allgene_percentile → build_interpretation omits the ruler there; it is gauged via the
    # SUBTYPE_SPECS omnibus path instead.)
    "cell_line_rna_expression": {
        "effect_field": "median_log2tpm_panel",
        "n_field": "n_cell_lines_evaluated",
        "direction": "higher_is_stronger",
        "categorical": ["expression_class", "allgene_percentile_class", "control_position_class"],
        "reference_frame": {
            "kind": "distance_to_cut",
            "value_field": "allgene_percentile",
            "scale": "percentile",
            "position_field": "allgene_percentile_class",
            "cut": {
                "card_id": "cellline-rna-distribution",
                "threshold": "allgene_top_decile",
                "label": "pan_cancer_top_decile",
            },
        },
    },
    "tumor_expression_distribution": {
        "effect_field": "median_log2tpm",
        "n_field": "n_tumor_samples",
        "direction": "higher_is_stronger",
        "categorical": ["tumor_expression_class", "allgene_percentile_class", "control_position_class"],
        "reference_frame": {
            "kind": "distance_to_cut",
            "value_field": "allgene_percentile",
            "scale": "percentile",
            "position_field": "allgene_percentile_class",
            "cut": {
                "card_id": "tumor-rna-distribution",
                "threshold": "allgene_top_decile",
                "label": "pan_cancer_top_decile",
            },
        },
    },
    "cell_line_protein_abundance": {
        "effect_field": "median_log2_abundance_panel",
        "n_field": "n_cell_lines_evaluated",
        "direction": "higher_is_stronger",
        "categorical": ["protein_expression_class", "allgene_percentile_class"],
        "reference_frame": {
            "kind": "distance_to_cut",
            "value_field": "allgene_percentile",
            "scale": "percentile",
            "position_field": "allgene_percentile_class",
            "cut": {
                "card_id": "cellline-protein-abundance",
                "threshold": "allgene_top_decile",
                "label": "pan_cancer_top_decile",
            },
        },
    },
    # tumor-elevation-breadth — a K-of-N breadth count, gauged on count_of_total: "elevated in 4 of 6
    # cohorts, past the 3-cohort breadth cut". value = n_cohorts_elevated; the total_field gives the
    # denominator; the cut single-sources broadly_elevated_min_cohorts. position = the breadth class.
    "tumor_elevation_breadth": {
        "effect_field": "fraction_elevated",
        "n_field": "n_cohorts_tested",
        "direction": "higher_is_stronger",
        "categorical": ["tumor_elevation_breadth_class", "rna_tumor_elevation_breadth_class"],
        "reference_frame": {
            "kind": "count_of_total",
            "value_field": "n_cohorts_elevated",
            "scale": "cohorts",
            "position_field": "tumor_elevation_breadth_class",
            "total_field": "n_cohorts_tested",
            "cut": {
                "card_id": "tumor-elevation-breadth",
                "threshold": "broadly_elevated_min_cohorts",
                "label": "breadth_cut",
            },
        },
    },
    # expression-purity-confound (display) — is the tumor signal intrinsic or a stromal-purity confound?
    # distance_to_cut on the purity↔expression correlation vs the intrinsic_r cut (0.3): a positive r past
    # the cut reads tumor-intrinsic; a negative r (toward confound_r -0.3) reads stromal confound. position
    # = purity_confound_class READ VERBATIM.
    "expression_purity_confound": {
        "effect_field": "expression_purity_pearson_r",
        "n_field": "n_paired_samples",
        "direction": "higher_is_stronger",
        "categorical": ["purity_confound_class"],
        "reference_frame": {
            "kind": "distance_to_cut",
            "value_field": "expression_purity_pearson_r",
            "scale": "pearson_r",
            "position_field": "purity_confound_class",
            "cut": {"card_id": "expression-purity-confound", "threshold": "intrinsic_r", "label": "intrinsic_cut"},
        },
    },
    # hpa-pathology-cancer-ihc (display) — antibody IHC protein-in-tumor. distance_to_cut on the
    # moderate/strong staining fraction vs the moderate-detection cut (0.66). position = protein_presence_class.
    "tumor_protein_ihc_presence": {
        "effect_field": "fraction_moderate_strong",
        "n_field": "n_patients_total",
        "direction": "higher_is_stronger",
        "categorical": ["protein_presence_class"],
        "reference_frame": {
            "kind": "distance_to_cut",
            "value_field": "fraction_moderate_strong",
            "scale": "fraction",
            "position_field": "protein_presence_class",
            "cut": {
                "card_id": "hpa-pathology-cancer-ihc",
                "threshold": "ihc_detected_moderate_max_fraction",
                "label": "moderate_ihc_cut",
            },
        },
    },
    # surface-modality-fit (§3.6)
    "sc_normal_surface_protein": {
        # FIELDS CORRECTED (2026-09-07): this spec's measurement_type is emitted by sc-surface-normal-safety
        # (surface CLR-ADT liability ladder), but the fields formerly named here (max_detection_fraction,
        # n_cell_types_above_20pct, sc_normal_safety_essential_class) belong to a DIFFERENT card
        # (sc-normal-celltype-expression, measurement_type sc_normal_celltype_expression) — so the numeric
        # salience never populated at runtime. Re-point to sc-surface-normal-safety's own summary_fields.
        # No reference_frame: max_mean_clr is a peak CLR-ADT DISPLAY level with no card-named cut → the
        # categorical sc_surface_normal_class liability ladder IS the ruler (correctly class-gauged).
        "effect_field": "max_mean_clr",
        "n_field": "n_celltypes_surface_displaying",
        "direction": "higher_is_worse",
        "categorical": ["sc_surface_normal_class"],
    },
    "rna_protein_concordance": {
        "effect_field": "rna_protein_r",
        "n_field": "n_paired_tumors",
        "direction": "higher_is_stronger",
        # rna_as_biomarker (Gap-A): rule-read by the rna-*-proxy rules (adequate/partial/poor proxy) on
        # BOTH concordance cards (they share this mt) — an {adequate/partial/poor_proxy, ...} class with
        # no descriptor. Categorical. One spec entry describes it for both cards (union, not sum).
        "categorical": ["rna_as_biomarker"],
        # RNA↔protein correlation on a GRADED BAND: the card names two concordance cuts (moderate 0.4,
        # strong 0.7), so "strongly concordant — r 0.74, past the 0.7 strong cut" reads the ladder rather
        # than a single 0.4 boundary. Replaces the former single distance_to_cut batch meter (value_field
        # unchanged = rna_protein_r → the atlas numeric feature stays byte-stable).
        "reference_frame": {
            "kind": "graded_band",
            "value_field": "rna_protein_r",
            "scale": "pearson_r",
            "cuts": [
                {
                    "card_id": "cellline-rna-protein-concordance",
                    "threshold": "moderate_concordance_r",
                    "label": "moderate",
                },
                {"card_id": "cellline-rna-protein-concordance", "threshold": "strong_concordance_r", "label": "strong"},
            ],
        },
    },
    # tractability-small-molecule (§3.7)
    "prism_compound_activity": {
        "strata_array": "top_compounds",
        "effect_field": "median_log2auc",
        "label_field": "drug_name",
        "direction": "lower_is_stronger",
        "categorical": ["prism_activity_class"],
        # gauge the across-compound median PRISM activity (top-level scalar; LOWER Log2AUC = more active) vs
        # the clinically-active cut (-0.10). position = prism_activity_class READ VERBATIM (the per-compound
        # depth lives in top_compounds[]; median_log2auc_across_compounds is the card-level summary).
        "reference_frame": {
            "kind": "distance_to_cut",
            "value_field": "median_log2auc_across_compounds",
            "scale": "log2auc",
            "position_field": "prism_activity_class",
            "cut": {
                "card_id": "prism-compound-activity",
                "threshold": "clinically_active_log2auc",
                "label": "clinically_active_cut",
            },
        },
    },
    "measured_potency_tractability": {
        "effect_field": "chembl_best_pchembl",
        "direction": "higher_is_stronger",
        "categorical": ["measured_bioactivity_class", "chembl_clinical_phase_class"],
        "extra_scalars": ["best_measured_potency_neglog_m"],
        # STAGE-2 ruler (cross-repo): distance_to_cut on the CROSS-SOURCE max potency (best_measured_potency_neglog_m,
        # -log10 M; HIGHER = more potent), gauged against the potent_neglog_m cut (6.0 = <=1 uM) NAMED on the card
        # (contracts #666). position = measured_bioactivity_class READ VERBATIM. verdict-INERT (no gate reads
        # it) but NOT display-only: rf[0] mints the FROZEN atlas column
        # measured_potency_tractability::num::best_measured_potency_neglog_m. See REACH OF A `reference_frame`.
        "reference_frame": [
            {
                "kind": "distance_to_cut",
                "value_field": "best_measured_potency_neglog_m",
                "scale": "neglog_M",
                "position_field": "measured_bioactivity_class",
                "cut": {
                    "card_id": "measured-potency-tractability",
                    "threshold": "potent_neglog_m",
                    "label": "potent_cut",
                },
            },
            # + cohort ruler: best measured potency vs the 150 known targets with a measured potency.
            {
                "kind": "cohort_percentile",
                "value_field": "best_measured_potency_neglog_m",
                "scale": "neglog_M",
                "cohort_key": "measured_potency_tractability::num::best_measured_potency_neglog_m",
            },
        ],
    },
    "structure_druggability": {
        "categorical": [
            "structural_ligandability_class",
            "hotspot_pocket_adjacency_call",
            "alphafold_confidence_class",
        ],
        "extra_scalars": ["alphafold_plddt_mean"],
    },
    # mechanism-and-pharmacology (§3.8)
    "signaling_network_mechanism": {
        "categorical": ["network_class"],
        "extra_scalars": ["n_upstream_regulators", "n_downstream_effectors"],
    },
    "pathway_activity_context": {
        "strata_array": "per_pathway",
        "effect_field": "activity_z",
        "label_field": "pathway",
        "direction": "higher_is_stronger",
        "categorical": ["pathway_activity_class"],
    },
    # combination-and-vulnerability (§3.9)
    "combinatorial_ko_dependency": {
        "strata_array": "ranked_partner_table",
        "effect_field": "mean_gi",
        "significance_field": "gi_ttest_pvalue",
        "label_field": "partner_gene",
        "direction": "lower_is_stronger",
        "categorical": ["combinatorial_dependency_class"],
        # gauge the STRONGEST partner's mean GI (top-level scalar; more negative = stronger interaction) vs
        # the constitutive-interaction cut (-0.25). position = combinatorial_dependency_class READ VERBATIM.
        "reference_frame": {
            "kind": "distance_to_cut",
            "value_field": "strongest_partner_mean_gi",
            "scale": "gi_chronos",
            "position_field": "combinatorial_dependency_class",
            "cut": {
                "card_id": "combinatorial-dependency",
                "threshold": "constitutive_mean_gi",
                "label": "constitutive_cut",
            },
        },
    },
    "drug_anchored_combination": {
        "strata_array": "top_co_targets",
        "effect_field": "mean_effect_shift",
        "significance_field": "frac_models_significant",
        "label_field": "co_target_gene",
        "direction": "lower_is_stronger",
        "categorical": ["combination_opportunity_class"],
        # strongest co-target's essentiality shift (more negative = combination) on a graded band
        # (supported -0.25 / strong -0.50). position = combination_opportunity_class READ VERBATIM.
        "reference_frame": {
            "kind": "graded_band",
            "value_field": "strongest_co_target_shift",
            "scale": "effect_shift",
            "position_field": "combination_opportunity_class",
            "cuts": [
                {"card_id": "combo-crispr-screen", "threshold": "supported_shift", "label": "supported"},
                {"card_id": "combo-crispr-screen", "threshold": "strong_shift", "label": "strong"},
            ],
        },
    },
    "drug_anchored_resistance": {
        "strata_array": "top_resistance_mediators",
        "effect_field": "mean_effect_shift",
        "significance_field": "frac_models_significant",
        "label_field": "rescuer_gene",
        "direction": "higher_is_stronger",
        "categorical": ["resistance_emergence_class"],
        # strongest rescuer's shift (more positive = stronger rescue) on a graded band (supported 0.25 /
        # strong 0.50). position = resistance_emergence_class READ VERBATIM.
        "reference_frame": {
            "kind": "graded_band",
            "value_field": "strongest_mediator_shift",
            "scale": "effect_shift",
            "position_field": "resistance_emergence_class",
            "cuts": [
                {"card_id": "resistance-emergence-signature", "threshold": "supported_shift", "label": "supported"},
                {"card_id": "resistance-emergence-signature", "threshold": "strong_shift", "label": "strong"},
            ],
        },
    },
    # immune-context (§3.10)
    "immune_context": {
        "effect_field": "cd8_high_minus_low",
        "n_field": "n_patients_joined",
        "direction": "higher_is_stronger",
        "categorical": ["immune_context_class", "antigen_conditioned_call", "antigen_high_immune_context_class"],
        # The gauge is on median_cd8_fraction, NOT on the spec's effect_field: cd8_high_minus_low is a
        # DELTA (antigen-high minus antigen-low) and is not comparable to fraction cuts — the scale
        # mismatch that made the 09-10 batch rollout skip this axis (see _BATCH_DISTANCE_TO_CUT_METERS).
        # median_cd8_fraction IS the quantity the card's own two thresholds cut, so it gauges cleanly.
        #
        # ★ WHAT THIS RULER MEASURES IS A RANK, NOT A DENSITY. cd8_fraction_cold_max (0.084) and
        # cd8_fraction_hot_min (0.113) are the Q1 and Q3 of the CD8 share across the 33 TCGA studies, so
        # `immune_hot` means "top-quartile CD8 share AMONG INDICATIONS", not "heavily infiltrated" in any
        # absolute sense. The band is therefore pan-cancer-relative and NOT an ICI-response predictor:
        # ICI-refractory PRAD (0.1312) reads immune_hot, while ICI-approved BLCA/LUAD/LUSC sit in
        # `intermediate`. The METRIC_GLOSS label carries that framing to every renderer — a bare 0.11 next
        # to a "hot" label reads as a density claim, which is the misread this gauge exists to prevent.
        # DISPLAY-ONLY / verdict-INERT — and here that label is ACCURATE rather than the loose one used
        # elsewhere in this file, for a checkable reason: this frame carries `atlas_numeric: False` (the third
        # reason is recorded just below), so it mints no atlas column and reaches display only. No rule reads
        # the frame, and it omits when the value is absent. Held by test_reference_frame_governance
        # invariant 5, whose opt-out ratchet reds if this axis ever starts minting.
        #
        # ★★ atlas_numeric: False — a THIRD reason for the opt-out, distinct from the two recorded on
        # numeric_feature_specs (non-monotone polarity; degenerate value). Here the value is not a property
        # of the entity the atlas indexes AT ALL: this card's primary call is target-INDEPENDENT (its own
        # caveat says so — it is the immune landscape of the INDICATION, not conditioned on the target
        # antigen), so median_cd8_fraction is IDENTICAL for every target in a given indication. Minting an
        # atlas numeric from it would make known targets cluster by indication rather than by biology, and
        # "stronger than X% of known targets" would be phrasing an indication property as a target property.
        # The target-DEPENDENT quantity on this card is the antigen-conditioned delta (cd8_high_minus_low) —
        # which is exactly the field that cannot carry this ruler, since fraction cuts do not gauge a delta.
        # So the axis gets a DISPLAY ruler and no atlas feature; that is the honest split, not an omission.
        "reference_frame": {
            "kind": "graded_band",
            "value_field": "median_cd8_fraction",
            "scale": "fraction",
            "atlas_numeric": False,
            "position_field": "immune_context_class",
            "cuts": [
                {
                    "card_id": "immune-context",
                    "threshold": "cd8_fraction_cold_max",
                    "label": "cold ceiling (pan-cancer Q1)",
                },
                {
                    "card_id": "immune-context",
                    "threshold": "cd8_fraction_hot_min",
                    "label": "hot floor (pan-cancer Q3)",
                },
            ],
        },
    },
    # differentiation-landscape (§3.11)
    "mutation_cooccurrence": {
        "strata_array": "top_cooccurring",
        "effect_field": "log2_odds_ratio",
        "significance_field": "bh_q_value",
        "label_field": "partner_gene",
        "direction": "higher_is_stronger",
        "categorical": ["cooccurrence_class"],
    },
    # ── GENOMIC CARD-DATA RULERS (2026-09-12) — the "later, threshold-named add" the 09-10 verdict-tail
    #    block below deferred, plus the three genomic verdict-bearing types that had NO spec at all.
    #
    #    MEASURED GAP: of the 23 measurement_types behind genomic-alteration-profile's 26 cards, 12 had no
    #    SALIENCE_SPEC and only 2 carried a reference_frame — so the subskill that decides driver status
    #    shipped almost no gauged numbers. Three of the 12 are VERDICT-BEARING (named by a gating rule in
    #    coverage/rule_role_partition.yaml): copy_number_alteration and mutation_variant_class_spectrum both
    #    key resolver rungs, and mutation_clonality gates the clonality read.
    #
    #    Every value_field + threshold below is single-sourced from the named card's `thresholds:` block and
    #    pinned by skills/tests/test_reference_frame_governance.py. Where a card declares NO numeric
    #    threshold there is deliberately NO ruler (fusion-rearrangement-landscape, splice-exon-skip-landscape,
    #    variant-level-interpretation, target-clonality): a gauge needs a contract-declared cut, and inventing
    #    one skills-side is exactly the re-hardcoding the governance test forbids. Those stay declared debt —
    #    they need a contracts-side threshold first.
    "copy_number_alteration": {
        "effect_field": "cn_recurrent_amplification_score",
        "n_field": "cn_n_cell_lines_evaluated",
        "direction": "higher_is_stronger",
        "categorical": [
            "copy_number_class",
            "patient_copy_number_class",
            "patient_focal_cn_class",
            "cn_distribution_shape",
            "cn_homozygous_deletion_recurrent",
        ],
        "extra_scalars": [
            "cn_recurrent_deletion_score",
            "cn_fraction_deep_deletion",
            "cn_fraction_high_amplification",
            "patient_high_amp_fraction",
            "patient_homdel_fraction",
            "cn_median_panel",
        ],
        # TWO rulers on the same cut, because the two arms of this classifier have a measured 20-40x
        # specificity gap and the reader must SEE which arm is talking. Over 1433 random gene columns
        # (card header, 2026-09-12): the amplification score clears 0.20 for 2.9% of genes genome-wide,
        # the deletion score for 60.1% — the deletion cut sits BELOW the genomic median, so a bare
        # "recurrently deleted" call is mostly reading the aneuploid cell-line background. Gauging both
        # against the SAME recurrent_event_fraction makes that asymmetry legible on the card instead of
        # only in the resolver's rung choice (resolver >= 1.9.0 keys its deletion rungs elsewhere).
        "reference_frame": [
            {
                "kind": "distance_to_cut",
                "value_field": "cn_recurrent_amplification_score",
                "scale": "event_fraction",
                "position_field": "copy_number_class",
                "cut": {
                    "card_id": "copy-number-distribution",
                    "threshold": "recurrent_event_fraction",
                    "label": "recurrent_event_cut",
                },
            },
            {
                "kind": "distance_to_cut",
                "value_field": "cn_recurrent_deletion_score",
                "scale": "event_fraction",
                "position_field": "copy_number_class",
                "cut": {
                    "card_id": "copy-number-distribution",
                    "threshold": "recurrent_event_fraction",
                    "label": "recurrent_event_cut",
                },
            },
        ],
    },
    "mutation_variant_class_spectrum": {
        "n_field": "mut_n_cell_lines_mutated",
        "direction": "higher_is_stronger",
        "categorical": ["mut_dominant_mutation_class", "mutation_landscape_class"],
        "extra_scalars": ["mut_mutation_rate", "mut_n_cell_lines_total", "mut_total_mutations"],
        # SHAPE, not strength — and the whole point of gauging it is to show how UNDISCRIMINATING the cut
        # is. mut-missense-dominant-supportive fires for 62% of the 26-target genomic review panel
        # INCLUDING both negative controls (GAPDH, ACTB), because most genes' somatic spectra are
        # missense-dominant by base-substitution statistics alone; resolver 1.9.0 demoted the shape rungs
        # below patient SNV recurrence for exactly that reason. A distance-to-cut ruler puts GAPDH's
        # fraction next to KRAS's instead of collapsing both to "missense_dominant".
        #
        # atlas_numeric: False — no single polarity exists. A high missense fraction reads DRIVER for an
        # oncogene and PASSENGER for a tumour suppressor, so signing it with a fixed _DIR_SIGN would be
        # wrong for whichever half of the corpus it is not describing. Displayed, never embedded.
        "reference_frame": [
            {
                "kind": "distance_to_cut",
                "value_field": "mut_fraction_missense",
                "scale": "mutation_fraction",
                "position_field": "mut_dominant_mutation_class",
                "atlas_numeric": False,
                "cut": {
                    "card_id": "mutation-type-counts",
                    "threshold": "missense_dominant_fraction",
                    "label": "missense_dominant_cut",
                },
            },
            {
                "kind": "distance_to_cut",
                "value_field": "mut_fraction_lof",
                "scale": "mutation_fraction",
                "position_field": "mut_dominant_mutation_class",
                "atlas_numeric": False,
                "cut": {
                    "card_id": "mutation-type-counts",
                    "threshold": "lof_dominant_fraction",
                    "label": "lof_dominant_cut",
                },
            },
        ],
    },
    # target-clonality declares NO numeric thresholds, so this is a spec WITHOUT a ruler — the class is the
    # ruler (governance invariant 1 accepts a non-empty `categorical` as gaugeable). clonal_fraction and
    # median_ccf are surfaced as numbers; what is missing is a contract-declared clonal cut to gauge against.
    "mutation_clonality": {
        "effect_field": "clonal_fraction",
        "n_field": "n_mutant_samples",
        "direction": "higher_is_stronger",
        "categorical": ["clonality_class"],
        "extra_scalars": ["median_ccf"],
    },
    # ── verdict-tail specs (2026-09-10): field names VERIFIED against each card's outputs.summary_fields.
    #    Rulers added 2026-09-12 (see the block above) where the card declares a numeric cut. ────────────
    # genomic-alteration-profile
    "cn_stratified_dependency": {
        "effect_field": "delta_chronos_amplified_vs_neutral",
        "significance_field": "cn_stratification_mannwhitney_q",
        "n_field": "n_amplified",
        "direction": "lower_is_stronger",
        "categorical": ["cn_stratification_class", "evidence_scope"],
        "extra_scalars": ["median_chronos_amplified", "median_chronos_neutral", "cn_stratification_effect_size"],
        # graded_band on the amplified-vs-neutral CHRONOS delta against the card's own two-step effect
        # ladder (moderate -0.2 / strong -0.5) — the exact cuts cn_stratification_class is banded on, so
        # the read-verbatim position can never contradict the gauge.
        "reference_frame": {
            "kind": "graded_band",
            "value_field": "delta_chronos_amplified_vs_neutral",
            "scale": "chronos_delta",
            "position_field": "cn_stratification_class",
            "cuts": [
                {
                    "card_id": "copy-number-stratified-dependency",
                    "threshold": "moderate_effect_delta",
                    "label": "moderate",
                },
                {"card_id": "copy-number-stratified-dependency", "threshold": "strong_effect_delta", "label": "strong"},
            ],
        },
    },
    "amp_expr_stratified_dependency": {
        "effect_field": "delta_chronos_amp_expr_vs_rest",
        "significance_field": "amp_expr_mannwhitney_q",
        "n_field": "n_amplified_overexpressed",
        "direction": "lower_is_stronger",
        "categorical": ["amp_expr_stratification_class", "evidence_scope"],
        "extra_scalars": ["median_chronos_amp_expr", "median_chronos_comparator", "amp_expr_effect_size"],
        "reference_frame": {
            "kind": "graded_band",
            "value_field": "delta_chronos_amp_expr_vs_rest",
            "scale": "chronos_delta",
            "position_field": "amp_expr_stratification_class",
            "cuts": [
                {
                    "card_id": "amp-expr-stratified-dependency",
                    "threshold": "moderate_effect_delta",
                    "label": "moderate",
                },
                {"card_id": "amp-expr-stratified-dependency", "threshold": "strong_effect_delta", "label": "strong"},
            ],
        },
    },
    "fusion_stratified_dependency": {
        "effect_field": "delta_chronos_fusion_positive_vs_negative",
        "significance_field": "fusion_stratification_mannwhitney_q",
        "n_field": "n_fusion_positive",
        "direction": "lower_is_stronger",
        "categorical": ["fusion_stratification_class", "fusion_stratification_confound", "evidence_scope"],
        "extra_scalars": ["median_chronos_fusion_positive", "median_chronos_fusion_negative"],
        "reference_frame": {
            "kind": "graded_band",
            "value_field": "delta_chronos_fusion_positive_vs_negative",
            "scale": "chronos_delta",
            "position_field": "fusion_stratification_class",
            "cuts": [
                {"card_id": "fusion-stratified-dependency", "threshold": "moderate_effect_delta", "label": "moderate"},
                {"card_id": "fusion-stratified-dependency", "threshold": "strong_effect_delta", "label": "strong"},
            ],
        },
    },
    "mutation_hotspot_frequency": {
        "effect_field": "overall_mutation_frequency",
        "n_field": "n_covered_pooled",
        "direction": "higher_is_stronger",
        "categorical": ["pooled_driver_recurrence_class", "driver_recurrence_class", "genie_driver_recurrence_class"],
        "extra_scalars": ["pooled_driver_recurrence_percentile", "genie_mutation_frequency", "n_mutated_pooled"],
        # The ruler for the rung resolver 1.9.0 PROMOTED to the top of the SNV arm. The gauged value is the
        # POOLED percentile (the field pooled_driver_recurrence_class is banded on — not the indication-only
        # driver_recurrence_percentile), against the top-1% cut the rung keys on. This is the number the
        # verdict now turns on, and until now it was an unlabelled entry in extra_scalars.
        "reference_frame": {
            "kind": "distance_to_cut",
            "value_field": "pooled_driver_recurrence_percentile",
            "scale": "percentile",
            "position_field": "pooled_driver_recurrence_class",
            "cut": {
                "card_id": "mutation-hotspot-frequency",
                "threshold": "driver_recurrence_top_1pct",
                "label": "top_1pct_cut",
            },
        },
    },
    "mutation_drug_response": {
        "effect_field": "delta_log2auc_mut_vs_wt",
        "significance_field": "drug_response_mannwhitney_q",
        "n_field": "n_mutant",
        "direction": "lower_is_stronger",
        "categorical": ["drug_response_stratification_class"],
        "extra_scalars": ["drug_response_ppv", "drug_response_effect_size", "median_log2auc_mutant"],
        # NOTE the effect ladder on this card is an order of magnitude tighter than the CHRONOS cards'
        # (-0.08 / -0.2 in log2 AUC vs -0.2 / -0.5 in CHRONOS) — which is precisely why the delta needs a
        # scale and a named cut rather than being read as a bare number next to a dependency delta.
        "reference_frame": {
            "kind": "graded_band",
            "value_field": "delta_log2auc_mut_vs_wt",
            "scale": "log2auc_delta",
            "position_field": "drug_response_stratification_class",
            "cuts": [
                {"card_id": "mutation-drug-response", "threshold": "moderate_effect_delta", "label": "moderate"},
                {"card_id": "mutation-drug-response", "threshold": "strong_effect_delta", "label": "strong"},
            ],
        },
    },
    "splice_exon_skip": {  # curated-event card: categorical + carrier count, no numeric effect
        "n_field": "n_depmap_carriers",
        "categorical": ["splice_exon_skip_class", "driver_direction"],
    },
    "fusion_rearrangement": {
        "effect_field": "fusion_frequency",
        "n_field": "n_samples_with_fusion",
        "direction": "higher_is_stronger",
        "categorical": ["fusion_class", "fusion_recurrence_confidence", "genie_sv_recurrence_class"],
        "extra_scalars": ["genie_sv_frequency", "genie_sv_recurrence_percentile"],
    },
    "variant_level_interpretation": {  # categorical + count + resistance-variant liability strata (label-only)
        "strata_array": "resistance_variants",
        "label_field": "variant",
        "n_field": "n_interpreted_variants",
        # has_oncogenic_variant dropped: contract #783 types it `boolean` (a flag, not a *_class string).
        "categorical": ["civic_variant_class"],
    },
    # differentiation-landscape (survival: no monotone effect — drive on class + logrank_p + medians)
    "expression_clinical_association": {
        "significance_field": "logrank_p",
        "n_field": "n_patients",
        "categorical": ["survival_association_class"],
        "extra_scalars": ["median_ostime_high_days", "median_ostime_low_days", "logrank_chi2"],
    },
    "alteration_clinical_association": {
        "significance_field": "logrank_p",
        "n_field": "n_patients",
        "categorical": ["alteration_survival_association_class"],
        "extra_scalars": ["median_ostime_mutated_days", "median_ostime_wildtype_days", "logrank_chi2"],
    },
    "subtype_survival_association": {
        "strata_array": "per_stratum",
        "label_field": "stratum",
        "effect_field": "median_ostime_days",
        "significance_field": "logrank_p",
        "n_field": "n_patients",
        "categorical": ["subtype_survival_association_class"],
        "extra_scalars": ["logrank_chi2", "logrank_df", "n_admissible_strata"],
    },
    # combination-and-vulnerability
    "synthetic_lethal_partner": {  # categorical + count + partner strata (no per-partner effect — upstream gap)
        "strata_array": "top_partners",
        "label_field": "partner",
        "n_field": "sl_partner_count",
        # has_experimental_partner dropped: contract #783 types it `boolean` (a flag, not a *_class string).
        "categorical": ["sl_partner_class", "best_evidence_tier"],
    },
    "chemical_combination_synergy": {
        "effect_field": "strongest_synergy_delta_emax",
        "n_field": "n_synergy_partners",
        "direction": "higher_is_stronger",
        "categorical": ["synergy_opportunity_class"],
        # extra_scalars dropped: strongest_synergy_partner_drug/_target are NAME strings (contract #783),
        # not numeric scalars — the numeric read yielded None, so they contributed no bits.
    },
    # cis-feature-coherence
    "methylation_silencing_coupling": {
        "effect_field": "methyl_expr_spearman_r",
        "significance_field": "methyl_expr_spearman_p",
        "n_field": "n_cell_lines_evaluated",
        "direction": "lower_is_stronger",
        "categorical": ["methylation_silencing_class", "silencing_driver", "evidence_scope"],
        "extra_scalars": ["subset_median_delta_log2tpm", "methyl_expr_slope_log2tpm_per_methyl"],
    },
    "patient_cis_coherence": {
        "effect_field": "cn_expr_spearman_r",
        "significance_field": "cn_expr_spearman_p",
        "n_field": "n_patients_cn_expr",
        "direction": "higher_is_stronger",
        "categorical": ["patient_cis_dosage_class", "patient_methylation_silencing_class", "evidence_scope"],
        "extra_scalars": ["delta_log2tpm_amplified_vs_neutral", "delta_log2tpm_methylated_vs_unmethylated"],
    },
    "cis_protein_dosage_coupling": {
        "effect_field": "cn_prot_spearman_r",
        "significance_field": "cn_prot_spearman_p",
        "n_field": "n_paired_models_cn_protein",
        "direction": "higher_is_stronger",
        "categorical": ["cis_protein_dosage_class", "evidence_scope"],
        "extra_scalars": ["delta_log2abundance_amplified_vs_neutral", "cn_prot_slope_log2abundance_per_cn"],
    },
    "expression_dependency_correlation": {
        "effect_field": "pearson_r",
        "significance_field": "pearson_p",
        "n_field": "n_cell_lines_evaluated",
        "direction": "lower_is_stronger",
        "categorical": ["correlation_class"],
        "extra_scalars": [
            "delta_chronos_top_vs_bottom_quartile",
            "chronos_at_high_expression",
            "chronos_at_low_expression",
        ],
    },
    "abundance_dependency_correlation": {
        "effect_field": "protein_dependency_pearson_r",
        "significance_field": "protein_dependency_pearson_p",
        "n_field": "n_paired_models",
        "direction": "lower_is_stronger",
        "categorical": ["abundance_dependency_class"],
        "extra_scalars": ["n_dependent_models", "protein_dependency_spearman_r"],
    },
    # surface-modality-fit
    "adc_tce_modality_fit": {  # composed VERDICT card — categorical only (emits no numeric anchor)
        "categorical": [
            "fit_class",
            "endocytosis_confidence",
            "surface_confirmation_state",
            "surface_family_class",
        ],
    },
    "modality_window": {
        "effect_field": "window_ratio_essential",
        "direction": "higher_is_stronger",
        "categorical": ["window_class", "therapeutic_window_class", "max_essential_normal_organ", "modality"],
        "extra_scalars": ["max_essential_normal_tpm", "window_ratio_full_normal", "max_full_normal_tpm"],
    },
    "shed_ectodomain_liability": {
        "effect_field": "media_mean_npx",
        "n_field": "media_n_lines_detected",
        "direction": "higher_is_worse",
        "categorical": ["shed_liability_class", "shed_evidence_tier", "shed_product", "shedding_protease"],
        # serum_marker dropped: contract #783 types it `string` (an assay NAME), not a numeric scalar.
        "extra_scalars": ["media_panel_high_npx"],
    },
}

# ── subtype-axis salience (§3.16): the parallel omnibus-per-axis / per-subgroup shapes ───────────────
# Keyed loosely by the summary fields a subtype-stratified card carries; the key_evidence builder tries
# each in order and uses the first present. Verdict-inert; null when the subtype axis is absent.
SUBTYPE_SPECS: dict = {
    # presence: subtype_omnibus_by_axis (multi-axis omnibus) + per_subgroup_metrics
    "subtype_omnibus_by_axis": {
        "axis_array": "subtype_omnibus_by_axis",
        "axis_field": "axis",
        "omnibus_field": "subtype_omnibus_p",
        "which_separate_field": "which_subtypes_separate",
        "driving_axis_field": "subtype_omnibus_driving_axis",
        "restriction_class_field": "subtype_stratification_class",
        "subgroup_array": "per_subgroup_metrics",
        "subgroup_label_field": "stratum_id",
        "subgroup_effect_field": "median_log2tpm",
        "subgroup_n_field": "n_tumor_samples",
    },
    # dependency: per_subgroup_metrics with median_chronos + a cross-subgroup delta
    "per_subgroup_metrics": {
        "subgroup_array": "per_subgroup_metrics",
        "subgroup_label_field": "stratum",
        "subgroup_effect_field": "median_chronos",
        "subgroup_n_field": "subgroup_n",
        "restriction_class_field": "subgroup_stratification_class",
    },
    # survival: per_axis_association with logrank_p
    "per_axis_association": {
        "axis_array": "per_axis_association",
        "axis_field": "axis",
        "omnibus_field": "logrank_p",
        "restriction_class_field": "subtype_survival_association_class",
    },
}


# ── batch meter rollout: attach distance_to_cut reference_frames to the remaining spec axes whose card
# already NAMES a usable cut (no target-contracts round-trip). Kept as a table + loop (not 12 inlined
# frames) for reviewability. value_field = the spec's effect_field (already a summary_field of the same
# card); the cut single-sources that card's named threshold; direction is already declared on each spec.
# verdict-INERT (no gate reads these) but EMPHATICALLY NOT display-only — this is the highest-reach frame
# site in the file. The table injects the PRIMARY frame for axes that had NONE, so it mints 4 of the 32
# frozen atlas columns: crispr_rnai_concordance::num::fraction_agree,
# normal_tissue_rna_breadth::num::highest_tissue_median, rnai_lof_dependency::num::rnai_median_dep_score and
# tumor_protein_abundance::num::protein_effect_size. Editing a value_field or a cut here MOVES a frozen
# column and every cohort_percentile computed from it.
# ★ And because these frames are INJECTED rather than written in a spec block, a literal-string scan of the
# specs reports them as absent — which is exactly how an audit concluded those 4 columns had no producing
# frame in today's source, and predicted a re-freeze would silently drop them. It would not: they are here.
# Like every reference_frame, the ruler omits gracefully when the value is absent (so data-sparse axes such
# as the combination legs simply carry no gauge until measured). See REACH OF A `reference_frame`.
# (immune_context is deliberately EXCLUDED: its cd8_high_minus_low is a DELTA, not comparable to the
# fraction cuts on that card — a scale mismatch — and the signal is indication-level anyway.)
# Only axes whose effect_field is a TOP-LEVEL summary_field of the card qualify (governance invariant 3):
# the 7 dropped candidates (prism median_log2auc, chemical spearman_r_crispr, predictability r2,
# combination mean_gi/mean_effect_shift, cooccurrence log2_odds_ratio) carry their magnitude in a per-strata
# / per-compound / per-partner array or a computed field, not a single card-level summary value, so they
# have no clean scalar to gauge here (they stay class-only until a scalar summary field exists).
_BATCH_DISTANCE_TO_CUT_METERS = {
    # measurement_type: (value_field, scale, cut_card_id, cut_threshold_key)
    "rnai_lof_dependency": (
        "rnai_median_dep_score",
        "demeter2",
        "pan-cancer-rnai-dependency-distribution",
        "moderately_dependent_threshold_demeter",
    ),
    "crispr_rnai_concordance": (
        "fraction_agree",
        "fraction",
        "crispr-rnai-dependency-concordance",
        "strongly_concordant_fraction_threshold",
    ),
    "normal_tissue_rna_breadth": ("highest_tissue_median", "log2tpm", "normal-tissue-liability-gtex", "high_log2tpm"),
    "tumor_protein_abundance": (
        "protein_effect_size",
        "protein_effect",
        "tumor-protein-abundance-cptac",
        "modest_up_effect",
    ),
    # (rna_protein_concordance graduated to an inline graded_band ruler — see its spec above)
}
for _mt, (_vf, _sc, _card, _cut) in _BATCH_DISTANCE_TO_CUT_METERS.items():
    _spec = SALIENCE_SPECS.get(_mt)
    if _spec is not None and not _spec.get("reference_frame"):
        _spec["reference_frame"] = {
            "kind": "distance_to_cut",
            "value_field": _vf,
            "scale": _sc,
            "cut": {"card_id": _card, "threshold": _cut, "label": _cut},
        }


# ── SECONDARY reference_frames (multi-ruler, tranche #3) ─────────────────────────────────────────────
# A single card often carries >1 orthogonal reading; key_evidence.interpretation is a LIST and the builder
# projects EVERY frame (feat/interp-multi-ruler). Here we append a second tumor-presence frame so the card
# view reads BOTH gauges (interp[0] stays the headline read the narrator/single-gauge leads with; the
# appended frame is the additional context). The append normalizes reference_frame dict→list; a frame whose
# value is absent at runtime simply drops out. DISPLAY-ONLY / verdict-INERT — ACCURATE here, for a reason
# specific to this block: every frame appended below lands at rf[1:], and only rf[0] mints an atlas column.
# ★ LATENT HAZARD, currently unreached: the `_rf is None` branch below makes the "secondary" the PRIMARY, so
# an entry added here for an axis carrying no other frame would silently mint a NEW atlas column and stop
# being display-only. All 6 current entries are safe (5 declare an inline frame; tumor_protein_abundance is
# framed by the batch meter above, which runs FIRST). Held by test_reference_frame_governance invariant 5.
#   - the 3 distribution cards: their pan-cancer allgene-percentile ruler (tranche #1) PLUS a within-panel /
#     within-tumor position gauge (where the median sits vs the panel spread or the high-expression cut).
#   - cptac + tumor-vs-adjacent: their call-cut ruler PLUS the pan-cancer allgene-percentile companion, so
#     ALL FIVE allgene-carrying cards read the population rank.
#   - single-cell: its malignant-detection cut ruler PLUS a comparator_delta vs the top microenvironment
#     compartment — the stromal-confound story a lone malignant fraction hides.
def _allgene_percentile_frame(card_id: str) -> dict:
    return {
        "kind": "distance_to_cut",
        "value_field": "allgene_percentile",
        "scale": "percentile",
        "position_field": "allgene_percentile_class",
        "cut": {"card_id": card_id, "threshold": "allgene_top_decile", "label": "pan_cancer_top_decile"},
    }


_SECONDARY_FRAMES = {
    "cell_line_rna_expression": {
        "kind": "floor_cut_ceiling",
        "value_field": "median_log2tpm_panel",
        "scale": "log2tpm",
        "position_field": "expression_class",
        "anchors": [
            {"role": "floor", "field": "p5_log2tpm_panel", "label": "panel_p5"},
            {"role": "ceiling", "field": "p95_log2tpm_panel", "label": "panel_p95"},
        ],
        "cut": {
            "card_id": "cellline-rna-distribution",
            "threshold": "highly_expressed_threshold_log2tpm",
            "label": "highly_expressed_cut",
        },
    },
    # tumor_expression_distribution serves BOTH tumor-rna-distribution (main) AND its by-subtype sibling.
    # (1) within-tumor median position — fires on the main card. (2) subtype ε² effect-size graded_band —
    # fires ONLY on the by-subtype card (which alone carries subtype_variance_explained; the main card lacks
    # it → build_interpretation drops that frame). So one shared spec gauges the subtype-panorama omnibus
    # effect ("large subtype effect — ε² 0.18, past the 0.14 large cut") without a schema change.
    "tumor_expression_distribution": [
        {
            "kind": "distance_to_cut",
            "value_field": "median_log2tpm",
            "scale": "log2tpm",
            "position_field": "tumor_expression_class",
            "cut": {"card_id": "tumor-rna-distribution", "threshold": "high_log2tpm", "label": "high_expression_cut"},
        },
        {
            "kind": "graded_band",
            "value_field": "subtype_variance_explained",
            "scale": "variance_explained",
            "position_field": "subtype_effect_size_class",
            "cuts": [
                {
                    "card_id": "tumor-rna-distribution-by-subtype",
                    "threshold": "subtype_effect_moderate",
                    "label": "moderate",
                },
                {"card_id": "tumor-rna-distribution-by-subtype", "threshold": "subtype_effect_large", "label": "large"},
            ],
        },
        # + cohort ruler (Phase 2): pan-cancer allgene percentile vs the known-target cohort (appended LAST).
        {
            "kind": "cohort_percentile",
            "value_field": "allgene_percentile",
            "scale": "percentile",
            "cohort_key": "tumor_expression_distribution::num::allgene_percentile",
        },
    ],
    "cell_line_protein_abundance": {
        "kind": "floor_cut_ceiling",
        "value_field": "median_log2_abundance_panel",
        "scale": "log2_abundance",
        "position_field": "protein_expression_class",
        "anchors": [
            {"role": "floor", "field": "p5_log2_abundance_panel", "label": "panel_p5"},
            {"role": "ceiling", "field": "p95_log2_abundance_panel", "label": "panel_p95"},
        ],
    },
    # tumor_protein_abundance: the raw-logFC primary (batch meter) reads protein_effect_size vs the 0.5
    # modest cut — but that RAW effect over-reads a large-n `small_effect` (cleared q via cohort size, not
    # biology). So we append TWO secondaries: the pan-cancer allgene-percentile companion, AND a
    # variance-standardized Cohen's-d graded_band (sample-size-INDEPENDENT effect SIZE) whose cuts
    # single-source the card's cohens_d_small/medium/large thresholds and whose position is the
    # protein_effect_standardized_class band read verbatim. frame[0] stays protein_effect_size → the atlas
    # numeric feature is byte-stable. DISPLAY-ONLY / verdict-INERT — ACCURATE, and this is the ONE site in the
    # file that already said why: both appended frames are rf[1:], so neither mints. The column stays
    # tumor_protein_abundance::num::protein_effect_size (injected by the batch meter above).
    "tumor_protein_abundance": [
        _allgene_percentile_frame("tumor-protein-abundance-cptac"),
        {
            "kind": "graded_band",
            "value_field": "protein_effect_cohens_d",
            "scale": "cohens_d",
            "position_field": "protein_effect_standardized_class",
            "cuts": [
                {"card_id": "tumor-protein-abundance-cptac", "threshold": "cohens_d_small", "label": "small"},
                {"card_id": "tumor-protein-abundance-cptac", "threshold": "cohens_d_medium", "label": "medium"},
                {"card_id": "tumor-protein-abundance-cptac", "threshold": "cohens_d_large", "label": "large"},
            ],
        },
    ],
    "tumor_vs_adjacent_expression": _allgene_percentile_frame("tumor-rna-vs-adjacent"),
    "sc_tumor_celltype_expression": {
        "kind": "comparator_delta",
        "value_field": "malignant_detection_fraction",
        "scale": "detection_fraction",
        "position_field": "sc_expression_class",
        "anchors": [
            {"role": "comparator", "field": "top_microenvironment_detection_fraction", "label": "microenvironment"}
        ],
    },
}
for _mt, _extra in _SECONDARY_FRAMES.items():
    _spec = SALIENCE_SPECS.get(_mt)
    if _spec is None:
        continue
    _new = _extra if isinstance(_extra, list) else [_extra]  # a mt may append >1 secondary frame
    _rf = _spec.get("reference_frame")
    if _rf is None:
        _spec["reference_frame"] = list(_new)
    elif isinstance(_rf, list):
        _rf.extend(_new)
    else:
        _spec["reference_frame"] = [_rf, *_new]

# FLEET-WIDE cohort ruler (Phase 2, fleet roll after the 4-meter pilot): every axis that carries a numeric
# reference_frame ALSO gets a `cohort_percentile` frame appended LAST — the card value placed as its
# percentile within the known-target cohort read from the re-frozen target-archetype atlas. The atlas
# numeric feature is keyed off the PRIMARY frame's value_field (feature_vectoriser.numeric_feature_specs),
# so the cohort_key is `{mt}::num::{primary.value_field}`. VERDICT-INERT + SELF-GATING: the reader
# (archetype_core.cohort_percentile) returns None when the atlas column is absent or under-powered (n<20),
# so build_interpretation silently drops the frame — a sparse axis carries no cohort ruler until the atlas
# grows, and no per-axis min-N bookkeeping is needed here. Skips the pilot axes already carrying one.
#
# OPT-OUT (2026-09-12): this flag is the ONLY mechanism that makes a frame genuinely display-only, which is
# why REACH OF A `reference_frame` at the top of this file points here. It is also a ONE-WAY DOOR with no
# red of its own — adding it to a shipped axis deletes a frozen column at the next re-freeze, and
# atlas_health reads a self-consistent narrowing as green — so the set of opt-outs is ratcheted in
# test_reference_frame_governance invariant 5.
# A frame carrying `atlas_numeric: False` is a DISPLAY-ONLY ruler and gets no cohort
# ruler either. The registry is shared — numeric_feature_specs() mints an atlas feature from every PRIMARY
# frame — so before this flag existed, adding a display ruler to a card whose gauged value is NOT monotone
# with "more supportive" (a mutation-SHAPE fraction: high missense reads driver for an oncogene and
# passenger for a TSG) also minted a polarity-ambiguous atlas feature, and _DIR_SIGN would have baked the
# wrong sign into the phenotype geometry for half the corpus. A cohort_percentile on such an axis is dead
# by construction (its atlas column is never built), so skipping it here avoids a vacuous frame too.
for _mt, _spec in SALIENCE_SPECS.items():
    _rf = _spec.get("reference_frame")
    _frames = _rf if isinstance(_rf, list) else ([_rf] if isinstance(_rf, dict) else [])
    if not _frames or any(isinstance(f, dict) and f.get("kind") == "cohort_percentile" for f in _frames):
        continue
    _primary = _frames[0]
    if _primary.get("atlas_numeric") is False:
        continue
    _vf, _scale = _primary.get("value_field"), _primary.get("scale")
    if not (_vf and _scale):
        continue
    _cohort_frame = {
        "kind": "cohort_percentile",
        "value_field": _vf,
        "scale": _scale,
        "cohort_key": f"{_mt}::num::{_vf}",
    }
    if isinstance(_rf, list):
        _rf.append(_cohort_frame)
    else:
        _spec["reference_frame"] = [_rf, _cohort_frame]


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
    for a in cap.get("numeric_anchors") or []:
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
    for a in (cap or {}).get("categorical_anchors") or []:
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


# ── SALIENCE IN BITS (Stage 1 of the retire-ranking-by-rules arc) ─────────────────────────────────────
# How SURPRISING is this card's value, measured against the frozen known-target cohort rather than against
# a hand-set rung? The unit is bits of self-information, so it is comparable across axes with no shared
# scale and no tuned weights — which is the whole point: `priority:` ladders churned +373/-207 lines in 60
# days precisely because ranking was encoded as hand-ordered rungs.
#
#   I_R(f) = -log2 p_hat,   p_hat = max( 2 * min(pct, 100-pct) / 100 , 1/(n+1) )
#
# TWO-SIDED, because a target at the 2nd percentile of a dependency column is exactly as informative as one
# at the 98th — the direction is already carried by `direction`/_DIR_SIGN, and folding it into the surprise
# would double-count polarity. A value at the median scores 0 bits: "unremarkable" is the correct reading of
# a middling number, not a small positive score.
#
# The 1/(n+1) FLOOR is the resolution cap the plan writes as `min(-log2 p_hat, log2(n_R+1))` — identical,
# because -log2(1/(n+1)) == log2(n+1). Stating it as a floor on p_hat rather than a ceiling on the bits
# makes the reason legible: an n-sample empirical column cannot express a tail smaller than one target's
# worth, so the most extreme value in a 180-target column is worth log2(181) ~= 7.5 bits and NOT infinity.
# Without it the extremum scores inf and wins every argmax forever (the same failure mode as the +-Inf
# log2FC rows that mis-attributed 1,564 genes: a non-finite sentinel is a number, and abs(inf) wins).
#
# THREE EXCLUSIONS, each measured rather than assumed:
#   1. NO q-VALUE PASS-THROUGH. "A q-value is already a tail probability, don't re-surprise it" is true in
#      general and wrong on this substrate: a driver q is ~0 for every gene that has one, so -log2 q is
#      maximal for essentially the whole corpus — the axis discriminates nothing while ranking as the most
#      surprising thing in the profile. Enforced two ways: bits ride the `cohort_percentile` frame only, so
#      a spec's `significance_field` is structurally out of reach, AND `scale` in _UNRANKABLE_SCALES is
#      refused in case a frame is ever authored directly over a q/p column.
#   2. atlas_numeric: False IS HONOURED. Those axes deliberately mint no atlas numeric while keeping a
#      display ruler, because a mutation-SHAPE fraction has no fixed polarity (high missense reads driver
#      for an oncogene and passenger for a TSG). Scoring them scores what was excluded on purpose.
#   3. THE REFERENCE MUST BE USABLE. reference_mask_fraction >= 0.6, read from the artifact. A column
#      measured in 48% of the corpus ranks against half a cohort; ::mask columns are excluded outright
#      (see cohort_reference_quality — the artifact records 1.000 for all 32 by construction).
#
# BITS ARE WITHHELD, NOT DEFAULTED. Every refusal above emits `bits_withheld: "<reason>"` and no `bits` key.
# This is the frame self-drop discipline that already governs _project_frame, extended one step: an absent
# atlas column must report NOTHING, because computing log2(n+1) against an empty column yields a confident
# 0 that is indistinguishable from a genuinely median value. A missing number that carries its own reason
# is auditable; a 0 that means "we could not look" is the display projection that guessed fleet-wide for
# months and survived because it was verdict-inert, so it still rendered — just wrong.
#
# DISPLAY-ONLY / VERDICT-INERT: additive keys on a gauged_value no gate reads. ACCURATE — and note this is a
# claim about the two ADDED KEYS, not about a reference_frame's reach: no atlas column is keyed off them.
_UNRANKABLE_SCALES = frozenset({"qvalue", "pvalue", "q_value", "p_value"})


def cohort_bits(percentile, n) -> float | None:
    """Two-sided empirical surprise in bits for a value at `percentile` within an n-sample cohort column.
    None when the inputs cannot support a number at all. 0.0 at the median is a real answer, not a miss."""
    if not isinstance(percentile, (int, float)) or isinstance(percentile, bool):
        return None
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        return None
    pct = min(max(float(percentile), 0.0), 100.0)
    p_hat = max(2.0 * min(pct, 100.0 - pct) / 100.0, 1.0 / (n + 1))
    v = round(-math.log2(min(p_hat, 1.0)), 3)
    # -log2(1.0) is -0.0, which round() preserves and json.dumps writes as "-0.0" — a signed zero would
    # make an exactly-median card byte-unstable against any golden written the other way. Normalise it.
    return 0.0 if v == 0 else v


def _bits_for_cohort_frame(rf: dict, pct, n, scope=None) -> tuple:
    """(bits, withheld_reason) for ONE cohort_percentile frame — exactly one of the two is None.

    ★ THE SCOPED QUALITY CHECK IS ADDITIONAL, NEVER A SUBSTITUTE, and that is what makes it safe to land.
    The pan-cancer gate below runs unchanged and first; only then, when the percentile was drawn from a
    NARROWED cohort, must that cohort ALSO be adequately measured. So the change is monotone — it can only
    ever WITHHOLD bits that today's code awards, never award bits today's code withholds — and a
    pre-2.0.0 artifact (no `reference_mask_fraction` at all) is still handled entirely by exclusion 3a.

    Why it is needed: `reference_mask_fraction` is a WHOLE-CORPUS number, so on a scoped gauge it certifies
    the wrong population. MEASURED on the 2026-09-13 atlas: of the 87 (indication x cohort_key) pairs that
    clear min_n=20, 71 would award bits, and ZERO of those 71 sit on a scoped cohort measured below the
    0.6 floor — so this gate changes nothing today. But the worst surviving margin is 0.622 against a
    0.600 floor (28 of 45 COADREAD rows on measured_potency_tractability), i.e. ONE target of slack, and
    step 5 adds 207. Same shape as the PCA solver pin: a no-op now, a landmine at the next re-freeze. The
    branch is therefore exercised by an explicit under-measured-scope test rather than by production."""
    if rf.get("atlas_numeric") is False:
        return None, "display_only_ruler"  # exclusion 2: no atlas numeric was minted on purpose
    if str(rf.get("scale") or "").lower() in _UNRANKABLE_SCALES:
        return None, "significance_scale_not_rankable"  # exclusion 1
    key = rf.get("cohort_key")
    from _skills_common.archetype_core import (
        PAN_CANCER_SCOPE,
        USABLE_REFERENCE_MASK_FRACTION,
        cohort_reference_quality,
    )

    q = cohort_reference_quality(key)
    if q is None:
        return None, "reference_quality_unknown"  # exclusion 3a: absent column / pre-2.0.0 artifact / ::mask
    if q < USABLE_REFERENCE_MASK_FRACTION:
        return None, f"reference_undermeasured_{q:.2f}"  # exclusion 3b — the fraction is IN the reason
    if scope and scope != PAN_CANCER_SCOPE:
        qs = cohort_reference_quality(key, indication=scope)
        if qs is None:
            return None, "scoped_reference_quality_unknown"  # exclusion 3c
        if qs < USABLE_REFERENCE_MASK_FRACTION:
            return None, f"scoped_reference_undermeasured_{qs:.2f}"  # exclusion 3d — names the scoped frac
    bits = cohort_bits(pct, n)
    return (bits, None) if bits is not None else (None, "percentile_unreadable")


# NO CROSS-FRAME AGGREGATOR SHIPS HERE, and that is a measured decision rather than an omission.
#
# The plan's score was S(f) = rho * c * lambda * min_R I_R(f) — a minimum over the reference frames R
# available for a fact. Two measurements taken against the 2026-09-13 atlas (297 targets, 20 usable
# reference columns) before writing a line of it:
#
#   1. min_R IS VACUOUS TODAY. Sweeping all 60 SALIENCE_SPECS, the per-spec count of cohort_percentile
#      frames is at most ONE (histogram: 28 specs with 0, 32 with exactly 1). The fleet loop appends one
#      cohort ruler per axis and skips any spec that already has one, so `min` over frames can never
#      differ from `max`. A minimum that cannot discriminate is decoration.
#   2. AGGREGATING ACROSS AXES RANKS THE NEGATIVE CONTROLS FIRST. Ranking all 297 corpus targets by the
#      mean of their top-5 bits puts the curated controls at ranks 1, 2, 3, 4, 6, 7 — OTX2 and MYH6
#      (control_absent), GAPDH, ACTB, PPIA, RPLP0 (control_housekeeping) — 10 of the top 20. The plan
#      pre-registered exactly this as a kill criterion, and it fires.
#
# The cause is NOT the bit formula and NOT the two-sided tail. A one-sided supportive-tail variant is
# WORSE (8 of 20, housekeeping at ranks 1-2-3). The cause is that 10 of the 20 usable columns are one
# measurement read ten ways — cell-line RNA, tumour RNA, normal-tissue breadth, tumour-vs-adjacent,
# tumour-vs-normal, single-cell, cell-line protein, IHC presence, elevation breadth, percentile crossing
# are all "how much of it is there". Summing them treats ten correlated readings as ten independent
# references, so a gene that is extreme on that ONE thing is credited ten times — which is the definition
# of a housekeeping control. Collapsing that family to a single column drops the controls from 10-of-20
# to 1-of-20 and turns the head of the list into KIF11, RRM1, SF3B1, MYC, EGFR.
#
# So the aggregation needs a correlation structure, not a tuning constant. Adding rho/c/lambda scalars
# here would re-create by hand exactly the ranking-by-tuned-rungs treadmill this work exists to retire.
# The atlas's `feature_corr` block was deferred at the last freeze for want of a consumer; the measurement
# above IS the consumer, and it now has a number attached. Until it ships, this module exposes the
# per-frame measurement only and refuses to add frames together.


def _project_frame(
    rf: dict, cap: dict, summary: dict, direction, card_id, contracts_repo, indication=None
) -> dict | None:
    """Project ONE reference_frame dict → a single gauged_value, or None when its value is absent (so a
    frame whose metric is not measured drops out, never null-fills). Enforces 'no bare number'
    (value ⇒ scale). Extracted so build_interpretation can iterate a LIST of frames on one card.

    `indication` scopes the cohort_percentile frame only; every other frame kind is indication-INVARIANT
    (they read the card's own summary/thresholds, which are already the requested indication's numbers)."""
    if not isinstance(rf, dict):
        return None
    # COHORT-PERCENTILE (Phase 2 meter): position the card value WITHIN the frozen known-target cohort read
    # from the re-frozen atlas (`cohort_key` = `{measurement_type}::num::{value_field}`), instead of only
    # against a fixed card cut. The value is polarity-signed to match the atlas convention (higher ==
    # stronger) via the spec's `direction`, so a larger percentile always means "stronger than more known
    # targets". Under-powered/absent columns drop the frame (never a bare or over-claimed number).
    # DISPLAY-ONLY / verdict-INERT — ACCURATE: this READS the shipped atlas artifact and feeds no gate, and
    # the cohort frame it appends lands LAST, so it mints nothing. It is the CONSUMER of the columns rf[0]
    # mints, which is why a re-freeze moves every value it returns.
    if rf.get("kind") == "cohort_percentile":
        raw = _read_num_field(rf.get("value_field"), summary, cap)
        scale = rf.get("scale")
        if raw is None or not scale:
            return None
        from _skills_common.archetype_core import PAN_CANCER_SCOPE, cohort_percentile
        from _skills_common.feature_vectoriser import _DIR_SIGN

        res = cohort_percentile(rf.get("cohort_key"), _DIR_SIGN.get(direction, 1.0) * raw, indication=indication)
        if res is None:
            return None
        # Direction-aware phrasing: the percentile is always "signed value exceeds X% of the cohort".
        # For a stronger-is-better axis that reads "stronger than X%"; for a higher_is_worse LIABILITY axis
        # (e.g. normal-tissue breadth) the same rank is a worse liability, so say "higher-liability than X%"
        # rather than mislabel a safety risk "stronger".
        pct, n, scope = res["percentile"], res["n"], res["scope"]
        rel = "higher-liability than" if direction == "higher_is_worse" else "stronger than"
        # NAME THE COHORT IN THE PROSE, not only in the machine-readable key. The pan-cancer wording stays
        # byte-identical to the pre-scoping string, so the 21-of-25 indications that fall back — and every
        # golden pinned against them — do not move; a SCOPED gauge appends " in <CODE>" so the reader sees
        # which cohort the number means without having to cross-reference `cohort_scope`.
        where = "" if scope == PAN_CANCER_SCOPE else f" in {scope}"
        gv = {
            "metric": rf.get("value_field"),
            "value": sig_round(raw),
            "scale": scale,
            "direction": direction,
            "frame": {"kind": "cohort_percentile", "anchors": []},
            "position": f"{rel} {pct:g}% of {n} known targets{where}",
            "cohort_percentile": pct,
            "cohort_n": n,
            "cohort_scope": scope,
        }
        # Stage-1 salience: two-sided empirical surprise in bits, or the REASON there is none. Reached only
        # after `res is not None`, so bits inherit this branch's existing self-drop for free — an absent or
        # under-powered atlas column drops the whole frame before we can report a confident 0 against it.
        bits, withheld = _bits_for_cohort_frame(rf, pct, n, scope)
        if bits is not None:
            gv["bits"] = bits
        else:
            gv["bits_withheld"] = withheld
        return gv
    value = _read_num_field(rf.get("value_field"), summary, cap)
    scale = rf.get("scale")
    if value is None or not scale:  # no bare frame without a value+scale
        return None
    gv = {
        "metric": rf.get("value_field"),
        "value": sig_round(value),
        "scale": scale,
        "direction": direction,
        "frame": {"kind": rf.get("kind"), "anchors": []},
    }
    pos = _read_str_field(rf.get("position_field"), summary, cap)  # READ VERBATIM (never recomputed)
    if pos is not None:
        gv["position"] = pos
        gv["position_source"] = rf.get("position_field")
    dist = _read_num_field(rf.get("distance_field"), summary, cap)  # PREFER the summary's own delta
    if dist is not None:
        gv["distance_to_cut"] = sig_round(dist)
    anchors = []
    for a in rf.get("anchors") or []:
        if not isinstance(a, dict):
            continue
        av = _read_num_field(a.get("field"), summary, cap)
        if av is not None:
            anchors.append({"role": a.get("role"), "label": a.get("label"), "value": sig_round(av)})
    # total denominator (count_of_total): a named summary field → a `total` anchor (the "of N")
    total = _read_num_field(rf.get("total_field"), summary, cap)
    if total is not None:
        anchors.append({"role": "total", "label": rf.get("total_field"), "value": sig_round(total)})
    # single cut (distance_to_cut / floor_cut_ceiling / count_of_total) OR a ladder of cuts (graded_band)
    for cut in ([rf["cut"]] if isinstance(rf.get("cut"), dict) else []) + list(rf.get("cuts") or []):
        if not isinstance(cut, dict):
            continue
        cv = contract_threshold(cut.get("card_id") or card_id, cut.get("threshold"), contracts_repo)
        if cv is not None:
            anchors.append({"role": "cut", "label": cut.get("label") or cut.get("threshold"), "value": sig_round(cv)})
    gv["frame"]["anchors"] = anchors
    # STAGE-3 convergence (2026-09-18): surface distance_to_cut on the DISPLAY gauged_value too — value − cut,
    # computed byte-for-byte the way claim_record.magnitude_from_interpretation does it (first `cut` anchor,
    # the sig_round'd gv value, round(,4)), so the display ruler and the factored record carry ONE coordinate
    # (claim_record reads it straight from here when present). PREFER an already-surfaced delta (distance_field,
    # set above) — only compute when absent. A frame with NO cut anchor (e.g. cohort_percentile) keeps
    # distance_to_cut ABSENT/NULL, never 0. A graded_band takes its FIRST cut, matching claim_record.
    if "distance_to_cut" not in gv:
        _cut = next((a["value"] for a in anchors if a.get("role") == "cut"), None)
        if isinstance(_cut, (int, float)) and not isinstance(_cut, bool):
            gv["distance_to_cut"] = round(gv["value"] - _cut, 4)
    return gv


def build_interpretation(
    cap: dict,
    summary: dict,
    spec: dict | None = None,
    card_id: str | None = None,
    contracts_repo: str | None = None,
    indication: str | None = None,
) -> list:
    """Project spec['reference_frame'] → key_evidence.interpretation[] (list of gauged_value). Deterministic
    (sig_round every number; absent layer omitted, never null-filled); [] when no frame or no value present.
    Enforces 'no bare number': a value is emitted only with a non-null scale.

    `reference_frame` is a dict OR a list of dicts — one card can carry >1 ruler (e.g. a distribution card
    gauged BOTH on its pan-cancer rank AND on its within-panel position). Frames are projected in order;
    frames whose value is absent drop out (a partially-measured card still emits the rulers it can).

    `indication` is the REQUEST's indication; it scopes the known-target cohort behind a cohort_percentile
    ruler (see archetype_core.cohort_percentile). Omitting it reproduces the pre-scoping pan-cancer gauge
    exactly, so a caller that has no indication in hand is never forced to invent one."""
    cap = cap or {}
    summary = summary or {}
    spec = spec or {}
    direction = spec.get("direction")
    rf = spec.get("reference_frame")
    frames = rf if isinstance(rf, list) else [rf]
    out = []
    for frame in frames:
        gv = _project_frame(frame, cap, summary, direction, card_id, contracts_repo, indication)
        if gv is not None:
            out.append(gv)
    return out


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
            from _skills_common.paths import DEFAULT_CONTRACTS_REPO

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
        for key in (
            "canonical_code",
            "oncotree_code",
            "depmap_lineage",
            "depmap_oncotree_lineage",
            "gtex_normal_tissue",
        ):
            v = e.get(key)
            if isinstance(v, str) and v:
                out.add(v.upper())
        for study in e.get("tcga_studies") or []:
            if isinstance(study, str) and study:
                out.add(study.upper())  # TCGA-COAD
                out.add(study.upper().replace("TCGA-", ""))  # COAD
    return frozenset(out)


__all__ = [
    "SALIENCE_SPECS",
    "SUBTYPE_SPECS",
    "spec_for",
    "indication_stratum_aliases",
    "sig_round",
    "build_interpretation",
    "contract_threshold",
    "cohort_bits",
]
