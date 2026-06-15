#!/usr/bin/env Rscript
# 03_deseq2.R — DESeq2 NB GLM, Wald test, lfcShrink with apeglm.
#
# Inputs:  output of 02_combat_seq.R
# Output:  same .rds with the DESeq2 results table added (one row per gene).
#          Result columns: baseMean, log2FoldChange (apeglm-shrunken),
#                          lfcSE, pvalue, padj.
#
# Methodology pinned by runbook decision (2026-06-15):
#   - Test:        Wald test (default)
#   - Shrinkage:   lfcShrink(method = "apeglm")  -- usable effect sizes
#   - Multiple testing: Tier-1 BH-FDR genome-wide, applied internally
#                       via DESeq2's independent filtering on baseMean
#   - Reference:   group "normal" (so log2FC > 0 means up in tumor)

suppressPackageStartupMessages({
  library(optparse)
  library(DESeq2)
  library(apeglm)  # for lfcShrink type = "apeglm"
})

option_list <- list(
  make_option("--in", type = "character", dest = "in_path",
              help = "Output of 02_combat_seq.R (.rds)"),
  make_option("--out", type = "character", help = "Output .rds path"),
  make_option("--threads", type = "integer", default = 4)
)
opts <- parse_args(OptionParser(option_list = option_list))
stopifnot(!is.null(opts$in_path), !is.null(opts$out))

# Parallelize DESeq2's per-gene fitting
suppressPackageStartupMessages(library(BiocParallel))
register(MulticoreParam(workers = opts$threads))

dat <- readRDS(opts$in_path)
counts <- if (!is.null(dat$counts_adj)) dat$counts_adj else dat$counts

# Build DESeqDataSet using the ALREADY-CORRECTED counts. Because ComBat-seq
# pre-corrected the counts, the design here drops the batch term to avoid
# double-correction; group remains.
design_no_batch <- ~ group

message("[03_deseq2] DESeqDataSet: ", nrow(counts), " genes × ", ncol(counts), " samples")
dds <- DESeqDataSetFromMatrix(
  countData = counts,
  colData   = dat$coldata,
  design    = design_no_batch
)

# Pre-filter very-low-count genes (speeds up + improves independent filtering).
keep <- rowSums(counts(dds) >= 10) >= 3
message("[03_deseq2] pre-filter: keeping ", sum(keep), "/", nrow(dds),
        " genes with ≥10 counts in ≥3 samples")
dds <- dds[keep, ]

# Fit and test
dds <- DESeq(dds, parallel = TRUE)
res_unshrunk <- results(dds, contrast = c("group", "tumor", "normal"), alpha = 0.05)

# Shrink effect sizes for usable downstream interpretation
coef_name <- "group_tumor_vs_normal"  # set by reference level from stage 01
res <- lfcShrink(dds, coef = coef_name, type = "apeglm",
                 parallel = TRUE, res = res_unshrunk)

# Convert to a tidy data.frame
results_df <- as.data.frame(res)
results_df$gene_symbol <- rownames(res)
results_df <- results_df[, c("gene_symbol", "baseMean", "log2FoldChange",
                             "lfcSE", "pvalue", "padj")]

# Note the actionability filter — applied at WRITE time (stage 04), NOT here.
# We persist all gene rows so downstream consumers can apply their own thresholds.

dat$dge_results <- results_df
dat$deseq2_version <- as.character(packageVersion("DESeq2"))
dat$apeglm_version <- as.character(packageVersion("apeglm"))
dat$dge_design <- "~ group  (post-ComBat-seq, batch already corrected)"
dat$dge_n_tumor <- sum(dat$coldata$group == "tumor")
dat$dge_n_normal <- sum(dat$coldata$group == "normal")
dat$dge_n_genes_tested <- nrow(results_df)

saveRDS(dat, opts$out)
message("[03_deseq2] wrote ", opts$out,
        "  (DESeq2 v", dat$deseq2_version,
        ", n_genes=", nrow(results_df),
        ", padj<0.05: ", sum(results_df$padj < 0.05, na.rm = TRUE), ")")
