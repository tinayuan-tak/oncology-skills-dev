#!/usr/bin/env Rscript
# 06_four_cell_driver.R — run the four-cell sensitivity DEG from ONE loaded
# recount3 bundle (output of 00_load_recount3.R) and emit sensitivity.parquet
# plus the two primary contrast parquets.
#
# Cells (see DESIGN_v2_four_cell_consolidation.md §2.1):
#   A  TCGA tumor vs TCGA adjacent-normal    | raw           | ~ group
#   B  TCGA tumor vs TCGA adjacent-normal    | ComBat(TSS)   | ~ group
#   C  TCGA tumor vs GTEx normal (joint)     | raw           | ~ group  (naive)
#   D  TCGA tumor vs GTEx normal (joint)     | ComBat(source)| ~ group
#
# A gene's `cells_supporting` = count of cells where padj<0.05 in the same
# direction as the dominant sign. `sig_all_four` = padj<0.05 same-direction in
# all four cells (the gold-standard call). Cells A/B are skipped when TCGA
# adjacent-normal < min_normals; cells C/D skipped when no GTEx tissue.

suppressPackageStartupMessages({
  library(optparse)
  library(DESeq2)
  library(apeglm)
  library(sva)
  library(BiocParallel)
  library(arrow)
})

`%||%` <- function(a, b) if (!is.null(a) && length(a) && !is.na(a[1])) a else b

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

# --- shared helpers ---------------------------------------------------------

# Pre-filter low-count genes on a per-cell sample subset. recount3 G026 carries
# ~64K genes, a large fraction of which are lncRNA/pseudogene with near-zero
# counts — these inflate DESeq2's dispersion-fit time (O(genes)) without adding
# testable signal. Require ≥10 counts in ≥25% of samples (DESeq2 vignette's
# independent-filtering spirit; stricter than the ≥3-sample floor so dispersion
# fitting stays tractable at cohort scale). Also drop the smallest-group floor.
# KNOWN TRADE-OFF (2026-08-13 review): the ≥10-counts-in-≥25%-of-samples floor is a perf/robustness
# filter, but it also DROPS a bimodal subset-restricted antigen expressed in <25% of the combined
# tumour+normal set (≈ a rare-subpopulation surface target) from that cell → it reads not_informative,
# so this axis under-detects exactly the patient-subset antigens a per-sample percentile view (Q2 card)
# is better suited to surface. Acceptable for the bulk selectivity call; noted so it is not mistaken
# for a measured absence.
prefilter <- function(mat) {
  min_samples <- max(3L, ceiling(0.25 * ncol(mat)))
  keep <- rowSums(mat >= 10) >= min_samples
  mat[keep, , drop = FALSE]
}

# DESeq2 fit + apeglm shrinkage for a two-level `group` factor
# (reference = "normal", so log2FC > 0 == up in tumor). Returns a tidy frame
# with gene_symbol, log2FoldChange, padj, baseMean.
#
# sfType="poscounts": DESeq2's default median-of-ratios size-factor estimator
# needs each retained gene to be nonzero in EVERY sample (to compute the
# geometric mean). At 1,500+ samples across ~30K recount3 loci, essentially
# every gene has at least one zero — hitting "every gene contains at least
# one zero" in estimateSizeFactorsForMatrix. Anders/Huber's "poscounts"
# estimator uses only positive counts per gene and is the field-standard fix
# for large-N cohorts. Cells A/B (~720 samples, dense recount3 counts)
# happen to have a non-empty all-nonzero gene subset and would work under
# either estimator; setting poscounts everywhere gives cell-consistent
# normalization semantics and never surprises on scale.
deseq2_fit <- function(mat, cd) {
  cd$group <- factor(cd$group, levels = c("normal", "tumor"))
  mat <- prefilter(mat)
  storage.mode(mat) <- "integer"
  dds <- DESeqDataSetFromMatrix(countData = mat, colData = cd, design = ~ group)
  dds <- DESeq(dds, parallel = TRUE, quiet = TRUE, sfType = "poscounts")
  res_un <- results(dds, contrast = c("group", "tumor", "normal"), alpha = 0.05)
  res <- lfcShrink(dds, coef = "group_tumor_vs_normal", type = "apeglm",
                   parallel = TRUE, res = res_un, quiet = TRUE)
  data.frame(gene_symbol   = rownames(res),
             log2FoldChange = res$log2FoldChange,
             padj           = res$padj,
             baseMean       = res$baseMean,
             stringsAsFactors = FALSE)
}

# ComBat-seq batch correction.
#
# `preserve_group`: when TRUE, ComBat_seq's group= argument protects the
# biological (tumor-vs-normal) signal during correction — CORRECT when batch is
# NOT confounded with group (e.g. cell B, batch = TCGA tissue-source-site: both
# tumors and normals span sites). When batch IS confounded with group (cell D,
# batch = source: every tumor is TCGA, every normal is GTEx), group= is
# mathematically impossible and ComBat_seq errors out — pass preserve_group =
# FALSE to run the source-scrubbing without group protection (accepting that it
# over-corrects; that is the intended "pessimistic" behaviour of cell D).
#
# Even when preserve_group = TRUE, partial confounding on some indications can
# still trip ComBat_seq; we catch that and fall back to no-group with a warning
# so a batch run never dies on one indication's cohort structure.
combat_correct <- function(mat, batch, group, preserve_group = TRUE) {
  mat <- as.matrix(mat); storage.mode(mat) <- "integer"
  # Drop batch levels with <2 samples (ComBat-seq requires ≥2 per batch).
  tb <- table(batch)
  ok <- batch %in% names(tb)[tb >= 2]
  if (!all(ok)) {
    message("[06_four_cell]     dropping ", sum(!ok),
            " samples in singleton batches before ComBat_seq")
  }
  bfac <- droplevels(factor(batch[ok]))
  run <- function(grp) ComBat_seq(counts = mat[, ok, drop = FALSE],
                                  batch = bfac, group = grp)
  adj <- NULL
  if (preserve_group) {
    adj <- tryCatch(run(group[ok]), error = function(e) {
      message("[06_four_cell]     ComBat_seq group-preservation failed (",
              conditionMessage(e), "); retrying without group protection")
      NULL
    })
  }
  if (is.null(adj)) adj <- run(NULL)   # confounded / cell D → no group arg
  # ESCA failure fix (2026-07-08): ComBat_seq's batch-mean shift can push
  # already-large counts past R's 32-bit integer max (2,147,483,647) for
  # indications with very high per-gene library sizes (esophageal squamous
  # carcinoma mucin/keratin family). `storage.mode(adj) <- "integer"`
  # silently NAs any value beyond that, then DESeq2's matrix validator
  # rejects the NAs with "NA values are not allowed in the count matrix".
  # Fix: clip to integer.max BEFORE cast so counts stay representable.
  # Round + clip to non-negative int range (ComBat can also produce small
  # negative values on rare genes — clip those to 0, matches DESeq2's
  # implicit non-negative-count contract).
  adj <- round(adj)
  adj[adj < 0] <- 0
  adj[adj > .Machine$integer.max] <- .Machine$integer.max
  storage.mode(adj) <- "integer"
  list(counts = adj, keep = ok)
}

run_cell <- function(label, mat, cd, combat_batch = NULL, preserve_group = TRUE) {
  n_t <- sum(cd$group == "tumor"); n_n <- sum(cd$group == "normal")
  cache_path <- file.path(opts$`out-dir`, sprintf("_cell_%s.rds", label))
  if (file.exists(cache_path)) {
    flog(sprintf("cell %s: reusing cached fit at %s", label, cache_path))
    return(readRDS(cache_path))
  }
  if (n_t < min_n || n_n < min_n) {
    flog(sprintf("cell %s SKIPPED (n_tumor=%d, n_normal=%d < %d)",
                 label, n_t, n_n, min_n))
    return(NULL)
  }
  if (!is.null(combat_batch)) {
    flog(sprintf("cell %s: ComBat_seq(batch=%s, preserve_group=%s) START",
                 label, combat_batch, preserve_group))
    cc <- combat_correct(mat, cd[[combat_batch]], cd$group,
                         preserve_group = preserve_group)
    mat <- cc$counts; cd <- cd[cc$keep, , drop = FALSE]
    flog(sprintf("cell %s: ComBat_seq DONE; %d samples remain", label, ncol(mat)))
  }
  flog(sprintf("cell %s: DESeq2 START (n_tumor=%d, n_normal=%d, n_genes_pre=%d)",
               label, sum(cd$group=="tumor"), sum(cd$group=="normal"), nrow(mat)))
  fit <- deseq2_fit(mat, cd)
  names(fit)[names(fit) == "log2FoldChange"] <- paste0("log2fc_", label)
  names(fit)[names(fit) == "padj"]           <- paste0("padj_", label)
  names(fit)[names(fit) == "baseMean"]        <- paste0("baseMean_", label)
  saveRDS(fit, cache_path)
  flog(sprintf("cell %s: DESeq2 DONE (%d genes, cached at %s)",
               label, nrow(fit), cache_path))
  fit
}

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
cellA <- NULL; cellB <- NULL; cellC <- NULL

if (length(adjacent_ids) >= min_n) {
  ids <- c(tumor_ids, adjacent_ids)
  cellA <- run_cell("A", counts[, ids], coldata[ids, ])

  # cell B: same samples, ComBat on TCGA tissue-source-site (plate proxy).
  #
  # SKIP_CELL_B env-var gate (added 2026-07-16): ComBat_seq's inner
  # sva:::match_quantiles is a doubly-nested pure-R loop over
  # (n_genes x n_samples) per batch, and on cohorts with many small TSS
  # batches (e.g. UCEC: 24 batches after singleton drop) it can grind for
  # 20+ hours without terminating in reasonable time. Cell B is only the
  # batch-correction robustness re-run of cell A; cells A + C carry the
  # load-bearing biology (raw tumor-vs-adjacent + tumor-vs-GTEx). This
  # env-var lets a targeted rerun skip cell B when it hits the perf
  # pathology, producing a valid A+C sensitivity.parquet (same shape as
  # HNSC's A/B-only or OV/SKCM's C-only products, which the downstream
  # fusion code already handles). Follow-up: replace match_quantiles with
  # a vectorized quantile-match, or collapse small TSS batches before
  # ComBat-seq.
  if (Sys.getenv("SKIP_CELL_B") == "1") {
    message("[06_four_cell] cell B SKIPPED — SKIP_CELL_B=1 env-var set ",
            "(match_quantiles perf cliff mitigation)")
  } else {
    cellB <- run_cell("B", counts[, ids], coldata[ids, ], combat_batch = "tcga_tss")
  }
} else {
  message("[06_four_cell] cells A/B SKIPPED — TCGA adjacent-normal < ", min_n)
}

# --- cell C: tumor vs GTEx, raw ---------------------------------------------
# Cell D (ComBat_seq batch=source) was RETIRED after the initial full-cohort
# COADREAD validation showed it collapses biology entirely: with source
# perfectly confounded with group, ComBat_seq(group=NULL) regresses out the
# tumor-vs-normal signal along with the source effect (empirical result:
# mean|log2FC|=0.05 vs 1.05-1.40 in cells A/B/C; only 1,205 sig genes vs
# 20-28K in A/B/C). The intended "pessimistic anchor" reads as noise, not
# signal. Trust anchor is therefore 3-cell (A/B/C); design doc §2.1
# documents the retirement and the reasoning. Future work: replace with
# an RUV/SVASeq-based source-adjustment that preserves group signal.
if (length(gtex_ids) >= min_n) {
  ids <- c(tumor_ids, gtex_ids)
  cellC <- run_cell("C", counts[, ids], coldata[ids, ])
} else {
  message("[06_four_cell] cell C SKIPPED — GTEx normal < ", min_n,
          " (no GTEx tissue for this indication?)")
}

cells <- Filter(Negate(is.null), list(A = cellA, B = cellB, C = cellC))
if (length(cells) == 0) stop("No cells ran — check sample availability.")

# --- join on gene_symbol (outer; a gene may be filtered out of some cells) --
merged <- Reduce(function(x, y) merge(x, y, by = "gene_symbol", all = TRUE), cells)

# --- sensitivity concordance ------------------------------------------------
lab_ran <- names(cells)
lfc_cols  <- paste0("log2fc_", lab_ran)
padj_cols <- paste0("padj_",   lab_ran)

lfc_mat  <- as.matrix(merged[, lfc_cols,  drop = FALSE])
padj_mat <- as.matrix(merged[, padj_cols, drop = FALSE])

sig_mat  <- !is.na(padj_mat) & padj_mat < 0.05
sign_mat <- sign(lfc_mat); sign_mat[is.na(sign_mat)] <- 0

# dominant direction = sign of the summed significant-cell log2FCs; ties→0
sig_lfc <- lfc_mat; sig_lfc[!sig_mat] <- 0
dom_score <- rowSums(sig_lfc, na.rm = TRUE)
dominant_direction <- ifelse(dom_score > 0, "up",
                       ifelse(dom_score < 0, "down", "none"))

# cells_supporting = # cells significant AND in the dominant direction.
# NOTE (2026-08-13 review): this counts cells A and B as TWO supporting votes, but they are the SAME
# tumour-vs-adjacent comparison (A = raw, B = ComBat robustness re-run on the identical sample set) —
# a robustness pair, NOT two independent comparators. So a gene significant in A+B alone reads
# supporting=2, which clears the reader's `modest` tier (supporting_frac >= 2/3) WITHOUT any GTEx
# (cell C) concurrence. Genuine cross-comparator agreement (adjacent family vs GTEx family) is exposed
# downstream via _family_direction (dge_deseq2/read.py). cells_supporting is a robustness count, not an
# independent-comparator count — documented in _classify_selectivity_from_sensitivity's KNOWN LIMITATIONS.
dom_sign <- ifelse(dominant_direction == "up", 1,
             ifelse(dominant_direction == "down", -1, 0))
supporting <- rowSums(sig_mat & (sign_mat == dom_sign), na.rm = TRUE)

# PER-GENE cells_ran: how many cells actually produced a testable estimate for
# this gene. Cell-level pre-filters may drop different genes, so a gene might
# be present in cells A/C/D but NA in cell B — its correct denominator is 3,
# not 4. Using a scalar `length(lab_ran)` here would let a 3/3 gene appear as
# 3/4 in the card renderer, understating its trust.
cells_ran_per_gene <- rowSums(!is.na(padj_mat))
sig_all <- (supporting == cells_ran_per_gene) & (cells_ran_per_gene > 0)

# discordance: ≥1 sig cell up AND ≥1 sig cell down
any_up   <- rowSums(sig_mat & sign_mat > 0, na.rm = TRUE) > 0
any_down <- rowSums(sig_mat & sign_mat < 0, na.rm = TRUE) > 0
discordant <- any_up & any_down

sens <- data.frame(
  gene_symbol        = merged$gene_symbol,
  cells_ran          = cells_ran_per_gene,
  cells_supporting   = supporting,
  dominant_direction = dominant_direction,
  sig_all_cells      = sig_all,
  discordant         = discordant,
  stringsAsFactors = FALSE
)
# attach the per-cell log2fc + padj for downstream forest plots
for (l in lab_ran) {
  sens[[paste0("log2fc_", l)]] <- merged[[paste0("log2fc_", l)]]
  sens[[paste0("padj_",   l)]] <- merged[[paste0("padj_",   l)]]
}
# max |log2fc| across cells (secondary magnitude signal)
sens$max_abs_log2fc <- apply(abs(lfc_mat), 1, max, na.rm = TRUE)
sens$max_abs_log2fc[!is.finite(sens$max_abs_log2fc)] <- NA_real_

sens <- sens[order(sens$gene_symbol), ]

# --- write outputs ----------------------------------------------------------
sens_path <- file.path(opts$`out-dir`, "sensitivity.parquet")
arrow::write_parquet(sens, sens_path, chunk_size = 1024,
                     compression = "snappy", use_dictionary = TRUE)
message(sprintf("[06_four_cell] wrote %s  (%d genes; sig_all_cells=%d; discordant=%d; cells_ran=%s)",
                sens_path, nrow(sens), sum(sens$sig_all_cells),
                sum(sens$discordant), paste(lab_ran, collapse = "")))

# Primary contrast parquets (backward-compat shape) for cells A (adjacent) & C (gtex)
write_contrast <- function(cell, lab, fname, n_normal_desc) {
  if (is.null(cell)) return(invisible(NULL))
  df <- data.frame(
    gene_symbol    = cell$gene_symbol,
    log2FoldChange = cell[[paste0("log2fc_", lab)]],
    padj           = cell[[paste0("padj_",   lab)]],
    baseMean       = cell[[paste0("baseMean_", lab)]],
    stringsAsFactors = FALSE)
  df$is_significant <- !is.na(df$padj) & df$padj < 0.05
  df$is_upregulated <- df$is_significant & df$log2FoldChange > 0
  df <- df[order(df$gene_symbol), ]
  p <- file.path(opts$`out-dir`, fname)
  arrow::write_parquet(df, p, chunk_size = 1024, compression = "snappy")
  message(sprintf("[06_four_cell] wrote %s  (%d genes, %s)",
                  p, nrow(df), n_normal_desc))
}
write_contrast(cellA, "A", "tumor_vs_adjacent.parquet", "cell A: TCGA adjacent-normal")
write_contrast(cellC, "C", "tumor_vs_gtex.parquet",     "cell C: GTEx normal, naive joint")

# provenance sidecar
prov <- list(
  substrate      = dat$metadata$substrate,
  tcga_studies   = dat$metadata$tcga_studies,
  gtex_tissue    = dat$metadata$gtex_tissue,
  cells_ran      = lab_ran,
  n_tumor        = length(tumor_ids),
  n_adjacent     = length(adjacent_ids),
  n_gtex         = length(gtex_ids),
  min_normals    = min_n,
  deseq2_version = as.character(packageVersion("DESeq2")),
  apeglm_version = as.character(packageVersion("apeglm")),
  sva_version    = as.character(packageVersion("sva")),
  schema_version = "1"
)
writeLines(yaml::as.yaml(prov), file.path(opts$`out-dir`, "provenance.yaml"))
message("[06_four_cell] done.")
