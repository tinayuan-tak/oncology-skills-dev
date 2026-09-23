#!/usr/bin/env Rscript
# 04_write_parquet.R — convert DESeq2 results to Parquet sorted by gene_symbol.
#
# WHY SORTED BY gene_symbol: per-gene retrieval (skills/query-target-evidence)
# uses pyarrow predicate pushdown — sub-second reads of one row out of 18K
# only work efficiently when the column is sorted (lets the reader skip
# row groups). This is the "compute globally, query locally" rule from the
# runbook made physical.
#
# Inputs:  output of 03_deseq2.R (.rds with $dge_results)
# Output:  Parquet at the path passed via --out

suppressPackageStartupMessages({
  library(optparse)
  library(arrow)
})

option_list <- list(
  make_option("--in", type = "character", dest = "in_path",
              help = "Output of 03_deseq2.R (.rds)"),
  make_option("--out", type = "character", help = "Output Parquet path (s3:// or local)"),
  make_option("--row-group-size", type = "integer", default = 1024,
              help = "Parquet row-group size (smaller = better point lookups)")
)
opts <- parse_args(OptionParser(option_list = option_list))
stopifnot(!is.null(opts$in_path), !is.null(opts$out))

dat <- readRDS(opts$in_path)
res <- dat$dge_results

# Add the actionability columns alongside the raw results.
# Consumers can choose to filter or not; we DO NOT pre-filter here.
res$is_significant <- !is.na(res$padj) & res$padj < 0.05
res$is_actionable  <- res$is_significant & abs(res$log2FoldChange) >= 1
res$is_upregulated <- res$is_actionable  & res$log2FoldChange > 0
res$n_tumor  <- dat$dge_n_tumor
res$n_normal <- dat$dge_n_normal

# Sort by gene_symbol for predicate-pushdown efficiency
res <- res[order(res$gene_symbol), ]

write_parquet(
  res,
  sink = opts$out,
  chunk_size = opts$`row-group-size`,
  compression = "snappy",
  use_dictionary = TRUE
)

message("[04_write_parquet] wrote ", opts$out,
        "  (", nrow(res), " rows, ",
        "actionable: ", sum(res$is_actionable, na.rm = TRUE), ", ",
        "upreg: ", sum(res$is_upregulated, na.rm = TRUE), ")")
