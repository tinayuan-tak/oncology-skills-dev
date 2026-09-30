# cooccurrence_fisher_pancohort/steps/ — pipeline stage scripts

Fresh session should pick up from here. Progress state below.

## Stage status (updated 2026-07-10 late evening checkpoint)

| # | Script | Lang | Status | Notes |
|---|---|---|---|---|
| 00 | `00_load_mc3.R` | R | **SHIPPED + SMOKE-TESTED** | 27s runtime on 753MB MC3 MAF. Parses to 14 TCGA-cohort sparse binary matrices + PANCAN (10,279 samples × 19,686 genes). Cohort labeling via built-in TSS→study mapping (BRCA/COAD/GBM/LUAD/OV/etc. all present; ~1.1M rows with unmapped TSS fall into OTHER_TSS — mapping is majority-coverage not exhaustive). |
| 01 | `01_panel_intersect.py` | Python | **SHIPPED + SMOKE-TESTED** | 13.5s runtime. 166-gene intersection across 10 workhorse GENIE panels + full 1,927-gene × 166-panel membership matrix. |
| 02 | `02_build_matrices.R` | R | **WRITTEN, UNTESTED** | Parses GENIE `data_mutations_extended.txt` (1.12GB) + `data_clinical_sample.txt`. Cohort labeling from GENIE CANCER_TYPE. Merges with MC3 matrices from stage 00 → per-source cohort matrices (no cross-source alignment in v1). |
| 03 | `03_fisher_per_source.R` | R | **WRITTEN, UNTESTED** | fisher.test() per pair per cohort per source. Filter: mutation rate ≥ 2% AND count ≥ 5. Emits log2_odds_ratio + fisher_p + BH-FDR-per-cohort with pair-symmetric row emission (both A→B and B→A). |
| 04 | `04_discover.R` | R | **NOT WRITTEN** | DISCOVER::pairwise.discover.test on per-cohort matrices. Filter: mutation rate ≥ 2%, pair count ≥ 5. DISCOVER installed as `library(discover)` v0.9.4. |
| 05 | `05_select.R` | R | **NOT WRITTEN** | `library(select); new.AL(...); select(...)` per cohort. SELECT installed v1.6.3. |
| 06 | `06_pool_and_write.R` | R | **NOT WRITTEN** | Union all prior results, apply `pooled_eligible` flag via panel-intersect gate from stage 01, BH-adjust genome-wide, `arrow::write_parquet`. |

## Fresh-session pickup

Environment is 100% operational as of this checkpoint. DISCOVER +
SELECT + all R + Python deps installed. Stage 00 + 01 smoke-tested
end-to-end. Stages 02 + 03 written but untested.

### Session lessons captured (env gotchas)

1. **`remotes::install_github(subdir="R")` is CASE-SENSITIVE** on Linux.
   The DISCOVER R package is at `R/` (capital) in the repo, NOT `r/`.
   Using `subdir="r"` returns HTTP 404 from the GitHub API. Silent
   failure mode — cost ~30 min of diagnostic time.
2. **`data.table::fread` on `.gz` files needs `r-r.utils` peer dep**
   in pixi. Not auto-installed with r-data.table.
3. **`options(warn=2)` at the top of setup.R is TOO aggressive** —
   it elevates deprecation warnings to fatal errors. Use explicit
   exit-status checks (`!requireNamespace()`) instead of global
   warn-to-error escalation.
4. **`install_github` uses GitHub PAT from git credential store** for
   the API. A private/scoped PAT can 404 on public repos where a
   direct `git clone` works. Fallback: manual `git clone` + `install_local`.

### Fresh-session pickup steps

1. Run stage 02 to build GENIE + MC3 unified matrices:
   ```
   pixi run Rscript onc_methods/cooccurrence_fisher_pancohort/steps/02_build_matrices.R \
       --work-dir /tmp/co-workdir
   ```
2. Run stage 03 Fisher tests:
   ```
   pixi run Rscript onc_methods/cooccurrence_fisher_pancohort/steps/03_fisher_per_source.R \
       --work-dir /tmp/co-workdir
   ```
3. Write stages 04/05/06 per contract below.
4. Run derive.py orchestrator end-to-end.
5. Biology validate 5 canonical pairs.
6. Upload + manifest + read.py + PR merge.

## Contract for each stage (unchanged from prior README)

Each stage takes `--work-dir <path>` and writes intermediate artifacts
under that directory. Later stages read prior stages' outputs via
well-known filenames in the work-dir. See `derive.py` for the
orchestration pattern.

## Schema of final parquet output

Enforced by stage 06. Column list defined in the derived manifest
`data-catalog/manifests/derived/pancohort-cooccurrence-fisher-v1.yaml`
(fresh session writes this after materializing the parquet + computing md5).

```
target_gene_symbol   string   primary index key
partner_gene_symbol  string
cohort               string   'PANCAN' | TCGA study code | GENIE cancer type
source               string   'tcga_mc3' | 'genie_v19' | 'pooled'
n_11, n_10, n_01, n_00  int32   2x2 cell counts
log2_odds_ratio      float64
fisher_p, fisher_bh_q  float64
discover_q_value     float64  nullable (may be all-null if DISCOVER dropped)
select_q_value       float64  nullable
select_score         float64  nullable
bh_q_value           float64  min-union — what read.py filters on
pooled_eligible      bool     TRUE iff both target + partner in panel-intersect gene set
ranking_score        float64  -log10(bh_q_value) * sign(log2_odds_ratio)
method_version       string
```

Sort order: `(target_gene_symbol ASC, bh_q_value ASC)` for parquet
predicate-pushdown-friendly reads.

## Biology validation (BLOCKING before merge)

Stage 06 (or a companion validation stage) must confirm all 5 canonical
pairs recover published signs:

  - TP53↔MDM2 in PANCAN: co-occurring, bh_q_value < 0.001
  - IDH1↔TP53 in GBM: mutually exclusive
  - KRAS↔BRAF in COAD: strong mutex (Yaeger 2017)
  - EGFR↔KRAS in LUAD: strong mutex
  - APC↔CTNNB1 in COAD: mutex

## Reference pattern to reuse

- R subprocess pattern: [../../dge_deseq2/r/live/run_pipeline.R:51-57](../../dge_deseq2/r/live/run_pipeline.R)
- R stage script structure: [../../dge_deseq2/r/legacy/03_deseq2.R](../../dge_deseq2/r/legacy/03_deseq2.R) is
  a good template for arg-parsing + rds-round-trip + logging.
- Panel-intersect (already done): [01_panel_intersect.py](01_panel_intersect.py)

## Panel-intersect stage — actual smoke-test results (2026-07-10)

- 166 panel files loaded from S3 GENIE gene_panels/
- 10 workhorse panels present: MSK-IMPACT{341,410,468,505},
  DFCI-ONCOPANEL-{1,2,3,3.1}, VICC-01-T7, VICC-01-D2
- Intersection: **166 genes** (MSK-IMPACT341 = smallest workhorse
  dominates the intersection)
- Full membership matrix: 1,927 unique genes × 166 panels
- Runtime: 13.5s
- Outputs: `panel_intersect_by_cohort.tsv` + `panel_membership.parquet`

For a larger effective panel-intersect gene set, fresh session could
drop MSK-IMPACT341 from the workhorse list — the 341-only genes are
already covered by the larger MSK panels. But 166 genes is defensible
for a pan-cohort pooled analysis (all the canonical driver genes are
in MSK-IMPACT341 by design).
