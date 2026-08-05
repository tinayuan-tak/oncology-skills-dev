# rnd-computational-biology-oncology-analysis-methods

Deterministic analytical methods for the Takeda v2 oncology target-evaluation framework.

## What this repo provides

Reusable, language-agnostic analytical code — packaged as CLIs (some R-driven, some Python, some containers). Methods are **skill-runtime-agnostic** — runnable from a Jupyter notebook, a SageMaker batch job, a Claude skill via subprocess, or directly from the command line.

This repo is the third of the v2 framework's five repos. Sits between [target-contracts](https://github.com/oneTakeda/rnd-computational-biology-oncology-target-contracts) (governance) and [claude-oncology-skills](https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills) (orchestration) in the dependency graph. Skills *call* methods; methods don't know about skills.

## Method inventory (71 methods + 4 shared helpers under `methods/`)

Methods are grouped below by the biology gate / evidence axis they serve. Each is a self-contained
module under `methods/<name>/` with a `read.py` library entry (consumed by the `compose-dashboard`
dispatcher) and, where it emits figures, a `cli.py` (CLI + figure emitters). The `*_precompute`
methods build the gene-sorted derived products that the per-target readers query by pushdown. The
four shared helpers (`io/`, `depmap_common`, `opentargets_common`, `subgroup_common`) hold code
reused across a family of methods and are not invoked directly.

**Presence & selectivity (expression, RNA + protein)**
`dge_deseq2` · `dge_tcga_gtex_precompute` · `tcga_gtex_expression_distribution` ·
`tcga_gtex_tpm_quantiles` · `tcga_tpm_precompute` · `gtex_tpm_precompute` ·
`depmap_expression_distribution` · `allgene_percentile_precompute` · `percentile_null` ·
`cptac_protein_deg` · `depmap_protein_abundance` · `depmap_rna_protein_concordance` ·
`expression_purity_confound` · `expression_clinical_association` · `tumor_presence_controls`

**Requirement / dependency (DepMap CRISPR + RNAi)**
`depmap_chronos` · `depmap_chronos_distribution` · `depmap_demeter_distribution` ·
`depmap_crispr_rnai_concordance` · `depmap_expression_dependency` · `depmap_mutation_dependency` ·
`dependency` (lineage selectivity) · `depmap_predictability` · `depmap_predictability_precompute` ·
`depmap_paralog_aggregator` · `synleth_partner_lookup` · `abundance_dependency` ·
`depmap_parquet_precompute` · `depmap_common`

**Genomic alteration (SNV / CN / fusion)**
`gdc_somatic_hotspot` · `depmap_mutation_type_counts` · `depmap_cn_distribution` ·
`cooccurrence_fisher_pancohort` · `genomic_event_model_match` · `functional_gene_state` ·
`driver_role_overlay` · `tcga_fusion_consensus` · `tcga_tmb`

**Mechanism & pharmacology**
`mechanism_composed` · `signor_mechanism_network` · `collectri_tf_regulon` ·
`phospho_pathway_activity` · `kinome_atlas_prediction` · `kinome_atlas_pwm_lookup`

**Tractability — small molecule (PRISM chemical-genetic)**
`depmap_prism_activity` · `depmap_prism_crispr_concordance` · `depmap_prism_precompute`

**Surface / modality fit (biologics)**
`cspa_surface_confirmation` · `surfaceome_family_fusion` · `surfaceome_cohort_ranking` ·
`topology_predictions_tmbed` · `surface_antigen_density_ladder` · `shed_ectodomain_liability` ·
`uniprot_gpi_anchor` · `structure_features_static`

**Safety (germline + normal-tissue liability)**
`gnomad_constraint` · `hpa_normal_tissue_liability` · `opentargets_gene_burden` ·
`opentargets_clinvar` · `opentargets_clingen` · `opentargets_mouse_phenotype` ·
`opentargets_target_prioritisation` · `opentargets_common`

**Target-intrinsic (indication-independent molecular dossier)**
`reactome_pathway_context` · `ppi_interactome` · `gene_ontology_annotation` ·
`uniprot_protein_features` · `gencode_exon_index`

**Subgroup / subtype substrate**
`subgroup_assigner_classifier` · `subgroup_assigner_directly_tagged` ·
`subgroup_assigner_maf_filter` · `sclc_george_harmonize` (SCLC NAPY subtype vertical) ·
`subgroup_common`

**RWD & shared I/O**
`tempus_rwd_aggregator` · `patient_model_expression_correspondence` · `io/` (shared loaders)

> The `target_id_resolver` (symbol → Ensembl/Entrez resolution) lives in
> `claude-oncology-skills/libs/target_id_resolver/`, co-located with its resolver-release YAMLs, and
> is consumed by methods here — it did not migrate into this repo.

## Layout

```
methods/
├── dge_deseq2/
│   ├── steps/                # 00_load_counts.R, 01_build_design.R, …, 05_provenance.R
│   ├── cli.py                # dge-deseq2 CLI entrypoint
│   └── tests/
├── depmap_chronos/
│   ├── cli.py                # CLI + figure helpers (emit_forest_plot, emit_lineage_strip, …)
│   ├── read.py               # library entry called by compose-dashboard dispatcher
│   └── tests/
├── depmap_chronos_distribution/
│   ├── cli.py                # CLI + figure helpers (emit_waterfall_plot, emit_histogram_kde_plot, …)
│   ├── read.py               # library entry
│   └── tests/
├── gdc_somatic_hotspot/
│   ├── cli.py
│   ├── read.py
│   └── tests/
├── tempus_rwd_aggregator/
│   ├── cli.py
│   └── tests/
├── subgroup_assigner_directly_tagged/
│   └── ...
├── subgroup_assigner_maf_filter/
│   └── ...
└── io/
    └── loaders/              # shared loader utilities (carved from batch/loaders/)
tests/
└── integration/              # cross-method integration smoke tests
pixi.toml                     # heavier env: R + DESeq2 + sklearn + bioconductor + pyarrow
DEVELOPMENT_GUIDELINES.md
README.md
```

## API convention: public vs private helpers

Method modules separate **library entry** (`read.py`) from **CLI + figure emission** (`cli.py`). The library entry returns a summary dict consumed by the compose-dashboard skill's dispatcher; figure emission helpers in `cli.py` are called BOTH by the CLI's Click entrypoint AND by the skill's figure-emitter registry.

To make this dual-caller pattern explicit, the following helpers are **public (no underscore prefix)**:

- `load_depmap_files`, `compute_summary_stats`, `compute_lineage_summary`
- `emit_waterfall_plot`, `emit_histogram_kde_plot`, `emit_forest_plot`, `emit_lineage_strip`, `emit_plot_data`, `emit_manifest`

Internal-only helpers (used inside one method only) keep the `_` prefix.

## Method-output contracts

Every iter-1 method has a corresponding output schema in `target-contracts/schemas/products/`:

- `expression-rna-tumor-vs-adjacent.result.schema.json`
- `dependency-depmap-chronos.result.schema.json`
- (gdc-somatic-hotspot, tempus-rwd-aggregator schemas land as those methods ship)

A method's output validates against its schema before `compose-dashboard` curates it into a card emission. Output schema drift is caught at compose-time, not silently in the rendered evidence package.

## Status

**71 methods + 4 shared helpers**, spanning every biology gate of the framework (see inventory above). The
dependency, expression, genomic-alteration, mechanism, PRISM-tractability, safety, and
target-intrinsic methods are wired into `compose-dashboard` dispatchers with tests + figure
emitters; the surface-density and structural-feature methods are partially wired (their upstream
derived products are still landing in `data-catalog`). Individual method status is tracked per-card
in `target-contracts` and in the framework-health dashboard there.

See the [skills repo](https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills)
for the framework overview and roadmap.
