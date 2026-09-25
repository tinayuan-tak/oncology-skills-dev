#!/usr/bin/env Rscript
# 00_load_xena_toil.R — load ONE indication's joint tumor+adjacent+GTEx counts
# from the Xena/Toil TcgaTargetGtex substrate (UCSC Toil recompute, STAR+RSEM,
# GENCODE v23), producing the SAME .rds shape as 00_load_recount3.R so both
# substrates feed the identical `_four_cell_lib.R` compute. Independent count
# substrate for the Stage-1 cross-substrate calibration (recount3 vs Xena/Toil).
#
# CRITICAL — expected_count transform: the Toil hub ships the matrix as
# log2(expected_count + 1), NOT raw integer counts (recorded in the source
# manifest). We recover DESeq2-usable counts with round(2^x - 1) (clamped at 0).
# Feeding the log2 values straight to DESeq2 would be a silent scale error.
#
# TARGET pediatric samples are excluded (only _study ∈ {TCGA, GTEX} are kept),
# matching the recount3 loader's TCGA-vs-GTEx universe.
#
# Output .rds mirrors 00_load_recount3.R:
#   list(counts = integer matrix (gene_symbol × sample),
#        coldata = data.frame(sample_id, group, source, study, smrin, smtsisch),
#        rowdata = data.frame(gene_symbol, gene_id, gene_stem),
#        metadata = list(substrate, indication, gtex_site, n_*))
# smrin/smtsisch are all-NA here — the Xena phenotype carries no RIN (and RIN is
# GTEx-only / non-identifiable anyway; see the recount3 loader note).

suppressPackageStartupMessages({
  library(optparse)
  library(data.table)
  library(yaml)
})

# Source the shared dedupe_one_aliquot_per_case() + resolve_xena_site_and_studies()
# (S-fix, analysis-methods#691; R-side roster consolidation, analysis-methods#733).
# Robust self-location under `pixi run Rscript`, same pattern as 06/07.
.args <- commandArgs(trailingOnly = FALSE)
.here <- dirname(normalizePath(sub("^--file=", "", .args[grepl("^--file=", .args)][1])))
source(file.path(.here, "_four_cell_lib.R"))

`%||%` <- function(a, b) if (!is.null(a) && length(a) && !is.na(a[1])) a else b

# indication → Xena `_primary_site` label(s) + TCGA study code(s), per arm — now the
# `xena_primary_site` / `tcga_studies` fields of config/indications.yaml (single source
# of truth shared with the Python side, analysis-methods#733), resolved by the shared
# `resolve_xena_site_and_studies()` helper rather than a forked R literal.
#
# The Xena phenotype keys tumor/adjacent/GTEx rows on `_primary_site` (a TISSUE label),
# so the TCGA arm can span more than one site for a COMPOSITE indication — COADREAD =
# colon + rectum (Xena splits `Colon` (COAD) from `Rectum` (READ)). The GTEx arm uses
# the tissue-level site, and GTEx carries no separate rectum, so `Colon` covers the
# colorectal normal.
#
# CAVEAT — this is a TISSUE filter, not a TCGA-study filter. It is correct only where a
# tissue maps 1:1 to the intended study set: true single-study tissues (brca=Breast,
# paad=Pancreas, …) and COADREAD (colon+rectum = exactly COAD+READ; no other TCGA study
# is `Colon`/`Rectum`). It is NOT correct for a tissue shared by multiple histologies you
# want to separate — `Lung` conflates LUAD+LUSC, `Kidney` conflates KIRC/KIRP/KICH.
# Those entries select the whole tissue; do not run them expecting a single histology
# without adding a `detailed_category` filter. recount3 (which filters by TCGA study
# code) is the substrate for those splits.
CFG_INDICATIONS <- yaml::read_yaml(file.path(.here, "..", "config", "indications.yaml"))$indications

option_list <- list(
  make_option("--indication", type = "character",
              help = "Indication slug (e.g. brca, paad) — maps to a _primary_site."),
  make_option("--primary-site", type = "character", default = NULL,
              help = "Override the _primary_site label directly (else from --indication)."),
  make_option("--bucket", type = "character", default = "onc-compbio"),
  make_option("--s3-prefix", type = "character",
              default = paste0("data-catalog/sources/xena-toil/",
                               "tcga-target-gtex-snapshot-2026-09-20"),
              help = "S3 prefix (under the bucket) for the Xena/Toil source release."),
  make_option("--matrix-cache", type = "character",
              default = "/home/sagemaker-user/xena_toil_gene_expected_count.gz",
              help = "Local cache path for the (large) expected_count matrix."),
  make_option("--out", type = "character", help = "Output .rds path"),
  make_option("--limit", type = "integer", default = NA_integer_,
              help = "Cap samples per group (smoke-testing). Default: no cap.")
)
opts <- parse_args(OptionParser(option_list = option_list))
stopifnot(!is.null(opts$indication) || !is.null(opts$`primary-site`), !is.null(opts$out))

ind  <- tolower(opts$indication %||% "")
# tcga_studies is resolved from config regardless of a --primary-site override (matches
# the pre-#733 behaviour, where TCGA_STUDIES_BY_INDICATION[[ind]] %||% toupper(ind) ran
# unconditionally): config/indications.yaml's own `tcga_studies` field, or toupper(ind).
cfg_entry <- CFG_INDICATIONS[[toupper(ind)]]
tcga_studies <- if (!is.null(cfg_entry$tcga_studies)) unlist(cfg_entry$tcga_studies, use.names = FALSE) else toupper(ind)
if (!is.null(opts$`primary-site`)) {
  # Explicit override: a comma-separated `_primary_site` list applied to BOTH
  # the TCGA and GTEx arms (escape hatch for a site not in the map).
  ov <- trimws(strsplit(opts$`primary-site`, ",")[[1]])
  tcga_sites <- ov
  gtex_sites <- ov
} else {
  m <- resolve_xena_site_and_studies(ind, CFG_INDICATIONS)
  if (is.null(m)) stop("no _primary_site mapping for indication '", ind,
                       "' — pass --primary-site explicitly")
  tcga_sites <- m$tcga_sites
  gtex_sites <- m$gtex_sites
}
gtex_tissue  <- paste(gtex_sites, collapse = "+")
bucket <- opts$bucket
prefix <- opts$`s3-prefix`

tmpdir <- tempfile("00_load_xena_")
dir.create(tmpdir, recursive = TRUE)
on.exit(unlink(tmpdir, recursive = TRUE), add = TRUE)

s3_get <- function(name, local) {
  uri <- paste0("s3://", bucket, "/", prefix, "/", name)
  res <- suppressWarnings(system2("aws",
             c("s3", "cp", "--quiet", shQuote(uri), shQuote(local)),
             stdout = TRUE, stderr = TRUE))
  if (!file.exists(local) || file.size(local) == 0) {
    stop("aws s3 cp failed for ", uri, " :: ", paste(res, collapse = " "))
  }
  local
}

# --- phenotype: pick tumor / adjacent / GTEx sample ids for this site --------
message("[00_load_xena_toil] indication=", ind,
        " tcga_sites=", paste(tcga_sites, collapse = "+"),
        " gtex_sites=", paste(gtex_sites, collapse = "+"))
pheno_local <- s3_get("TcgaTargetGTEX_phenotype.txt.gz",
                      file.path(tmpdir, "pheno.txt.gz"))
# encoding="Latin-1": the Xena phenotype carries non-UTF-8 bytes in some
# tissue/disease labels (e.g. accented characters in `detailed_category`). Read
# under UTF-8 those bytes make tolower()/grepl throw "invalid multibyte string",
# so we tag the strings as Latin-1 at read time.
ph <- data.table::fread(cmd = paste("gzip -dc", shQuote(pheno_local)),
                        sep = "\t", header = TRUE, showProgress = FALSE,
                        colClasses = "character", encoding = "Latin-1")
setnames(ph, "_sample_type", "sample_type", skip_absent = TRUE)
setnames(ph, "_primary_site", "primary_site", skip_absent = TRUE)
setnames(ph, "_study", "study", skip_absent = TRUE)
stopifnot(all(c("sample", "sample_type", "primary_site", "study") %in% names(ph)))

tumor_ids    <- ph[study == "TCGA" & sample_type == "Primary Tumor"       & tolower(primary_site) %in% tolower(tcga_sites), sample]
adjacent_ids <- ph[study == "TCGA" & sample_type == "Solid Tissue Normal" & tolower(primary_site) %in% tolower(tcga_sites), sample]
gtex_ids     <- ph[study == "GTEX" & sample_type == "Normal Tissue"       & tolower(primary_site) %in% tolower(gtex_sites), sample]

# One-aliquot-per-case dedup (S-fix, analysis-methods#691), TCGA arm only —
# GTEx samples are one draw per donor per tissue, not GDC-style technical
# aliquots, so the legacy loader's dedup never applied to them either. The
# Xena `sample` barcode is the 15-char TCGA sample barcode
# (TCGA-XX-XXXX-TT, e.g. "TCGA-V4-A9EE-01") with no aliquot/vial suffix, so
# case_id is its first 12 characters; order key = the barcode itself
# (deterministic, mirrors the recount3 loader's ascending-id-first policy).
case_id_of <- function(ids) substr(ids, 1, 12)
tumor_ids <- dedupe_one_aliquot_per_case(
  tumor_ids, setNames(case_id_of(tumor_ids), tumor_ids), label = "tumor")
adjacent_ids <- dedupe_one_aliquot_per_case(
  adjacent_ids, setNames(case_id_of(adjacent_ids), adjacent_ids), label = "adjacent-normal")

if (!is.na(opts$limit)) {
  tumor_ids    <- head(tumor_ids, opts$limit)
  adjacent_ids <- head(adjacent_ids, opts$limit)
  gtex_ids     <- head(gtex_ids, opts$limit)
}
message(sprintf("[00_load_xena_toil]   %d tumor (TCGA) + %d adjacent (TCGA) + %d GTEx normal",
                length(tumor_ids), length(adjacent_ids), length(gtex_ids)))
stopifnot(length(tumor_ids) > 0)
wanted <- c(tumor_ids, adjacent_ids, gtex_ids)

# --- matrix: download once (cache), then slice ONLY the wanted columns -------
# The matrix is ~60K genes × ~19K samples of log2(count+1). Parsing all columns
# just to select ~1e3 is wasteful, so we read the header, resolve wanted-column
# indices, and `cut` them out of the decompressed stream before fread — the R
# side then only ever parses a narrow table.
mcache <- opts$`matrix-cache`
if (!file.exists(mcache) || file.size(mcache) == 0) {
  message("[00_load_xena_toil]   downloading expected_count matrix to cache ", mcache)
  s3_get("TcgaTargetGtex_gene_expected_count.gz", mcache)
} else {
  message("[00_load_xena_toil]   reusing cached matrix ", mcache,
          " (", round(file.size(mcache) / 1e6), " MB)")
}

hdr <- strsplit(readLines(gzfile(mcache), n = 1), "\t", fixed = TRUE)[[1]]
stopifnot(identical(hdr[1], "sample"))
col_idx <- match(wanted, hdr)
missing <- wanted[is.na(col_idx)]
if (length(missing)) {
  message("[00_load_xena_toil]   WARNING: ", length(missing),
          " phenotype samples absent from the matrix (dropped): ",
          paste(head(missing, 3), collapse = ", "))
  wanted <- wanted[!is.na(col_idx)]
  col_idx <- col_idx[!is.na(col_idx)]
}
idx_arg <- paste(c(1L, sort(col_idx)), collapse = ",")   # 1 = gene id column
message("[00_load_xena_toil]   slicing ", length(col_idx), " sample columns from the matrix")
mat_dt <- data.table::fread(
  cmd = paste("gzip -dc", shQuote(mcache), "| cut -f", idx_arg),
  sep = "\t", header = TRUE, showProgress = FALSE)
setnames(mat_dt, 1, "gene_id")

# --- recover integer counts from log2(count + 1) ----------------------------
# xena_log2_to_counts (in _four_cell_lib.R) inverts Toil's log2(expected_count+1)
# transform: round(2^x-1), clamped at 0, integer-stored. It is a shared, unit-
# tested function (test_xena_log2_to_counts.py) so the round-trip/non-negativity/
# integer invariant this loader depends on can't silently drift.
gene_id <- mat_dt$gene_id
vals <- as.matrix(mat_dt[, -1])
storage.mode(vals) <- "double"
counts <- xena_log2_to_counts(vals)
rownames(counts) <- gene_id

# --- map Ensembl gene_id → HGNC symbol via the probemap; collapse by sum -----
pm_local <- s3_get("gencode.v23.annotation.gene.probemap",
                   file.path(tmpdir, "probemap.tsv"))
pm <- data.table::fread(pm_local, sep = "\t", header = TRUE, showProgress = FALSE)
# probemap: id (versioned Ensembl) , gene (symbol), chrom, ...
id2sym <- setNames(pm$gene, pm$id)
gene_symbol <- id2sym[gene_id]
# fall back to a version-stripped join for any id the probemap versions differ on
na_sym <- is.na(gene_symbol)
if (any(na_sym)) {
  stem_map <- setNames(pm$gene, sub("\\..*$", "", pm$id))
  gene_symbol[na_sym] <- stem_map[sub("\\..*$", "", gene_id[na_sym])]
}
keep <- !is.na(gene_symbol) & gene_symbol != ""
message(sprintf("[00_load_xena_toil]   HGNC-mappable: %d/%d genes",
                sum(keep), length(gene_id)))
counts <- counts[keep, , drop = FALSE]
gene_id_kept <- gene_id[keep]
gene_symbol  <- gene_symbol[keep]
gene_stem_kept <- sub("\\..*$", "", gene_id_kept)

dup <- duplicated(gene_symbol) | duplicated(gene_symbol, fromLast = TRUE)
if (any(dup)) {
  message("[00_load_xena_toil]   collapsing ", sum(dup), " rows across ",
          length(unique(gene_symbol[dup])), " duplicate symbols (sum)")
  counts <- rowsum(counts, gene_symbol)
  storage.mode(counts) <- "integer"
  first_idx <- !duplicated(gene_symbol)
  gi  <- setNames(gene_id_kept[first_idx],   gene_symbol[first_idx])
  gsm <- setNames(gene_stem_kept[first_idx], gene_symbol[first_idx])
  rowdata <- data.frame(gene_symbol = rownames(counts),
                        gene_id   = unname(gi[rownames(counts)]),
                        gene_stem = unname(gsm[rownames(counts)]),
                        stringsAsFactors = FALSE)
} else {
  rownames(counts) <- gene_symbol
  rowdata <- data.frame(gene_symbol = gene_symbol, gene_id = gene_id_kept,
                        gene_stem = gene_stem_kept, stringsAsFactors = FALSE)
}

# --- coldata (aligned to the matrix column order) ---------------------------
grp_of <- setNames(
  c(rep("tumor", length(tumor_ids)), rep("normal", length(adjacent_ids)),
    rep("normal", length(gtex_ids))),
  c(tumor_ids, adjacent_ids, gtex_ids))
src_of <- setNames(
  c(rep("TCGA", length(tumor_ids)), rep("TCGA", length(adjacent_ids)),
    rep("GTEx", length(gtex_ids))),
  c(tumor_ids, adjacent_ids, gtex_ids))
sample_ids <- colnames(counts)
coldata <- data.frame(
  sample_id = sample_ids,
  group     = unname(grp_of[sample_ids]),
  source    = unname(src_of[sample_ids]),
  study     = ifelse(unname(src_of[sample_ids]) == "GTEx",
                     paste0("GTEX_", gsub("[^A-Za-z]", "", paste(gtex_sites, collapse = ""))),
                     paste0("TCGA_", toupper(ind))),
  smrin     = NA_real_,   # Xena phenotype carries no RIN; GTEx-only + non-identifiable anyway
  smtsisch  = NA_real_,
  stringsAsFactors = FALSE)
rownames(coldata) <- coldata$sample_id
stopifnot(ncol(counts) == nrow(coldata))

# --- QC: drop empty libraries ----------------------------------------------
lib <- colSums(counts)
empty <- lib == 0
if (any(empty)) {
  message("[00_load_xena_toil] dropping ", sum(empty), " empty libraries (libsize == 0)")
  counts  <- counts[, !empty, drop = FALSE]
  coldata <- coldata[!empty, , drop = FALSE]
}

out <- list(
  counts = counts, coldata = coldata, rowdata = rowdata,
  metadata = list(
    substrate    = "xena-toil/tcga-target-gtex-snapshot-2026-09-20 (GENCODE v23, RSEM expected_count)",
    indication   = ind,
    tcga_studies = tcga_studies,   # read by 06_four_cell_driver.R provenance
    gtex_tissue  = gtex_tissue,    # read by 06_four_cell_driver.R provenance
    gtex_site    = gtex_tissue,    # back-compat alias (method_development scripts)
    n_genes      = nrow(counts),
    n_tumor      = sum(coldata$group == "tumor"),
    n_adjacent   = sum(coldata$group == "normal" & coldata$source == "TCGA"),
    n_gtex       = sum(coldata$group == "normal" & coldata$source == "GTEx"),
    gtex_available = any(coldata$source == "GTEx")))
saveRDS(out, opts$out)
message(sprintf(paste0("[00_load_xena_toil] wrote %s  (%d genes × %d samples; ",
                       "%d tumor, %d TCGA-adjacent, %d GTEx)"),
                opts$out, nrow(counts), ncol(counts),
                out$metadata$n_tumor, out$metadata$n_adjacent, out$metadata$n_gtex))
