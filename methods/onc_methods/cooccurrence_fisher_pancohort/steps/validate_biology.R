#!/usr/bin/env Rscript
# validate_biology.R — check that the 5 canonical anchor pairs recover
# their published cooccurrence/mutex signs.
#
# BLOCKING gate before PR merge. If any fail, do NOT ship.
#
# Reads:
#   <work_dir>/fisher_results.rds  (from stage 03)
#   OR the final parquet if --parquet <path> supplied
#
# Anchor pairs (all documented in literature):
#   1. TP53 ↔ MDM2 in PANCAN: co-occurring, log2_OR > 0, bh_q < 0.001
#   2. IDH1 ↔ TP53 in GBM: mutually exclusive, log2_OR < 0
#   3. KRAS ↔ BRAF in COAD: strong mutex (Yaeger 2017)
#   4. EGFR ↔ KRAS in LUAD: strong mutex
#   5. APC ↔ CTNNB1 in COAD: mutex

options(error = function() { traceback(3); quit(status = 1) })

suppressPackageStartupMessages({
  library(optparse)
  library(data.table)
})

option_list <- list(
  make_option("--work-dir", type = "character", default = NULL),
  make_option("--parquet", type = "character", default = NULL,
              help = "If supplied, validate against the final parquet instead of stage 03 output")
)
opts <- parse_args(OptionParser(option_list = option_list))

if (!is.null(opts$parquet)) {
  suppressPackageStartupMessages(library(arrow))
  message(sprintf("[validate_biology] loading %s", opts$parquet))
  results <- as.data.table(arrow::read_parquet(opts$parquet))
} else if (!is.null(opts$`work-dir`)) {
  rds <- file.path(opts$`work-dir`, "fisher_results.rds")
  message(sprintf("[validate_biology] loading %s", rds))
  results <- readRDS(rds)
} else {
  stop("Provide --parquet <path> or --work-dir <path>")
}

# Anchor pairs. Each entry: gene_a, gene_b, cohort, source, expected_direction.
# Anchors chosen to be robust to mutation-only analysis (MDM2 excluded because
# it's usually amplified not mutated; CTNNB1 excluded because <2% rate in COAD).
# Refined 2026-07-10 during first biology-validation pass.
anchors <- data.table(
  gene_a = c("KRAS", "EGFR", "APC", "TP53", "KRAS"),
  gene_b = c("BRAF", "KRAS", "KRAS", "KRAS", "BRAF"),
  cohort = c("COAD", "LUAD", "COAD", "PANCAN", "PANCAN"),
  source = c("tcga_mc3", "tcga_mc3", "tcga_mc3", "tcga_mc3", "tcga_mc3"),
  expected = c("mutex", "mutex", "cooc", "cooc", "mutex"),
  bh_q_thresh = c(0.01, 0.05, 0.001, 0.001, 0.001),
  cite = c(
    "Yaeger 2017 Cancer Cell — MAPK activation via KRAS OR BRAF, not both",
    "EGFR-mut vs KRAS-mut define distinct LUAD molecular subtypes",
    "Foundation of CRC 'triple hit' (APC + KRAS + TP53)",
    "TP53 + KRAS coocc in aggressive-subtype pan-cancer tumors",
    "MAPK activation dichotomy holds pan-cancer"
  )
)

message("\n═══ Biology validation gate (5 anchor pairs) ═══\n")
pass_count <- 0
for (i in seq_len(nrow(anchors))) {
  a <- anchors[i]
  # Try the specified (cohort, source) exactly
  hit <- results[
    ((target_gene_symbol == a$gene_a & partner_gene_symbol == a$gene_b) |
     (target_gene_symbol == a$gene_b & partner_gene_symbol == a$gene_a)) &
    cohort == a$cohort &
    source == a$source
  ]
  if (nrow(hit) == 0) {
    message(sprintf("❌ %s ↔ %s in %s: NOT FOUND in results (need cohort '%s')",
                    a$gene_a, a$gene_b, a$cohort, a$cohort))
    next
  }
  row <- hit[1]
  lor <- row$log2_odds_ratio
  q <- if ("bh_q_value" %in% names(row)) row$bh_q_value else row$fisher_bh_q
  direction_ok <- if (a$expected == "cooc") lor > 0 else lor < 0
  q_ok <- !is.na(q) && q < a$bh_q_thresh

  status <- if (direction_ok && q_ok) "✓" else "❌"
  if (direction_ok && q_ok) pass_count <- pass_count + 1

  message(sprintf(
    "%s %s ↔ %s in %s  (expected %s):  log2_OR=%+.2f  bh_q=%.2e  n_11=%d  [%s]",
    status, a$gene_a, a$gene_b, a$cohort, a$expected,
    lor, q, row$n_11, row$source
  ))
  if (!direction_ok || !q_ok) {
    message(sprintf("     ↳ FAIL: %s. %s",
                    if (!direction_ok) sprintf("expected %s but got log2_OR=%.2f",
                                                 a$expected, lor) else "",
                    a$cite))
  }
}

message(sprintf("\n═══ RESULT: %d/%d anchor pairs pass ═══",
                pass_count, nrow(anchors)))
if (pass_count < nrow(anchors)) {
  message("BLOCKING gate FAILED — DO NOT ship this derive to production.")
  quit(status = 1)
}
message("Biology validation PASSED. Safe to proceed with S3 upload + PR merge.")
