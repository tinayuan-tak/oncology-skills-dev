#!/usr/bin/env python
"""tumor-presence scorecard adapter (#1988, A0c) — the NORMATIVE example the sibling adapters
(#1989-#1993) copy.

Epic #1985's component scorecard (A0a, `_skills_common.component_scorecard`) records ONE cell per
``(skill x layer)`` with four independent criteria — accuracy / utilization / fail_open /
panel_consistency, each GREEN|RED|NULL — plus a cell-level ``built`` flag. This script is the ENTIRE
adapter write surface for tumor-presence: it builds the shard in memory and calls
``write_skill_shard``, which touches exactly ``scorecard/tumor-presence.json``.

## Layer mapping (this skill's own architecture, not a generic guess)

The generic ``L1/L2a/L2b/L3/L4`` grain maps onto tumor-presence's landed evidence-property layers
(``_skills_common.evidence_frame.ClaimType`` + the reference-vertical epic #1938):

  L1  — the 18 cards themselves (OBSERVATIONAL_PROPERTY): raw per-card measurements + their
        disposition ledger (``field_disposition.yaml``).
  L2a — ``source_properties`` (SK#1941 EXPORTED section): the per-source observational properties,
        formalized as a named, reconstructable export.
  L2b — ``integrated_properties`` (SK#1941 EXPORTED section): the concordance ISLANDS built earlier
        (coverage #1517/#1578, abundance #1589/#1594, subtype_restriction #1830/#1840).
  L3  — ``l3d`` (SK#1940, DOMAIN_INTERPRETATION): the "tumor-expression biology story" — a
        within-domain, claim-ID-traceable synthesis over the L2b islands.
  L4  — SYNTHESIS / decision views. Epic #1938 explicitly puts this OUT OF SCOPE for the tumor-presence
        reference vertical ("L4 facet synthesis + decision views (deferred horizontal epic)") — so
        ``built=False`` (NOT_BUILT), not a defect.

## What "accuracy" means at each layer (and why L2a/L2b/L3 are honestly NULL there)

Only L1 carries genuine raw-substrate re-derivation in this shard: L2a/L2b/L3 are DETERMINISTIC
re-projections/aggregations over L1's already-validated card summaries (no new arithmetic over raw
substrate) — independently re-deriving them from S3 would just re-run L1's own accuracy check under a
different name. Per the directive ("leave a criterion NULL rather than fabricate a reading you cannot
support"), their accuracy criterion is NULL with that reasoning recorded in evidence, not a fabricated
GREEN riding on L1's coattails.

## Panel-consistency is COMPUTED, not hand-typed (the teeth)

`collect_panel_rows()` is the live function that makes the L1 panel_consistency GREEN a property of
the package BYTES, not an author's claim: it loads (or live-emits + caches, via `_load_package`) each
of the 5 roster pairs' tumor-presence decision.json, extracts two verdict-bearing card classes, and
computes three non-vacuity checks (classes aren't constant across the roster; the thin-coverage
control genuinely degrades relative to the others). `skills/tumor-presence/tests/test_scorecard_shard.py`
monkeypatches `_load_package` with a doctored (constant-class / all-missing) panel and asserts the
checks go RED — proving the checks have teeth, independent of live data or network access.

NOTE ON PROVENANCE (a genuine finding worth carrying forward to A0b + the sibling adapters):
`eval/run_scorecard_panel.py --emit` (the A0b #2000 harness, which drives target-profile's full
15-subskill `--full-package`) TIMED OUT at 900s for BOTH EPCAM and HTR1D in this environment (see
`eval/scorecard_panel_report.json`, generated 2026-09-28T19:13:30Z) — the full composition is too slow
for that timeout on a richly- or thinly-covered target alike. `_load_package` therefore drives
tumor-presence's OWN, much lighter entrypoint directly (`scripts/run.py --target <T> --indication <I>`,
no `--full-package` fan-out), which finishes in well under a minute per target and reads the identical
cards.

## Evidence recipe siblings should copy

Every evidence dict below either (a) names a COMMITTED, currently-green test (accuracy/utilization/
fail_open — re-run before trusting the shard) or (b) is COMPUTED live from real per-target packages
(panel_consistency), never a static claim with no test/artifact behind it.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
SKILLS_ROOT = SKILL_DIR.parent
REPO_ROOT = SKILLS_ROOT.parent

from _skills_common import component_scorecard as cs  # noqa: E402

SKILL = "tumor-presence"

# ── L1 evidence: accuracy / utilization / fail_open (test-backed, static evidence dicts) ──────────

_L1_ACCURACY_EVIDENCE = {
    "method": (
        "Independent raw-substrate re-derivation, reusing analysis-methods' T3 recomputation anchors "
        "(plan foamy-bird Stage I) one step further than analysis-methods' own tests: asserts the "
        "re-derived number ALSO equals the tumor-presence golden's card summary for the same "
        "target/indication, so two repos' independent captures must agree at full float64 precision."
    ),
    "test": "skills/tumor-presence/tests/test_scorecard_l1_accuracy_rederivation.py",
    "batch_a_test": "skills/tumor-presence/tests/test_scorecard_l1_accuracy_rederivation_batch_a.py",
    "batch_b_test": "skills/tumor-presence/tests/test_scorecard_l1_accuracy_rederivation_batch_b.py",
    "batch_c_test": "skills/tumor-presence/tests/test_scorecard_l1_accuracy_rederivation_batch_c.py",
    "batch_d_test": "skills/tumor-presence/tests/test_scorecard_l1_accuracy_rederivation_batch_d.py",
    "batch_e_test": "skills/tumor-presence/tests/test_scorecard_l1_accuracy_rederivation_batch_e.py",
    "batch_f_test": "skills/tumor-presence/tests/test_scorecard_l1_accuracy_rederivation_batch_f.py",
    "cards_covered": [
        "cellline-rna-distribution",
        "tumor-scrna-celltype-expression",
        "tumor-rna-distribution",
        "cellline-protein-abundance",
        "tumor-rna-vs-adjacent",
        "tumor-elevation-breadth",
        "tumor-protein-abundance-cptac",
        "cellline-rna-protein-concordance",
        "rna-protein-concordance-tumor",
        "expression-purity-confound",
        "hpa-pathology-cancer-ihc",
        "sc-normal-celltype-expression",
        "normal-tissue-liability",
        "tumor-rna-distribution-by-subtype",
        "cellline-rna-distribution-by-subtype",
        "tumor-protein-distribution-by-subtype",
        "cellline-protein-abundance-procan",
    ],
    # 17 of 17 — the roster is CLOSED (batch F, #2088). Batch F enrolled the final four (the
    # by-subtype distribution trio + the ProCan cell-line protein card) via analysis-methods
    # subtype-panorama / procan recomputation anchors bridged to the EPCAM/COADREAD golden.
    "cards_not_yet_covered": [],
    "raw_substrate": {
        "cellline-rna-distribution": "analysis-methods anchor epcam_26q1.cellline_rna_distribution.json "
        "+ expression_vectors/epcam_26q1.cellline_rna_distribution.parquet (2446-model raw log2(TPM+1) "
        "panel + resolved lineage)",
        "tumor-scrna-celltype-expression": "analysis-methods anchor epcam_coadread.sc_celltype.json + "
        "sc_compartment_rows/sc_pseudobulk__compartment_rows.parquet (raw per-(dataset,donor,"
        "compartment) pseudobulk rows)",
        "tumor-rna-distribution": "analysis-methods anchor epcam_coadread.tumor_rna_distribution.json "
        "(batch A, #2043) — REUSES the already-committed tumor_normal_tpm/recount3_gtex__"
        "percentile_crossing_vectors.parquet (the same raw per-sample tumor log2(TPM+1) vector the "
        "tumor-vs-normal-percentile-crossing anchors freeze; read_tumor_expression_distribution and "
        "read_tumor_vs_normal_percentile_crossing both read it through the identical read_tumor_samples)",
        "cellline-protein-abundance": "analysis-methods anchor epcam_gygi.cellline_protein_abundance.json "
        "(batch A, #2043) + protein_vectors/epcam_gygi.cellline_protein_abundance.parquet (375-model raw "
        "Gygi TMT log2-abundance panel + resolved lineage) + the shared panel-wide all-protein median "
        "null (protein_vectors/depmap_gygi_allgene_median_null.parquet)",
        "tumor-rna-vs-adjacent": "analysis-methods anchor epcam_coadread.tumor_rna_vs_adjacent.json "
        "(batch B, #2044) + dge_rows/coadread-dge-df06320__log2fc_null.parquet (the raw provider gene "
        "row from the per-indication tumor-vs-adjacent DESeq2 product expression-rna-tumor-vs-adjacent, "
        "plus the product's all-gene log2FoldChange null); re-derived through "
        "onc_methods.dge_deseq2.read.read_dge_gene_row. BOUNDARY: gtex_log2_fc/gtex_q_value come from a "
        "separate GTEx reader (not read_dge_gene_row) and are NOT bridged; the adjacent-arm adequacy "
        "logic (#864/#865) is sensitivity-family only and does NOT reach this path.",
        "tumor-elevation-breadth": "analysis-methods anchor epcam.tumor_elevation_breadth.json "
        "(batch B, #2044), two-layer: dge_rows/epcam.cptac_cohort_rows.parquet (per-cohort CPTAC rows "
        "-> methods.cptac_protein_deg.read.read_tumor_elevation_breadth, the PRIMARY layer) + "
        "dge_rows/epcam.rna_stack_rows.parquet (stacked pancan rows -> "
        "onc_methods.dge_deseq2.derive_pancan_stack.read_rna_tumor_elevation_breadth). Validates the "
        "elevated-cohort counting + pan-cohort BH/FDR + composite-indication dedupe roll-ups, NOT the "
        "upstream DEG runs.",
        "tumor-protein-abundance-cptac": "analysis-methods anchor epcam_coad.cptac_protein_abundance.json "
        "(batch C, #2045) + dge_rows/epcam.cptac_target_rows.parquet (the target's raw per-cohort CPTAC "
        "df rows) + dge_rows/epcam_coad.cptac_allgene_effect_null.parquet (the matched cohort's all-gene "
        "protein_effect_size null, the within-cohort percentile denominator); re-derived through "
        "onc_methods.cptac_protein_deg.read.read_target_summary (only the _load_indexed S3-load seam mocked). "
        "WITHIN-COHORT SEMANTICS (#1512/#1664): COADREAD is a LEAF indication -> a single CPTAC cohort "
        "(COAD), so the representative-cohort pick is over one candidate and NO cross-cohort aggregation "
        "of non-comparable TMT ratios occurs on this path; the all-gene percentile is a within-cohort rank.",
        "cellline-rna-protein-concordance": "analysis-methods anchor "
        "epcam_26q1.cellline_rna_protein_concordance.json (batch D, #2046) + rna_protein_concordance_vectors/"
        "epcam_26q1.cellline_rna_protein_concordance.{rna,protein}.parquet (the gene's full per-ModelID "
        "DepMap RNA log2(TPM+1) dict + the full Gygi TMT protein log2-abundance dict); re-derived through "
        "onc_methods.depmap_rna_protein_concordance.read.read_rna_protein_concordance (only the _paired_rna_protein "
        "S3-load seam mocked), pinned at 26q1 to match the committed golden's DepMap vintage.",
        "rna-protein-concordance-tumor": "analysis-methods anchor "
        "epcam_coadread.tumor_rna_protein_concordance.json (batch D, #2046) + rna_protein_concordance_vectors/"
        "epcam_coadread.tumor_rna_protein_concordance.parquet (the matched per-tumor CPTAC "
        "(patient_id, gene, rna_log2tpm, protein_log2abundance, cohort) rows from "
        "cptac-rna-protein-matched-per-sample-v1); re-derived through "
        "onc_methods.depmap_rna_protein_concordance.read.read_tumor_rna_protein_concordance (only the "
        "_read_matched_cohort S3-load seam mocked).",
        "expression-purity-confound": "analysis-methods anchor epcam_coadread.expression_purity_confound.json "
        "(batch D, #2046) + purity_confound_vectors/epcam_coadread.expression_purity_confound.{expr,purity}.parquet "
        "(per-sample recount3 tumor [case, log2_tpm] rows + per-case ABSOLUTE purity from the TCGA pancanatlas "
        "static snapshot); re-derived through methods.expression_purity_confound.read.read_expression_purity_confound "
        "(read_tumor_samples_with_case + _load_purity_by_case seams mocked). NO slope field is emitted (Pearson r, "
        "Spearman r, Pearson p, median purity, IQR only).",
        "hpa-pathology-cancer-ihc": "analysis-methods anchor epcam_coadread.hpa_pathology_cancer_ihc.json "
        "(batch D, #2046) + hpa_ihc_rows/epcam.hpa_pathology_cancer_ihc.rows.parquet (the per-cancer-type product "
        "rows for the gene from hpa-pathology-cancer-ihc-per-gene-v1); re-derived through "
        "onc_methods.hpa_pathology_cancer_ihc.read.read_target_summary (pyarrow read_table seam mocked). BOUNDARY: the "
        "reader is a LOOKUP, not an aggregation — the n_*/fraction/protein_presence_class patient-count aggregation "
        "is precomputed UPSTREAM in data-catalog's hpa-pathology-cancer-ihc-per-gene-v1 build (no aggregation "
        "arithmetic exists in analysis-methods); the anchor validates the OncoTree->HPA cancer-type resolution + "
        "gene predicate + cancer_type row selection + field projection path.",
        "sc-normal-celltype-expression": "analysis-methods anchor epcam_coadread.sc_normal_celltype.json "
        "(batch E, #2047) + sc_normal_celltype_rows/epcam_coadread.sc_normal_celltype_rows.parquet (the "
        "per-(tissue, cell_type) Tier-1 cross-donor-aggregated rows across all 9 queried tissues); "
        "re-derived through methods.sc_normal_expression.cli.build_summary (only the "
        "read_gene_celltype_rows S3-load seam mocked). DO-NOT-REFILE: the Tier-1 product's cross-donor "
        "aggregate is an UNWEIGHTED cross-donor median BY DESIGN (data-catalog's Tier-2->Tier-1 build, "
        "out of scope for this anchor, which validates the READ + CLASSIFY path only).",
        "cellline-protein-abundance-procan": "analysis-methods anchor epcam.procan_protein_abundance.json "
        "(batch F, #2088) + procan_vectors/epcam.procan_rows.parquet (the accession's per-model raw "
        "ProCan DIA/SWATH log_abundance rows, uniprot_base==P16422) + procan_vectors/"
        "procan_allprotein_median_null.parquet (the panel-wide all-protein median null, one row per "
        "protein at its median — the percentile + broadly_high denominators the product ships no "
        "sidecar for); re-derived through onc_methods.procan_protein_abundance.cli.load_and_classify"
        "(product_path=, null_path=) with the symbol->UniProt lookup pinned to the captured accession. "
        "HONEST DRIFT (pinned, cross-linked #2061/#2261, golden NOT regenerated): every numeric field "
        "(median/p5/p25/p75/p95/IQR/fraction_detected/allgene_percentile) is BYTE-EXACT vs the golden, "
        "but protein_expression_class re-derives lineage_restricted->sub_broad_detection (the golden "
        "predates the current detection-band classifier, which also emits the new "
        "protein_high_abundance_class_cutoff key) — a pure classifier evolution over identical substrate.",
        "cellline-rna-distribution-by-subtype": "analysis-methods anchor "
        "epcam_coadread.cellline_rna_subtype.json (batch F, #2088) + subtype_panorama_vectors/"
        "epcam.depmap_tpm_26q3.json (the gene's full per-ModelID DepMap 26Q3 log2(TPM+1) dict) + "
        "subtype_panorama_vectors/coadread.depmap_subgroup_assignments.parquet (the DepMap-side MSI "
        "assignment shard); re-derived through onc_methods.depmap_expression_distribution.read."
        "build_expression_subtype_panorama (seams _cached_tpm + subgroup_common.scoping.load_assignments "
        "mocked). HONEST DRIFT (pinned, cross-linked #2061, golden NOT regenerated across the vintage "
        "boundary — an owner call): the golden is DepMap-26Q1, the live reader 26Q3 (subgroup_n 27->28, "
        "median 9.6038->9.6131, pooled 9.8646->9.8724, source_cohort/_data_source 26q1->26q3); plus the "
        "finer AM#659 exploratory grade (underpowered->exploratory, same not-`measured` state), the "
        "now-emitted subtype_enrich_log2_delta (None->1.0), and the new assignment_manifest stamp. The "
        "verdict-bearing subtype_stratification_class / n_subtypes_measured + per-stratum class / "
        "fraction_expressed / subtype_signal are byte-stable.",
        "tumor-protein-distribution-by-subtype": "analysis-methods anchor "
        "epcam_coadread.tumor_protein_subtype.json (batch F, #2088) + subtype_panorama_vectors/"
        "epcam.cptac_per_sample.parquet (the target's raw per-aliquot CPTAC tumor-vs-reference "
        "log2_ratio rows) + subtype_panorama_vectors/coadread.cptac_subgroup_assignments.parquet (the "
        "CPTAC MSI assignment shard); re-derived through onc_methods.cptac_protein_distribution.read."
        "build_protein_subtype_panorama (seams cptac_protein_deg.read.read_per_sample + "
        "subgroup_common.scoping.load_assignments mocked). Every measured value (median_log2_ratio / "
        "class / detectable_fraction / subgroup_n / subtype_signal / pooled_cohort_median) is BYTE-EXACT "
        "vs the golden; HONEST DRIFT (pinned, cross-linked #2061): the finer exploratory grade "
        "(underpowered->exploratory), the now-emitted subtype_enrich_log2_delta (None->0.25), and the "
        "new assignment_manifest stamp.",
        "tumor-rna-distribution-by-subtype": "analysis-methods anchor "
        "epcam_coadread.tumor_rna_subtype.json (batch F, #2088) + subtype_panorama_vectors/"
        "epcam.tcga_long_tcga.parquet + epcam.gtex_long.parquet (the tumor + matched-normal per-sample "
        "log2(TPM+1) slices, the _read_gene seam) + tcga_uuid_barcode_sidecar.parquet (UUID->barcode "
        "case bridge) + coadread.tcga_subtype_assignments_union.parquet (the unioned molecular+MAF "
        "assignment shard) + pancanatlas_purity_by_case.json + epcam_coadread.tumor_allgene_percentile.json; "
        "re-derived through onc_methods.tcga_gtex_expression_distribution.cli.build_subtype_panorama "
        "(seams _read_gene, _load_sidecar, _load_subtype_assignments, _tumor_allgene_percentile, "
        "expression_purity_confound.read._load_purity_by_case, and scoping.load_assignments [the "
        "per-stratum join-coverage guard's independent second load] all mocked). ALL 25 scalar rollup "
        "fields + every per-stratum median/percentile/class/subtype_signal across all 14 strata are "
        "BYTE-EXACT vs the golden; HONEST DRIFT (pinned, cross-linked #2061, ADDITIVE): the golden's "
        "vintage dropped the per-stratum five-number spread (p5/q1/mean/q3/sd_log2tpm, AM#857) + the "
        "applied subtype_enrich_log2_delta (TC#811) — all None in the golden, values in the current "
        "reader on every stratum (one coefficient_of_variation differs only by ~1e-15 float "
        "re-association).",
        "normal-tissue-liability": "analysis-methods anchor epcam_coadread.hpa_normal_tissue_liability.json "
        "(batch E, #2047) + hpa_normal_liability_rows/epcam.hpa_normal_tissue_liability.row.json (the "
        "target's single raw HPA master-TSV row); re-derived through "
        "onc_methods.hpa_normal_tissue_liability.cli.compute_summary directly (no seam mock — pure function "
        "of its row argument). BOUNDARY: a LOOKUP + classification, not an aggregation — the IHC calls "
        "themselves are precomputed upstream by HPA.",
    },
    "reconciliation": (
        "fraction_expressed, fraction_highly_expressed, expression_class (cellline-rna-distribution); "
        "sc_expression_class, malignant_detection_fraction, malignant_abundance_log1p_cp10k, "
        "malignant_n_donors, malignant_n_cells, top_microenvironment_compartment "
        "(tumor-scrna-celltype-expression); median/p95/p99/min/max_log2tpm, coefficient_of_variation, "
        "distribution_pattern, detectable/moderate/high_fraction, tumor_expression_class "
        "(tumor-rna-distribution, batch A); fraction_detected, median/p5/p95_log2_abundance_panel, "
        "n_lineages_evaluated, n_lineage_restricted_lineages, protein_expression_class "
        "(cellline-protein-abundance, batch A); log2_fc, q_value, n_tumor, n_adjacent, base_mean, "
        "is_significant/is_actionable/is_upregulated_provider_call, expression_call_class, "
        "allgene_percentile(_class/_context) (tumor-rna-vs-adjacent, batch B); the protein-layer "
        "roll-up tumor_elevation_breadth_class, n_cohorts_tested/elevated, fraction_elevated, "
        "median_effect_across_elevated, most_elevated_cohorts, cohorts_tested + the RNA-layer "
        "vintage-stable rna_tumor_elevation_breadth_class, rna_n_indications_elevated, "
        "rna_median_max_log2fc_across_elevated, rna_most_elevated_indications "
        "(tumor-elevation-breadth, batch B); cohort, protein_expression_class, protein_effect_size, "
        "allgene_percentile(_class/_context), protein_bh_q_value, protein_p_value, "
        "protein_median_log2_tumor/normal, n_tumor/normal_samples, protein_effect_size_se, "
        "protein_effect_standardized_t/cohens_d/class/method (tumor-protein-abundance-cptac, batch C); "
        "the derived-statistics quartet (batch D, #2046): rna_protein_r/rna_protein_spearman/n_paired_models/"
        "protein_detection_fraction/rna_expressed_fraction/rna_high_protein_low_fraction/rna_as_biomarker/"
        "rna_proxy_classified_on/rna_proxy_class_boundary_fragile (cellline-rna-protein-concordance) and the "
        "cptac_cohort/substrate/rna_protein_r/rna_protein_spearman/n_paired_tumors/rna_as_biomarker/"
        "rna_proxy_classified_on/rna_proxy_class_boundary_fragile (rna-protein-concordance-tumor); "
        "purity_confound_class/n_paired_samples/n_expr_samples/median_purity (expression-purity-confound); "
        "and the full protein_presence_class/fraction_detected/fraction_moderate_strong/staining_score/n_high/"
        "n_medium/n_low/n_not_detected/n_patients_total/prognostic_* /hpa_cancer_type set "
        "(hpa-pathology-cancer-ihc, byte-exact); and batch E (#2047): "
        "sc_normal_expression_class/sc_normal_safety_essential_class/max_detection_cell_type/"
        "max_detection_fraction/expressing_donor_fraction_max/n_cell_types_above_20pct/"
        "n_reliable_cell_types/tissues_queried/origin_tissues/indication/method_version "
        "(sc-normal-celltype-expression) and normal_tissue_breadth_class/hpa_tissue_distribution/"
        "hpa_tissue_specificity/n_specific_tissues/specific_tissues/method_version "
        "(normal-tissue-liability, vintage-stable subset) "
        "all match at full precision between the independent "
        "recompute and tests/fixtures/epcam_coadread_decision.json (the two concordance ci95 bounds + the "
        "purity correlation coefficients are honestly-pinned verdict-inert drifts from batch D, and the "
        "sc-normal safety-essential-panel growth + normal-tissue-liability essential_tissue_flag flip are "
        "honestly-pinned drifts from batch E, see boundary); and batch F (#2088, the ROSTER CLOSER): the "
        "procan numeric distribution (median/p5/p25/p75/p95/IQR/fraction_detected/allgene_percentile), the "
        "cellline-rna-by-subtype + tumor-protein-by-subtype rollup class + per-stratum measured values, and "
        "ALL 25 tumor-rna-by-subtype scalar rollup fields + every per-stratum median/percentile/class/"
        "subtype_signal across the 14 strata all match at full precision; the batch-F drifts (procan class "
        "reclassification, the cell-line 26Q1->26Q3 vintage, the finer exploratory grade, the now-emitted "
        "subtype_enrich_log2_delta + five-number spread, and the new assignment_manifest / "
        "protein_high_abundance_class_cutoff stamps) are honestly-pinned verdict-inert drifts, see boundary)"
    ),
    "boundary": (
        "Anchors validate the read/aggregation path, NOT the upstream DESeq2/DEG runs (that provenance "
        "belongs to data-catalog). #1663: no n-field is fabricated — only fields the readers emit are "
        "asserted. DATA-LEVEL FINDING (honestly recorded, golden NOT regenerated): "
        "tumor-elevation-breadth's RNA-layer denominator drifted — the committed golden's "
        "rna_n_indications_tested=26 predates the current pancan-dge-tumor-vs-normal-v1 product's 27 "
        "indications (one NON-elevated indication added upstream). The elevated numerator (10), the "
        "elevated indication set, and the median max-log2fc are byte-identical, so only the denominator "
        "and its dependent rna_fraction_elevated shifted; pinned as denominator-only by "
        "test_elevation_breadth_rna_drift_is_denominator_only_and_non_elevated. "
        "#1664 CROSS-LINK (tumor-protein-abundance-cptac, batch C — honestly recorded, GREEN not RED): "
        "#1664 flagged read_target_summary's cross-cohort aggregation (representative-cohort pick over "
        "reference-pool-relative TMT ratios the manifest warns are NOT magnitude-comparable). The "
        "flagship EPCAM/COADREAD re-derivation reproduces the golden BYTE-EXACT because COADREAD is a "
        "LEAF indication -> a single CPTAC cohort (COAD): the representative-cohort pick is over one "
        "candidate, so NO cross-cohort aggregation of non-comparable ratios occurs on this "
        "verdict-bearing per-indication path, and the all-gene percentile is a within-cohort rank. The "
        "#1664-flagged aggregation is confined to the umbrella (NSCLC->LUAD+LSCC) and indication-FREE "
        "pan-cancer paths, where the #1664 F1 fix already ranks on the comparable |Cohen's d| axis "
        "(read.py read_target_summary). This card's within-cohort semantics are therefore sound; the "
        "#1664 concern does not bite the leaf-indication card path. "
        "#1510 ADJUDICATION (batch D, #2046 — SETTLED GREEN): #1510 flagged rna_proxy_classified_on as a "
        "corpus-tell that shipped rna_as_biomarker classes MIGHT have been computed on Pearson, not the "
        "intended Spearman. The re-derivation through the REAL reader reproduces rna_as_biomarker + "
        "rna_proxy_classified_on='spearman' byte-exact against the golden for BOTH concordance grains, and "
        "the reader provably classifies on the Spearman value (methods read.py G10). The AM half's KRAS "
        "cell-line anchor is the decisive witness: Pearson r=0.5524 would classify partial_proxy but Spearman "
        "r=0.3154 classifies poor_proxy, and the reader emits poor_proxy — so the class tracks Spearman, NOT "
        "Pearson. The #1510 concern is resolved GREEN on this read path (#1650's consumer of "
        "rna_proxy_class_boundary_fragile reads an accurate flag). "
        "TWO HONESTLY-RECORDED verdict-inert DRIFTS (golden NOT regenerated, class byte-stable, NOT silently "
        "normalized): (1) both concordance cards' ci95_low/high — the committed golden's Fisher-z CI used the "
        "PEARSON SE coefficient (1.0); the current reader uses the SPEARMAN coefficient (1.06, ~6% wider — the "
        "F3 fix), so the golden's ci95 predates F3 and the re-derived band is strictly WIDER on both bounds "
        "while rna_proxy_class_boundary_fragile + rna_as_biomarker are unchanged (pinned by "
        "test_cellline_ci95_drift_is_the_f3_prefix_wider_band_and_class_invariant + the tumor sibling, "
        "cross-linked #1510). (2) expression-purity-confound's correlation coefficients "
        "(expression_purity_pearson_r/_spearman_r/_pearson_p) drift at the ~4th decimal from the golden (the "
        "recount3 tumor-expression snapshot advanced slightly since the golden was built); "
        "purity_confound_class/n_paired_samples/n_expr_samples/median_purity are byte-exact, so the class is "
        "stable (pinned bounded + class-invariant by "
        "test_purity_correlation_drift_is_bounded_and_class_invariant). "
        "hpa-pathology-cancer-ihc reconciles BYTE-EXACT — its reader is a LOOKUP (the patient-count "
        "aggregation is precomputed upstream in data-catalog's hpa-pathology-cancer-ihc-per-gene-v1; the "
        "anchor validates the OncoTree->HPA resolution + selection + projection path, NOT the aggregation). "
        "BATCH E (#2047) — CORRECTED DENOMINATOR: the issue's own title claims '15/17->17/17, closes the "
        "roster'; the committed baseline this batch actually started from (batch D, PR#2068) carried "
        "11/17, so this batch closes 11->13/17, NOT the full roster (4 by-subtype/ProCan cards remain, "
        "see cards_not_yet_covered). TWO MORE HONESTLY-RECORDED verdict-inert DRIFTS (golden NOT "
        "regenerated — full structural regen tracked in #2061, behind the 26Q3 migration + #1638): "
        "(1) sc-normal-celltype-expression's safety-essential cell-type panel grew by 38 keys and lost "
        "exactly one (`interneuron`, a regex tightening to word-boundary matching) since the golden's "
        "vintage (stats.py #663/#664 renal-tubule + gut/pancreas fixes); every panel key the golden DOES "
        "carry, other than the one named removal, is byte-exact, and "
        "sc_normal_expression_class/sc_normal_safety_essential_class/max_detection_cell_type/"
        "max_detection_fraction are unchanged (pinned by "
        "test_sc_normal_schema_growth_is_additive_and_class_invariant). (2) normal-tissue-liability's "
        "essential_tissue_flag moves unknown->present for EPCAM (essential_tissues_flagged []->"
        "['intestine'], safety_tissue_flags gains essential_tissue) because 'intestine' was promoted to "
        "the canonical essential-tissue set on 2026-09-18 — predating, and unrelated to, the "
        "#1793/#1794 safety-pin bump this issue was held on; the golden simply predates that promotion. "
        "Two more keys (hpa_ihc_reliability, essential_tissue_low_reliability, AM#745 antibody "
        "reliability) are new and absent from the golden entirely. normal_tissue_breadth_class/"
        "hpa_tissue_distribution/hpa_tissue_specificity/n_specific_tissues/specific_tissues/"
        "method_version are byte-exact (pinned by "
        "test_hpa_liability_essential_tissue_flag_drift_is_pinned_verdict_inert_and_cross_linked_2061). "
        "BATCH F (#2088) — ROSTER CLOSER, FOUR HONESTLY-RECORDED verdict-inert DRIFTS (golden NOT "
        "regenerated — full structural regen incl. the cell-line 26Q1->26Q3 vintage boundary, a "
        "product-semantics OWNER call, tracked in #2061): (1) cellline-protein-abundance-procan's "
        "protein_expression_class re-derives lineage_restricted->sub_broad_detection over a BYTE-EXACT "
        "numeric substrate (the golden predates the current detection-band classifier + its new "
        "protein_high_abundance_class_cutoff key, #2261) — pinned by "
        "test_procan_class_drift_is_pinned_classifier_evolution_cross_linked_2061. (2) "
        "cellline-rna-distribution-by-subtype is DepMap-26Q1 in the golden vs 26Q3 live (subgroup_n "
        "27->28, median 9.6038->9.6131, pooled 9.8646->9.8724, source_cohort/_data_source 26q1->26q3) "
        "plus the finer AM#659 exploratory grade + the now-emitted subtype_enrich_log2_delta (None->1.0) "
        "+ the new assignment_manifest stamp; class/fraction_expressed/subtype_signal + the verdict-"
        "bearing rollup are byte-stable (pinned by "
        "test_cellline_rna_drift_is_vintage_and_emission_and_grade_pinned_2061). (3) "
        "tumor-protein-distribution-by-subtype's measured values are BYTE-EXACT; only the finer "
        "exploratory grade + the now-emitted subtype_enrich_log2_delta (None->0.25) + the new "
        "assignment_manifest stamp drift (pinned by "
        "test_cptac_protein_drift_is_grade_and_emission_and_stamp_pinned_2061). (4) "
        "tumor-rna-distribution-by-subtype's 25 scalar rollup fields + every per-stratum median/"
        "percentile/class/subtype_signal across all 14 strata are BYTE-EXACT; the golden's vintage "
        "dropped the per-stratum five-number spread (p5/q1/q3/mean/sd_log2tpm, AM#857) + the applied "
        "subtype_enrich_log2_delta (TC#811), all None in the golden and values in the current reader on "
        "every stratum, ADDITIVE-only (one coefficient_of_variation differs by ~1e-15 float "
        "re-association) (pinned by test_tumor_rna_additive_spread_and_delta_drift_is_pinned_2061)."
    ),
    "teeth": (
        "test_cellline_rna_distribution_teeth_mutated_input_breaks_the_golden_match, "
        "test_sc_celltype_teeth_dropping_malignant_rows_breaks_the_golden_match, "
        "test_tumor_rna_distribution_teeth_mutated_input_breaks_the_golden_match, "
        "test_cellline_protein_abundance_teeth_mutated_input_breaks_the_golden_match (batch A) and "
        "test_tumor_rna_vs_adjacent_teeth_flipping_significance_breaks_the_golden_match + the two "
        "batch-B elevation-breadth layer teeth (stripping elevated cohorts collapses the protein "
        "breadth; flipping RNA direction collapses the RNA breadth) and the two batch-C CPTAC teeth "
        "(forcing the matched-cohort row's protein_effect_size to +Inf collapses the class to "
        "data_unavailable; shifting the all-gene null moves the within-cohort percentile off the golden) "
        "and the batch-D (#2046) teeth — shuffling the protein values across models/tumors breaks the "
        "RNA<->protein correlation for both concordance grains (n_paired unchanged); permuting purity "
        "across cases breaks the expression<->purity correlation and forcing purity to track expression "
        "flips the class to tumor_intrinsic; dropping the resolved HPA cancer-type row collapses the IHC "
        "read to data_unavailable; and the batch-E (#2047) teeth — dropping every row for the named "
        "essential-organ driver cell type moves sc_normal_safety_essential_class off the golden's "
        "critical_organ_liability, and blanking the HPA specific-intensity column moves "
        "essential_tissue_flag/essential_tissues_flagged off their live-derived values; and the batch-F "
        "(#2088) teeth — emptying the frozen procan rows collapses protein_expression_class to "
        "data_unavailable (and its median off the golden), zeroing the frozen per-ModelID DepMap TPM "
        "moves the cellline-rna MSS stratum's class off broadly_high, emptying the CPTAC per-aliquot "
        "frame collapses tumor-protein n_subtypes_measured off the golden, and zeroing the frozen "
        "per-sample tumor log2(TPM+1) moves the tumor-rna CIMP_High stratum's median_log2tpm off the "
        "golden — mutate the raw input and assert the "
        "match breaks — proving the reconciliation is a live function of substrate, not a self-echo"
    ),
    "status_as_of": "2026-09-30",
}

_L1_UTILIZATION_EVIDENCE = {
    "method": (
        "field_disposition.yaml ledger: every emitted summary_field of all 18 cards carries an "
        "explicit disposition (signal|context|provenance|display); the REACH tier further requires "
        "every role:signal field be reached by a declared reader or carry a waived_because."
    ),
    "tests": [
        "skills/tumor-presence/tests/test_field_disposition_complete.py::test_ledger_wellformed (always runs)",
        "skills/tumor-presence/tests/test_field_disposition_complete.py"
        "::test_ledger_matches_emitted (ratchet vs run.py CARDS' emitted summary_fields)",
        "skills/tumor-presence/tests/test_field_disposition_complete.py"
        "::test_the_reach_measurement_is_not_vacuous (>= 60 role:signal rows measured)",
        "skills/tumor-presence/tests/test_field_disposition_complete.py"
        "::test_signal_fields_are_reader_reached_or_waived (zero un-reached, un-waived signal fields)",
    ],
    "coverage": "all 18 cards ledgered; ledger's own card set == run.py CARDS (test-enforced equality)",
    "status_as_of": "2026-09-28",
}

_L1_FAIL_OPEN_EVIDENCE = {
    "method": (
        "the shared open-world invariant (`_skills_common.claim_record`, 'ignorance != negation'): "
        "a data_unavailable/unreachable bucket forces state=unknown, direction=neutral, "
        "magnitude.level=none — never a manufactured directional finding."
    ),
    "tests": [
        "skills/tumor-presence/tests/test_claim_record_shadow.py::test_data_unavailable_open_world "
        "(ordinary path, pre-existing)",
        "skills/tumor-presence/tests/test_scorecard_l1_fail_open_probe.py"
        "::test_data_unavailable_degrades_conservatively_ordinary_path (ordinary path, re-asserted "
        "locally for this shard)",
        "skills/tumor-presence/tests/test_scorecard_l1_fail_open_probe.py"
        "::test_teeth_defeating_the_open_world_guard_lets_the_raw_token_leak (TEETH — monkeypatches "
        "claim_record.OPEN_WORLD_AVAILABILITY to frozenset() and shows finding.state leaks the raw "
        "'data_unavailable' token instead of 'unknown'; probe goes RED without the guard, GREEN with it)",
    ],
    "status_as_of": "2026-09-28",
}

# ── L1 panel_consistency: COMPUTED live from real per-target packages ──────────────────────────────

ROSTER: tuple[tuple[str, str], ...] = (
    ("EPCAM", "COADREAD"),
    ("KRAS", "COADREAD"),
    ("ERBB2", "BRCA"),
    ("PLK1", "COADREAD"),
    ("HTR1D", "COADREAD"),
)

RUN_PY = SKILL_DIR / "scripts" / "run.py"
PANEL_CACHE_DIR = SKILL_DIR / "scripts" / ".panel_cache"  # gitignored; see .panel_cache/.gitignore

# Tokens that mean "this bucket read as data-limited/degraded", used to detect whether the
# thin-coverage/abstention roster control (HTR1D) genuinely degrades relative to the others.
_DEGRADED_CELLLINE_CLASSES = frozenset({"lineage_restricted", "broadly_low", "data_unavailable"})
_DEGRADED_SC_CLASSES = frozenset({"broadly_low", "data_unavailable"})


def _load_package(target: str, indication: str, *, timeout: int = 300) -> tuple[dict | None, str | None]:
    """Load tumor-presence's decision.json for one roster pair — from the on-disk cache if present,
    else a live run of this skill's OWN entrypoint (no --full-package fan-out; see module docstring
    for why). Returns (package_dict, source_str), or (None, None) if genuinely unavailable (no
    creds, live run failed/timed out) — absence is reported, never silently substituted."""
    dest = PANEL_CACHE_DIR / f"{target}__{indication.lower()}"
    cached = dest / "decision.json"
    if cached.exists():
        try:
            return json.loads(cached.read_text()), str(cached.relative_to(REPO_ROOT))
        except (OSError, json.JSONDecodeError):
            pass
    dest.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            [sys.executable, str(RUN_PY), "--target", target, "--indication", indication, "--out", str(dest)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, None
    if r.returncode != 0 or not cached.exists():
        return None, None
    return json.loads(cached.read_text()), str(cached.relative_to(REPO_ROOT))


def _load_envelope(target: str, indication: str, *, timeout: int = 300) -> tuple[dict | None, str | None]:
    """Load tumor-presence's evidence_package.json (the SK#1941 --emit-envelope export) for one
    roster pair — from the on-disk cache if present, else a live `run.py --emit-envelope` invocation.
    Shares the SAME gitignored per-target cache directory as `_load_package` (a bare decision.json
    run there does not satisfy this — the envelope file is only written under --emit-envelope), so
    the two loaders never race: each writes/reads its own filename inside the shared dest dir.
    Returns (envelope_dict, source_str), or (None, None) if genuinely unavailable — absence is
    reported (#2071), never silently substituted."""
    dest = PANEL_CACHE_DIR / f"{target}__{indication.lower()}"
    cached = dest / "evidence_package.json"
    if cached.exists():
        try:
            return json.loads(cached.read_text()), str(cached.relative_to(REPO_ROOT))
        except (OSError, json.JSONDecodeError):
            pass
    dest.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run(
            [
                sys.executable,
                str(RUN_PY),
                "--target",
                target,
                "--indication",
                indication,
                "--out",
                str(dest),
                "--emit-envelope",
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return None, None
    if r.returncode != 0 or not cached.exists():
        return None, None
    return json.loads(cached.read_text()), str(cached.relative_to(REPO_ROOT))


def collect_panel_rows() -> tuple[list[dict], dict]:
    """The panel-consistency criterion's live computation: one row per roster pair (its two
    verdict-bearing card classes, or PACKAGE_MISSING) plus non-vacuity checks over the roster."""
    rows: list[dict] = []
    for target, indication in ROSTER:
        pkg, source = _load_package(target, indication)
        if pkg is None:
            rows.append({"target": target, "indication": indication, "status": "PACKAGE_MISSING", "source": None})
            continue
        cards = {c["card_id"]: c.get("summary", {}) for c in pkg.get("cards", [])}
        rows.append(
            {
                "target": target,
                "indication": indication,
                "status": "OK",
                "source": source,
                "cellline_rna_expression_class": cards.get("cellline-rna-distribution", {}).get("expression_class"),
                "sc_expression_class": cards.get("tumor-scrna-celltype-expression", {}).get("sc_expression_class"),
            }
        )

    ok_rows = [r for r in rows if r["status"] == "OK"]
    all_present = len(ok_rows) == len(ROSTER)
    cellline_classes = {r.get("cellline_rna_expression_class") for r in ok_rows} - {None}
    sc_classes = {r.get("sc_expression_class") for r in ok_rows} - {None}

    htr1d = next((r for r in ok_rows if r["target"] == "HTR1D"), None)
    others = [r for r in ok_rows if r["target"] != "HTR1D"]
    thin_coverage_control_degrades = False
    if htr1d is not None and others:
        htr1d_degraded = (
            htr1d.get("cellline_rna_expression_class") in _DEGRADED_CELLLINE_CLASSES
            or htr1d.get("sc_expression_class") in _DEGRADED_SC_CLASSES
        )
        others_not_degraded = any(
            o.get("cellline_rna_expression_class") not in _DEGRADED_CELLLINE_CLASSES
            and o.get("sc_expression_class") not in _DEGRADED_SC_CLASSES
            for o in others
        )
        thin_coverage_control_degrades = htr1d_degraded and others_not_degraded

    checks = {
        "all_roster_rows_present": all_present,
        "cellline_class_not_constant": len(cellline_classes) > 1,
        "sc_class_not_constant": len(sc_classes) > 1,
        "thin_coverage_control_degrades": thin_coverage_control_degrades,
    }
    checks["all_pass"] = all(checks.values())
    return rows, checks


def _panel_consistency_criterion() -> cs.Criterion:
    rows, checks = collect_panel_rows()
    all_present = checks["all_roster_rows_present"]
    evidence = {
        "method": (
            "per-target rows across the whole 5-target roster (not one flagship), COMPUTED live by "
            "collect_panel_rows() (see module docstring) rather than hand-typed: tumor-presence's "
            "verdict-bearing card classes must differ meaningfully across archetypes (flagship "
            "surface, flagship intrinsic driver, amplified surface, pan-essential control, "
            "thin-coverage abstention control) rather than collapsing to one constant reading, and the "
            "thin-coverage control must show the honest degraded/limited reads its archetype predicts."
        ),
        "roster_source": "eval/SCORECARD_PANEL_ROSTER.md",
        "capture_method": (
            "scorecard_adapter.py::_load_package -> skills/tumor-presence/scripts/run.py "
            "--target <T> --indication <I> (direct, no --full-package fan-out; "
            "eval/run_scorecard_panel.py --emit timed out at 900s for EPCAM/HTR1D in this environment)"
        ),
        "rows": rows,
        "checks": checks,
        "status_as_of": time.strftime("%Y-%m-%d", time.gmtime()),
    }
    if not all_present:
        missing = [f"{r['target']}/{r['indication']}" for r in rows if r["status"] == "PACKAGE_MISSING"]
        evidence["null_reason"] = (
            f"package(s) unavailable for {missing} (no cache, and a live run failed/timed out/lacked "
            "credentials) — left NULL rather than scoring a partial roster."
        )
        evidence["packages_missing"] = missing
        return cs.Criterion(status=cs.NULL, evidence=evidence)
    return cs.Criterion(status=(cs.GREEN if checks["all_pass"] else cs.RED), evidence=evidence)


# ── L2a / L2b / L3 evidence (shared rationale) ─────────────────────────────────────────────────

_ACCURACY_NULL_REASON = (
    "deterministic re-projection/aggregation over L1's already-validated card summaries; no new "
    "arithmetic over raw substrate is performed at this layer, so an independent raw-substrate "
    "re-derivation here would duplicate L1's own accuracy check under a different name rather than "
    "add information. Left NULL per directive rather than fabricating a reading this layer's own "
    "logic cannot support; L1's accuracy evidence is the substrate-level proof this layer builds on."
)

_L2A_UTILIZATION_EVIDENCE = {
    "method": "SK#1941 EXPORTED source_properties section reconstructs downward to L1 card_ids.",
    "test": (
        "skills/tumor-presence/tests/test_evidence_package_sections.py"
        "::test_sections_are_named_and_reconstruct_downward_to_l1"
    ),
    "status_as_of": "2026-09-28",
}
_L2A_FAIL_OPEN_EVIDENCE = {
    "method": "no claim vector resolved -> section omitted (byte-stable), never a fabricated empty/zero shape.",
    "test": "skills/tumor-presence/tests/test_evidence_package_sections.py::test_no_claim_vector_yields_no_sections",
    "status_as_of": "2026-09-28",
}

_L2B_UTILIZATION_EVIDENCE = {
    "method": (
        "SK#1941 EXPORTED integrated_properties section; each island's provenance.sources[*] "
        "reconstructs to L1 card_ids."
    ),
    "test": (
        "skills/tumor-presence/tests/test_evidence_package_sections.py"
        "::test_sections_are_named_and_reconstruct_downward_to_l1"
    ),
    "status_as_of": "2026-09-28",
}
_L2B_FAIL_OPEN_EVIDENCE = {
    "method": (
        "never-lift discipline: a stratum/arm with fewer than 2 measured arms yields None (nothing to "
        "reconcile), not a fabricated agree/disagree call; the section itself is omitted when no claim "
        "vector resolves."
    ),
    "tests": [
        "skills/tumor-presence/tests/test_subtype_layer_concordance.py "
        "(single-arm strata resolve to None, not a fabricated concordance call)",
        "skills/tumor-presence/tests/test_evidence_package_sections.py::test_no_claim_vector_yields_no_sections",
    ],
    "status_as_of": "2026-09-28",
}

_L3_UTILIZATION_EVIDENCE = {
    "method": (
        "every l3d chapter cites the L2b claim ID it rests on and names the vector it reconstructs "
        "from; cross_domain_claims is an always-empty, machine-checked floor (the story never "
        "over-claims outside tumor-presence's own scope)."
    ),
    "tests": [
        "skills/tumor-presence/tests/test_l3d_expression_biology_story.py"
        "::test_every_chapter_cites_a_claim_id_present_on_its_named_vector",
        "skills/tumor-presence/tests/test_l3d_expression_biology_story.py::test_story_makes_no_cross_domain_claim",
        "skills/tumor-presence/tests/test_evidence_package_sections.py"
        "::test_sections_are_named_and_reconstruct_downward_to_l1",
    ],
    "status_as_of": "2026-09-28",
}
_L3_FAIL_OPEN_EVIDENCE = {
    "method": "no L2b island resolves -> the l3d key is OMITTED (byte-stable), never an empty-but-present story.",
    "test": (
        "skills/tumor-presence/tests/test_l3d_expression_biology_story.py"
        "::test_no_island_resolves_omits_the_story_byte_stable"
    ),
    "status_as_of": "2026-09-28",
}

# ── L2a / L2b / L3 panel_consistency: COMPUTED live from the --emit-envelope export (#2071) ────────
# Extends the L1 panel-consistency pattern (collect_panel_rows/_panel_consistency_criterion above) one
# layer up: instead of two verdict-bearing card classes, each row carries the SHAPE of the SK#1941
# envelope export's three named sections (source_properties L2a / integrated_properties L2b / l3d L3)
# — the set of source-property keys populated, the set of integrated-island keys populated, and
# whether/how-many-chaptered the l3d story is. "Non-constancy" at this layer means the SHAPE differs
# across archetypes (a richly-covered flagship should populate more source-properties/islands/chapters
# than the thin-coverage control), mirroring L1's class-non-constancy + thin-coverage-degrades checks.


def collect_envelope_rows() -> tuple[list[dict], dict]:
    """The L2a/L2b/L3 panel_consistency criteria's shared live computation: one row per roster pair's
    --emit-envelope export shape, plus non-vacuity + structural-shape checks over the roster. Each of
    the three per-layer criterion builders below reads the relevant subset of `checks`."""
    rows: list[dict] = []
    for target, indication in ROSTER:
        env, source = _load_envelope(target, indication)
        if env is None:
            rows.append({"target": target, "indication": indication, "status": "PACKAGE_MISSING", "source": None})
            continue
        sp = env.get("source_properties") or {}
        ip = {k: v for k, v in (env.get("integrated_properties") or {}).items() if k != "_disclaimer"}
        l3d = env.get("l3d")
        rows.append(
            {
                "target": target,
                "indication": indication,
                "status": "OK",
                "source": source,
                "source_properties_keys": sorted(sp.keys()),
                "integrated_properties_keys": sorted(ip.keys()),
                "l3d_present": l3d is not None,
                "l3d_chapter_count": (len(l3d.get("chapters") or []) if isinstance(l3d, dict) else None),
            }
        )

    ok_rows = [r for r in rows if r["status"] == "OK"]
    all_present = len(ok_rows) == len(ROSTER)

    def _shape_not_constant(key: str) -> bool:
        shapes = {tuple(r.get(key) or []) for r in ok_rows}
        return len(shapes) > 1

    htr1d = next((r for r in ok_rows if r["target"] == "HTR1D"), None)
    others = [r for r in ok_rows if r["target"] != "HTR1D"]

    def _thin_coverage_narrower(count_key: str) -> bool:
        """HTR1D's export must be no richer than, and strictly narrower than at least one other
        roster member's — the honest degrade its thin-coverage archetype predicts."""
        if htr1d is None or not others:
            return False
        htr1d_n = len(htr1d.get(count_key) or [])
        other_ns = [len(o.get(count_key) or []) for o in others]
        return bool(other_ns) and htr1d_n <= min(other_ns) and any(n > htr1d_n for n in other_ns)

    l3d_present_values = {r["l3d_present"] for r in ok_rows}
    l3d_chapter_counts = {r["l3d_chapter_count"] for r in ok_rows if r["l3d_present"]}
    l3d_narrower = False
    if htr1d is not None and others:
        htr1d_chapters = htr1d.get("l3d_chapter_count") or 0
        other_chapters = [(o.get("l3d_chapter_count") or 0) for o in others]
        l3d_narrower = (not htr1d["l3d_present"] and any(o["l3d_present"] for o in others)) or (
            bool(other_chapters)
            and htr1d_chapters <= min(other_chapters)
            and any(c > htr1d_chapters for c in other_chapters)
        )

    checks = {
        "all_roster_rows_present": all_present,
        "source_properties_keys_not_constant": _shape_not_constant("source_properties_keys"),
        "integrated_properties_keys_not_constant": _shape_not_constant("integrated_properties_keys"),
        "l3d_presence_or_shape_not_constant": (len(l3d_present_values) > 1) or (len(l3d_chapter_counts) > 1),
        "thin_coverage_control_narrower_source_properties": _thin_coverage_narrower("source_properties_keys"),
        "thin_coverage_control_narrower_integrated_properties": _thin_coverage_narrower("integrated_properties_keys"),
        "thin_coverage_control_narrower_l3d": l3d_narrower,
    }
    return rows, checks


_ENVELOPE_CAPTURE_METHOD = (
    "scorecard_adapter.py::_load_envelope -> skills/tumor-presence/scripts/run.py "
    "--target <T> --indication <I> --emit-envelope (shares the gitignored per-target "
    "scripts/.panel_cache/<T>__<i>/ directory with _load_package's decision.json, writing/reading "
    "the sibling evidence_package.json filename)."
)


def _envelope_panel_criterion(
    *,
    rows: list[dict],
    checks: dict,
    layer_check_names: tuple[str, ...],
    method: str,
) -> cs.Criterion:
    all_present = checks["all_roster_rows_present"]
    layer_checks = {"all_roster_rows_present": all_present}
    for name in layer_check_names:
        layer_checks[name] = checks[name]
    layer_checks["all_pass"] = all(layer_checks.values())
    evidence = {
        "method": method,
        "roster_source": "eval/SCORECARD_PANEL_ROSTER.md",
        "capture_method": _ENVELOPE_CAPTURE_METHOD,
        "rows": rows,
        "checks": layer_checks,
        "status_as_of": time.strftime("%Y-%m-%d", time.gmtime()),
    }
    if not all_present:
        missing = [f"{r['target']}/{r['indication']}" for r in rows if r["status"] == "PACKAGE_MISSING"]
        evidence["null_reason"] = (
            f"envelope(s) unavailable for {missing} (no cache, and a live --emit-envelope run "
            "failed/timed out/lacked credentials) — left NULL rather than scoring a partial roster."
        )
        evidence["packages_missing"] = missing
        return cs.Criterion(status=cs.NULL, evidence=evidence)
    return cs.Criterion(status=(cs.GREEN if layer_checks["all_pass"] else cs.RED), evidence=evidence)


def _l2a_panel_consistency_criterion(rows: list[dict], checks: dict) -> cs.Criterion:
    return _envelope_panel_criterion(
        rows=rows,
        checks=checks,
        layer_check_names=(
            "source_properties_keys_not_constant",
            "thin_coverage_control_narrower_source_properties",
        ),
        method=(
            "per-target rows across the whole 5-target roster of the SK#1941 --emit-envelope export's "
            "source_properties (L2a) section: the SET of populated source-property keys must differ "
            "meaningfully across archetypes rather than collapsing to one constant shape, and the "
            "thin-coverage control must populate no more (and strictly fewer than at least one other "
            "roster member's) source-property keys."
        ),
    )


def _l2b_panel_consistency_criterion(rows: list[dict], checks: dict) -> cs.Criterion:
    return _envelope_panel_criterion(
        rows=rows,
        checks=checks,
        layer_check_names=(
            "integrated_properties_keys_not_constant",
            "thin_coverage_control_narrower_integrated_properties",
        ),
        method=(
            "per-target rows across the whole 5-target roster of the SK#1941 --emit-envelope export's "
            "integrated_properties (L2b) section: the SET of populated concordance-island keys must "
            "differ meaningfully across archetypes rather than collapsing to one constant shape, and "
            "the thin-coverage control must populate no more (and strictly fewer than at least one "
            "other roster member's) island keys."
        ),
    )


def _l3_panel_consistency_criterion(rows: list[dict], checks: dict) -> cs.Criterion:
    return _envelope_panel_criterion(
        rows=rows,
        checks=checks,
        layer_check_names=("l3d_presence_or_shape_not_constant", "thin_coverage_control_narrower_l3d"),
        method=(
            "per-target rows across the whole 5-target roster of the SK#1941 --emit-envelope export's "
            "l3d (L3) section: EITHER whether the story resolves at all OR its chapter count must "
            "differ meaningfully across archetypes rather than collapsing to one constant shape, and "
            "the thin-coverage control must resolve no richer a story (absent, or no more chapters, "
            "and strictly fewer than at least one other roster member's) than the richer archetypes."
        ),
    )


def build_shard() -> cs.SkillShard:
    """Build the tumor-presence scorecard shard in memory. Calls `collect_panel_rows()` (L1) and
    `collect_envelope_rows()` (L2a/L2b/L3, #2071) live, so re-running this script re-derives the
    panel evidence rather than replaying a stale table."""
    shard = cs.baseline_shard(SKILL)
    envelope_rows, envelope_checks = collect_envelope_rows()

    shard.cells["L1"] = cs.Cell(
        built=True,
        criteria={
            "accuracy": cs.Criterion(status=cs.GREEN, evidence=_L1_ACCURACY_EVIDENCE),
            "utilization": cs.Criterion(status=cs.GREEN, evidence=_L1_UTILIZATION_EVIDENCE),
            "fail_open": cs.Criterion(status=cs.GREEN, evidence=_L1_FAIL_OPEN_EVIDENCE),
            "panel_consistency": _panel_consistency_criterion(),
        },
        notes=(
            "L1 = the 18 cards (OBSERVATIONAL_PROPERTY): 7 ladder-verdict-bearing + 3 L2b-island "
            "substrate + 3 corroboration/certainty-bearing + 1 verdict-adjacent (hpa-pathology-cancer-ihc) "
            "+ 2 safety-comparators + 1 (cellline-protein-abundance-procan, corroboration-bearing). "
            "accuracy measured for ALL 17 of the 18 cards with a landed analysis-methods T3 anchor bridged "
            "to the EPCAM/COADREAD golden (cellline-rna-distribution, tumor-scrna-celltype-expression; "
            "tumor-rna-distribution + cellline-protein-abundance — batch A, #2043; tumor-rna-vs-adjacent "
            "+ tumor-elevation-breadth — batch B, #2044; tumor-protein-abundance-cptac — batch C, #2045; "
            "cellline-rna-protein-concordance + rna-protein-concordance-tumor + expression-purity-confound "
            "+ hpa-pathology-cancer-ihc — batch D, #2046; sc-normal-celltype-expression + "
            "normal-tissue-liability — batch E, #2047; the by-subtype distribution trio "
            "[tumor-rna-distribution-by-subtype, cellline-rna-distribution-by-subtype, "
            "tumor-protein-distribution-by-subtype] + cellline-protein-abundance-procan — batch F, #2088). "
            "Batch F is the ROSTER CLOSER: 13 -> 17/17, cards_not_yet_covered -> []. The four subtype/procan "
            "anchors re-derive through their real subtype-panorama / procan readers offline and bridge to "
            "the golden's stable subset, with the vintage/grade/emission/classifier drifts honestly pinned "
            "(golden NOT regenerated; see boundary + cross-link #2061)."
        ),
    )

    shard.cells["L2a"] = cs.Cell(
        built=True,
        criteria={
            "accuracy": cs.Criterion(status=cs.NULL, evidence={"reason": _ACCURACY_NULL_REASON}),
            "utilization": cs.Criterion(status=cs.GREEN, evidence=_L2A_UTILIZATION_EVIDENCE),
            "fail_open": cs.Criterion(status=cs.GREEN, evidence=_L2A_FAIL_OPEN_EVIDENCE),
            "panel_consistency": _l2a_panel_consistency_criterion(envelope_rows, envelope_checks),
        },
        notes="L2a = source_properties (SK#1941 EXPORTED section, --emit-envelope).",
    )

    shard.cells["L2b"] = cs.Cell(
        built=True,
        criteria={
            "accuracy": cs.Criterion(status=cs.NULL, evidence={"reason": _ACCURACY_NULL_REASON}),
            "utilization": cs.Criterion(status=cs.GREEN, evidence=_L2B_UTILIZATION_EVIDENCE),
            "fail_open": cs.Criterion(status=cs.GREEN, evidence=_L2B_FAIL_OPEN_EVIDENCE),
            "panel_consistency": _l2b_panel_consistency_criterion(envelope_rows, envelope_checks),
        },
        notes=(
            "L2b = integrated_properties (SK#1941 EXPORTED section): the coverage/abundance/"
            "subtype_restriction concordance islands (#1517/#1578, #1589/#1594, #1830/#1840)."
        ),
    )

    shard.cells["L3"] = cs.Cell(
        built=True,
        criteria={
            "accuracy": cs.Criterion(status=cs.NULL, evidence={"reason": _ACCURACY_NULL_REASON}),
            "utilization": cs.Criterion(status=cs.GREEN, evidence=_L3_UTILIZATION_EVIDENCE),
            "fail_open": cs.Criterion(status=cs.GREEN, evidence=_L3_FAIL_OPEN_EVIDENCE),
            "panel_consistency": _l3_panel_consistency_criterion(envelope_rows, envelope_checks),
        },
        notes="L3 = l3d, the 'tumor-expression biology story' (SK#1940, DOMAIN_INTERPRETATION).",
    )

    shard.cells["L4"] = cs.Cell(
        built=False,
        criteria={name: cs.Criterion(status=cs.NULL, evidence=None) for name in cs.CRITERIA},
        notes=(
            "L4 (SYNTHESIS / decision views) is explicitly OUT OF SCOPE for the tumor-presence "
            "reference vertical per epic #1938 ('L4 facet synthesis + decision views (deferred "
            "horizontal epic)') — an architecture gap by design, not a defect. built=false; no "
            "criterion may be measured on an unbuilt layer."
        ),
    )

    return shard


def main() -> int:
    scorecard_dir = REPO_ROOT / cs.SCORECARD_DIRNAME
    shard = build_shard()
    path = cs.write_skill_shard(scorecard_dir, shard)
    print(f"[tumor-presence scorecard adapter] wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
