# CMS classifier — design (Phase 0) + scaffold (Phase 1)

Adds a third `classifier_method` to `subgroup_assigner_classifier` that assigns colorectal
(COADREAD) samples to the four **Consensus Molecular Subtypes** (CMS1–4; Guinney et al. 2015,
Nat Med). CMS requires a signature/template classifier, NOT the marker z-score methods the module
ships today (`single_gene_zscore_threshold`, `napy_zscore_classifier`).

## Phase 0 — decisions (locked 2026-08-20)

### D1. Classifier: **CMScaller (NTP)**, not Guinney's CMSclassifier RF
- **CMScaller** (Eide et al. 2017, Sci Rep; `github.com/Lothelab/CMScaller`) — nearest-template
  prediction (NTP), single-sample, ships its 787-gene CMS templates as package data. It was built
  *specifically* to extend CMS beyond the original TCGA microarray/RNA-seq training cohort to
  cell lines / PDX / organoids — exactly our DepMap use case.
- Guinney's `CMSclassifier` (RF/SSP) is platform-calibrated to the training tumor cohort and
  degrades off-distribution. Kept as an OPTIONAL second `cms_method` value for the TCGA validation
  cross-check only.

### D2. Cohort: **DepMap Bowel lineage is the target**, NOT TCGA
- **TCGA COADREAD CMS is already live** as `derivation_source: directly_tagged_source_provided`
  from `guinney-2015-crc-cms-consortium` (the `CMS_final_*` field), handled by
  `subgroup_assigner_directly_tagged`. Running a classifier on TCGA would be redundant AND would
  need a per-sample recount3 COADREAD TPM matrix that is not materialized.
- The classifier's real value is **DepMap Bowel lineage** (`OmicsExpressionProteinCodingGenesTPMLogp1`
  × `Model.csv` `OncotreeLineage == "Bowel"`, ~146 lines), which has no pre-provided CMS labels.

### D3. Stratum-derivation conflict → **option B (DepMap-scoped classifier strata)**
A single catalog stratum cannot be both `directly_tagged` (TCGA) and `classifier_run` (DepMap)
under the current subgroup-catalog schema (one `data_source` per stratum). Two options were
considered:
- **(A)** extend the stratum schema with a `data_source_overrides` block (per-source derivation).
  Cleanest long-term; touches the target-contracts subgroup_catalog schema + all three assigners.
- **(B)** add DepMap-scoped `classifier_run` CMS strata to `COADREAD/2026-Q2.yaml`
  (`applicable_data_sources: [depmap]`, `data_source.method: cms_classifier`), leaving the TCGA
  `directly_tagged` CMS strata untouched.

**Chosen: (B)** for this iteration — lowest-touch, no schema change (the
`subgroup_assignment.schema.json` already enumerates `classifier_run` +
`subgroup_assigner_classifier_run`), and it isolates the fraught cell-line CMS call from the
trusted TCGA labels. (A) is the follow-up if more cohorts need dual-derivation. Strata ids are
disambiguated by the assigner's `data_source` filter.

### D4. Honest scientific caveat (surfaced, not hidden)
CMS was defined on tumor tissue; cell lines lack the stromal/immune compartments that define
**CMS1 (immune)** and **CMS4 (mesenchymal)**, which recover poorly in DepMap. DepMap CMS
assignments MUST be flagged `hypothesis_generating` (the same discipline the SCLC catalog applies),
and many Bowel lines will be `unclassifiable` (below the NTP FDR floor). NTP (D1) is chosen partly
because it degrades more gracefully off-tissue than the RF.

## Phase 1 — R scaffold (this PR)
- `pixi.toml`: + `bioconductor-biobase` (CMScaller dep; `limma` already present).
- `setup.R`: idempotent `remotes::install_github("Lothelab/CMScaller@<pin>")` (mirrors
  `cooccurrence_fisher_pancohort/setup.R`).
- `steps/run_cms.R`: optparse CLI — read an Entrez-rownamed expression matrix (samples = columns),
  run `CMScaller::CMScaller()`, write per-sample `{sample_id, CMS, p.value, FDR}` parquet
  (`arrow::write_parquet`).

## Phases 2–4 (NOT in this PR — see build spec in session memory)
- **2** (python wiring): add `cms_classifier` to `SUPPORTED_CLASSIFIER_METHODS`; full-matrix
  expression loader (widen usecols to the CMScaller template genes; HGNC→Entrez via
  `hgnc_entrez_crosswalk`; filter Bowel lineage); `_run_cms_classifier()` shells to `run_cms.R`
  and reshapes NTP output to the tall `is_member` form with an FDR floor.
- **3** (catalog + shard): DepMap-scoped `classifier_run` CMS strata in `COADREAD/2026-Q2.yaml`;
  shard manifest `depmap-subgroup-assignments-coadread-cms-v1`.
- **4** (validation): synthetic-matrix unit test + a biology gate — run against the CMScaller-bundled
  TCGA example / Guinney `cms_labels_public_all.txt` ground truth and confirm concordance on
  consensus samples.
