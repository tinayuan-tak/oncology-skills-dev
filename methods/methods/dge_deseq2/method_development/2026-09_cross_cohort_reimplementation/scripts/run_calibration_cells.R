#!/usr/bin/env Rscript
# run_calibration_cells.R — compute the THREE calibration cells for one
# (substrate × indication) loaded matrix and write them as TSVs the Python
# concordance step joins on gene_symbol:
#
#   A  = TCGA tumor vs TCGA adjacent-normal      (deseq2_fit, ~ group)   — the ANCHOR
#   C  = TCGA tumor vs GTEx normal (naive)        (deseq2_fit, ~ group)   — the confounded arm
#   Cr = TCGA tumor vs GTEx normal (RUVg-corrected) (ruvg_fit, ~ W_k + group)
#
# Cell B (within-TCGA ComBat re-run of A) is DELIBERATELY SKIPPED: it is a
# robustness re-run of the SAME samples/comparator as A and adds nothing to the
# A-vs-Cr concordance question the calibration exists to answer, while being the
# most expensive cell (ComBat_seq over the full matrix). The production drivers
# (06/07) still run B; this dev-only runner does not.
#
# Each cell is written only if its two groups both clear --min-normals. A missing
# cell (e.g. xena-paad adjacent n=4 is fine, but a cohort with 0 adjacent) simply
# yields no TSV for that cell; the Python side treats an absent anchor as "no A
# comparison available" rather than an error.

suppressPackageStartupMessages({
  library(optparse)
  library(data.table)
  library(DESeq2)
  library(RUVSeq)
  library(apeglm)
})

option_list <- list(
  make_option("--in", type = "character", dest = "in_rds",
              help = "Input .rds from a 00_load_*.R loader (counts + coldata)."),
  make_option("--out-dir", type = "character", help = "Output directory for cell TSVs + provenance."),
  make_option("--substrate", type = "character", default = "unknown",
              help = "Substrate label recorded in provenance (recount3 | xena-toil)."),
  make_option("--indication", type = "character", default = "unknown"),
  make_option("--min-normals", type = "integer", default = 3L),
  make_option("--k", type = "integer", default = 2L, help = "RUVg latent factor count."),
  make_option("--threads", type = "integer", default = 4L)
)
opts <- parse_args(OptionParser(option_list = option_list))
stopifnot(!is.null(opts$in_rds), !is.null(opts$`out-dir`))
out_dir <- opts$`out-dir`
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)

# BiocParallel: bound worker count so serial multi-run orchestration does not
# oversubscribe the host (memory-pressure reboots — see corpus-regen notes).
suppressPackageStartupMessages(library(BiocParallel))
register(MulticoreParam(workers = opts$threads))

# Resolve the shared cell library relative to THIS script's location so the dev
# runner and the production drivers source byte-identical compute.
args_all <- commandArgs(trailingOnly = FALSE)
script_path <- sub("^--file=", "", args_all[grep("^--file=", args_all)])
steps_dir <- normalizePath(file.path(dirname(script_path), "..", "..", "..", "steps"))
source(file.path(steps_dir, "_four_cell_lib.R"))

obj <- readRDS(opts$in_rds)
counts <- obj$counts
cd     <- obj$coldata
stopifnot(ncol(counts) == nrow(cd), all(colnames(counts) == rownames(cd)))

tumor  <- cd$sample_id[cd$group == "tumor"]
adj    <- cd$sample_id[cd$group == "normal" & cd$source == "TCGA"]
gtex   <- cd$sample_id[cd$group == "normal" & cd$source == "GTEx"]
message(sprintf("[calib] %s/%s: %d tumor, %d TCGA-adjacent, %d GTEx",
                opts$substrate, opts$indication, length(tumor), length(adj), length(gtex)))

write_cell <- function(df, label) {
  # Normalize to a stable column set: gene_symbol, log2fc, padj, svalue, baseMean.
  keep <- data.frame(
    gene_symbol = df$gene_symbol,
    log2fc      = df$log2FoldChange,
    padj        = df$padj,
    svalue      = if ("svalue" %in% names(df)) df$svalue else NA_real_,
    baseMean    = df$baseMean,
    stringsAsFactors = FALSE)
  path <- file.path(out_dir, sprintf("cell_%s.tsv", label))
  data.table::fwrite(keep, path, sep = "\t")
  message(sprintf("[calib]   wrote cell %s (%d genes) -> %s", label, nrow(keep), path))
}

prov <- list(substrate = opts$substrate, indication = opts$indication,
             n_tumor = length(tumor), n_adjacent = length(adj), n_gtex = length(gtex),
             min_normals = opts$`min-normals`, k = opts$k, cells = list())

run_deseq_cell <- function(label, ids_norm) {
  if (length(ids_norm) < opts$`min-normals`) {
    message(sprintf("[calib]   cell %s SKIPPED (n_normal=%d < %d)",
                    label, length(ids_norm), opts$`min-normals`))
    prov$cells[[label]] <<- list(ran = FALSE, reason = "insufficient normals")
    return(invisible(NULL))
  }
  ids <- c(tumor, ids_norm)
  fit <- deseq2_fit(counts[, ids, drop = FALSE], cd[ids, , drop = FALSE], with_svalue = TRUE)
  write_cell(fit, label)
  prov$cells[[label]] <<- list(ran = TRUE, n_genes = nrow(fit),
                               n_tumor = length(tumor), n_normal = length(ids_norm))
}

# --- cell A (anchor) --------------------------------------------------------
run_deseq_cell("A", adj)
# --- cell C (naive cross-cohort) --------------------------------------------
run_deseq_cell("C", gtex)
# --- cell Cr (RUVg-corrected cross-cohort) ----------------------------------
if (length(gtex) >= opts$`min-normals`) {
  ids <- c(tumor, gtex)
  fit <- ruvg_fit(counts[, ids, drop = FALSE], cd[ids, , drop = FALSE], k = opts$k)
  write_cell(fit, "Cr")
  ruv <- attr(fit, "ruv")
  prov$cells[["Cr"]] <- list(ran = TRUE, n_genes = nrow(fit),
                             n_tumor = length(tumor), n_normal = length(gtex),
                             k = ruv$k, control_strategy = ruv$control_strategy,
                             n_control = ruv$n_control, n_empirical = ruv$n_empirical,
                             n_hk_present = ruv$n_hk_present,
                             n_hk_in_control = ruv$n_hk_in_control)
} else {
  message("[calib]   cell Cr SKIPPED (insufficient GTEx normals)")
  prov$cells[["Cr"]] <- list(ran = FALSE, reason = "insufficient GTEx normals")
}

jsonlite::write_json(prov, file.path(out_dir, "provenance.json"),
                     auto_unbox = TRUE, pretty = TRUE, null = "null")
message("[calib] done: ", out_dir)
