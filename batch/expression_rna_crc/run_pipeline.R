#!/usr/bin/env Rscript
# run_pipeline.R — chain stages 00 → 05 in order, with intermediate .rds in tmp/.
#
# This is a thin wrapper. Each stage is independently runnable (see batch/expression_rna_crc/README.md);
# this just spares you typing the chain by hand for an end-to-end run.
#
# Usage:
#   Rscript run_pipeline.R --config configs/crc.yaml \
#                          --catalog-repo /path/to/data-catalog \
#                          --git-sha $(git rev-parse HEAD) \
#                          --out-dir /tmp/expression_rna_crc \
#                          --parquet-uri s3://onc-compbio/data-catalog/derived/crc-dge/$(git rev-parse HEAD)/tumor_vs_adjacent.parquet

suppressPackageStartupMessages({
  library(optparse)
})

option_list <- list(
  make_option("--config", type = "character"),
  make_option("--catalog-repo", type = "character"),
  make_option("--git-sha", type = "character"),
  make_option("--out-dir", type = "character", default = "/tmp/expression_rna_crc"),
  make_option("--parquet-uri", type = "character",
              help = "Final Parquet destination (s3:// or local)"),
  make_option("--joint-gtex", action = "store_true", default = FALSE),
  make_option("--threads", type = "integer", default = 4)
)
opts <- parse_args(OptionParser(option_list = option_list))
stopifnot(!is.null(opts$config), !is.null(opts$`git-sha`),
          !is.null(opts$`parquet-uri`))

dir.create(opts$`out-dir`, showWarnings = FALSE, recursive = TRUE)
HERE <- dirname(sys.frame(1)$ofile)
if (is.null(HERE) || !nzchar(HERE)) HERE <- "batch/expression_rna_crc"

run <- function(script, args) {
  cmd <- paste("Rscript", file.path(HERE, script),
               paste(args, collapse = " "))
  message(">>> ", cmd)
  status <- system(cmd)
  if (status != 0) stop(script, " failed with status ", status)
}

f <- function(name) file.path(opts$`out-dir`, name)

run("00_load_counts.R", c(
  paste0("--config=",       shQuote(opts$config)),
  paste0("--catalog-repo=", shQuote(opts$`catalog-repo`)),
  paste0("--out=",          shQuote(f("00_counts.rds")))
))

run("01_build_design.R", c(
  paste0("--counts=", shQuote(f("00_counts.rds"))),
  paste0("--out=",    shQuote(f("01_design.rds"))),
  if (isTRUE(opts$`joint-gtex`)) "--joint-gtex" else ""
))

run("02_combat_seq.R", c(
  paste0("--in=",  shQuote(f("01_design.rds"))),
  paste0("--out=", shQuote(f("02_corrected.rds")))
))

run("03_deseq2.R", c(
  paste0("--in=",      shQuote(f("02_corrected.rds"))),
  paste0("--out=",     shQuote(f("03_deseq2.rds"))),
  paste0("--threads=", opts$threads)
))

run("04_write_parquet.R", c(
  paste0("--in=",  shQuote(f("03_deseq2.rds"))),
  paste0("--out=", shQuote(opts$`parquet-uri`))
))

run("05_provenance.R", c(
  paste0("--in=",            shQuote(f("03_deseq2.rds"))),
  paste0("--config=",        shQuote(opts$config)),
  paste0("--git-sha=",       shQuote(opts$`git-sha`)),
  paste0("--parquet-path=",  shQuote(opts$`parquet-uri`)),
  paste0("--out=",           shQuote(f("05_provenance.yaml")))
))

message("=== pipeline complete ===")
message("  Parquet:    ", opts$`parquet-uri`)
message("  Provenance: ", f("05_provenance.yaml"))
