#!/usr/bin/env Rscript
# run_cms.R — Phase-1 CMS NTP stage. Shelled out from the python method (_run_cms_classifier, Phase 2)
# via subprocess, mirroring methods/dge_deseq2/steps + cooccurrence_fisher_pancohort/derive.py.
#
# Reads an expression matrix parquet (genes × samples; row key = Entrez id in an `entrez_id` column,
# remaining columns = sample ids of log2(count+1) / TPM values), runs CMScaller::CMScaller (nearest-
# template prediction of CRC Consensus Molecular Subtypes), and writes a per-sample parquet with
# {sample_id, CMS, p_value, FDR}. Determinism: NTP is deterministic given a fixed matrix + templates;
# no RNG seeding needed. Fails loudly (non-zero exit) so the python orchestrator surfaces R errors.
options(error = function() { traceback(3); quit(status = 1) })

suppressPackageStartupMessages({
  library(optparse)
  library(arrow)
  library(CMScaller)
})

opt <- parse_args(OptionParser(option_list = list(
  make_option("--emat", type = "character", help = "input expression-matrix parquet (entrez_id + sample columns)"),
  make_option("--out", type = "character", help = "output per-sample CMS parquet"),
  make_option("--rnaseq", type = "logical", default = TRUE, help = "TRUE for log2 RNA-seq counts (default)"),
  make_option("--fdr", type = "double", default = 0.05, help = "NTP FDR floor; above → unclassified (NA)")
)))
if (is.null(opt$emat) || is.null(opt$out)) stop("--emat and --out are required")

# --- load the expression matrix (entrez_id rownames × sample columns) ---
df <- as.data.frame(arrow::read_parquet(opt$emat))
if (!("entrez_id" %in% colnames(df))) stop("input parquet must carry an `entrez_id` column (row key)")
rownames(df) <- as.character(df$entrez_id)
df$entrez_id <- NULL
emat <- as.matrix(df)                 # genes (Entrez rownames) × samples (columns)
storage.mode(emat) <- "double"
message("[run_cms.R] emat: ", nrow(emat), " genes x ", ncol(emat), " samples")

# --- NTP CMS prediction ---
# CMScaller returns a data.frame: rownames = sample ids; columns include `prediction`, `p.value`, `FDR`.
res <- CMScaller::CMScaller(emat, RNAseq = as.logical(opt$rnaseq), doPlot = FALSE)

pred <- as.character(res$prediction)
# apply the FDR floor: a sample above the floor is unclassified (NA CMS) — honest "unclassifiable".
pred[is.na(res$FDR) | res$FDR > opt$fdr] <- NA_character_

out <- data.frame(
  sample_id = rownames(res),
  CMS       = pred,
  p_value   = as.numeric(res$p.value),
  FDR       = as.numeric(res$FDR),
  stringsAsFactors = FALSE
)
arrow::write_parquet(out, opt$out)
message("[run_cms.R] wrote ", nrow(out), " sample assignments -> ", opt$out,
        " (", sum(!is.na(out$CMS)), " classified, ", sum(is.na(out$CMS)), " unclassifiable)")
