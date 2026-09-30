#!/usr/bin/env Rscript
# run_pipeline.R — lives in r/live/ alongside the production recount3 loader + four-cell
# drivers. Each --contrast is independently runnable (see onc_methods/dge_deseq2/README.md);
# this just spares you typing the chain by hand for an end-to-end run. --contrast
# tumor_vs_adjacent reaches into ../legacy/ for the quarantined single-cell GDC-STAR chain
# (00_load_counts.R + 01-05) — see r/legacy/README.md for why that chain is kept at all.
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
  make_option("--subgroup-assignments", type = "character", default = NULL,
              help = "subgroup_assignments.parquet path (four_cell_sensitivity_by_subgroup)."),
  make_option("--subgroup-axis", type = "character", default = NULL,
              help = "Subgroup axis label (four_cell_sensitivity_by_subgroup)."),
  make_option("--strata", type = "character", default = NULL,
              help = "Comma-separated stratum_ids (four_cell_sensitivity_by_subgroup)."),
  make_option("--min-subgroup-tumor", type = "integer", default = 10L,
              help = "Minimum tumor members for a stratum to be emitted (07)."),
  make_option("--substrate", type = "character", default = "recount3",
              help = paste("four_cell_sensitivity count substrate:",
                           "recount3 (default, GENCODE v26 — the classifier substrate) |",
                           "xena_toil (secondary/diagnostic, GENCODE v23 — S1b #694).")),
  make_option("--indication", type = "character", default = NULL,
              help = "Indication slug for the xena_toil loader (required when --substrate xena_toil)."),
  make_option("--threads", type = "integer", default = 4)
)
opts <- parse_args(OptionParser(option_list = option_list))
stopifnot(!is.null(opts$`git-sha`))
# The xena_toil loader selects samples by --indication (not a recount3 config),
# so --config is required for every path EXCEPT the xena_toil substrate.
if (!identical(opts$substrate, "xena_toil")) stopifnot(!is.null(opts$config))

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
# cells A/C and emits sensitivity.parquet + the two contrast parquets.
if (identical(opts$contrast, "four_cell_sensitivity")) {
  # Two count substrates feed the SAME four-cell driver (06). recount3 (default)
  # is the classifier substrate; xena_toil is the S1b secondary/diagnostic one
  # (analysis-methods#694) — a distinct GENCODE v23 loader that emits the same
  # .rds shape. The intermediate is named 00_recount3.rds either way (a local
  # temp in out-dir, no external contract); 06 reads whichever loader wrote it.
  if (identical(opts$substrate, "xena_toil")) {
    stopifnot(!is.null(opts$indication))
    run("00_load_xena_toil.R", c(
      paste0("--indication=", shQuote(opts$indication)),
      paste0("--out=", shQuote(f("00_recount3.rds")))
    ))
  } else {
    run("00_load_recount3.R", c(
      paste0("--config=", shQuote(opts$config)),
      if (!is.null(opts$`gtex-tissue`))
        paste0("--gtex-tissue=", shQuote(opts$`gtex-tissue`)) else "",
      paste0("--out=", shQuote(f("00_recount3.rds")))
    ))
  }
  run("06_four_cell_driver.R", c(
    paste0("--in=",      shQuote(f("00_recount3.rds"))),
    paste0("--out-dir=", shQuote(opts$`out-dir`)),
    paste0("--threads=", opts$threads)
  ))
  message("=== four-cell sensitivity pipeline complete ===")
  message("  Sensitivity:  ", f("sensitivity.parquet"))
  message("  Contrasts:    ", f("tumor_vs_adjacent.parquet"), " + ",
          f("tumor_vs_gtex.parquet"))
  message("  Diagnostic:   ", f("adj_vs_gtex.parquet"), " (adj-vs-GTEx QC, #695)")
  message("  Provenance:   ", f("provenance.yaml"))
  quit(status = 0)
}

# === four_cell_sensitivity_by_subgroup: per-subgroup DESeq2 =================
# Same recount3 substrate as four_cell_sensitivity (00_load_recount3), then the
# stratified driver (07) restricts the tumor arm per stratum and emits the tall
# sensitivity_by_subgroup.parquet. Normals stay whole-cohort.
if (identical(opts$contrast, "four_cell_sensitivity_by_subgroup")) {
  stopifnot(!is.null(opts$`subgroup-assignments`), !is.null(opts$`subgroup-axis`),
            !is.null(opts$strata))
  run("00_load_recount3.R", c(
    paste0("--config=", shQuote(opts$config)),
    if (!is.null(opts$`gtex-tissue`))
      paste0("--gtex-tissue=", shQuote(opts$`gtex-tissue`)) else "",
    paste0("--out=", shQuote(f("00_recount3.rds")))
  ))
  run("07_stratified_four_cell_driver.R", c(
    paste0("--in=",          shQuote(f("00_recount3.rds"))),
    paste0("--assignments=", shQuote(opts$`subgroup-assignments`)),
    paste0("--axis=",        shQuote(opts$`subgroup-axis`)),
    paste0("--strata=",      shQuote(opts$strata)),
    paste0("--min-subgroup-tumor=", opts$`min-subgroup-tumor`),
    paste0("--out-dir=",     shQuote(opts$`out-dir`)),
    paste0("--threads=",     opts$threads)
  ))
  message("=== per-subgroup four-cell sensitivity pipeline complete ===")
  message("  Sensitivity:  ", f("sensitivity_by_subgroup.parquet"))
  message("  Provenance:   ", f("provenance_by_subgroup.yaml"))
  quit(status = 0)
}

# === tumor_vs_adjacent (legacy GDC-STAR chain) ==============================
# Quarantined under ../legacy/ (analysis-methods#692, S0): no production caller uses this
# contrast anymore (four_cell_sensitivity/recount3 is the live path above), but the R4
# byte-identity gate (tests/test_byte_identity_vs_legacy_coadread.py) still exercises it as a
# historical-parity check, so the chain itself is kept runnable, just relocated.
stopifnot(!is.null(opts$`parquet-uri`))

run("../legacy/00_load_counts.R", c(
  paste0("--config=",       shQuote(opts$config)),
  paste0("--catalog-repo=", shQuote(opts$`catalog-repo`)),
  paste0("--out=",          shQuote(f("00_counts.rds")))
))

run("../legacy/01_build_design.R", c(
  paste0("--counts=", shQuote(f("00_counts.rds"))),
  paste0("--out=",    shQuote(f("01_design.rds"))),
  if (isTRUE(opts$`joint-gtex`)) "--joint-gtex" else ""
))

run("../legacy/02_combat_seq.R", c(
  paste0("--in=",  shQuote(f("01_design.rds"))),
  paste0("--out=", shQuote(f("02_corrected.rds")))
))

run("../legacy/03_deseq2.R", c(
  paste0("--in=",      shQuote(f("02_corrected.rds"))),
  paste0("--out=",     shQuote(f("03_deseq2.rds"))),
  paste0("--threads=", opts$threads)
))

run("../legacy/04_write_parquet.R", c(
  paste0("--in=",  shQuote(f("03_deseq2.rds"))),
  paste0("--out=", shQuote(opts$`parquet-uri`))
))

run("../legacy/05_provenance.R", c(
  paste0("--in=",            shQuote(f("03_deseq2.rds"))),
  paste0("--config=",        shQuote(opts$config)),
  paste0("--git-sha=",       shQuote(opts$`git-sha`)),
  paste0("--parquet-path=",  shQuote(opts$`parquet-uri`)),
  paste0("--out=",           shQuote(f("05_provenance.yaml")))
))

message("=== pipeline complete ===")
message("  Parquet:    ", opts$`parquet-uri`)
message("  Provenance: ", f("05_provenance.yaml"))
