#!/usr/bin/env Rscript
# kscan_cr.R — RUVg k-sensitivity curve for the Stage-1 calibration (plan B4).
#
# The main calibration runner (run_calibration_cells.R) computes cell Cr at a
# single --k. This script re-fits ONLY cell Cr at a list of k values for one
# already-loaded matrix, writing cell_Cr_k{K}.tsv beside the existing A/C cells.
# Cells A and C do NOT depend on k, so they are reused as-is by the Python
# concordance step — we never recompute them here. This keeps the k-scan cheap:
# one ruvg_fit per k, no wasted anchor/naive re-fits.
#
# Purpose: the k=2 calibration was inconclusive-to-negative (RUVg-Cr did not
# improve concordance with the within-TCGA anchor A). The k-scan tests whether
# that is a k-tuning artifact or a structural property of the fully-confounded
# cross-cohort design (cohort collinear with group).

suppressPackageStartupMessages({
  library(optparse)
  library(data.table)
  library(DESeq2)
  library(RUVSeq)
  library(apeglm)
  library(BiocParallel)
})

option_list <- list(
  make_option("--in", type = "character", dest = "in_rds",
              help = "Input .rds from a 00_load_*.R loader (counts + coldata)."),
  make_option("--out-dir", type = "character",
              help = "Existing cells__<substrate>__<indication> dir (Cr TSVs written here)."),
  make_option("--ks", type = "character", default = "1,4,6",
              help = "Comma-separated k values to fit (k=2 already done by main runner)."),
  make_option("--min-normals", type = "integer", default = 3L),
  make_option("--threads", type = "integer", default = 4L)
)
opts <- parse_args(OptionParser(option_list = option_list))
stopifnot(!is.null(opts$in_rds), !is.null(opts$`out-dir`))
register(MulticoreParam(workers = opts$threads))

args_all <- commandArgs(trailingOnly = FALSE)
script_path <- sub("^--file=", "", args_all[grep("^--file=", args_all)])
steps_dir <- normalizePath(file.path(dirname(script_path), "..", "..", "..", "steps"))
source(file.path(steps_dir, "_four_cell_lib.R"))

obj <- readRDS(opts$in_rds)
counts <- obj$counts
cd     <- obj$coldata
stopifnot(ncol(counts) == nrow(cd), all(colnames(counts) == rownames(cd)))

tumor <- cd$sample_id[cd$group == "tumor"]
gtex  <- cd$sample_id[cd$group == "normal" & cd$source == "GTEx"]
if (length(gtex) < opts$`min-normals`) stop("insufficient GTEx normals for k-scan")

write_cr <- function(df, k) {
  keep <- data.frame(
    gene_symbol = df$gene_symbol,
    log2fc      = df$log2FoldChange,
    padj        = df$padj,
    svalue      = if ("svalue" %in% names(df)) df$svalue else NA_real_,
    baseMean    = df$baseMean,
    stringsAsFactors = FALSE)
  path <- file.path(opts$`out-dir`, sprintf("cell_Cr_k%d.tsv", k))
  data.table::fwrite(keep, path, sep = "\t")
  message(sprintf("[kscan]   wrote cell Cr k=%d (%d genes) -> %s", k, nrow(keep), path))
}

ids <- c(tumor, gtex)
ks <- as.integer(strsplit(opts$ks, ",")[[1]])
for (k in ks) {
  message(sprintf("[kscan] fitting Cr at k=%d (%d tumor + %d GTEx)", k, length(tumor), length(gtex)))
  fit <- ruvg_fit(counts[, ids, drop = FALSE], cd[ids, , drop = FALSE], k = k)
  write_cr(fit, k)
}
message("[kscan] done: ", opts$`out-dir`)
