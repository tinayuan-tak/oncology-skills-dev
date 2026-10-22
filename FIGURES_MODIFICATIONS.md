# Figure review & modifications

Living review of every figure the skills produce. Branch: `test-unified-changes`.
Write what should change under **Comments**; the work done and its commit go under **Work done**.

## How to use this file

1. Open the figure in `~/skill-outputs/figure-audit/<skill>/figures/` (card figures are under `cards/<card>/`).
2. Under its entry, write what needs to change in **Comments** and set **Status** to 💬.
3. When a fix lands, **Work done** gets the date, commit, and a one-line summary, and the status moves to 🟡.
4. You sign off by setting ✅ (or ➖ if you looked and nothing needs changing).
5. When every figure in a skill is ✅ or ➖, mark the skill ✅ in the [Skills](#skills) table.

Card figures shared by several skills have **one** entry, under the first skill that shows them;
the other skills link to it. A comment there applies everywhere the figure appears.

| Status | Meaning |
|:-:|---|
| ⬜ | Not reviewed |
| 💬 | Changes requested (see Comments) |
| 🔧 | In progress |
| 🟡 | Fix applied — awaiting your review |
| ✅ | Done |
| ➖ | Reviewed, no changes needed |

**Standard case:** `PIK3CA` / `BRCA`, figures from the 2026-10-08 sweep. To regenerate one skill:

```bash
AWS_PROFILE=cbg pixi run python skills/<skill>/scripts/run.py \
    --target PIK3CA --indication BRCA --out ~/skill-outputs/figure-audit/<skill> --figures
```

## Skills

| Skill | Skill status |
|-------|:-:|
| [tumor-presence](#tumor-presence) | ⬜ |
| [tumor-selectivity](#tumor-selectivity) | ⬜ |
| [functional-requirement](#functional-requirement) | ⬜ |
| [combination-and-vulnerability](#combination-and-vulnerability) | ⬜ |
| [genomic-alteration-profile](#genomic-alteration-profile) | ⬜ |
| [mechanism-and-pharmacology](#mechanism-and-pharmacology) | ⬜ |
| [differentiation-landscape](#differentiation-landscape) | ⬜ |
| [tractability-small-molecule](#tractability-small-molecule) | ⬜ |
| [surface-modality-fit](#surface-modality-fit) | ⬜ |
| [immune-context](#immune-context) | ⬜ |
| [on-target-safety-liability](#on-target-safety-liability) | ⬜ |
| [translational-readiness](#translational-readiness) | ⬜ |
| [target-intrinsic](#target-intrinsic) | ⬜ |
| [cis-feature-coherence](#cis-feature-coherence) | ⬜ |

## Figures by skill

### tumor-presence

**Skill-level figures**

#### `figure_card_board.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `figure_claim_vector.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `figure_headline_hero.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `figure_presence_context_matrix.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `figure_subgroup_signals.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Card figures**

#### `cellline-protein-abundance/figure_density_protein_abundance.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `cellline-protein-abundance/figure_lineage_strip_protein.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `cellline-rna-distribution/figure_density_expression.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `cellline-rna-distribution/figure_lineage_strip_expression.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `cellline-rna-protein-concordance/figure_rna_protein_concordance.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `expression-purity-confound/figure_expression_purity_confound.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `normal-tissue-liability/figure_normal_tissue_expression_heatmap.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**
  - 2026-10-08 — was missing because `polars` wasn't installed; now emits under pixi. No code change. Not yet looked at.

#### `rna-protein-concordance-tumor/figure_rna_protein_concordance_tumor.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `tumor-elevation-breadth/figure_pan_cancer_by_tissue_distribution.svg`
- **Status:** 🟡 Ready for review
- **Comments:**
- **Work done:**
  - 2026-10-07 `32c4924e` — figure was never emitted (stale `methods.` import crashed the renderer).
  - 2026-10-07 `e32aaedf` — yellow/green row boxes now drawn only on rows with significance asterisks.

#### `tumor-protein-abundance-cptac/figure_protein_per_cohort_tumor_vs_normal.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `tumor-rna-distribution/figure_expression_distribution.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `tumor-rna-vs-adjacent/figure_tumor_vs_normal_selectivity_4panel.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `tumor-scrna-celltype-expression/figure_sc_compartment_detection.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

---

### tumor-selectivity

**Skill-level figures**

#### `figure_headline_hero.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `figure_selectivity_evidence_strip.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `figure_subgroup_signals.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Card figures**

#### `tumor-vs-normal-percentile-crossing/figure_expression_distribution.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `tumor-vs-normal-selectivity/figure_tumor_vs_normal_selectivity_4panel.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Shared card figures** (reviewed under the skill named)

- `expression-purity-confound/figure_expression_purity_confound.svg` → [tumor-presence](#tumor-presence)
- `tumor-protein-abundance-cptac/figure_protein_per_cohort_tumor_vs_normal.svg` → [tumor-presence](#tumor-presence)
- `tumor-scrna-celltype-expression/figure_sc_compartment_detection.svg` → [tumor-presence](#tumor-presence)

---

### functional-requirement

**Skill-level figures**

#### `figure_headline_hero.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `figure_subgroup_signals.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Card figures**

#### `abundance-dependency/figure_abundance_dependency.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `crispr-rnai-dependency-concordance/figure_concordance_overlay_density.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `crispr-rnai-dependency-concordance/figure_concordance_partition_bar.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `crispr-rnai-dependency-concordance/figure_concordance_scatter.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `dependency-lineage-selectivity/figure_forest_plot.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `dependency-lineage-selectivity/figure_lineage_strip.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `dependency-lineage-selectivity/figure_oncotree_forest_plot.svg`
- **Status:** 🟡 Ready for review
- **Comments:**
- **Work done:**
  - 2026-10-08 `86c8de15` — new: the per-OncotreeCode forest existed in code but was never called; wired on live + offline paths.

#### `dependency-predictability/figure_feature_importance_bar.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `dependency-predictability/figure_lineage_predictability.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `expression-dependency-correlation/figure_lineage_stratified_scatter.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `expression-dependency-correlation/figure_scatter_with_regression.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `genomic-event-model-match/figure_genomic_event_model_match.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `organoid-crispr-dependency/figure_organoid_lineage_dependency.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `pan-cancer-crispr-dependency-distribution/figure_histogram_kde.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `pan-cancer-crispr-dependency-distribution/figure_waterfall.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `pan-cancer-rnai-dependency-distribution/figure_histogram_kde_rnai.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `pan-cancer-rnai-dependency-distribution/figure_waterfall_rnai.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `prism-crispr-concordance/figure_concordance_scatter.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `prism-crispr-concordance/figure_concordance_vocab_panel.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `prism-crispr-concordance/figure_dual_responders_bar.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `recommended-models/figure_recommended_models.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

---

### combination-and-vulnerability

**Skill-level figures**

#### `figure_headline_hero.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `figure_subgroup_signals.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

---

### genomic-alteration-profile

**Skill-level figures**

#### `figure_subgroup_signals.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Card figures**

#### `alteration-role/figure_alteration_role.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `copy-number-distribution/figure_cn_amplification_pie.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `copy-number-distribution/figure_cn_amplification_stacked.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `copy-number-distribution/figure_cn_deletion_pie.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `copy-number-distribution/figure_cn_deletion_stacked.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `copy-number-distribution/figure_density_cn.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `copy-number-distribution/figure_lineage_strip_cn.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `copy-number-distribution/figure_waterfall_cn.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `copy-number-stratified-dependency/figure_cn_amplification_strip.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `copy-number-stratified-dependency/figure_cn_deletion_strip.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `functional-gene-state/figure_functional_gene_state.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `fusion-rearrangement-landscape/figure_fusion_frequency_pie.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `fusion-rearrangement-landscape/figure_fusion_frequency_stacked.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `fusion-stratified-dependency/figure_fusion_stratified_strip.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `mutation-hotspot-frequency/figure_hotspot_pie.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `mutation-hotspot-frequency/figure_mutation_frequency_pie.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `mutation-hotspot-frequency/figure_mutation_frequency_stacked.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `mutation-stratified-dependency/figure_mut_vs_wt_strip.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `mutation-stratified-dependency/figure_per_hotspot_chronos.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `mutation-type-counts/figure_mutation_class_bar.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `mutation-type-counts/figure_mutation_lineage_bar.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Shared card figures** (reviewed under the skill named)

- `dependency-predictability/figure_feature_importance_bar.svg` → [functional-requirement](#functional-requirement)
- `dependency-predictability/figure_lineage_predictability.svg` → [functional-requirement](#functional-requirement)
- `genomic-event-model-match/figure_genomic_event_model_match.svg` → [functional-requirement](#functional-requirement)

---

### mechanism-and-pharmacology

**Skill-level figures**

#### `figure_headline_hero.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `figure_subgroup_signals.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Card figures**

#### `phospho-pathway-activity/figure_phospho_pathway_activity.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Shared card figures** (reviewed under the skill named)

- `dependency-predictability/figure_feature_importance_bar.svg` → [functional-requirement](#functional-requirement)
- `dependency-predictability/figure_lineage_predictability.svg` → [functional-requirement](#functional-requirement)

---

### differentiation-landscape

**Skill-level figures**

#### `figure_headline_hero.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `figure_subgroup_signals.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Card figures**

#### `expression-clinical-association/figure_expression_clinical_association.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

---

### tractability-small-molecule

**Skill-level figures**

#### `figure_headline_hero.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `figure_subgroup_signals.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Card figures**

#### `prism-compound-activity/figure_activity_vocab_panel.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `prism-compound-activity/figure_lineage_activity_bar.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `prism-compound-activity/figure_top_compounds_bar.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Shared card figures** (reviewed under the skill named)

- `dependency-predictability/figure_feature_importance_bar.svg` → [functional-requirement](#functional-requirement)
- `dependency-predictability/figure_lineage_predictability.svg` → [functional-requirement](#functional-requirement)
- `mutation-hotspot-frequency/figure_hotspot_pie.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `mutation-hotspot-frequency/figure_mutation_frequency_pie.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `mutation-hotspot-frequency/figure_mutation_frequency_stacked.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `prism-crispr-concordance/figure_concordance_scatter.svg` → [functional-requirement](#functional-requirement)
- `prism-crispr-concordance/figure_concordance_vocab_panel.svg` → [functional-requirement](#functional-requirement)
- `prism-crispr-concordance/figure_dual_responders_bar.svg` → [functional-requirement](#functional-requirement)

---

### surface-modality-fit

**Skill-level figures**

#### `figure_headline_hero.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `figure_subgroup_signals.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Shared card figures** (reviewed under the skill named)

- `copy-number-distribution/figure_cn_amplification_pie.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `copy-number-distribution/figure_cn_amplification_stacked.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `copy-number-distribution/figure_cn_deletion_pie.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `copy-number-distribution/figure_cn_deletion_stacked.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `copy-number-distribution/figure_density_cn.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `copy-number-distribution/figure_lineage_strip_cn.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `copy-number-distribution/figure_waterfall_cn.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `normal-tissue-liability/figure_normal_tissue_expression_heatmap.svg` → [tumor-presence](#tumor-presence)
- `rna-protein-concordance-tumor/figure_rna_protein_concordance_tumor.svg` → [tumor-presence](#tumor-presence)
- `tumor-scrna-celltype-expression/figure_sc_compartment_detection.svg` → [tumor-presence](#tumor-presence)

---

### immune-context

**Skill-level figures**

#### `figure_headline_hero.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `figure_subgroup_signals.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Card figures**

#### `immune-context/figure_immune_context_leukocyte_composition.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

---

### on-target-safety-liability

**Skill-level figures**

#### `figure_headline_hero.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `figure_subgroup_signals.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Card figures**

#### `gnomad-lof-constraint/figure_constraint_scores_gauge_panel.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `normal-tissue-liability-gtex/figure_normal_tissue_liability.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Shared card figures** (reviewed under the skill named)

- `alteration-role/figure_alteration_role.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `copy-number-distribution/figure_cn_amplification_pie.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `copy-number-distribution/figure_cn_amplification_stacked.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `copy-number-distribution/figure_cn_deletion_pie.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `copy-number-distribution/figure_cn_deletion_stacked.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `copy-number-distribution/figure_density_cn.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `copy-number-distribution/figure_lineage_strip_cn.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `copy-number-distribution/figure_waterfall_cn.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `functional-gene-state/figure_functional_gene_state.svg` → [genomic-alteration-profile](#genomic-alteration-profile)
- `normal-tissue-liability/figure_normal_tissue_expression_heatmap.svg` → [tumor-presence](#tumor-presence)
- `pan-cancer-crispr-dependency-distribution/figure_histogram_kde.svg` → [functional-requirement](#functional-requirement)
- `pan-cancer-crispr-dependency-distribution/figure_waterfall.svg` → [functional-requirement](#functional-requirement)

---

### translational-readiness

**Skill-level figures**

_None emitted._

**Shared card figures** (reviewed under the skill named)

- `organoid-crispr-dependency/figure_organoid_lineage_dependency.svg` → [functional-requirement](#functional-requirement)

---

### target-intrinsic

**Skill-level figures**

#### `figure_headline_hero.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `figure_subgroup_signals.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Shared card figures** (reviewed under the skill named)

- `gnomad-lof-constraint/figure_constraint_scores_gauge_panel.svg` → [on-target-safety-liability](#on-target-safety-liability)
- `normal-tissue-liability/figure_normal_tissue_expression_heatmap.svg` → [tumor-presence](#tumor-presence)

---

### cis-feature-coherence

**Skill-level figures**

#### `figure_headline_hero.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

#### `figure_subgroup_signals.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Card figures**

#### `cis-feature-expression-coherence/figure_cn_expression_scatter.svg`
- **Status:** ⬜ Not reviewed
- **Comments:**
- **Work done:**

**Shared card figures** (reviewed under the skill named)

- `abundance-dependency/figure_abundance_dependency.svg` → [functional-requirement](#functional-requirement)
- `expression-dependency-correlation/figure_lineage_stratified_scatter.svg` → [functional-requirement](#functional-requirement)
- `expression-dependency-correlation/figure_scatter_with_regression.svg` → [functional-requirement](#functional-requirement)

---

## Reference

### Finding a missing figure

Figure emission is best-effort: a broken figure still exits 0, so check `run.log`.

| Sign | Meaning | Seen here |
|------|---------|-----------|
| `[figures] emit failed for <card>` in `run.log` | emitter raised; the exception was swallowed | stale imports, 2026-10-07 |
| card folder exists but has no `.svg` | emitter ran and returned nothing (failed read / no data) | — |
| no folder and no log line | emitter never called, or the card's read failed upstream | oncotree forest; normal-tissue-liability |

Figures come in two tiers. **Card figures** (`figures/cards/<card>/`) come from
`CARD_FIGURE_EMITTERS` in `skills/_skills_common/_figure_emitters/_registry.py`. **Skill-level
figures** (`figures/` root: hero, subgroup signals, claim vector) come from the skill itself.
Count both: combination-and-vulnerability has no card figures by design.

### Change history

- **2026-10-07 `32c4924e`** — 12 deferred imports still used the pre-consolidation name
  `methods.`; each raised `ModuleNotFoundError` when its figure rendered and the emitter
  swallowed it. Fixed in `tcga_gtex_tpm_quantiles/read.py`, `_figure_emitters/_expression.py`,
  `_figure_emitters/_dependency.py`, and two `test_figures.py`. Restored the breadth figure and
  latent DepMap-dependency, fusion, driver-role, and patient-CN figures.
- **2026-10-07 `e32aaedf`** — breadth-figure row boxes used `if sig`, but `sig` is a non-empty
  label for non-significant rows too (`ns`, `†`, `—`). Now gates on `sig.startswith("*")`,
  matching `cptac_protein_deg`. PPIA/COADREAD: 20 → 14 boxes. Significance here is an
  effect-size tier (|Δ| and n), not a p-value. Test: `test_elevation_boxes_only_on_significant_rows`.
- **2026-10-08 `86c8de15`** — `emit_oncotree_forest_plot` was never called, and the persisted
  `plot_data.parquet` dropped `OncotreeCode`, so the offline render path could not build it.
  Wired on both paths, column persisted and restored, figure declared in the card YAML,
  `per_oncotree_code_stats` reach re-derived in functional-requirement's `field_disposition.yaml`.
  Test: `test_oncotree_forest_figure.py`.
- **2026-10-08 (no commit)** — normal-tissue-liability's HPA reader needs `polars`, which is in
  `pixi.toml` but was missing from base conda. Fixed by installing pixi and running under it.

### Known failures that are not figure regressions

Seen while gating `86c8de15` under pixi. All reproduce without this branch's changes, and will
need owners before anything here lands on `main`.

- **contracts:** `build_wiring_ledger --self-check` — data-catalog has 6 manifests the
  committed ledger lacks (chembl, PRISM v5, three sc-composition donor subsets).
- **methods:** 3 × `depmap_predictability_precompute`; `test_reader_absence_discipline` flags
  broad `except`s in `load_subtype_assignments`, `_expression.py`, `_genomic.py`.
- **skills:** `figure_card_contract_parity[copy-number-distribution]` and
  `cn_distribution_gallery_convergence` (cn naming mismatch);
  `card_emits_declared_summary_fields` for dependency-lineage-selectivity
  (`indication_dependency_class`) and tumor-vs-normal-selectivity; `field_read_health_sidecar`
  staleness; `test_l3d_dependency_story` (`DEPENDENCY_BIOLOGY_STORY_L3D` missing).
- **env:** `ruff` not installed locally (`pipx install ruff==0.16.6`).

### Other open items

- [ ] translational-readiness emits no skill-level figures; genomic-alteration-profile emits only
      one. Confirm whether that's expected.
- [ ] `_ensure_methods_path()` is now a no-op with a misleading docstring; remove it?
- [ ] Extend `test_import_discipline` to scan `skills/`, where the stale imports hid.
