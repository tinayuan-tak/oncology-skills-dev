# oncology-skills — v2 architecture (in development)

> **You are on the `v2-architecture` branch.** This branch is the redesigned target-evaluation platform: compute and retrieval are physically separated, evidence is published as standardized per-target artifacts, and the data layer is anchored on a versioned catalog with full GDC release + manifest UUID + pipeline-version pinning.
>
> **For the v1 plugin** (currently installable via Claude Code's marketplace — the seven indication × modality skills that have been validating targets like SCD1, PCDH7, WEE1 in day-to-day work): see [`main` branch README](https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills/blob/main/README.md). v1 remains the production system until v2 reaches feature parity.

---

## What v2 is, and why it exists

A target evaluation in v2 produces a **standardized `evidence.json` artifact per `(indication, subtype, gene, dimension)`** in `s3://onc-compbio/core-artifacts/`. Eight dimensions: `expression-rna`, `expression-protein` (CPTAC), `dependency` (DepMap), `mutation-profile`, `survival`, `safety`, `target-biology`, `literature`.

The single most important structural decision: **`batch/` vs `skills/` separation.** Batch jobs do scheduled compute and write artifacts; they are never invoked by Claude. Skills are retrieval-only and *can be* invoked by Claude. This makes "wire a skill to recompute on every call" physically impossible — which was the v1 failure mode (a single skill loading a 4 GB expression matrix and chunk-scanning it for one gene, on every invocation).

The second-most important: **compute globally, query locally.** DGE runs once per indication across all ~18K genes and is cached as a Parquet sorted by gene_symbol; per-gene queries do predicate-pushdown reads of one row, not full scans. If a query reads the whole file instead of one row, the architecture silently fails at scale.

```
LAYER 1  COMPUTATION (batch/ jobs — scheduled / cron / manual)
   8 analysis dimensions × indication-aware pipelines, each produces evidence.json
        │ writes to
        ▼
LAYER 2  ARTIFACT STORE (the lingua franca)
   s3://onc-compbio/core-artifacts/{indication}/{subtype}/{gene}/{dimension}/
   per artifact: evidence.json + provenance.yaml + report.md + figure.png
        │ consumed by                    │ loaded by ETL
        ▼                                ▼
LAYER 3a  Skills (retrieval-only)   LAYER 3b  Knowledge Graph (planned)
   read evidence.json per facet        multi-hop discovery queries
```

---

## Eight dimensions, parameterized by `(indication, subtype, gene)`

| Dimension | What | Source(s) |
|---|---|---|
| `expression-rna` | DGE on RNA-seq | GDC TCGA (canonical pin) + recount3 for joint TCGA+GTEx |
| `expression-protein` | DEG on proteomics (mass spec) | CPTAC where available (CRC, PDAC, …) |
| `dependency` | CRISPR Chronos scores, lineage selectivity | DepMap quarterly |
| `mutation-profile` | Somatic mutation freq, canonical variants, hotspots | GDC TCGA somatic |
| `survival` | KM curves, hazard ratios, log-rank p | GDC TCGA clinical |
| `safety` | HPA IHC normal-tissue map, gnomAD pLI, knockout phenotype | HPA + gnomAD |
| `target-biology` | Subcellular localization, surface vs intracellular, structure, modality-fit | UniProt + HPA subcellular + SurfaceomeDB |
| `literature` | Extracted facts (CRISPR/RNAi study counts, clinical phase, IC50, pLI) — facts only, no synthesized risk score | PubMed via LLM (port of v1's `literature_evidence` schema) |

**`subtype` is a path axis**, default `all`. Stratified analyses produce one artifact per stratum (e.g., `crc/CMS4/SCD1/expression-rna/`, `crc/MSS-RASmut/SCD1/expression-rna/`). Subtype is *molecular* (CMS, RAS, MSI). Treatment-line stratification (1L-2L, 3L+, CPI-status) lives inside the `expression-rna` result payload as a `tempus_summary:` block — see Tempus integration below.

**Therapeutic modality** (small molecule vs antibody vs ADC vs PROTAC vs mRNA) is **NOT a dimension**. It lives at the workflow / skill orchestration layer, where it decides which dimensions are required for a defensible eval (an ADC needs `expression-rna` + `expression-protein` + `target-biology` + `safety`; a small-molecule intracellular target can skip surface-confirmation checks) and how to *interpret* evidence per modality class. Artifacts themselves remain modality-agnostic. Re-evaluating a target as a different modality = same artifacts, new lens.

---

## What's on this branch today

| Path | What it is | Status |
|---|---|---|
| [core-artifacts-schema/evidence.schema.json](core-artifacts-schema/evidence.schema.json) | The artifact contract. Required: `gene`, `indication`, `subtype` (default `all`), `dimension`, `provenance.catalog_refs` (lineage to catalog manifest IDs), `result`, `summary`, `confidence`, `label` (`pre-specified` \| `exploratory`). Tagged-union 8-dim enum, `additionalProperties: false`. JSON Schema Draft 2020-12. | ✓ schema complete + tested |
| [skills/query-target-evidence/](skills/query-target-evidence/) | First v2 skill — RETRIEVAL-ONLY. Reads `core-artifacts/{indication}/{subtype}/{gene}/{dimension}/evidence.json`, validates, checks staleness, returns. **Has no analysis code.** If an artifact is missing, names the batch job that produces it; does NOT trigger compute. | ✓ contract complete; awaiting first artifact |
| [batch/expression_rna_crc/](batch/expression_rna_crc/) | First batch compute pipeline. Pure-R Bioconductor: `00_load_counts.R` → `01_build_design.R` → `02_combat_seq.R` → `03_deseq2.R` → `04_write_parquet.R` → `05_provenance.R`. Methodology: DESeq2 + ComBat-seq + lfcShrink(apeglm) on raw integer counts. | ✓ pipeline scaffolded; `00_load_counts.R` awaits canonical-source loader |
| [batch/loaders/](batch/loaders/) | Python `Protocol` for source-specific loaders (oncoland, gdc, xena-toil, recount3) — used by future Python-orchestrated batch jobs. R DGE pipeline reads sources directly. | ✓ interface defined |
| [configs/crc.yaml](configs/crc.yaml) | CRC indication parameters: TCGA cohorts, CMS subtypes, MSS/MSI flags, BRAF V600E flag, BH-FDR tier 1/2/3 spec, GTEx reference, output path templates. | ✓ |
| [notebooks/](notebooks/) | Exploration before code hardens into `batch/`. The runbook's three-notebook sequence (data inventory → global CRC DGE → SCD1 evidence PoC) lives here during prototyping. | scaffolded |

**Sister repo (the data catalog v2 depends on):** [`oneTakeda/rnd-computational-biology-oncology-data-catalog`](https://github.com/oneTakeda/rnd-computational-biology-oncology-data-catalog). Describes `s3://onc-compbio/data-catalog/sources/` (external releases received whole) and `data-catalog/derived/` (team-produced intermediates). First real source-release manifest (`tcga-gdc-dr45-0-test5.yaml`) is committed there; the full TCGA pan-cancer mirror is in progress.

---

## Decisions logged

- **Compute / retrieve separation, enforced physically.** Batch jobs in `batch/{dimension}_{indication}/` write Parquet + evidence artifacts; skills in `skills/query-{dimension}-evidence/` read them. The two never share code. See the runbook on the v1.7.4 failure mode this fixes.
- **Eight dimensions** (revised 2026-06-15 from the runbook's original 8): `expression` was split into `expression-rna` + `expression-protein` so a target eval can explicitly say "RNA up but protein flat" — these are first-class evidence types, not nested fields. `genomic-context` renamed to `mutation-profile` (scoped to somatic mutations; CN/SV deferred). `clinical-outcomes` renamed to `survival`. `patient-stratification` was dropped as a dimension; modeled instead as a **subtype path axis** parameterizing every dimension.
- **DGE methodology = DESeq2 + ComBat-seq + lfcShrink(apeglm)** on raw integer counts, with actionability filter `padj < 0.05 AND |log2FC| ≥ 1 AND baseMean cutoff`. Wilcoxon-on-TPM (the v1 approach) was considered and rejected as not field default for indication-specific tumor-vs-normal DGE.
- **R is the language for the DGE batch.** DESeq2 + ComBat-seq are R/Bioconductor canon. The interface to the rest of the platform is the **Parquet artifact**, not in-process function calls. Python skills consume what R writes — process boundary as architectural seam.
- **Canonical TCGA source = GDC DR45.0**, with full release version + manifest UUIDs + pipeline `workflow_version` pinning (2025 PLOS ONE PMC11878898 found ~44% of genes drift across GDC releases due to pipeline shifts; the release tag alone is insufficient). Cross-comparable TCGA + GTEx layer = recount3 (preferred) or UCSC Xena/Toil. Source decision sourced from the deep-research workflow `wf_f6040283-fdb` (23/25 claims confirmed, 22 primary sources).
- **OncoLand demoted to TPM convenience cache** (`system_of_record: false`, `license: proprietary`). DESeq2 needs raw counts; OncoLand ships TPM-only; it is automatically excluded from canonical compute.
- **Tempus RWD integrates as a `tempus_summary:` block inside the `expression-rna` artifact's `result`** (NOT a separate dimension or subtype). Preserves the Takeda-specific `iDAS_group` strata (MSS_RASMut_3L+, MSS_RASWT_1L2L, etc.) and the RWD-specific `pct_detected` field. Catalog manifest for the Tempus deposit is `tempus-crc-2026-03-17.yaml` (forthcoming) with `system_of_record: false` since the data is pre-aggregated by an upstream pipeline.
- **No DVC.** The catalog manifest's `s3_uri` + `md5` already provide reproducibility; DVC would add tooling overhead without commensurate value at current team size.
- **No `production/` stage in the catalog.** A derived dataset is "blessed" by being cited from `core-artifacts/`; the catalog's `cited_by:` field tracks citations automatically. Anything currently cited by a core artifact is under implicit "do not delete" protection.

The full v2 design rationale and decision log lives in [`personal-notes/strategy/oncology-platform-implementation-runbook.md`](https://github.com/takoncoder/personal-notes/blob/main/strategy/oncology-platform-implementation-runbook.md).

---

## AWS configuration

Two AWS profiles map to two distinct Takeda accounts (deliberate data-sovereignty separation):

| Profile | AWS account | Used by | Purpose |
|---------|---|---------|---------|
| `cbg` | `557690623046` (`tec-rnd-cbg-dev`) | All v2 batch + retrieval; anything reading `s3://onc-compbio/...` | S3 access to the data catalog and core-artifacts |
| `cmp-dev` | `888307857004` (`tec-rnd-cmp-dev`) | Bedrock SDK calls (literature dimension, future LLM-as-judge) | Bedrock access for Sonnet + Opus |

On a fresh SageMaker space:

```bash
aws sso login --profile cbg
aws sso login --profile cmp-dev
export AWS_PROFILE=cbg     # default for data work
```

> The home directory on this SageMaker space is on ephemeral EBS, not EFS — every restart wipes `~/`. The recovery script at [`personal-notes/bin/bootstrap.sh`](https://github.com/takoncoder/personal-notes/blob/main/bin/bootstrap.sh) re-establishes both profiles, gh auth, repo clones, and pixi in one command. Run it after every space restart.

---

## Local development

```bash
git clone https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills.git
cd rnd-computational-biology-oncology-claude-oncology-skills
git checkout v2-architecture
pixi install
```

The repo-root `pixi.toml` carries the env for the v2 batch pipeline (R + DESeq2 + ComBat-seq via Bioconductor — to be added — plus python tooling for `query_evidence.py`). The v1 skills under `skills/{analysis,workflow}-*/` each carry their own `pixi.toml` and remain isolated.

To run the retrieval skill against the live S3:

```bash
export AWS_PROFILE=cbg
pixi run python skills/query-target-evidence/scripts/query_evidence.py \
    --gene SCD1 --indication crc --subtype all --dimension expression-rna
```

(Today this returns `[MISSING] SCD1/crc/all/expression-rna — no artifact. Produced by: batch/expression_rna_crc/run_pipeline.R` — the contract is in place; the first real artifact lands once the GDC mirror completes and the batch pipeline runs.)

---

## Branching strategy

| Branch | Purpose |
|--------|---------|
| `main` | v1 — currently plugin-installable production system |
| **`v2-architecture`** | **You are here.** v2 redesign (compute/retrieve separation, evidence artifact contract, data catalog integration) |
| `feat/*` | Feature branches off `v2-architecture` |

When v2 reaches parity with v1's analytical capabilities, it will be merged to `main` and v1 will become a legacy install path documented in release notes.

---

## Versioning

v2 work is unversioned during development on this branch. The first v2 release will be tagged `v2.0.0` after the merge to `main`, and will be a **major** semver bump because the dimension naming, S3 path schema, and skill-invocation patterns are all breaking changes from v1.

---

## Requirements

- **Python** ≥ 3.10
- **R** ≥ 4.4 with Bioconductor 3.20+ (DESeq2, sva for ComBat-seq, apeglm for lfcShrink, arrow for Parquet) — for the batch DGE pipeline. To be wired into the repo `pixi.toml`.
- **pixi** for env management
- **AWS credentials** — `cbg` profile for S3, `cmp-dev` profile for Bedrock (see [AWS configuration](#aws-configuration))

---

## License

Internal use only — Computational Biology Oncology Team, Takeda Pharmaceuticals.

---

## Authors

- **v1 (main):** Ming-Ju Tsai (ming-ju.tsai@takeda.com)
- **v2 architecture (this branch):** Ryan Abo (ryan.abo@takeda.com), with v1 as foundation
