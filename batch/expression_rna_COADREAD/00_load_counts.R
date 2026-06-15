#!/usr/bin/env Rscript
# 00_load_counts.R — load raw integer counts for the COADREAD cohort + matched normal.
#
# Inputs:  configs/COADREAD.yaml (the indication config, with `source.manifest_id`
#          pointing at a data-catalog source-release manifest)
# Output:  an .rds with a list:
#            counts:    integer matrix (genes × samples)
#            coldata:   data.frame (sample_id, group ∈ {tumor, normal},
#                                   batch, source, cohort, ...)
#            rowdata:   data.frame (gene_symbol, ensembl_id, biotype if available)
#            metadata:  list of source release info (release, retrieved_date, ...)
#
# This script is the SINGLE place in the R pipeline that touches a specific
# data source. Everything downstream (01-05) operates on the produced .rds.

suppressPackageStartupMessages({
  library(optparse)
  library(yaml)
})

option_list <- list(
  make_option("--config", type = "character", help = "Path to indication config YAML"),
  make_option("--catalog-repo", type = "character", default = NULL,
              help = "Path to local clone of the data-catalog repo (for resolving manifest_id)"),
  make_option("--out", type = "character", help = "Output .rds path")
)
opts <- parse_args(OptionParser(option_list = option_list))

stopifnot(!is.null(opts$config), !is.null(opts$out))

cfg <- yaml::read_yaml(opts$config)
src <- cfg$source
if (is.null(src) || is.null(src$manifest_id) || identical(src$manifest_id, "TODO")) {
  stop(
    "configs/COADREAD.yaml `source.manifest_id` is not set. ",
    "This pipeline cannot run until a canonical source is chosen ",
    "(see deep-research outcome) and a corresponding source-release manifest ",
    "exists in the data-catalog repo. Set source.manifest_id to that manifest's id."
  )
}

# --- resolve manifest -------------------------------------------------------
# Read the data-catalog manifest by id to get the s3_uri and per-file metadata.
# The catalog-repo path is supplied via --catalog-repo (preferred) or env var.
catalog_repo <- opts$`catalog-repo` %||% Sys.getenv("DATA_CATALOG_REPO", unset = NA)
if (is.na(catalog_repo) || !dir.exists(catalog_repo)) {
  stop(
    "Cannot resolve manifest '", src$manifest_id, "': ",
    "data-catalog repo path not provided. Pass --catalog-repo /path/to/clone ",
    "or set DATA_CATALOG_REPO. Repo: oneTakeda/rnd-computational-biology-oncology-data-catalog."
  )
}
manifest_path <- file.path(catalog_repo, "manifests", "sources",
                           paste0(src$manifest_id, ".yaml"))
if (!file.exists(manifest_path)) {
  stop("Manifest not found at: ", manifest_path)
}
manifest <- yaml::read_yaml(manifest_path)
stopifnot(manifest$type == "source-release")

message("[00_load_counts] resolved source manifest: ", src$manifest_id)
message("[00_load_counts]   s3_uri: ", manifest$s3_uri)
message("[00_load_counts]   release: ", manifest$version)

# --- source-specific loader -------------------------------------------------
# This is the ONLY place in the pipeline where the choice of source matters.
# When the canonical source is decided (deep-research outcome), implement a
# dispatcher here keyed on manifest$provider:
#
#   provider == "gdc"      → load STAR-Counts MAFs (raw integer counts) per sample,
#                            join into a gene × sample matrix.
#   provider == "xena-toil"→ download the TCGA-TARGET-GTEx Toil recompute counts
#                            file, restrict to COAD/READ + colon GTEx, build matrix.
#   provider == "recount3" → use the recount3 R package to fetch the TCGA-COAD
#                            and TCGA-READ projects' RangedSummarizedExperiment;
#                            extract assay 'raw_counts' (NOT TPM).
#   provider == "omicsoft" → BLOCKED. OncoLand ships log2(TPM+1), not raw counts.
#                            DESeq2 requires raw integer counts. Fall back to
#                            another provider for the canonical compute; OncoLand
#                            stays as a TPM convenience cache.
#
# Each branch must return:
#   list(counts = integer_matrix, coldata = df, rowdata = df, metadata = list)

stop(
  "TODO(deep-research-outcome): implement source-specific loader for provider='",
  manifest$provider, "'. ",
  "DESeq2 requires raw integer counts; loader must return counts as `integer` matrix, ",
  "not TPM/FPKM/log values. See scaffolded branches in this file's comments."
)

# When implemented, the final step is:
#   saveRDS(list(counts = counts, coldata = coldata, rowdata = rowdata,
#                metadata = list(manifest_id = src$manifest_id,
#                                release = manifest$version,
#                                retrieved_date = manifest$retrieved_date,
#                                provider = manifest$provider)),
#           opts$out)
#   message("[00_load_counts] wrote ", opts$out)

`%||%` <- function(a, b) if (!is.null(a) && !is.na(a)) a else b
