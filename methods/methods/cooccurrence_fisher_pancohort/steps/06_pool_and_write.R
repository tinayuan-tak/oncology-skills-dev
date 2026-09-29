#!/usr/bin/env Rscript
# Stage 06 — pool all prior stage results into the final parquet.
#
# Merges Fisher (stage 03) + DISCOVER (stage 04) + SELECT (stage 05)
# per-cohort per-source pair results into ONE unified data.table.
# Applies the panel-intersect BLOCKER-fix `pooled_eligible` flag from
# stage 01. BH-adjusts genome-wide across sources. Writes parquet
# with the schema declared in the derived manifest.
#
# Reads:
#   <work_dir>/fisher_results.rds        (stage 03)
#   <work_dir>/discover_results.rds      (stage 04)
#   <work_dir>/select_results.rds        (stage 05)
#   <work_dir>/panel_intersect_by_cohort.tsv  (stage 01)
#
# Writes:
#   --out-parquet path
#
# Output schema (matches data-catalog derived manifest):
#   target_gene_symbol, partner_gene_symbol, cohort, source,
#   n_11, n_10, n_01, n_00,
#   log2_odds_ratio, fisher_p, fisher_bh_q,
#   discover_q_value, select_q_value, select_wMI, select_wMI_perc, select_APC,
#   bh_q_value (min-union of fisher_bh_q + discover_q + select_q),
#   pooled_eligible,
#   ranking_score = -log10(bh_q_value) * sign(log2_odds_ratio),
#   method_version

options(error = function() { traceback(3); quit(status = 1) })

suppressPackageStartupMessages({
  library(optparse)
  library(data.table)
  library(arrow)
})

option_list <- list(
  make_option("--work-dir", type = "character", default = NULL),
  make_option("--out-parquet", type = "character", default = NULL)
)
opts <- parse_args(OptionParser(option_list = option_list))
if (is.null(opts$`work-dir`) || is.null(opts$`out-parquet`)) {
  stop("--work-dir and --out-parquet required")
}
work_dir <- opts$`work-dir`
out_parquet <- opts$`out-parquet`

# --- Load stage outputs ---
message("[06_pool] loading stage results ...")
fisher <- readRDS(file.path(work_dir, "fisher_results.rds"))
discover <- tryCatch(
  readRDS(file.path(work_dir, "discover_results.rds")),
  error = function(e) { message("  DISCOVER results missing — proceeding without"); NULL }
)
select_r <- tryCatch(
  readRDS(file.path(work_dir, "select_results.rds")),
  error = function(e) { message("  SELECT results missing — proceeding without"); NULL }
)
message(sprintf("  fisher rows: %s", formatC(nrow(fisher), big.mark=",")))
if (!is.null(discover)) message(sprintf("  discover rows: %s", formatC(nrow(discover), big.mark=",")))
if (!is.null(select_r)) message(sprintf("  select rows: %s", formatC(nrow(select_r), big.mark=",")))

# --- Load panel-intersect ---
panel <- fread(file.path(work_dir, "panel_intersect_by_cohort.tsv"),
               sep = "\t", header = TRUE)
panel_genes <- unique(panel$gene_symbol)
message(sprintf("[06_pool] panel-intersect gene set: %d genes",
                length(panel_genes)))

# --- Merge Fisher + DISCOVER + SELECT on (target, partner, cohort, source) ---
setkey(fisher, target_gene_symbol, partner_gene_symbol, cohort, source)
combined <- copy(fisher)
if (!is.null(discover) && nrow(discover) > 0) {
  setkey(discover, target_gene_symbol, partner_gene_symbol, cohort, source)
  combined <- merge(
    combined, discover[, .(target_gene_symbol, partner_gene_symbol, cohort,
                            source, discover_q_value, discover_direction)],
    by = c("target_gene_symbol", "partner_gene_symbol", "cohort", "source"),
    all.x = TRUE
  )
} else {
  combined[, `:=`(discover_q_value = NA_real_, discover_direction = NA_character_)]
}
if (!is.null(select_r) && nrow(select_r) > 0) {
  setkey(select_r, target_gene_symbol, partner_gene_symbol, cohort, source)
  select_cols <- c("target_gene_symbol", "partner_gene_symbol", "cohort", "source")
  for (c in c("select_q_value", "select_wMI", "select_wMI_perc", "select_APC")) {
    if (c %in% names(select_r)) select_cols <- c(select_cols, c)
  }
  combined <- merge(
    combined, select_r[, ..select_cols],
    by = c("target_gene_symbol", "partner_gene_symbol", "cohort", "source"),
    all.x = TRUE
  )
} else {
  combined[, `:=`(select_q_value = NA_real_, select_wMI = NA_real_,
                   select_wMI_perc = NA_real_, select_APC = NA_real_)]
}

# --- Panel-intersect eligibility flag ---
combined[, pooled_eligible := (target_gene_symbol %in% panel_genes) &
                              (partner_gene_symbol %in% panel_genes)]

# --- Union q-value (min across the three stat tests) ---
combined[, bh_q_value := pmin(fisher_bh_q,
                              ifelse(is.na(discover_q_value), 1, discover_q_value),
                              ifelse(is.na(select_q_value), 1, select_q_value),
                              na.rm = TRUE)]

# --- Ranking score ---
combined[, ranking_score := -log10(pmax(bh_q_value, 1e-300)) *
                             sign(log2_odds_ratio)]

# --- Method version ---
combined[, method_version := "0.1.0"]

# --- Column ordering to match the derived manifest ---
col_order <- c(
  "target_gene_symbol", "partner_gene_symbol", "cohort", "source",
  "n_11", "n_10", "n_01", "n_00",
  "log2_odds_ratio", "fisher_p", "fisher_bh_q",
  "discover_q_value", "select_q_value", "select_wMI", "select_wMI_perc", "select_APC",
  "bh_q_value", "pooled_eligible", "ranking_score", "method_version"
)
# Retain only columns present
present <- intersect(col_order, names(combined))
combined <- combined[, ..present]

# --- Sort for predicate-pushdown-friendly reads ---
setorder(combined, target_gene_symbol, bh_q_value)

# --- Coerce types (arrow is picky) ---
combined[, n_11 := as.integer(n_11)]
combined[, n_10 := as.integer(n_10)]
combined[, n_01 := as.integer(n_01)]
combined[, n_00 := as.integer(n_00)]
combined[, pooled_eligible := as.logical(pooled_eligible)]

# --- Write parquet ---
message(sprintf("[06_pool] writing %s rows to %s ...",
                formatC(nrow(combined), big.mark=","), out_parquet))
arrow::write_parquet(combined, out_parquet, compression = "snappy")
message(sprintf("[06_pool] parquet size: %.1f MB",
                file.info(out_parquet)$size / 1e6))

# --- Report summary stats ---
message(sprintf("[06_pool] cohorts: %d", length(unique(combined$cohort))))
message(sprintf("[06_pool] sources: %s",
                paste(unique(combined$source), collapse=", ")))
message(sprintf("[06_pool] pooled_eligible rows: %s (%.1f%%)",
                formatC(sum(combined$pooled_eligible), big.mark=","),
                100 * mean(combined$pooled_eligible)))
message(sprintf("[06_pool] rows with bh_q < 0.05: %s",
                formatC(sum(combined$bh_q_value < 0.05, na.rm=TRUE), big.mark=",")))
message(sprintf("[06_pool] rows with bh_q < 0.001: %s",
                formatC(sum(combined$bh_q_value < 0.001, na.rm=TRUE), big.mark=",")))

message("[06_pool] DONE")
