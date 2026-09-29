#!/usr/bin/env Rscript
# Stage 04 — DISCOVER pairwise mutual-exclusivity + co-occurrence test.
#
# DISCOVER (Canisius 2016 Genome Biology 17:261) uses a Poisson-binomial
# null accounting for per-sample TMB, addressing the spurious co-mutation
# signal that plain Fisher's exact produces on samples with different
# mutation burdens.
#
# Reads:
#   <work_dir>/matrices_by_cohort.rds  (from stage 02)
#
# Writes:
#   <work_dir>/discover_results.rds  — data.table of pair results
#
# Filters per cohort:
#   - mutation rate >= 2% AND count >= 5 (same as Fisher stage 03)
#   - Skip cohorts with < 5 qualifying genes (DISCOVER needs meaningful gene set)
#
# DISCOVER API:
#   background <- discover.matrix(m)  # fit Poisson-binomial background
#   result_me <- pairwise.discover.test(background[genes,], alternative="less")   # mutex
#   result_co <- pairwise.discover.test(background[genes,], alternative="greater") # cooc
#   → returns per-pair p-values with FDR-adjusted q-values via BH.

options(error = function() { traceback(3); quit(status = 1) })

suppressPackageStartupMessages({
  library(optparse)
  library(data.table)
  library(Matrix)
  library(discover)
})

option_list <- list(
  make_option("--work-dir", type = "character", default = NULL),
  make_option("--min-mut-rate", type = "double", default = 0.02),
  make_option("--min-mut-count", type = "integer", default = 5),
  make_option("--fdr-thresh", type = "double", default = 0.5,
              help = "Emit DISCOVER results with q <= this threshold (default 0.5)")
)
opts <- parse_args(OptionParser(option_list = option_list))
if (is.null(opts$`work-dir`)) stop("--work-dir required")
work_dir <- opts$`work-dir`

matrices <- readRDS(file.path(work_dir, "matrices_by_cohort.rds"))
message(sprintf("[04_discover] loaded %d cohorts", length(matrices)))

compute_discover_for_cohort <- function(m, cohort_label) {
  n_samples <- nrow(m)
  gene_counts <- Matrix::colSums(m)
  gene_rates <- gene_counts / n_samples
  keep <- which(gene_counts >= opts$`min-mut-count` &
                gene_rates >= opts$`min-mut-rate`)
  if (length(keep) < 5) {
    message(sprintf("  [%s] SKIP: only %d genes pass filter",
                    cohort_label, length(keep)))
    return(NULL)
  }
  m_flt <- m[, keep, drop = FALSE]
  genes <- colnames(m_flt)
  n_genes <- length(genes)
  message(sprintf("  [%s] %d samples, %d genes; fitting background ...",
                  cohort_label, n_samples, n_genes))

  # DISCOVER expects a matrix (samples x genes but transposed to genes x samples
  # for its internal representation). Convert sparse → dense-ish; DISCOVER
  # accepts sparse but the API is smoother with a plain matrix for small
  # per-cohort gene sets (~200-500 genes typically pass the 2% filter).
  m_dense <- as.matrix(t(m_flt))  # now genes x samples

  # discover.matrix fits the Poisson-binomial background — this is
  # the compute-heavy step (~seconds for ~500 genes × ~1000 samples).
  bg <- tryCatch({
    discover::discover.matrix(m_dense)
  }, error = function(e) {
    message(sprintf("  [%s] discover.matrix ERROR: %s", cohort_label,
                    conditionMessage(e)))
    return(NULL)
  })
  if (is.null(bg)) return(NULL)

  # Pairwise mutex test (alternative='less' = under-representation vs null)
  res_me <- tryCatch({
    discover::pairwise.discover.test(bg, alternative = "less",
                                      fdr.method = "DBH")
  }, error = function(e) {
    message(sprintf("  [%s] pairwise.discover.test(less) ERROR: %s",
                    cohort_label, conditionMessage(e)))
    return(NULL)
  })
  # Pairwise co-occurrence test (alternative='greater' = over-representation)
  res_co <- tryCatch({
    discover::pairwise.discover.test(bg, alternative = "greater",
                                      fdr.method = "DBH")
  }, error = function(e) {
    message(sprintf("  [%s] pairwise.discover.test(greater) ERROR: %s",
                    cohort_label, conditionMessage(e)))
    return(NULL)
  })

  # Result objects have $p.values (matrix) and $q.values (matrix)
  # gene_i x gene_j triangular. Extract into long-form data.table.
  extract_pairs <- function(res, direction) {
    if (is.null(res)) return(NULL)
    # discover result stores upper-triangular p/q values
    p_mat <- as.matrix(res$p.values)
    q_mat <- as.matrix(res$q.values)
    if (is.null(p_mat) || nrow(p_mat) == 0) return(NULL)
    # Convert to long-form
    idx <- which(!is.na(p_mat), arr.ind = TRUE)
    if (nrow(idx) == 0) return(NULL)
    dt <- data.table(
      target_gene_symbol = rownames(p_mat)[idx[, 1]],
      partner_gene_symbol = colnames(p_mat)[idx[, 2]],
      discover_p_value = p_mat[idx],
      discover_q_value = q_mat[idx],
      discover_direction = direction
    )
    dt
  }

  me_dt <- extract_pairs(res_me, "mutex")
  co_dt <- extract_pairs(res_co, "cooc")
  combined <- rbindlist(list(me_dt, co_dt), fill = TRUE)
  if (nrow(combined) == 0) return(NULL)

  # Add cohort + source
  parts <- strsplit(cohort_label, ":", fixed = TRUE)[[1]]
  src <- if (parts[1] == "MC3") "tcga_mc3" else if (parts[1] == "GENIE") "genie_v19" else "unknown"
  co_label <- if (length(parts) >= 2) parts[2] else cohort_label
  combined[, `:=`(cohort = co_label, source = src)]

  # Emit pair-symmetric (both A→B and B→A) for read.py index compatibility
  flipped <- copy(combined)
  setnames(flipped, c("target_gene_symbol", "partner_gene_symbol"),
                    c("partner_gene_symbol", "target_gene_symbol"))
  combined <- rbind(combined, flipped)

  return(combined)
}

all_results <- list()
t0 <- proc.time()
for (co in names(matrices)) {
  message(sprintf("[04_discover] cohort '%s' ...", co))
  r <- compute_discover_for_cohort(matrices[[co]], co)
  if (!is.null(r)) all_results[[co]] <- r
}

combined <- rbindlist(all_results, fill = TRUE)
message(sprintf("[04_discover] total pair-rows: %s (%.1fs elapsed)",
                formatC(nrow(combined), big.mark=","),
                (proc.time() - t0)["elapsed"]))

out <- file.path(work_dir, "discover_results.rds")
saveRDS(combined, out)
message(sprintf("[04_discover] wrote %s (%.1f MB)",
                out, file.info(out)$size / 1e6))
message(sprintf("[04_discover] DONE"))
