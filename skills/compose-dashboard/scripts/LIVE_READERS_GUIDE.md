# Live-Mode Readers — iter-1b Execution Session Guide

This document describes how to add live-mode data extraction for the remaining iter-1b cards.
**Important architectural correction (post-discipline-review):** data extraction logic
lives in the **methods/ repo**, not in this skill. The skill's role is to *dispatch*
to methods; methods do the *compute*. This is the framework's layer-distinction
discipline applied at the data-access boundary.

## The proper two-layer pattern

```
skills/compose-dashboard/scripts/_live_readers.py
  ├── CARD_DISPATCHERS = {card_id → dispatcher function}
  └── Each dispatcher:
       1. Resolves framework context (manifest selection from indication, etc.)
       2. Imports the corresponding method module from methods/
       3. Calls the method's read function
       4. Returns the method's summary dict unchanged
       NO data-extraction logic here. NO Parquet reads. NO column normalization.

methods/<method_name>/read.py
  └── Pure compute:
       1. Loads manifest YAML or known S3 paths
       2. Reads Parquet/CSV via pyarrow/pandas
       3. Filters to gene/lineage/strata
       4. Normalizes columns to summary_fields convention
       5. Returns summary dict with _data_source provenance
       Importable from notebooks, batch jobs, AgenticBoost — NOT skill-coupled.
```

## Two readers already migrated (this session)

### 1. `tumor-rna-vs-adjacent` — DGE Parquet
- **Method module**: `methods/dge_deseq2/read.py::read_dge_gene_row(target, manifest_id)`
- **Skill dispatcher**: `_dispatch_expression_tumor_vs_adjacent(target, indication)` — maps indication → manifest_id, calls the method
- **Data**: `s3://onc-compbio/data-catalog/derived/COADREAD-dge/df06320/tumor_vs_adjacent.parquet`
- **Pattern**: pyarrow predicate pushdown on `gene_symbol == target`
- **Iter-2 expansion**: as PDAC/NSCLC/SCLC/GC DGE products land, extend `indication_to_dge_manifest` in the dispatcher

### 2. `dependency-lineage-selectivity` — DepMap Chronos
- **Method module**: `methods/depmap_chronos/read.py::read_lineage_selectivity(target, indication)`
- **Skill dispatcher**: `_dispatch_dependency_lineage_selectivity` — direct passthrough
- **Data**: `s3://onc-compbio/data-catalog/sources/depmap-consortium/dmc-26q1/` (CRISPRGeneEffect.csv + Model.csv)
- **Pattern**: pandas `usecols=` to read only the target's gene column + lineage metadata
- **Indication→lineage map**: `INDICATION_TO_DEPMAP_LINEAGE` in `methods/depmap_chronos/read.py`

## Four readers remaining (iter-1b execution session)

For each: author the **method module first** (compute lives there), then a **thin
dispatcher in `_live_readers.py`** (orchestration lives here).

### 3. `mutation-hotspot-frequency`
- **New method module**: `methods/gdc_somatic_hotspot/read.py::read_hotspot_frequencies(target, indication)`
- **Data**: `gdc-pancohort-somatic-dr45-0` source manifest; MAF files
- **Strategy**: filter MAF rows to `Hugo_Symbol == target AND Variant_Classification != 'Silent'`; group by indication's TCGA cohort; compute overall frequency + per-codon hotspot frequencies + co-occurrence stats
- **Notes**: MAF is large (~hundreds of MB); use pandas with `usecols=` for memory efficiency

### 4. `tumor-vs-normal-selectivity`
- **Reuses existing**: `methods/dge_deseq2/read.py` for tumor side
- **New method module**: `methods/gtex_normal_tissue/read.py::read_max_normal_tpm(target)` — BUT GTEx is not yet mirrored (iter-1b blocker → Path 2)
- **Workaround for iter-1b**: dispatcher calls `read_dge_gene_row()` only, fills GTEx-derived fields as None; interpretation rules degrade gracefully

### 5. `antigen-prevalence`
- **New method module**: `methods/dge_deseq2/read.py::read_prevalence_stats(target, manifest_id, clinical_relevance_tpm, high_expression_tpm)`
- **Strategy**: from per-sample expression matrix, compute fraction_clinically_relevant + fraction_high_expression at the given thresholds. The per-sample matrix is at `s3://onc-compbio/data-catalog/sources/tcga-gdc-dr45-0/...star-counts.parquet` or similar — verify source manifest.

### 6. `rwd-stratified-expression`
- **New method module**: `methods/tempus_rwd_aggregator/read.py::read_stratified_expression(target, indication)`
- **Data**: `tempus-crc-2026-03-17` pre-aggregated CSV
- **Strategy**: load CSV (small, pre-aggregated); filter to target gene; emit `per_stratum_metrics` list directly from rows

## Quality bar for each reader (method side)

- ✅ Pure compute — no dashboard/synthesis/orchestration awareness
- ✅ Importable from any Python context: `from methods.<method> import read_*`
- ✅ Returns dict matching card_spec's `summary_fields` (None for unavailable fields)
- ✅ Includes `_data_source` + `_data_s3_uri` (or `_data_csv_path`) provenance
- ✅ Handles "target not in data" + "indication not mapped" gracefully (None values + `_data_note`)
- ✅ Tests in `methods/<method>/tests/` independent of skill code

## Quality bar for each dispatcher (skill side)

- ✅ Thin: at most 20 lines (manifest selection + method import + passthrough call)
- ✅ NO data-extraction logic — if you find yourself reading a Parquet here, you're in the wrong layer
- ✅ Indication-to-manifest resolution belongs here (skill knowledge: which derived manifest is which); the method shouldn't need to know about indication semantics, just manifest IDs

## End-to-end test pattern

```bash
AWS_PROFILE=cbg python3 -m scripts.compose_dashboard \
  --target KRAS --indication COADREAD \
  --execution-mode live-stub-fallback \
  --out /tmp/test_run --deterministic-timestamps
```

Each card's `summary._data_source` field should show the manifest_id when live,
or `"STUB"` when fallen back. The discipline check: a card's data flow can be
audited by reading `methods/<method>/read.py`, not by tracing skill code.

## Why this matters

The plan's layer-distinction discipline (master plan § Dashboard, Interpretation,
Inference Layers) only holds if extraction is in methods and orchestration is in
skills. A notebook user, an AgenticBoost integration, or Tina's dashboards can
all `from methods.depmap_chronos import read_lineage_selectivity` without
importing this skill. That's the architectural commitment — and it required
this refactor to honor.
