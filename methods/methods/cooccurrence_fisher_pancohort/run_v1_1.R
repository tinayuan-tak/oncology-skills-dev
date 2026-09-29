#!/usr/bin/env Rscript
# run_v1_1.R — PR 1 v1.1 follow-up: run DISCOVER + SELECT stages then
# re-pool parquet with DISCOVER + SELECT columns populated.
#
# This is a follow-up job that ASSUMES stages 00-03 have already run
# (matrices_by_cohort.rds + fisher_results.rds + panel_intersect.tsv
# exist in --work-dir). Purpose: run the compute-heavy DISCOVER + SELECT
# stages that were deferred in PR 1 v1, then update stage 06's parquet
# output with real DISCOVER + SELECT q-values.
#
# Runtime: potentially hours (DISCOVER + SELECT are per-cohort
# permutation-based). Meant to be run out-of-band via
# `pixi run Rscript ... &` and checked back later.
#
# Reads:
#   <work_dir>/matrices_by_cohort.rds
#   <work_dir>/panel_intersect_by_cohort.tsv
#   <work_dir>/fisher_results.rds
# Writes:
#   <work_dir>/discover_results.rds
#   <work_dir>/select_results.rds
#   <work_dir>/cooccurrence_fisher.v1_1.parquet (v1.1 with all lanes)

options(error = function() { traceback(3); quit(status = 1) })

args <- commandArgs(trailingOnly = TRUE)
if (length(args) < 2 || args[1] != "--work-dir") {
  stop("Usage: run_v1_1.R --work-dir <path> [--out-parquet <path>]")
}
work_dir <- args[2]
out_parquet <- file.path(work_dir, "cooccurrence_fisher.v1_1.parquet")
if (length(args) >= 4 && args[3] == "--out-parquet") {
  out_parquet <- args[4]
}

# Wall-clock timing
overall_t0 <- proc.time()
log <- function(msg) message(sprintf("[run_v1_1 %.0fs] %s",
                                       (proc.time() - overall_t0)["elapsed"], msg))

steps_dir <- file.path(
  dirname(sub("^--file=", "", grep("^--file=", commandArgs(FALSE), value = TRUE)[1])),
  "steps"
)
if (!dir.exists(steps_dir)) {
  # Fallback: assume we're launched from analysis-methods repo root
  steps_dir <- "methods/cooccurrence_fisher_pancohort/steps"
}
log(sprintf("steps dir: %s", steps_dir))

# --- Stage 04: DISCOVER ---
log("Stage 04: DISCOVER (per-cohort Poisson-binomial null)")
system2("Rscript", args = c(file.path(steps_dir, "04_discover.R"),
                             "--work-dir", work_dir))

# --- Stage 05: SELECT ---
log("Stage 05: SELECT (per-cohort BiRewire null + wMI)")
system2("Rscript", args = c(file.path(steps_dir, "05_select.R"),
                             "--work-dir", work_dir))

# --- Stage 06: re-pool + write v1.1 parquet ---
log("Stage 06: re-pool with populated DISCOVER + SELECT columns")
system2("Rscript", args = c(file.path(steps_dir, "06_pool_and_write.R"),
                             "--work-dir", work_dir,
                             "--out-parquet", out_parquet))

log(sprintf("DONE. Output: %s", out_parquet))
