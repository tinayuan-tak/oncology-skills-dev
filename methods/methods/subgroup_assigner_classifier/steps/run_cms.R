#!/usr/bin/env Rscript
# run_cms.R — Phase-1 CMS NTP stage. Shelled out from the python method (_run_cms_classifier, Phase 2)
# via subprocess, mirroring methods/dge_deseq2/steps + cooccurrence_fisher_pancohort/derive.py.
#
# Reads an expression matrix parquet (genes × samples; row key = Entrez id in an `entrez_id` column,
# remaining columns = sample ids of log2(count+1) / TPM values), runs CMScaller::CMScaller (nearest-
# template prediction of CRC Consensus Molecular Subtypes), and writes a per-sample parquet with
# {sample_id, CMS, p_value, FDR}. Fails loudly (non-zero exit) so the python orchestrator surfaces R errors.
#
# DETERMINISM (this comment previously claimed the opposite, and it was wrong): the ASSIGNMENT step of
# NTP is deterministic — correlate each sample to each template, take the nearest — but the p-value and
# FDR come from a PERMUTATION null (CMScaller's default nPerm = 1000, and it prints "1000 permutation(s)"
# on every run). CMScaller exposes `seed` precisely because of this and forwards it to ntp(); leaving it
# NULL leaves R's RNG seeded from the clock, so samples sitting near the --fdr floor cross it in either
# direction between runs. MEASURED on byte-identical input: 2 of 131 DepMap Bowel models changed class
# across three runs, moving the CMS3 count 20/19/20 and CMS4 33/32/32. Any expected_n declared off an
# unseeded run is a FLAKY FLOOR, so the seed is pinned below.
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
# Pinned, not exposed as a CLI flag: no caller has a reason to vary it, and an option nothing passes
# is dead coverage. 42 matches the repo's python convention (depmap_predictability_precompute uses
# random_state = 42). Changing this value re-rolls the FDR null and can move counts near the floor.
CMS_NTP_SEED <- 42L

# CMScaller returns a data.frame: rownames = sample ids; columns include `prediction`, `p.value`, `FDR`.
res <- CMScaller::CMScaller(emat, RNAseq = as.logical(opt$rnaseq), doPlot = FALSE, seed = CMS_NTP_SEED)
message("[run_cms.R] NTP seed: ", CMS_NTP_SEED, " (permutation FDR is RNG-driven; see header)")

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
