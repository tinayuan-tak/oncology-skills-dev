#!/usr/bin/env Rscript
# Stage 05 — SELECT mutual-exclusivity + co-occurrence via evolutionary
# dependencies (Mina 2020 Nat Genet 52:1198).
#
# SELECT uses BiRewire bipartite-graph null (more principled than
# Poisson-binomial for large TMB variance) + a wMI (weighted Mutual
# Information) statistic capturing evolutionary dependencies.
#
# Reads:
#   <work_dir>/matrices_by_cohort.rds  (from stage 02)
#
# Writes:
#   <work_dir>/select_results.rds  — data.table of pair results
#
# Filters per cohort (same as Fisher/DISCOVER):
#   mutation rate >= 2% AND count >= 5
#
# SELECT API:
#   al <- new.AL(binary_matrix)          # AL = Alteration List
#   result <- select(al, ...)            # returns list with $ALP (pairs table)

options(error = function() { traceback(3); quit(status = 1) })

suppressPackageStartupMessages({
  library(optparse)
  library(data.table)
  library(Matrix)
  library(select)
})

option_list <- list(
  make_option("--work-dir", type = "character", default = NULL),
  make_option("--min-mut-rate", type = "double", default = 0.02),
  make_option("--min-mut-count", type = "integer", default = 5),
  make_option("--n-permut", type = "integer", default = 100,
              help = "Number of null permutations (default 100; paper uses 1000; lower for speed)"),
  make_option("--n-cores", type = "integer", default = 4)
)
opts <- parse_args(OptionParser(option_list = option_list))
if (is.null(opts$`work-dir`)) stop("--work-dir required")
work_dir <- opts$`work-dir`

matrices <- readRDS(file.path(work_dir, "matrices_by_cohort.rds"))
message(sprintf("[05_select] loaded %d cohorts", length(matrices)))

# Working folder for SELECT's intermediate .RData files (SELECT writes these)
select_work <- file.path(work_dir, "select_intermediate")
dir.create(select_work, recursive = TRUE, showWarnings = FALSE)

compute_select_for_cohort <- function(m, cohort_label) {
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
  # SELECT wants alterations x samples (transposed) as a plain matrix
  al_matrix <- as.matrix(t(m_flt))  # genes x samples
  message(sprintf("  [%s] %d samples, %d genes; running SELECT ...",
                  cohort_label, n_samples, nrow(al_matrix)))

  # Per-cohort subfolder to isolate SELECT's intermediate files
  cohort_folder <- file.path(select_work,
                              gsub("[^A-Za-z0-9_-]", "_", cohort_label))
  dir.create(cohort_folder, recursive = TRUE, showWarnings = FALSE)

  # Build AL. new.AL(alterations_matrix, sample_class = NULL,
  #                  alteration_class = NULL, remove.unknown.class.samples = FALSE)
  # For v1 we don't emit subtype/class info — plain alteration matrix.
  al <- tryCatch({
    select::new.AL(
      al = al_matrix,
      # If no sample_class provided, SELECT treats all samples as one class
      sample.class = rep("all", ncol(al_matrix)),
      alteration.class = rep("all", nrow(al_matrix))
    )
  }, error = function(e) {
    message(sprintf("  [%s] new.AL ERROR: %s", cohort_label, conditionMessage(e)))
    return(NULL)
  })
  if (is.null(al)) return(NULL)

  # Run SELECT. Ends with a data.frame $ALP containing per-pair results
  # with columns like: alteration_A, alteration_B, wMI, wMI.perc,
  # APC (Alteration Pairwise Coefficient), FDR.
  result <- tryCatch({
    select::select(
      al = al,
      folder = paste0(cohort_folder, "/"),
      n.cores = opts$`n-cores`,
      n.permut = opts$`n-permut`,
      save.intermediate.files = FALSE,
      calculate_APC_threshold = FALSE,   # skip threshold calc for speed
      calculate_FDR = TRUE,
      verbose = FALSE
    )
  }, error = function(e) {
    message(sprintf("  [%s] select() ERROR: %s", cohort_label, conditionMessage(e)))
    return(NULL)
  })
  if (is.null(result)) return(NULL)

  # Extract pair-results table
  alp <- result$alteration.pairwise
  if (is.null(alp) || length(alp) == 0) return(NULL)

  # SELECT's ALP is a list; the pair-results table is typically at
  # $ALP or has entries like $wMI (matrix), $wMI.perc (matrix), $FDR (matrix).
  # Extract into long-form data.table.
  # This structure is version-dependent; we'll defensively probe.
  extract_alp <- function(alp) {
    dt_list <- list()
    for (measure in c("wMI", "wMI.perc", "APC", "FDR")) {
      if (measure %in% names(alp)) {
        mat <- as.matrix(alp[[measure]])
        if (!is.null(mat) && nrow(mat) > 0) {
          idx <- which(!is.na(mat), arr.ind = TRUE)
          if (nrow(idx) > 0) {
            dt <- data.table(
              target_gene_symbol = rownames(mat)[idx[, 1]],
              partner_gene_symbol = colnames(mat)[idx[, 2]],
              value = mat[idx],
              measure = measure
            )
            dt_list[[measure]] <- dt
          }
        }
      }
    }
    if (length(dt_list) == 0) return(NULL)
    long <- rbindlist(dt_list)
    # Pivot to wide: one row per pair with all measures as columns
    wide <- dcast(long, target_gene_symbol + partner_gene_symbol ~ measure,
                  value.var = "value")
    return(wide)
  }

  pairs_dt <- extract_alp(alp)
  if (is.null(pairs_dt) || nrow(pairs_dt) == 0) {
    message(sprintf("  [%s] SELECT returned no pair results", cohort_label))
    return(NULL)
  }

  # Rename columns to SELECT-prefix convention
  setnames(pairs_dt,
           c("wMI", "wMI.perc", "APC", "FDR"),
           c("select_wMI", "select_wMI_perc", "select_APC", "select_q_value"),
           skip_absent = TRUE)

  # Add cohort + source
  parts <- strsplit(cohort_label, ":", fixed = TRUE)[[1]]
  src <- if (parts[1] == "MC3") "tcga_mc3" else if (parts[1] == "GENIE") "genie_v19" else "unknown"
  co_label <- if (length(parts) >= 2) parts[2] else cohort_label
  pairs_dt[, `:=`(cohort = co_label, source = src)]

  # Pair-symmetric
  flipped <- copy(pairs_dt)
  setnames(flipped, c("target_gene_symbol", "partner_gene_symbol"),
                    c("partner_gene_symbol", "target_gene_symbol"))
  pairs_dt <- rbind(pairs_dt, flipped)

  return(pairs_dt)
}

all_results <- list()
t0 <- proc.time()
for (co in names(matrices)) {
  message(sprintf("[05_select] cohort '%s' ...", co))
  r <- compute_select_for_cohort(matrices[[co]], co)
  if (!is.null(r)) all_results[[co]] <- r
}

combined <- rbindlist(all_results, fill = TRUE)
message(sprintf("[05_select] total pair-rows: %s (%.1fs elapsed)",
                formatC(nrow(combined), big.mark=","),
                (proc.time() - t0)["elapsed"]))

out <- file.path(work_dir, "select_results.rds")
saveRDS(combined, out)
message(sprintf("[05_select] wrote %s (%.1f MB)",
                out, file.info(out)$size / 1e6))
message(sprintf("[05_select] DONE"))
