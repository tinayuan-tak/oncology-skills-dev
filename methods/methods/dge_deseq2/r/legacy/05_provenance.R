#!/usr/bin/env Rscript
# 05_provenance.R — write provenance.yaml alongside the Parquet artifact.
#
# Records exactly what produced this artifact: source manifest id (which traces
# back to the data-catalog re-obtainable origin), software versions, design
# formula, parameter hash, git commit, dates. This pairs with the catalog's
# `derived` manifest that downstream skills will cite.

suppressPackageStartupMessages({
  library(optparse)
  library(yaml)
  library(digest)
})

option_list <- list(
  make_option("--in", type = "character", dest = "in_path",
              help = "Output of 03_deseq2.R (.rds with metadata + version info)"),
  make_option("--config", type = "character", help = "configs/{indication}.yaml"),
  make_option("--git-sha", type = "character", help = "git commit sha of producing code"),
  make_option("--parquet-path", type = "character",
              help = "S3 (or local) path of the Parquet from 04_write_parquet.R"),
  make_option("--out", type = "character", help = "Output provenance.yaml path")
)
opts <- parse_args(OptionParser(option_list = option_list))
stopifnot(!is.null(opts$in_path), !is.null(opts$config),
          !is.null(opts$`git-sha`), !is.null(opts$out))

dat <- readRDS(opts$in_path)
cfg <- yaml::read_yaml(opts$config)

# Hash the config + design + version triple — this is the "did anything material
# change?" key. If two runs produce the same hash, they should produce identical
# Parquets (modulo nondeterminism in the deps, which DESeq2 does not have for
# fixed inputs).
parameter_hash <- digest::digest(list(
  config = cfg,
  design = dat$dge_design,
  combat_seq_applied = isTRUE(dat$combat_seq_applied),
  deseq2 = dat$deseq2_version,
  apeglm = dat$apeglm_version,
  combat_seq = dat$combat_seq_version
), algo = "sha256")

provenance <- list(
  artifact_kind = "dge-parquet",
  indication = cfg$indication,
  comparison = "tumor_vs_adjacent_normal",
  parquet_uri = opts$`parquet-path`,
  source = list(
    manifest_id = cfg$source$manifest_id,
    catalog_repo = cfg$source$catalog_repo,
    release = dat$metadata$release,
    retrieved_date = dat$metadata$retrieved_date
  ),
  method = list(
    name = "DESeq2 + ComBat-seq + lfcShrink(apeglm)",
    test = "Wald",
    multiple_testing = "BH-FDR (independent filtering on baseMean)",
    shrinkage = "apeglm",
    actionability_filter = "padj<0.05 AND |log2FoldChange|>=1",
    design_formula = dat$dge_design,
    combat_seq_applied = isTRUE(dat$combat_seq_applied)
  ),
  versions = list(
    DESeq2 = dat$deseq2_version,
    apeglm = dat$apeglm_version,
    sva = dat$combat_seq_version,
    R = paste(R.version$major, R.version$minor, sep = ".")
    # `bioconductor` is set below via tryCatch — do NOT call BiocManager::version()
    # eagerly here: this list is built before the tryCatch runs, so an unguarded
    # call would abort the whole script if BiocManager were absent, and its value
    # is overwritten below regardless. BiocManager is now a declared pixi dep
    # (r-biocmanager), so the tryCatch records the real Bioconductor release.
  ),
  cohort = list(
    n_tumor = dat$dge_n_tumor,
    n_normal = dat$dge_n_normal,
    n_genes_tested = dat$dge_n_genes_tested
  ),
  git_commit = opts$`git-sha`,
  parameter_hash = parameter_hash,
  computed_date = format(Sys.time(), "%Y-%m-%d"),
  computed_by = Sys.getenv("USER", unset = "unknown"),
  label = if (isTRUE(cfg$exploratory)) "exploratory" else "pre-specified"
)

# Record the Bioconductor release. BiocManager is a declared pixi dep, so this
# resolves to the real version; the tryCatch stays as a cross-environment guard
# so a provenance write never aborts if some other R env lacks it (falls back to
# "unknown" rather than crashing — but the pixi env must, and does, have it).
provenance$versions$bioconductor <- tryCatch(
  as.character(BiocManager::version()),
  error = function(e) "unknown"
)

yaml::write_yaml(provenance, opts$out)
message("[05_provenance] wrote ", opts$out,
        "  (parameter_hash: ", substr(parameter_hash, 1, 12), "…)")
