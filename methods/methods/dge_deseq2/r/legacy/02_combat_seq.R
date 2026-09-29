#!/usr/bin/env Rscript
# 02_combat_seq.R — ComBat-seq batch correction on raw integer counts.
#
# WHEN TO RUN: only when joint TCGA + GTEx (or any multi-source) cohort is in
# play. ComBat-seq is part of the `sva` Bioconductor package. It expects a
# count matrix and a batch factor; it returns batch-adjusted integer counts
# that DESeq2 (stage 03) consumes as if they were raw.
#
# Inputs:  output of 01_build_design.R
# Output:  same .rds with a corrected `counts_adj` matrix added.
#          original `counts` is preserved (raw, pre-correction).

suppressPackageStartupMessages({
  library(optparse)
  library(sva)  # provides ComBat_seq
})

option_list <- list(
  make_option("--in", type = "character", dest = "in_path",
              help = "Output of 01_build_design.R (.rds)"),
  make_option("--out", type = "character", help = "Output .rds path"),
  make_option("--skip-if-single-source", action = "store_true", default = TRUE,
              help = "Skip correction if no batch term in design (default TRUE)")
)
opts <- parse_args(OptionParser(option_list = option_list))
stopifnot(!is.null(opts$in_path), !is.null(opts$out))

dat <- readRDS(opts$in_path)

if (!isTRUE(dat$has_batch) && opts$`skip-if-single-source`) {
  message("[02_combat_seq] no batch term in design; skipping ComBat-seq.")
  dat$counts_adj <- dat$counts
  dat$combat_seq_applied <- FALSE
  saveRDS(dat, opts$out)
  quit(status = 0)
}

batch <- dat$coldata$batch
group <- dat$coldata$group

message("[02_combat_seq] running ComBat_seq on ",
        nrow(dat$counts), " genes × ", ncol(dat$counts), " samples")
message("[02_combat_seq]   batch levels: ", paste(levels(batch), collapse = ", "))

counts_adj <- ComBat_seq(
  counts = as.matrix(dat$counts),
  batch  = batch,
  group  = group   # preserve biological signal during correction
)

storage.mode(counts_adj) <- "integer"  # DESeq2 wants integer
dat$counts_adj <- counts_adj
dat$combat_seq_applied <- TRUE
dat$combat_seq_version <- as.character(packageVersion("sva"))

saveRDS(dat, opts$out)
message("[02_combat_seq] wrote ", opts$out, "  (sva v", dat$combat_seq_version, ")")
