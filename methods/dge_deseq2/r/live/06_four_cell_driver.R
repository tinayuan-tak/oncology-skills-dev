#!/usr/bin/env Rscript
# 06_four_cell_driver.R — run the four-cell sensitivity DEG from ONE loaded
# recount3 bundle (output of 00_load_recount3.R) and emit sensitivity.parquet
# plus the primary contrast parquets and the adjacent-vs-GTEx QC diagnostic.
#
# Cells (see DESIGN_v2_four_cell_consolidation.md §2.1):
#   A  TCGA tumor vs TCGA adjacent-normal    | raw           | ~ group
#   C  TCGA tumor vs GTEx normal (joint)     | raw           | ~ group  (naive)
#   AG TCGA adjacent-normal vs GTEx normal   | raw           | ~ group  (diagnostic-only)
#
# Cell B (ComBat-seq TSS re-run of cell A on the SAME samples) was removed in
# analysis-methods#727: it was a robustness re-run of cell A, not an independent
# comparator, and its ComBat-seq step both inflated/sign-flipped log2FC and was
# the pipeline's perf cliff. Cell D (ComBat source) was retired earlier (see the
# cell C block below).
#
# A gene's `cells_supporting` = count of cells where padj<0.05 in the same
# direction as the dominant sign. `sig_all_cells` = padj<0.05 same-direction in
# all cells that ran (the gold-standard call). Cell A is skipped when TCGA
# adjacent-normal < min_normals; cell C is skipped when no GTEx tissue.
#
# Cell AG (adjacent-vs-GTEx, analysis-methods#695) is a NORMAL-vs-NORMAL QC
# contrast, not a selectivity vote — it measures the combined TCGA-vs-GTEx
# nuisance envelope (batch + field-effect + RIN/ischemic + annotation), so a
# LARGE effect is the expected diagnostic signal, not a defect. Like cell Cr
# (RUVg, diagnostic-only), it is emitted as its OWN byproduct (adj_vs_gtex.parquet)
# and is NEVER added to the `cells` list that feeds assemble_sensitivity — so it
# does not enter sensitivity.parquet, cells_supporting, or any concordance
# column. Its best downstream use is as the evaluation target for a source-
# correction (RUVg / cell Cr) — does correction shrink it toward the null?

suppressPackageStartupMessages({
  library(optparse)
  library(DESeq2)
  library(apeglm)
  library(sva)
  library(BiocParallel)
  library(arrow)
})

# Source the shared four-cell compute (prefilter / deseq2_fit / run_cell /
# assemble_sensitivity). Robust self-location under `pixi run Rscript`.
.args <- commandArgs(trailingOnly = FALSE)
.here <- dirname(normalizePath(sub("^--file=", "", .args[grepl("^--file=", .args)][1])))
source(file.path(.here, "_four_cell_lib.R"))
# S3b (#702): the per-contrast QC report bundle (figures/ + metrics row). Pure
# functions of the fit's attributes — defined separately, side-effect-free.
source(file.path(.here, "_qc_figures.R"))

option_list <- list(
  make_option("--in", type = "character", dest = "in_path",
              help = "Output of 00_load_recount3.R (.rds)"),
  make_option("--out-dir", type = "character",
              help = "Directory for sensitivity.parquet + the two contrast parquets"),
  make_option("--min-normals", type = "integer", default = 3,
              help = "Minimum samples per group for a cell to run (DESeq2 floor)."),
  make_option("--threads", type = "integer", default = 4)
)
opts <- parse_args(OptionParser(option_list = option_list))
stopifnot(!is.null(opts$in_path), !is.null(opts$`out-dir`))
dir.create(opts$`out-dir`, showWarnings = FALSE, recursive = TRUE)
register(MulticoreParam(workers = opts$threads))

# Force line-buffered writes so a background run's log is inspectable live.
options(warn = 1)
flog <- function(msg) {
  writeLines(paste0("[", format(Sys.time(), "%H:%M:%S"), "] ", msg))
  flush(stdout())
}

dat     <- readRDS(opts$in_path)
counts  <- dat$counts
coldata <- dat$coldata
min_n   <- opts$`min-normals`

# --- additive gene-id annotation (analysis-methods#835, #761 S1; verdict-NEUTRAL) ---
# Carry the loader's rowdata gene_id (versioned Ensembl, e.g. ENSG00000133703.13)
# and its unversioned gene_stem onto an emitted per-gene frame by LEFT-joining on
# gene_symbol. Purely ADDITIVE provenance columns: the loader already collapsed
# counts to ONE row per gene_symbol (rowsum), and every downstream vote / parquet
# filter still keys on gene_symbol, so gene_symbol / log2FC / padj stay
# byte-identical. The join uses match() on the frame's OWN gene_symbol, so row
# order is preserved (no re-sort). A bundle that predates rowdata (or lacks the
# columns) gets explicit NA columns, keeping the emitted schema stable across
# substrates / vintages.
rowdata <- dat$rowdata
annotate_gene_ids <- function(df) {
  if (is.null(rowdata) ||
      !all(c("gene_symbol", "gene_id", "gene_stem") %in% names(rowdata))) {
    df$gene_id   <- NA_character_
    df$gene_stem <- NA_character_
    return(df)
  }
  mi <- match(df$gene_symbol, rowdata$gene_symbol)
  df$gene_id   <- as.character(rowdata$gene_id)[mi]
  df$gene_stem <- as.character(rowdata$gene_stem)[mi]
  df
}

# The four-cell compute (prefilter / deseq2_fit / run_cell / assemble_sensitivity)
# is sourced from _four_cell_lib.R above and shared with
# 07_stratified_four_cell_driver.R. run_cell is called with (out_dir, min_n,
# flog) — previously closed-over globals, now explicit args.

# --- sample partitions ------------------------------------------------------
is_tumor    <- coldata$group == "tumor"                          # all TCGA tumor
is_adjacent <- coldata$group == "normal" & coldata$source == "TCGA"
is_gtex     <- coldata$group == "normal" & coldata$source == "GTEx"

tumor_ids    <- rownames(coldata)[is_tumor]
adjacent_ids <- rownames(coldata)[is_adjacent]
gtex_ids     <- rownames(coldata)[is_gtex]

message(sprintf("[06_four_cell] partitions: %d tumor | %d TCGA-adjacent | %d GTEx",
                length(tumor_ids), length(adjacent_ids), length(gtex_ids)))

# --- cell A: tumor vs adjacent, raw -----------------------------------------
cellA <- NULL; cellC <- NULL; cellAG <- NULL

# Known-marker panel for the fail-loud sign check (S3a #701): the pan-cancer
# tumor-UP proliferation panel is a global-sign-inversion tripwire for the
# tumor-vs-normal cells A/C. Cell AG (normal-vs-normal) is DELIBERATELY given
# no panel — proliferation markers are not expected up between two normal
# cohorts, so a sign check there would be meaningless.
qc_indication <- dat$metadata$tcga_studies
tumor_panel   <- marker_panel_for(qc_indication)

if (length(adjacent_ids) >= min_n) {
  ids <- c(tumor_ids, adjacent_ids)
  cellA <- run_cell("A", counts[, ids], coldata[ids, ], opts$`out-dir`, min_n, flog,
                    qc_panel = tumor_panel, qc_indication = qc_indication)
} else {
  message("[06_four_cell] cell A SKIPPED — TCGA adjacent-normal < ", min_n)
}

# --- cell C: tumor vs GTEx, raw ---------------------------------------------
# Cell D (ComBat_seq batch=source) was RETIRED after the initial full-cohort
# COADREAD validation showed it collapses biology entirely: with source
# perfectly confounded with group, ComBat_seq(group=NULL) regresses out the
# tumor-vs-normal signal along with the source effect (empirical result at the
# time, when cell B still ran: mean|log2FC|=0.05 vs 1.05-1.40 in the other
# cells; only 1,205 sig genes vs 20-28K). The intended "pessimistic anchor"
# reads as noise, not signal. Trust anchor is therefore cells A/C (cell B
# removed in #727); design doc §2.1
# documents the retirement and the reasoning. Future work: replace with
# an RUV/SVASeq-based source-adjustment that preserves group signal.
if (length(gtex_ids) >= min_n) {
  ids <- c(tumor_ids, gtex_ids)
  cellC <- run_cell("C", counts[, ids], coldata[ids, ], opts$`out-dir`, min_n, flog,
                    qc_panel = tumor_panel, qc_indication = qc_indication)
} else {
  message("[06_four_cell] cell C SKIPPED — GTEx normal < ", min_n,
          " (no GTEx tissue for this indication?)")
}

# --- cell AG: adjacent-normal vs GTEx normal, raw (DIAGNOSTIC-ONLY) ----------
# Normal-vs-normal QC contrast (analysis-methods#695): does the TCGA-vs-GTEx
# nuisance envelope (cross-cohort batch + field-cancerized peritumoral effect +
# RIN/ischemic + annotation skew) that confounds cell C also show up between the
# two NORMAL cohorts? A large effect is the EXPECTED signal here.
#
# `deseq2_fit`/`run_cell` are reused UNCHANGED: both hardcode a two-level
# `group` factor (levels normal/tumor) with contrast (tumor, normal). This cell
# has no tumor arm, so we RELABEL the coldata we pass — TCGA-adjacent takes the
# "tumor" (positive) level and GTEx takes the "normal" (reference) level. The
# SIGN CONVENTION is therefore: log2FC > 0 == higher in TCGA adjacent-normal
# than in GTEx normal — the SAME TCGA-positive / GTEx-reference orientation as
# cell C, so the two are directly comparable. The convention is also written
# INTO adj_vs_gtex.parquet (positive_group / reference_group columns) so the
# sign is never left to a naming convention. The `study` covariate in
# deseq2_fit self-disables exactly as it does for cell C: the GTEx ("normal")
# arm is a single study level, so the both-groups-span->1-study guard is false
# and the design stays ~ group.
#
# Substrate: this cell runs on WHATEVER substrate's bundle carries both
# partitions (recount3 AND xena_toil), guarded by the same min_n check as cells
# A/C — 06 is substrate-agnostic, so no gate is added (user decision, #695).
# It is diagnostic-only and classifier-excluded on every substrate.
if (length(adjacent_ids) >= min_n && length(gtex_ids) >= min_n) {
  ids <- c(adjacent_ids, gtex_ids)
  cd_ag <- coldata[ids, , drop = FALSE]
  cd_ag$group <- ifelse(rownames(cd_ag) %in% adjacent_ids, "tumor", "normal")
  cellAG <- run_cell("AG", counts[, ids], cd_ag, opts$`out-dir`, min_n, flog)
} else {
  message("[06_four_cell] cell AG SKIPPED — need >= ", min_n,
          " each of TCGA-adjacent AND GTEx normal")
}

# NOTE: cellAG is DELIBERATELY absent from this list — it is a normal-vs-normal
# QC diagnostic, not a selectivity comparator, so it must never join the
# concordance vote (cells_supporting / sig_all_cells). Mirrors cell Cr. Its
# exclusion is proved byte-identical-before/after in
# tests/test_adj_vs_gtex_excluded_from_sensitivity.py.
cells <- Filter(Negate(is.null), list(A = cellA, C = cellC))
if (length(cells) == 0) stop("No cells ran — check sample availability.")

# --- sensitivity concordance (shared with 07; see _four_cell_lib.R) ---------
# NOTE (analysis-methods#727): cell B (the ComBat robustness re-run of cell A on
# the identical tumour-vs-adjacent sample set) was removed — counting it as a
# second supporting vote double-counted the SAME comparison, and it corrupted
# log2FC. The remaining cells A (tumour vs TCGA adjacent) and C (tumour vs GTEx)
# are the two GENUINELY independent comparators; their cross-comparator agreement
# is exposed downstream via _family_direction (dge_deseq2/read.py).
lab_ran <- names(cells)
sens <- assemble_sensitivity(cells)
# Additive provenance: gene_id / gene_stem alongside the gene_symbol key (#835).
sens <- annotate_gene_ids(sens)

# --- write outputs ----------------------------------------------------------
sens_path <- file.path(opts$`out-dir`, "sensitivity.parquet")
arrow::write_parquet(sens, sens_path, chunk_size = 1024,
                     compression = "snappy", use_dictionary = TRUE)
message(sprintf("[06_four_cell] wrote %s  (%d genes; sig_all_cells=%d; discordant=%d; cells_ran=%s)",
                sens_path, nrow(sens), sum(sens$sig_all_cells),
                sum(sens$discordant), paste(lab_ran, collapse = "")))

# Primary contrast parquets (backward-compat shape) for cells A (adjacent) & C
# (gtex). `positive_group`/`reference_group`: when supplied, two CONSTANT string
# columns record the sign convention (log2FC > 0 == higher in positive_group)
# directly in the parquet — used by the normal-vs-normal adj_vs_gtex byproduct,
# whose sign is otherwise uninterpretable. Default NULL leaves cells A/C's
# products byte-identical (no extra columns).
write_contrast <- function(cell, lab, fname, n_normal_desc,
                           positive_group = NULL, reference_group = NULL) {
  if (is.null(cell)) return(invisible(NULL))
  df <- data.frame(
    gene_symbol    = cell$gene_symbol,
    log2FoldChange = cell[[paste0("log2fc_", lab)]],
    padj           = cell[[paste0("padj_",   lab)]],
    baseMean       = cell[[paste0("baseMean_", lab)]],
    stringsAsFactors = FALSE)
  df$is_significant <- !is.na(df$padj) & df$padj < 0.05
  df$is_upregulated <- df$is_significant & df$log2FoldChange > 0
  if (!is.null(positive_group)) {
    df$positive_group  <- positive_group
    df$reference_group <- reference_group
  }
  # Additive gene_id / gene_stem provenance (#835) — keyed on gene_symbol, so the
  # verdict-bearing columns (log2FoldChange / padj / gene_symbol) are unchanged.
  df <- annotate_gene_ids(df)
  df <- df[order(df$gene_symbol), ]
  p <- file.path(opts$`out-dir`, fname)
  arrow::write_parquet(df, p, chunk_size = 1024, compression = "snappy")
  message(sprintf("[06_four_cell] wrote %s  (%d genes, %s)",
                  p, nrow(df), n_normal_desc))
}
write_contrast(cellA, "A", "tumor_vs_adjacent.parquet", "cell A: TCGA adjacent-normal")
write_contrast(cellC, "C", "tumor_vs_gtex.parquet",     "cell C: GTEx normal, naive joint")
# adj_vs_gtex.parquet — diagnostic-only normal-vs-normal QC byproduct (#695).
# NOT a contrast that feeds any verdict; positive = TCGA adjacent-normal.
write_contrast(cellAG, "AG", "adj_vs_gtex.parquet",
               "cell AG: TCGA adjacent-normal (+) vs GTEx normal (ref), DIAGNOSTIC-ONLY",
               positive_group  = "TCGA_adjacent_normal",
               reference_group = "GTEx_normal")

# provenance sidecar
#
# schema_version 2 (analysis-methods#695): adds the `adj_vs_gtex` byproduct
# block below. `cells_ran` continues to list ONLY the sensitivity-vote cells
# (A/C) — the AG diagnostic is recorded separately so a consumer that reads
# cells_ran for the concordance grid never mistakes AG for a comparator.
prov <- list(
  substrate      = dat$metadata$substrate,
  tcga_studies   = dat$metadata$tcga_studies,
  gtex_tissue    = dat$metadata$gtex_tissue,
  cells_ran      = lab_ran,
  n_tumor        = length(tumor_ids),
  n_adjacent     = length(adjacent_ids),
  n_gtex         = length(gtex_ids),
  min_normals    = min_n,
  adj_vs_gtex    = list(
    ran             = !is.null(cellAG),
    byproduct       = "adj_vs_gtex.parquet",
    positive_group  = "TCGA_adjacent_normal",
    reference_group = "GTEx_normal",
    classifier_input = FALSE,
    note = paste("diagnostic-only normal-vs-normal QC contrast; measures the",
                 "combined TCGA-vs-GTEx nuisance envelope (batch + field effect",
                 "+ RIN/ischemic + annotation). NOT a selectivity vote: excluded",
                 "from sensitivity.parquet / cells_supporting / concordance.",
                 "Consume direction/rank, not absolute log2FC (cross-cohort size",
                 "factors are partly a normalization artifact).")
  ),
  deseq2_version = as.character(packageVersion("DESeq2")),
  apeglm_version = as.character(packageVersion("apeglm")),
  sva_version    = as.character(packageVersion("sva")),
  schema_version = "2"
)
writeLines(yaml::as.yaml(prov), file.path(opts$`out-dir`, "provenance.yaml"))

# --- per-contrast QC report bundles (S3b, github analysis-methods#702) --------
# For every cell that RAN (A/C and the diagnostic AG), emit a QC bundle
# (figures/ + metrics.csv) under <out-dir>/qc/<cell>/ alongside the parquets, and
# a per-run qc_summary.csv (one row per cell) that the cross-indication index
# (scripts/build_qc_index.py) concatenates across runs. Reads each fit's
# attr(,"qc")/attr(,"fig"); NEVER touches the emitted parquets (byte-identical).
qc_bundle_root <- file.path(opts$`out-dir`, "qc")
dir.create(qc_bundle_root, showWarnings = FALSE, recursive = TRUE)
ind_label  <- paste(dat$metadata$tcga_studies, collapse = "+")
subs_label <- dat$metadata$substrate %||% "recount3"
qc_cells   <- Filter(Negate(is.null), list(A = cellA, C = cellC, AG = cellAG))
qc_rows    <- Filter(Negate(is.null), lapply(names(qc_cells), function(lab) {
  emit_qc_bundle(qc_cells[[lab]], file.path(qc_bundle_root, lab), lab,
                 indication = ind_label, substrate = subs_label, emit = flog)
}))
if (length(qc_rows)) {
  qc_summary <- do.call(rbind, qc_rows)
  write.csv(qc_summary, file.path(qc_bundle_root, "qc_summary.csv"), row.names = FALSE)
  flog(sprintf("[06_four_cell] QC bundles: %d cell(s) -> %s", nrow(qc_summary), qc_bundle_root))
}
message("[06_four_cell] done.")
