#!/usr/bin/env Rscript
# 01_build_design.R — build the DESeq2 design from the counts + coldata.
#
# Inputs:  output of 00_load_counts.R (.rds)
# Output:  an .rds with the same fields PLUS:
#            design_formula:  formula object passed to DESeqDataSet
#            coldata:         coldata with factor levels set explicitly
#                             (group, batch as factors with reference levels)

suppressPackageStartupMessages({
  library(optparse)
})

option_list <- list(
  make_option("--counts", type = "character", help = "Output of 00_load_counts.R (.rds)"),
  make_option("--out", type = "character", help = "Output .rds path"),
  make_option("--joint-gtex", action = "store_true", default = FALSE,
              help = "Whether GTEx samples are included (drives batch term)")
)
opts <- parse_args(OptionParser(option_list = option_list))
stopifnot(!is.null(opts$counts), !is.null(opts$out))

dat <- readRDS(opts$counts)
coldata <- dat$coldata

stopifnot("group" %in% names(coldata),
          all(coldata$group %in% c("tumor", "normal")))

# Set factor reference: tumor as the contrast level, normal as reference.
# DESeq2 reports fold change as group<level> / group<reference>, so
# log2FC > 0 means upregulated in tumor.
coldata$group <- factor(coldata$group, levels = c("normal", "tumor"))

# Design formula: include batch term if either explicitly joint-GTEx or
# coldata has a non-trivial `source` column with multiple unique values.
has_batch <- opts$`joint-gtex` ||
             ("source" %in% names(coldata) && length(unique(coldata$source)) > 1)

if (has_batch) {
  if ("source" %in% names(coldata)) {
    coldata$batch <- factor(coldata$source)
  } else if ("batch" %in% names(coldata)) {
    coldata$batch <- factor(coldata$batch)
  } else {
    stop("--joint-gtex set but no `source` or `batch` column in coldata")
  }
  design_formula <- ~ batch + group
  message("[01_build_design] design: ~ batch + group  (",
          nlevels(coldata$batch), " batch levels)")
} else {
  design_formula <- ~ group
  message("[01_build_design] design: ~ group  (single source, no batch term)")
}

# Sanity checks before downstream steps spend compute on a misconfigured run.
if (sum(coldata$group == "tumor") < 3 || sum(coldata$group == "normal") < 3) {
  stop("Need ≥3 samples per group; got tumor=",
       sum(coldata$group == "tumor"), ", normal=",
       sum(coldata$group == "normal"))
}

dat$coldata <- coldata
dat$design_formula <- design_formula
dat$has_batch <- has_batch

saveRDS(dat, opts$out)
message("[01_build_design] wrote ", opts$out, "  (n_tumor=",
        sum(coldata$group == "tumor"), ", n_normal=",
        sum(coldata$group == "normal"), ")")
