#!/usr/bin/env Rscript
# run_pipeline.R — chain stages 00 → 05 in order, with intermediate .rds in tmp/.
#
# This is a thin wrapper. Each stage is independently runnable (see batch/expression_rna_COADREAD/README.md);
# this just spares you typing the chain by hand for an end-to-end run.
#
# Usage:
#   Rscript run_pipeline.R --config configs/COADREAD.yaml \
#                          --catalog-repo /path/to/data-catalog \
#                          --git-sha $(git rev-parse HEAD) \
#                          --out-dir /tmp/expression_rna_COADREAD \
#                          --parquet-uri s3://onc-compbio/data-catalog/derived/COADREAD-dge/$(git rev-parse HEAD)/tumor_vs_adjacent.parquet

suppressPackageStartupMessages({
  library(optparse)
})

option_list <- list(
  make_option("--config", type = "character"),
  make_option("--catalog-repo", type = "character"),
  make_option("--git-sha", type = "character"),
  make_option("--out-dir", type = "character", default = "/tmp/expression_rna_COADREAD"),
  make_option("--parquet-uri", type = "character",
              help = "Final Parquet destination (s3:// or local)"),
  make_option("--contrast", type = "character", default = "tumor_vs_adjacent",
              help = paste("tumor_vs_adjacent (legacy GDC-STAR chain 00->05) |",
                           "four_cell_sensitivity (recount3 loader +",
                           "four-cell driver, emits sensitivity.parquet)")),
  make_option("--joint-gtex", action = "store_true", default = FALSE),
  make_option("--gtex-tissue", type = "character", default = NULL,
              help = "Override recount3 GTEx tissue code (four_cell_sensitivity only)."),
  make_option("--threads", type = "integer", default = 4)
)
opts <- parse_args(OptionParser(option_list = option_list))
stopifnot(!is.null(opts$config), !is.null(opts$`git-sha`))

dir.create(opts$`out-dir`, showWarnings = FALSE, recursive = TRUE)

# Robust self-location: the standard `sys.frame(1)$ofile` idiom errors out
# under `pixi run Rscript ...` because the wrapper changes the call stack.
# Parse `--file=` from commandArgs instead — set on every Rscript invocation.
locate_self <- function() {
  args <- commandArgs(trailingOnly = FALSE)
  m <- regmatches(args, regexpr("^--file=", args))
  hit <- args[grepl("^--file=", args)]
  if (length(hit)) return(dirname(normalizePath(sub("^--file=", "", hit[1]))))
  "batch/expression_rna_COADREAD"
}
HERE <- locate_self()

run <- function(script, args) {
  cmd <- paste("Rscript", file.path(HERE, script),
               paste(args, collapse = " "))
  message(">>> ", cmd)
  status <- system(cmd)
  if (status != 0) stop(script, " failed with status ", status)
}

f <- function(name) file.path(opts$`out-dir`, name)

# === four_cell_sensitivity: recount3 loader → four-cell driver ==============
# Bypasses the linear 00→05 GDC-STAR chain. Loads ALL sample groups (TCGA tumor
# + TCGA adjacent-normal + GTEx normal) from ONE recount3 substrate, then runs
# cells A/B/C/D and emits sensitivity.parquet + the two contrast parquets.
if (identical(opts$contrast, "four_cell_sensitivity")) {
  run("00_load_recount3.R", c(
    paste0("--config=", shQuote(opts$config)),
    if (!is.null(opts$`gtex-tissue`))
      paste0("--gtex-tissue=", shQuote(opts$`gtex-tissue`)) else "",
    paste0("--out=", shQuote(f("00_recount3.rds")))
  ))
  run("06_four_cell_driver.R", c(
    paste0("--in=",      shQuote(f("00_recount3.rds"))),
    paste0("--out-dir=", shQuote(opts$`out-dir`)),
    paste0("--threads=", opts$threads)
  ))
  message("=== four-cell sensitivity pipeline complete ===")
  message("  Sensitivity:  ", f("sensitivity.parquet"))
  message("  Contrasts:    ", f("tumor_vs_adjacent.parquet"), " + ",
          f("tumor_vs_gtex.parquet"))
  message("  Provenance:   ", f("provenance.yaml"))
  quit(status = 0)
}

# === tumor_vs_adjacent (legacy GDC-STAR chain) ==============================
stopifnot(!is.null(opts$`parquet-uri`))

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
