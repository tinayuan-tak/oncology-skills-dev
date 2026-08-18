#!/usr/bin/env Rscript
# 00_load_recount3.R — load ALL sample groups for the four-cell sensitivity
# pipeline from ONE substrate: recount3 tcga-gtex-2023-01-04 (monorail uniform
# reprocess, Gencode v26 / G026).
#
# Unlike 00_load_counts.R (which assembles a matrix from per-file GDC-STAR TSVs
# for the tumor-vs-adjacent path), this loader reads recount3's pre-matrixed
# `gene_sums` files (genes × samples) for BOTH TCGA studies and the GTEx tissue,
# then labels every sample with group ∈ {tumor, normal} + source ∈ {TCGA, GTEx}.
#
# WHY one substrate: cells A/B (tumor-vs-adjacent) and C/D (tumor-vs-GTEx) must
# share an aligner, else an A-vs-C disagreement conflates comparator with
# aligner. See DESIGN_v2_four_cell_consolidation.md §2.1.
#
# Output .rds: list(
#   counts    = integer matrix (gene_symbol × sample),  HGNC-collapsed
#   coldata   = data.frame(sample_id, group, source, tcga_tss, submitter_id, study)
#   rowdata   = data.frame(gene_symbol, gene_id, gene_stem)
#   metadata  = list(substrate, tcga_studies, gtex_tissue, counts, n_*)
# )
# `submitter_id` is the TCGA patient barcode (gdc_cases.submitter_id) for TCGA
# samples, NA for GTEx — the join key to subgroup-assignments.patient_id used by
# 07_stratified_four_cell_driver.R. Additive column; the whole-cohort four-cell
# driver (06) ignores it, so its output is unaffected.

suppressPackageStartupMessages({
  library(optparse)
  library(yaml)
  library(data.table)
})

`%||%` <- function(a, b) if (!is.null(a) && length(a) && !is.na(a[1])) a else b

option_list <- list(
  make_option("--config", type = "character",
              help = "Indication config YAML (tcga_cohorts + gtex_reference)"),
  make_option("--recount3-prefix", type = "character",
              default = "data-catalog/sources/recount3/tcga-gtex-2023-01-04",
              help = "S3 prefix (under the bucket) for the recount3 substrate."),
  make_option("--bucket", type = "character", default = "onc-compbio"),
  make_option("--ensembl-map-s3", type = "character",
              default = paste0("data-catalog/sources/ensembl-id-mapping/",
                               "release-116-snapshot-2026-06-18/",
                               "hsapiens_gene_id_map_release-116.tsv"),
              help = "S3 key for the Ensembl-116 gene_id → HGNC map."),
  make_option("--gtex-tissue", type = "character", default = NULL,
              help = "Override GTEx tissue code (else derived from config)."),
  make_option("--out", type = "character", help = "Output .rds path"),
  make_option("--limit", type = "integer", default = NA_integer_,
              help = "Cap samples per group (smoke-testing). Default: no cap.")
)
opts <- parse_args(OptionParser(option_list = option_list))
stopifnot(!is.null(opts$config), !is.null(opts$out))

cfg <- yaml::read_yaml(opts$config)
bucket <- opts$bucket
r3     <- opts$`recount3-prefix`

# --- indication → TCGA studies + GTEx tissue --------------------------------
tcga_studies <- cfg$tcga_cohorts
stopifnot(length(tcga_studies) > 0)

# GTEx tissue: explicit flag wins; else config's gtex_reference; else NULL.
gtex_tissue <- opts$`gtex-tissue`
if (is.null(gtex_tissue)) {
  # config carries gtex_reference$tissues as recount3-subregion names
  # (e.g. "Colon_Sigmoid"); the recount3 gene_sums are keyed by the parent
  # tissue code ("COLON"). Map here via cfg$gtex_reference$recount3_code if set,
  # else fall back to the study→tissue table below.
  gtex_tissue <- cfg$gtex_reference$recount3_code %||% NULL
}
# Study → recount3 GTEx tissue code (parent tissue). Mirrors the Python
# precompute's INDICATION_TO_GTEX_TISSUE. NULL means no clean GTEx match.
GTEX_TISSUE_BY_STUDY <- list(
  COAD = "COLON", READ = "COLON", LUAD = "LUNG", LUSC = "LUNG",
  BRCA = "BREAST", PAAD = "PANCREAS", SKCM = "SKIN", STAD = "STOMACH",
  PRAD = "PROSTATE", OV = "OVARY", KIRC = "KIDNEY", GBM = "BRAIN",
  LGG = "BRAIN", BLCA = "BLADDER", LIHC = "LIVER", CESC = "CERVIX_UTERI",
  ESCA = "ESOPHAGUS", HNSC = NULL
)
if (is.null(gtex_tissue)) {
  gtex_tissue <- GTEX_TISSUE_BY_STUDY[[tcga_studies[1]]]
}
message("[00_load_recount3] tcga_studies: ", paste(tcga_studies, collapse = ", "),
        " | gtex_tissue: ", gtex_tissue %||% "(none — cells C/D will be skipped)")

# --- staging dir + s3 helper ------------------------------------------------
tmpdir <- tempfile("00_load_recount3_")
dir.create(tmpdir, recursive = TRUE)
on.exit(unlink(tmpdir, recursive = TRUE), add = TRUE)

s3_get <- function(key, local) {
  uri <- paste0("s3://", bucket, "/", key)
  # capture combined output so a failed transfer surfaces the AWS error text;
  # stdout=FALSE + stderr=TRUE is an invalid combination in R (warns), so
  # capture stdout to a string and fold stderr into it.
  res <- suppressWarnings(system2("aws",
             c("s3", "cp", "--quiet", shQuote(uri), shQuote(local)),
             stdout = TRUE, stderr = TRUE))
  if (!file.exists(local) || file.size(local) == 0) {
    stop("aws s3 cp failed for ", uri, " :: ", paste(res, collapse = " "))
  }
  local
}

# --- Ensembl → HGNC map -----------------------------------------------------
message("[00_load_recount3] loading Ensembl-116 → HGNC map")
map_local <- s3_get(opts$`ensembl-map-s3`, file.path(tmpdir, "ensembl_map.tsv"))
ens_map <- data.table::fread(map_local, sep = "\t", header = TRUE,
                             showProgress = FALSE)
# columns: "Gene stable ID", "Gene stable ID version", "HGNC ID",
#          "HGNC symbol", "Gene name". Join on unversioned stable ID.
ens_map <- ens_map[!is.na(`HGNC symbol`) & `HGNC symbol` != "", ]
ens2hgnc <- setNames(ens_map$`HGNC symbol`, ens_map$`Gene stable ID`)
message("[00_load_recount3]   ", length(ens2hgnc), " Ensembl → HGNC mappings")

# --- gene_sums reader -------------------------------------------------------
# recount3 gene_sums: `##`-prefixed comment lines, then a header row starting
# "gene_id\t<sampleID>...", then one row per gene "ENSG....<ver>\t<counts>".
read_gene_sums <- function(cohort, code) {
  key <- sprintf("%s/%s/%s/gene_sums/%s.gene_sums.%s.G026.gz",
                 r3, cohort, code, cohort, code)
  local <- file.path(tmpdir, sprintf("%s.%s.gene_sums.gz", cohort, code))
  s3_get(key, local)
  message("[00_load_recount3]   reading gene_sums ", cohort, "/", code)
  # skip="gene_id" jumps past the ## comment lines to the header row.
  dt <- data.table::fread(cmd = paste("gzip -dc", shQuote(local)),
                          sep = "\t", header = TRUE, skip = "gene_id",
                          showProgress = FALSE)
  setnames(dt, 1, "gene_id")
  dt
}

read_metadata <- function(cohort, code) {
  key <- sprintf("%s/%s/%s/metadata/%s.%s.%s.MD.gz",
                 r3, cohort, code, cohort, cohort, code)
  local <- file.path(tmpdir, sprintf("%s.%s.MD.gz", cohort, code))
  s3_get(key, local)
  data.table::fread(cmd = paste("gzip -dc", shQuote(local)),
                    sep = "\t", header = TRUE, showProgress = FALSE,
                    colClasses = "character")
}

# --- collect TCGA (tumor + adjacent-normal) per study -----------------------
# recount3 TCGA gene_sums columns are gdc_file_id UUIDs (== external_id).
tcga_pieces <- list()
tcga_cols   <- list()  # per study: list(tumor=<ids>, normal=<ids>, tss=named vec)

for (study in tcga_studies) {
  gs <- read_gene_sums("tcga", study)
  md <- read_metadata("tcga", study)

  st_col  <- "gdc_cases.samples.sample_type"
  id_col  <- "gdc_file_id"
  tss_col <- "gdc_cases.tissue_source_site.code"
  # gdc_cases.submitter_id is the CASE (patient) barcode TCGA-XX-XXXX — the join
  # key to the subgroup-assignments product's `patient_id` column (subgroup
  # stratification, 2026-08-18). Molecular subgroups (MSI, CMS, ...) are
  # patient-level properties, so a patient-barcode join is both correct and
  # robust to the sample-vs-aliquot-barcode truncation the sample_id path risks.
  sub_col <- "gdc_cases.submitter_id"
  stopifnot(st_col %in% names(md), id_col %in% names(md))

  tumor_ids  <- md[get(st_col) == "Primary Tumor",        get(id_col)]
  normal_ids <- md[get(st_col) == "Solid Tissue Normal",  get(id_col)]
  tss_by_id  <- setNames(md[[tss_col]], md[[id_col]])
  # Patient-barcode-by-file-id map (NA vector when the column is absent, so the
  # loader never dies on a metadata schema change; the stratified driver then
  # simply finds no members and the whole-cohort emit is unaffected).
  submitter_by_id <- if (sub_col %in% names(md)) {
    setNames(md[[sub_col]], md[[id_col]])
  } else {
    message("[00_load_recount3]   WARNING: ", sub_col, " absent in ", study,
            " metadata — submitter_id column will be NA (subgroup join disabled)")
    setNames(rep(NA_character_, nrow(md)), md[[id_col]])
  }

  # Keep only ids that are actually columns in the gene_sums matrix.
  present  <- setdiff(names(gs), "gene_id")
  tumor_ids  <- intersect(tumor_ids,  present)
  normal_ids <- intersect(normal_ids, present)
  message(sprintf("[00_load_recount3]   %s: %d tumor + %d adjacent-normal (of %d cols)",
                  study, length(tumor_ids), length(normal_ids), length(present)))

  tcga_pieces[[study]] <- gs
  tcga_cols[[study]]   <- list(tumor = tumor_ids, normal = normal_ids,
                               tss = tss_by_id, submitter = submitter_by_id)
}

# --- GTEx (all normal) ------------------------------------------------------
gtex_gs <- NULL
gtex_ids <- character(0)
if (!is.null(gtex_tissue)) {
  gtex_gs <- read_gene_sums("gtex", gtex_tissue)
  gtex_md <- read_metadata("gtex", gtex_tissue)
  stopifnot("external_id" %in% names(gtex_md))
  gtex_ids <- intersect(gtex_md$external_id, setdiff(names(gtex_gs), "gene_id"))
  message(sprintf("[00_load_recount3]   GTEx %s: %d normal samples",
                  gtex_tissue, length(gtex_ids)))
}

# --- align all matrices on gene_id (inner join) -----------------------------
# All recount3 G026 matrices share the same gene set + order, but inner-join
# defensively in case a study's matrix differs.
all_mats <- tcga_pieces
if (!is.null(gtex_gs)) all_mats[["__gtex__"]] <- gtex_gs

common_genes <- Reduce(intersect, lapply(all_mats, function(m) m$gene_id))
message("[00_load_recount3] common genes across all matrices: ", length(common_genes))
stopifnot(length(common_genes) > 1000)

# Build the combined counts matrix + coldata.
col_blocks <- list()
coldata_rows <- list()

for (study in tcga_studies) {
  gs <- tcga_pieces[[study]]
  gs <- gs[match(common_genes, gene_id), ]
  ci <- tcga_cols[[study]]
  for (grp in c("tumor", "normal")) {
    ids <- ci[[grp]]
    if (!length(ids)) next
    if (!is.na(opts$limit)) ids <- head(ids, opts$limit)
    block <- as.matrix(gs[, ..ids])
    col_blocks[[paste0(study, "_", grp)]] <- block
    coldata_rows[[paste0(study, "_", grp)]] <- data.frame(
      sample_id = ids, group = grp, source = "TCGA",
      tcga_tss  = unname(ci$tss[ids]) %||% NA_character_,
      submitter_id = unname(ci$submitter[ids]),
      study     = study, stringsAsFactors = FALSE)
  }
}
if (!is.null(gtex_gs) && length(gtex_ids)) {
  gs <- gtex_gs[match(common_genes, gene_id), ]
  ids <- gtex_ids
  if (!is.na(opts$limit)) ids <- head(ids, opts$limit)
  col_blocks[["gtex_normal"]] <- as.matrix(gs[, ..ids])
  coldata_rows[["gtex_normal"]] <- data.frame(
    sample_id = ids, group = "normal", source = "GTEx",
    tcga_tss = NA_character_, submitter_id = NA_character_,
    study = paste0("GTEX_", gtex_tissue),
    stringsAsFactors = FALSE)
}

counts_mat <- do.call(cbind, col_blocks)
storage.mode(counts_mat) <- "integer"
rownames(counts_mat) <- common_genes
coldata <- do.call(rbind, coldata_rows)
rownames(coldata) <- coldata$sample_id
stopifnot(ncol(counts_mat) == nrow(coldata))

# --- QC: drop empty libraries (libsize == 0) --------------------------------
# recount3 ships a small number of failed sequencing/alignment libraries
# (e.g. GTEX-14BMU-1526-SM-5TDE6.1 in the COLON tissue file has libsize=0).
# These break every downstream normalization (DESeq2 size factors NA-out at
# assignment). Drop them at the load step so all downstream cells see a
# clean cohort.
lib_sizes <- colSums(counts_mat)
empty <- lib_sizes == 0
if (any(empty)) {
  message(sprintf("[00_load_recount3] dropping %d empty libraries (libsize == 0): %s",
                  sum(empty), paste(head(colnames(counts_mat)[empty], 5), collapse = ", ")))
  counts_mat <- counts_mat[, !empty, drop = FALSE]
  coldata    <- coldata[!empty, , drop = FALSE]
}

# --- map gene_id → HGNC symbol; collapse duplicates by sum ------------------
gene_stem <- sub("\\..*$", "", common_genes)
gene_symbol <- ens2hgnc[gene_stem]
keep <- !is.na(gene_symbol)
message(sprintf("[00_load_recount3] HGNC-mappable: %d/%d genes",
                sum(keep), length(common_genes)))
counts_mat  <- counts_mat[keep, , drop = FALSE]
gene_id_kept <- common_genes[keep]
gene_stem_kept <- gene_stem[keep]
gene_symbol <- gene_symbol[keep]

# Collapse multiple gene_ids → one gene_symbol by summing counts (tximport
# gene-level convention; matches 00_load_counts.R behaviour).
dup <- duplicated(gene_symbol) | duplicated(gene_symbol, fromLast = TRUE)
if (any(dup)) {
  message("[00_load_recount3]   collapsing ", sum(dup), " rows across ",
          length(unique(gene_symbol[dup])), " duplicate symbols (sum)")
  counts_mat <- rowsum(counts_mat, gene_symbol)
  storage.mode(counts_mat) <- "integer"
  rowdata <- data.frame(gene_symbol = rownames(counts_mat),
                        stringsAsFactors = FALSE)
  # keep first gene_id/stem seen per symbol for provenance
  first_idx <- !duplicated(gene_symbol)
  gi <- setNames(gene_id_kept[first_idx], gene_symbol[first_idx])
  gsm <- setNames(gene_stem_kept[first_idx], gene_symbol[first_idx])
  rowdata$gene_id   <- unname(gi[rowdata$gene_symbol])
  rowdata$gene_stem <- unname(gsm[rowdata$gene_symbol])
} else {
  rownames(counts_mat) <- gene_symbol
  rowdata <- data.frame(gene_symbol = gene_symbol, gene_id = gene_id_kept,
                        gene_stem = gene_stem_kept, stringsAsFactors = FALSE)
}

out <- list(
  counts   = counts_mat,
  coldata  = coldata,
  rowdata  = rowdata,
  metadata = list(
    substrate    = paste0("recount3/tcga-gtex-2023-01-04 (G026)"),
    tcga_studies = tcga_studies,
    gtex_tissue  = gtex_tissue,
    n_genes      = nrow(counts_mat),
    n_tumor      = sum(coldata$group == "tumor"),
    n_adjacent   = sum(coldata$group == "normal" & coldata$source == "TCGA"),
    n_gtex       = sum(coldata$group == "normal" & coldata$source == "GTEx"),
    gtex_available = !is.null(gtex_gs)
  )
)
saveRDS(out, opts$out)
message(sprintf(paste0("[00_load_recount3] wrote %s  (%d genes × %d samples; ",
                       "%d tumor, %d TCGA-adjacent, %d GTEx)"),
                opts$out, nrow(counts_mat), ncol(counts_mat),
                out$metadata$n_tumor, out$metadata$n_adjacent, out$metadata$n_gtex))
