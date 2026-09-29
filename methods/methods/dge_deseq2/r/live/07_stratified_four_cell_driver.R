#!/usr/bin/env Rscript
# 07_stratified_four_cell_driver.R — per-subgroup tumor-vs-normal sensitivity DEG.
#
# The emit-time half of unblocking the `tumor-vs-normal-selectivity` card for
# molecular subgroups (2026-08-18). It runs the SAME contrast as
# 06_four_cell_driver.R (cells A/C via _four_cell_lib.R) but restricts the
# TUMOR samples to each stratum's member set, then concatenates a tall
# per-gene x per-stratum sensitivity table.
#
# WHY normals stay whole-cohort: a molecular subgroup (MSI-H, CMS2, KRAS-mut, …)
# is a TUMOR property — there is no "MSI-H adjacent normal" or "MSI-H GTEx". So
# only the tumor arm is subset; the TCGA-adjacent (cell A) and GTEx (cell C)
# comparators are the same whole-cohort normals every stratum is contrasted
# against. This is exactly the biological question the card asks: "is the target
# tumor-selective WITHIN this molecular subgroup, against the shared normal
# baseline?" — and it keeps the per-stratum log2FC on the same scale as the
# whole-cohort product (same normals, same pipeline).
#
# JOIN: recount3 tumor samples carry coldata$submitter_id (TCGA patient barcode,
# TCGA-XX-XXXX). The subgroup-assignments parquet carries patient_id at the same
# grain. Membership = assignments[stratum_id == S & is_member == TRUE]$patient_id.
# A near-zero match rate for a non-empty member set is the id-convention-mismatch
# signature (mirrors subgroup_common.scoping.JoinCoverage) — we warn, not fail.
#
# Output: sensitivity_by_subgroup.parquet — the 06 sensitivity schema plus
#   stratum_id, subgroup_axis, subgroup_n_tumor (tumor members that survived the
#   recount3 join for this stratum), n_adjacent, n_gtex (shared, per-stratum
#   constant) — one block of gene rows per stratum. Plus provenance.yaml.

suppressPackageStartupMessages({
  library(optparse)
  library(DESeq2)
  library(apeglm)
  library(sva)
  library(BiocParallel)
  library(arrow)
})

.args <- commandArgs(trailingOnly = FALSE)
.here <- dirname(normalizePath(sub("^--file=", "", .args[grepl("^--file=", .args)][1])))
source(file.path(.here, "_four_cell_lib.R"))
# S3b (#702): per-contrast QC report bundle (figures/ + metrics row), emitted
# per stratum. Pure functions of the fit's attributes; side-effect-free.
source(file.path(.here, "_qc_figures.R"))

option_list <- list(
  make_option("--in", type = "character", dest = "in_path",
              help = "Output of 00_load_recount3.R (.rds) — must carry coldata$submitter_id"),
  make_option("--assignments", type = "character",
              help = "subgroup_assignments.parquet (sample_id, patient_id, stratum_id, is_member)"),
  make_option("--axis", type = "character",
              help = "Subgroup axis label recorded in the product (e.g. msi_status)"),
  make_option("--strata", type = "character",
              help = "Comma-separated stratum_ids to emit (e.g. MSI_H,MSS)"),
  make_option("--out-dir", type = "character",
              help = "Directory for sensitivity_by_subgroup.parquet + provenance"),
  make_option("--min-normals", type = "integer", default = 3,
              help = "Minimum samples per group for a cell to run (DESeq2 floor)."),
  make_option("--min-subgroup-tumor", type = "integer", default = 10,
              help = "Minimum tumor members for a stratum to be emitted at all."),
  make_option("--threads", type = "integer", default = 4)
)
opts <- parse_args(OptionParser(option_list = option_list))
stopifnot(!is.null(opts$in_path), !is.null(opts$assignments),
          !is.null(opts$axis), !is.null(opts$strata), !is.null(opts$`out-dir`))
dir.create(opts$`out-dir`, showWarnings = FALSE, recursive = TRUE)
register(MulticoreParam(workers = opts$threads))

options(warn = 1)
flog <- function(msg) {
  writeLines(paste0("[", format(Sys.time(), "%H:%M:%S"), "] ", msg)); flush(stdout())
}

dat     <- readRDS(opts$in_path)
counts  <- dat$counts
coldata <- dat$coldata
min_n   <- opts$`min-normals`
strata  <- trimws(strsplit(opts$strata, ",")[[1]])

# Fail-loud output-QC panel (S3a #701): the same pan-cancer tumor-UP
# global-sign-inversion tripwire the whole-cohort driver (06) uses. Cells A/C
# are tumor-vs-normal here too (only the tumor arm is subset per stratum), so
# the panel applies unchanged per stratum.
qc_indication <- dat$metadata$tcga_studies
tumor_panel   <- marker_panel_for(qc_indication)

if (!"submitter_id" %in% names(coldata)) {
  stop("bundle coldata has no `submitter_id` column — re-run 00_load_recount3.R ",
       "with the 2026-08-18 patient-barcode patch before stratifying.")
}

# --- whole-cohort partitions (normals are shared across strata) -------------
is_tumor    <- coldata$group == "tumor"
is_adjacent <- coldata$group == "normal" & coldata$source == "TCGA"
is_gtex     <- coldata$group == "normal" & coldata$source == "GTEx"

all_tumor_ids <- rownames(coldata)[is_tumor]
adjacent_ids  <- rownames(coldata)[is_adjacent]
gtex_ids      <- rownames(coldata)[is_gtex]
flog(sprintf("whole-cohort partitions: %d tumor | %d TCGA-adjacent | %d GTEx",
             length(all_tumor_ids), length(adjacent_ids), length(gtex_ids)))

# Patient barcode per recount3 tumor sample (TCGA-XX-XXXX). Defensive truncation
# to the first three barcode fields so a longer submitter form still joins.
trunc_barcode <- function(x) {
  vapply(strsplit(x, "-"), function(p) paste(head(p, 3), collapse = "-"), character(1))
}
tumor_patient <- trunc_barcode(coldata[all_tumor_ids, "submitter_id"])
names(tumor_patient) <- all_tumor_ids

# --- load subgroup assignments ----------------------------------------------
assign <- as.data.frame(arrow::read_parquet(opts$assignments))
stopifnot(all(c("stratum_id", "is_member") %in% names(assign)))
member_key <- if ("patient_id" %in% names(assign) &&
                  any(!is.na(assign$patient_id))) "patient_id" else "sample_id"
flog(sprintf("assignments: %d rows; joining recount3 patient barcode -> assignments$%s",
             nrow(assign), member_key))

members_for <- function(stratum) {
  m <- assign[assign$stratum_id == stratum &
              !is.na(assign$is_member) & assign$is_member == TRUE, member_key]
  unique(trunc_barcode(as.character(m)))
}

# --- per-stratum four-cell fit ----------------------------------------------
run_stratum <- function(stratum) {
  members <- members_for(stratum)
  strat_tumor_ids <- all_tumor_ids[tumor_patient %in% members]
  n_members <- length(members)
  n_matched <- length(strat_tumor_ids)
  match_rate <- if (n_members) n_matched / n_members else NA_real_

  flog(sprintf("stratum %s: %d assignment members -> %d recount3 tumor samples matched (%.0f%%)",
               stratum, n_members, n_matched,
               if (is.na(match_rate)) 0 else 100 * match_rate))
  # id-convention-mismatch guard (JoinCoverage analog): non-empty member set that
  # matches near-zero recount3 tumors is a barcode-grain mismatch, not an empty
  # stratum. 0.05 mirrors subgroup_common.scoping._MATCH_RATE_FLOOR.
  if (n_members > 0 && !is.na(match_rate) && match_rate < 0.05) {
    warning(sprintf(paste0("stratum '%s': only %d/%d members (%.1f%%) matched recount3 ",
                           "tumor barcodes — likely a sample-id-convention mismatch, not an ",
                           "empty stratum. Check the assignments patient_id grain."),
                    stratum, n_matched, n_members, 100 * match_rate))
  }
  if (n_matched < opts$`min-subgroup-tumor`) {
    flog(sprintf("stratum %s SKIPPED — %d tumor members < --min-subgroup-tumor=%d",
                 stratum, n_matched, opts$`min-subgroup-tumor`))
    return(NULL)
  }

  # Per-stratum cell caches are namespaced by stratum so strata never collide.
  strat_dir <- file.path(opts$`out-dir`, paste0("_strat_", stratum))
  dir.create(strat_dir, showWarnings = FALSE, recursive = TRUE)

  cellA <- cellC <- NULL
  if (length(adjacent_ids) >= min_n) {
    ids <- c(strat_tumor_ids, adjacent_ids)
    cellA <- run_cell("A", counts[, ids], coldata[ids, ], strat_dir, min_n, flog,
                      qc_panel = tumor_panel, qc_indication = qc_indication)
  } else {
    flog(sprintf("stratum %s: cell A SKIPPED — TCGA adjacent < %d", stratum, min_n))
  }
  if (length(gtex_ids) >= min_n) {
    ids <- c(strat_tumor_ids, gtex_ids)
    cellC <- run_cell("C", counts[, ids], coldata[ids, ], strat_dir, min_n, flog,
                      qc_panel = tumor_panel, qc_indication = qc_indication)
  } else {
    flog(sprintf("stratum %s: cell C SKIPPED — GTEx normal < %d", stratum, min_n))
  }

  cells <- Filter(Negate(is.null), list(A = cellA, C = cellC))
  if (length(cells) == 0) {
    flog(sprintf("stratum %s SKIPPED — no cells ran", stratum))
    return(NULL)
  }

  # Per-contrast QC bundles (S3b #702) for this stratum, under
  # <out-dir>/_strat_<stratum>/qc/<cell>/. indication carries the stratum so the
  # cross-indication index disambiguates strata.
  qc_root <- file.path(strat_dir, "qc")
  dir.create(qc_root, showWarnings = FALSE, recursive = TRUE)
  ind_label  <- paste0(paste(dat$metadata$tcga_studies, collapse = "+"), ":", stratum)
  subs_label <- dat$metadata$substrate %||% "recount3"
  qc_rows <- Filter(Negate(is.null), lapply(names(cells), function(lab) {
    emit_qc_bundle(cells[[lab]], file.path(qc_root, lab), lab,
                   indication = ind_label, substrate = subs_label, emit = flog)
  }))
  if (length(qc_rows)) {
    write.csv(do.call(rbind, qc_rows), file.path(qc_root, "qc_summary.csv"),
              row.names = FALSE)
  }

  sens <- assemble_sensitivity(cells)
  sens$stratum_id       <- stratum
  sens$subgroup_axis    <- opts$axis
  sens$subgroup_n_tumor <- n_matched
  sens$n_adjacent       <- length(adjacent_ids)
  sens$n_gtex           <- length(gtex_ids)
  flog(sprintf("stratum %s DONE — %d genes; cells=%s; n_tumor=%d",
               stratum, nrow(sens), paste(names(cells), collapse = ""), n_matched))
  list(sens = sens, cells_ran = names(cells), n_tumor = n_matched)
}

results <- lapply(strata, run_stratum)
names(results) <- strata
ok <- Filter(Negate(is.null), results)
if (length(ok) == 0) stop("No strata produced a fit — check members / sample availability.")

# --- concat + write ---------------------------------------------------------
# Union columns across strata (a stratum where cell C was skipped lacks those
# log2fc/padj cols); rbind after aligning to the full column set.
sens_list <- lapply(ok, function(x) x$sens)
all_cols <- Reduce(union, lapply(sens_list, names))
sens_list <- lapply(sens_list, function(df) {
  miss <- setdiff(all_cols, names(df))
  for (m in miss) df[[m]] <- NA
  df[, all_cols, drop = FALSE]
})
combined <- do.call(rbind, sens_list)
# Sort by stratum then gene so the parquet groups per stratum (query_optimization).
combined <- combined[order(combined$stratum_id, combined$gene_symbol), ]

out_path <- file.path(opts$`out-dir`, "sensitivity_by_subgroup.parquet")
arrow::write_parquet(combined, out_path, chunk_size = 1024,
                     compression = "snappy", use_dictionary = TRUE)
flog(sprintf("wrote %s (%d rows across %d strata: %s)",
             out_path, nrow(combined), length(ok), paste(names(ok), collapse = ", ")))

prov <- list(
  substrate       = dat$metadata$substrate,
  tcga_studies    = dat$metadata$tcga_studies,
  gtex_tissue     = dat$metadata$gtex_tissue,
  subgroup_axis   = opts$axis,
  assignments     = basename(opts$assignments),
  member_key      = member_key,
  strata_emitted  = names(ok),
  strata_requested = strata,
  n_tumor_by_stratum = setNames(lapply(ok, function(x) x$n_tumor), names(ok)),
  cells_ran_by_stratum = setNames(lapply(ok, function(x) x$cells_ran), names(ok)),
  n_adjacent      = length(adjacent_ids),
  n_gtex          = length(gtex_ids),
  min_normals     = min_n,
  min_subgroup_tumor = opts$`min-subgroup-tumor`,
  deseq2_version  = as.character(packageVersion("DESeq2")),
  apeglm_version  = as.character(packageVersion("apeglm")),
  sva_version     = as.character(packageVersion("sva")),
  schema_version  = "1"
)
writeLines(yaml::as.yaml(prov), file.path(opts$`out-dir`, "provenance_by_subgroup.yaml"))
flog("07_stratified_four_cell_driver done.")
