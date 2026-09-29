#!/usr/bin/env Rscript
# 00_load_counts.R — load raw integer counts for the COADREAD cohort + matched normal.
#
# Inputs:  configs/COADREAD.yaml (the indication config, with `source.manifest_id`
#          pointing at a data-catalog source-release manifest)
# Output:  an .rds with a list:
#            counts:    integer matrix (genes × samples), rownames = gene_symbol
#            coldata:   data.frame (sample_id, case_id, project_id,
#                                   group ∈ {tumor, normal})
#            rowdata:   data.frame (gene_symbol, gene_id, gene_type)
#            metadata:  list of source release info (manifest_id, release,
#                                                    retrieved_date, provider, ...)
#
# This script is the SINGLE place in the R pipeline that touches a specific
# data source. Everything downstream (01-05) operates on the produced .rds.

suppressPackageStartupMessages({
  library(optparse)
  library(yaml)
  library(data.table)
  library(parallel)
})

`%||%` <- function(a, b) if (!is.null(a) && !is.na(a)) a else b

option_list <- list(
  make_option("--config", type = "character", help = "Path to indication config YAML"),
  make_option("--catalog-repo", type = "character", default = NULL,
              help = "Path to local clone of the data-catalog repo (for resolving manifest_id)"),
  make_option("--out", type = "character", help = "Output .rds path"),
  make_option("--limit", type = "integer", default = NA_integer_,
              help = "Cap the number of files loaded (smoke-testing). Default: no cap."),
  make_option("--threads", type = "integer", default = 4,
              help = "Concurrent S3 downloads.")
)
opts <- parse_args(OptionParser(option_list = option_list))

stopifnot(!is.null(opts$config), !is.null(opts$out))

cfg <- yaml::read_yaml(opts$config)
src <- cfg$source
if (is.null(src) || is.null(src$manifest_id) || identical(src$manifest_id, "TODO")) {
  stop(
    "configs/", basename(opts$config), " `source.manifest_id` is not set. ",
    "This pipeline cannot run until a canonical source is chosen and a corresponding ",
    "source-release manifest exists in the data-catalog repo. Set source.manifest_id ",
    "to that manifest's id."
  )
}

# --- resolve manifest -------------------------------------------------------
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
message("[00_load_counts]   s3_uri:  ", manifest$s3_uri)
message("[00_load_counts]   release: ", manifest$version)
message("[00_load_counts]   files in manifest: ", length(manifest$files))

# --- source-specific loader -------------------------------------------------
if (identical(manifest$provider, "gdc")) {

  # 1. Filter manifest's files[] to the indication's project_ids.
  cohorts <- cfg$tcga_cohorts
  stopifnot(length(cohorts) > 0)
  project_ids <- paste0("TCGA-", cohorts)
  message("[00_load_counts] filtering to project_ids: ",
          paste(project_ids, collapse = ", "))

  files_in_cohort <- Filter(
    function(f) !is.null(f$project_id) && f$project_id %in% project_ids,
    manifest$files
  )
  message("[00_load_counts]   files in cohort: ", length(files_in_cohort))

  # 2. Label each file as tumor or adjacent-normal via TCGA barcode suffix.
  # TCGA barcodes encode sample type in the 4th hyphen-separated field, e.g.
  # TCGA-AA-3534-11A-01R-A22A-07 → "11A"; the 2-char prefix is the type.
  # -01..-09 are tumors (-01 Primary Tumor); -10..-19 are normals (-11 Solid
  # Tissue Normal). Per cfg$dge$tcga_barcode_suffixes, this single-source
  # regime takes ONLY -01 (Primary Tumor) and -11 (Solid Tissue Normal); other
  # tumor types (-02 Recurrent, -06 Metastatic, etc.) are excluded so the
  # contrast is biologically clean.
  tumor_suffixes  <- cfg$dge$tcga_barcode_suffixes$tumor
  normal_suffixes <- cfg$dge$tcga_barcode_suffixes$adjacent_normal
  stopifnot(length(tumor_suffixes) > 0, length(normal_suffixes) > 0)

  classify_sample <- function(sample_id) {
    if (is.null(sample_id) || !nzchar(sample_id)) return(NA_character_)
    parts <- strsplit(sample_id, "-", fixed = TRUE)[[1]]
    if (length(parts) < 4) return(NA_character_)
    suffix2 <- substr(parts[4], 1, 2)  # e.g. "01" from "01A"
    suffix_dash <- paste0("-", suffix2)
    if (suffix_dash %in% tumor_suffixes)  return("tumor")
    if (suffix_dash %in% normal_suffixes) return("normal")
    return(NA_character_)
  }

  groups <- vapply(files_in_cohort,
                   function(f) classify_sample(f$sample_id),
                   character(1))
  keep_mask <- !is.na(groups)
  n_dropped <- sum(!keep_mask)
  if (n_dropped > 0) {
    message("[00_load_counts]   dropped ", n_dropped,
            " files (sample type other than primary-tumor/adjacent-normal)")
  }
  files_in_cohort <- files_in_cohort[keep_mask]
  groups <- groups[keep_mask]

  message("[00_load_counts]   tumor files:  ", sum(groups == "tumor"))
  message("[00_load_counts]   normal files: ", sum(groups == "normal"))

  # Multi-aliquot dedup: TCGA contributes >1 file per (case_id, group) for a
  # small fraction of patients (technical-replicate vials, biological aliquots
  # from the same tumor block). These violate DESeq2's per-sample independence
  # assumption — one aliquot per (case_id, sample_type) is the field convention.
  # Ordering by GDC file_id (UUID) and taking the first match is deterministic
  # and reviewable. See runbook entry "TCGA pseudo-replicate handling".
  dedup_policy <- cfg$dge$sample_dedup %||% "one_per_case_group_first_by_file_id"
  if (identical(dedup_policy, "one_per_case_group_first_by_file_id")) {
    file_ids <- vapply(files_in_cohort,
                       function(f) f$source_id %||% "", character(1))
    ord <- order(file_ids)
    files_in_cohort <- files_in_cohort[ord]
    groups <- groups[ord]
    case_ids <- vapply(files_in_cohort,
                       function(f) f$case_id %||% NA_character_, character(1))
    keys <- paste(case_ids, groups, sep = "|")
    keep_one <- !duplicated(keys)
    n_dropped_dup <- sum(!keep_one)
    if (n_dropped_dup > 0) {
      message("[00_load_counts]   deduped ", n_dropped_dup,
              " files (one aliquot per case+group; alphabetical-first by file_id). ",
              "Policy: '", dedup_policy, "'.")
    }
    files_in_cohort <- files_in_cohort[keep_one]
    groups <- groups[keep_one]
    message("[00_load_counts]   post-dedup: ", sum(groups == "tumor"),
            " tumor + ", sum(groups == "normal"), " normal (",
            length(files_in_cohort), " files)")
  } else {
    stop("Unknown sample_dedup policy: '", dedup_policy,
         "'. Implemented: 'one_per_case_group_first_by_file_id'.")
  }

  # Apply --limit (after dedup so the smoke set never accidentally pulls
  # duplicate aliquots).
  if (!is.na(opts$limit) && length(files_in_cohort) > opts$limit) {
    # Stratified subsample: half tumor, half normal (or as close as possible).
    half <- max(1L, opts$limit %/% 2L)
    t_idx <- which(groups == "tumor")
    n_idx <- which(groups == "normal")
    take_t <- head(t_idx, min(half, length(t_idx)))
    take_n <- head(n_idx, min(opts$limit - length(take_t), length(n_idx)))
    keep <- sort(c(take_t, take_n))
    files_in_cohort <- files_in_cohort[keep]
    groups <- groups[keep]
    message("[00_load_counts] --limit ", opts$limit,
            ": loading ", sum(groups == "tumor"), " tumor + ",
            sum(groups == "normal"), " normal")
  }

  if (length(files_in_cohort) < 2) {
    stop("Fewer than 2 files match cohort + sample-type filters; nothing to load.")
  }

  # 3. Stream each STAR-Counts TSV from S3 and assemble the count matrix.
  # Strategy: aws s3 cp via system2() is the most battle-tested under SSO auth;
  # paws.storage works but adds an auth-resolution surface this code doesn't
  # need. Files are small (~5 MB ea), parallelism via mclapply on threads.
  s3_uri <- manifest$s3_uri
  if (!endsWith(s3_uri, "/")) s3_uri <- paste0(s3_uri, "/")

  tmpdir <- tempfile("00_load_counts_")
  dir.create(tmpdir, recursive = TRUE)
  on.exit(unlink(tmpdir, recursive = TRUE), add = TRUE)

  star_counts_cols <- c(
    "gene_id", "gene_name", "gene_type",
    "unstranded", "stranded_first", "stranded_second",
    "tpm_unstranded", "fpkm_unstranded", "fpkm_uq_unstranded"
  )

  load_one <- function(i) {
    f <- files_in_cohort[[i]]
    src_uri <- paste0(s3_uri, f$path)
    # Use file_id (UUID) as local name to avoid path-component clashes.
    local <- file.path(tmpdir, paste0(f$source_id %||% sprintf("file_%05d", i), ".tsv"))
    res <- system2("aws", c("s3", "cp", "--quiet",
                            shQuote(src_uri), shQuote(local)),
                   stdout = FALSE, stderr = TRUE)
    if (!file.exists(local) || file.size(local) == 0) {
      stop("aws s3 cp failed for ", src_uri,
           " (status=", res, ")")
    }
    # skip="ENSG" jumps to the first line starting with "ENSG", neatly
    # bypassing the "# gene-model" comment line, the column header line, and
    # the 4 N_unmapped/N_multimapping/N_noFeature/N_ambiguous metadata rows.
    # Read all 9 STAR-Counts columns then subset — fread's `select` matches
    # the file's V1/V2... names, not col.names, when header=FALSE.
    dt <- data.table::fread(
      local, sep = "\t", header = FALSE, skip = "ENSG",
      col.names = star_counts_cols
    )
    file.remove(local)
    dt[, .(gene_id, gene_name, gene_type, unstranded = as.integer(unstranded))]
  }

  message("[00_load_counts] downloading + parsing ",
          length(files_in_cohort), " files (",
          opts$threads, " threads)…")
  per_sample <- parallel::mclapply(
    seq_along(files_in_cohort), load_one,
    mc.cores = max(1L, opts$threads),
    mc.preschedule = FALSE
  )

  # Surface any worker errors immediately — mclapply silently returns
  # try-error objects on failure.
  err_idx <- which(vapply(per_sample, inherits, logical(1), "try-error"))
  if (length(err_idx) > 0) {
    stop(length(err_idx), " files failed to load. First error:\n",
         attr(per_sample[[err_idx[1]]], "condition")$message)
  }

  # 4. Build rowdata from the first file (gene set is uniform across STAR-Counts
  # at one workflow_version, verified against manifest pipeline.workflow_version).
  rowdata <- per_sample[[1]][, c("gene_id", "gene_name", "gene_type")]
  setnames(rowdata, "gene_name", "gene_symbol")

  # Verify gene order is identical across files (cheap check on first/last).
  for (j in c(2L, length(per_sample))) {
    if (j <= length(per_sample) &&
        !identical(per_sample[[j]]$gene_id, rowdata$gene_id)) {
      stop("Gene order mismatch between files; STAR-Counts assumed uniform but isn't.")
    }
  }

  # 5. Assemble the gene × sample integer matrix from the `unstranded` columns.
  counts_mat <- do.call(cbind, lapply(per_sample, function(dt) dt$unstranded))
  storage.mode(counts_mat) <- "integer"
  rownames(counts_mat) <- rowdata$gene_id  # temp; aggregated to gene_symbol below

  sample_ids <- vapply(files_in_cohort,
                       function(f) f$sample_id %||% NA_character_,
                       character(1))
  colnames(counts_mat) <- sample_ids

  # 6. Aggregate by gene_symbol — GENCODE v36 has ~50-150 cases where a single
  # gene_symbol maps to multiple gene_ids (PAR_Y duplicates on chrY, a handful
  # of immunoglobulin/pseudogene families). 03_deseq2.R indexes results by
  # rownames(res) and stores them as `gene_symbol`, so the count matrix MUST
  # be keyed by gene_symbol. Sum across duplicates is standard practice
  # (matches tximport's gene-level summing convention).
  dup_mask <- duplicated(rowdata$gene_symbol) | duplicated(rowdata$gene_symbol, fromLast = TRUE)
  n_dup_symbols <- length(unique(rowdata$gene_symbol[dup_mask]))
  if (n_dup_symbols > 0) {
    message("[00_load_counts]   aggregating ", sum(dup_mask),
            " gene_id rows across ", n_dup_symbols,
            " duplicate gene_symbols (sum)")
    counts_mat <- rowsum(counts_mat, rowdata$gene_symbol)
    storage.mode(counts_mat) <- "integer"
    # Collapse rowdata to one row per gene_symbol (keep first gene_id seen).
    rowdata <- rowdata[!duplicated(rowdata$gene_symbol), ]
    rowdata <- rowdata[match(rownames(counts_mat), rowdata$gene_symbol), ]
  } else {
    rownames(counts_mat) <- rowdata$gene_symbol
  }

  # 7. Build coldata.
  coldata <- data.frame(
    sample_id  = sample_ids,
    case_id    = vapply(files_in_cohort,
                        function(f) f$case_id %||% NA_character_, character(1)),
    project_id = vapply(files_in_cohort,
                        function(f) f$project_id %||% NA_character_, character(1)),
    group      = groups,
    stringsAsFactors = FALSE,
    row.names  = sample_ids
  )

  # 8. Save the .rds.
  out <- list(
    counts   = counts_mat,
    coldata  = coldata,
    rowdata  = as.data.frame(rowdata),
    metadata = list(
      manifest_id    = src$manifest_id,
      release        = manifest$version,
      retrieved_date = manifest$retrieved_date,
      provider       = manifest$provider,
      pipeline       = manifest$pipeline,
      n_files        = length(files_in_cohort),
      cohorts        = cohorts,
      counts_column  = "unstranded",
      sample_filter  = "primary-tumor (-01) + adjacent-normal (-11) only"
    )
  )

  saveRDS(out, opts$out)
  message("[00_load_counts] wrote ", opts$out,
          "  (", nrow(counts_mat), " genes × ", ncol(counts_mat), " samples; ",
          sum(coldata$group == "tumor"), " tumor + ",
          sum(coldata$group == "normal"), " normal)")

} else {
  # Other providers — scaffolded but not implemented for the first run:
  #   provider == "xena-toil"→ Toil TCGA-TARGET-GTEx recompute counts file
  #   provider == "recount3" → recount3 R package: TCGA-COAD/READ
  #                            RangedSummarizedExperiment, assay 'raw_counts'
  #   provider == "omicsoft" → BLOCKED: OncoLand ships log2(TPM+1), not raw counts
  stop(
    "Unimplemented loader for provider='", manifest$provider, "'. ",
    "DESeq2 requires raw integer counts; loader must return counts as `integer` matrix, ",
    "not TPM/FPKM/log values. Only provider='gdc' implemented in this build."
  )
}
