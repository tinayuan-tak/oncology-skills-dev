#!/usr/bin/env Rscript
# _four_cell_lib.R — shared compute for the four-cell tumor-vs-normal DEG.
#
# Sourced by BOTH 06_four_cell_driver.R (whole-cohort) and
# 07_stratified_four_cell_driver.R (per-subgroup). Extracting the cell helpers
# + sensitivity-concordance assembly here guarantees that a per-stratum log2FC
# is produced by the IDENTICAL pipeline (DESeq2 NB-GLM + apeglm shrinkage,
# poscounts size factors, the same prefilter) as the whole-cohort log2FC — so
# the two are on the same scale and the card's trust-anchor semantics
# (cells_supporting / cells_ran, selectivity_class) carry over unchanged to the
# subgroup panorama. This file defines functions ONLY; it runs no code and
# reads no CLI args, so sourcing it is side-effect-free.
#
# Every function is a pure move of the corresponding block that lived inline in
# 06_four_cell_driver.R prior to 2026-08-18; run_cell was parameterised on
# out_dir / min_n / flog (previously closed-over globals) so it is reusable.

`%||%` <- function(a, b) if (!is.null(a) && length(a) && !is.na(a[1])) a else b

# Pre-filter low-count genes on a per-cell sample subset. recount3 G026 carries
# ~64K genes, a large fraction of which are lncRNA/pseudogene with near-zero
# counts — these inflate DESeq2's dispersion-fit time (O(genes)) without adding
# testable signal. Require >=10 counts in >=25% of samples (DESeq2 vignette's
# independent-filtering spirit; stricter than the >=3-sample floor so dispersion
# fitting stays tractable at cohort scale). Also drop the smallest-group floor.
# KNOWN TRADE-OFF (2026-08-13 review): the >=10-counts-in->=25%-of-samples floor is a perf/robustness
# filter, but it also DROPS a bimodal subset-restricted antigen expressed in <25% of the combined
# tumour+normal set (~ a rare-subpopulation surface target) from that cell -> it reads not_informative,
# so this axis under-detects exactly the patient-subset antigens a per-sample percentile view (Q2 card)
# is better suited to surface. Acceptable for the bulk selectivity call; noted so it is not mistaken
# for a measured absence. NOTE (2026-08-18): in a per-subgroup fit the denominator is the STRATUM's
# sample count, so the 25%-of-samples floor is relative to the (smaller) stratum — a gene expressed in
# a stratum-specific subpopulation is MORE likely to clear it here than in the whole-cohort fit.
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
# every gene has at least one zero. Anders/Huber's "poscounts" estimator uses
# only positive counts per gene and is the field-standard fix for large-N
# cohorts; setting it everywhere gives cell-consistent normalization semantics.
deseq2_fit <- function(mat, cd) {
  cd$group <- factor(cd$group, levels = c("normal", "tumor"))
  mat <- prefilter(mat)
  storage.mode(mat) <- "integer"
  # Study covariate for POOLED multi-study indications (NSCLC=LUAD+LUSC, COADREAD=COAD+READ):
  # adjust the tumor-vs-normal effect for study so a pooled contrast is not confounded by the
  # study mix. Applied ONLY when BOTH groups span >1 study level (cells A/B, where tumor AND
  # adjacent each include both studies -> full-rank). NOT the GTEx contrast (cell C): GTEx normal
  # is a single study in group=normal, so `study` is confounded with `group` there -> stays ~ group.
  # group is the last term so lfcShrink(coef="group_tumor_vs_normal") is unaffected. Self-guards
  # identically in the per-subgroup driver (07). Ported from main's 06 study-covariate PR 2026-08-18.
  use_study <- ("study" %in% colnames(cd)) &&
    min(tapply(as.character(cd$study), cd$group, function(s) length(unique(s)))) > 1
  if (use_study) {
    cd$study <- factor(cd$study)
    design <- ~ study + group
    message(sprintf("[four_cell_lib]   study-adjusted design (~ study + group); %d studies",
                    nlevels(cd$study)))
  } else {
    design <- ~ group
  }
  dds <- DESeqDataSetFromMatrix(countData = mat, colData = cd, design = design)
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

# ComBat-seq batch correction. See 06_four_cell_driver.R history for the full
# rationale (preserve_group semantics, ESCA integer-overflow clip).
combat_correct <- function(mat, batch, group, preserve_group = TRUE) {
  mat <- as.matrix(mat); storage.mode(mat) <- "integer"
  tb <- table(batch)
  ok <- batch %in% names(tb)[tb >= 2]
  if (!all(ok)) {
    message("[four_cell_lib]     dropping ", sum(!ok),
            " samples in singleton batches before ComBat_seq")
  }
  bfac <- droplevels(factor(batch[ok]))
  run <- function(grp) ComBat_seq(counts = mat[, ok, drop = FALSE],
                                  batch = bfac, group = grp)
  adj <- NULL
  if (preserve_group) {
    adj <- tryCatch(run(group[ok]), error = function(e) {
      message("[four_cell_lib]     ComBat_seq group-preservation failed (",
              conditionMessage(e), "); retrying without group protection")
      NULL
    })
  }
  if (is.null(adj)) adj <- run(NULL)
  adj <- round(adj)
  adj[adj < 0] <- 0
  adj[adj > .Machine$integer.max] <- .Machine$integer.max
  storage.mode(adj) <- "integer"
  list(counts = adj, keep = ok)
}

# Run one cell (fit DESeq2 on a sample subset). Parameterised on out_dir / min_n
# / flog (previously globals inside 06); label-suffixed cache .rds lets a
# resumed / re-run cohort reuse a completed fit.
run_cell <- function(label, mat, cd, out_dir, min_n, flog,
                     combat_batch = NULL, preserve_group = TRUE) {
  n_t <- sum(cd$group == "tumor"); n_n <- sum(cd$group == "normal")
  cache_path <- file.path(out_dir, sprintf("_cell_%s.rds", label))
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

# Assemble the per-gene sensitivity-concordance frame from a named list of
# per-cell fits (cells that ran, e.g. list(A=cellA, C=cellC)). This is the exact
# block that lived inline in 06 after the cells ran — moved verbatim so the
# whole-cohort and per-subgroup products share concordance semantics. Returns a
# gene-sorted data.frame with cells_ran / cells_supporting / dominant_direction
# / sig_all_cells / discordant / per-cell log2fc+padj / max_abs_log2fc.
assemble_sensitivity <- function(cells) {
  if (length(cells) == 0) stop("assemble_sensitivity: no cells ran")
  merged <- Reduce(function(x, y) merge(x, y, by = "gene_symbol", all = TRUE), cells)

  lab_ran   <- names(cells)
  lfc_cols  <- paste0("log2fc_", lab_ran)
  padj_cols <- paste0("padj_",   lab_ran)

  lfc_mat  <- as.matrix(merged[, lfc_cols,  drop = FALSE])
  padj_mat <- as.matrix(merged[, padj_cols, drop = FALSE])

  sig_mat  <- !is.na(padj_mat) & padj_mat < 0.05
  sign_mat <- sign(lfc_mat); sign_mat[is.na(sign_mat)] <- 0

  sig_lfc <- lfc_mat; sig_lfc[!sig_mat] <- 0
  dom_score <- rowSums(sig_lfc, na.rm = TRUE)
  dominant_direction <- ifelse(dom_score > 0, "up",
                        ifelse(dom_score < 0, "down", "none"))

  dom_sign <- ifelse(dominant_direction == "up", 1,
              ifelse(dominant_direction == "down", -1, 0))
  supporting <- rowSums(sig_mat & (sign_mat == dom_sign), na.rm = TRUE)

  cells_ran_per_gene <- rowSums(!is.na(padj_mat))
  sig_all <- (supporting == cells_ran_per_gene) & (cells_ran_per_gene > 0)

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
  for (l in lab_ran) {
    sens[[paste0("log2fc_", l)]] <- merged[[paste0("log2fc_", l)]]
    sens[[paste0("padj_",   l)]] <- merged[[paste0("padj_",   l)]]
  }
  sens$max_abs_log2fc <- apply(abs(lfc_mat), 1, max, na.rm = TRUE)
  sens$max_abs_log2fc[!is.finite(sens$max_abs_log2fc)] <- NA_real_
  sens[order(sens$gene_symbol), ]
}
