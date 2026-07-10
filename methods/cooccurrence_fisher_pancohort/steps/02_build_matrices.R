#!/usr/bin/env Rscript
# Stage 02 — build per-cohort binary alteration matrices from GENIE +
# combine with MC3 matrices from stage 00.
#
# Reads:
#   <work_dir>/mc3_binary_matrix.rds       (from stage 00)
#   S3: genie-public-v19-0/data_mutations_extended.txt (1.12 GB TSV)
#   S3: genie-public-v19-0/data_clinical_sample.txt (~40 MB — for CANCER_TYPE)
#
# Writes:
#   <work_dir>/matrices_by_cohort.rds — list<cohort_label, sparseMatrix>
#     cohort_label format: "MC3:<TCGA-code>" | "GENIE:<cancer_type>" | "PANCAN"
#
# Cohort labeling (v1 discipline):
#   Per-source cohorts kept SEPARATE. TCGA and GENIE use different
#   OncoTree hierarchies; mapping between them is a research question
#   itself. v1 emits both per-source cohorts + a pan-cohort union;
#   downstream stages decide which comparisons to run.
#
# Nonsyn filter applied to GENIE mutations (same set as MC3 stage 00).

options(error = function() { traceback(3); quit(status = 1) })

suppressPackageStartupMessages({
  library(optparse)
  library(data.table)
  library(Matrix)
})

# --- CLI ---
option_list <- list(
  make_option("--work-dir", type = "character", default = NULL)
)
opts <- parse_args(OptionParser(option_list = option_list))
if (is.null(opts$`work-dir`)) stop("--work-dir required")
work_dir <- opts$`work-dir`

# --- Config ---
S3_BUCKET <- "onc-compbio"
GENIE_PREFIX <- "data-catalog/sources/synapse/genie-public-v19-0"
LOCAL_MUT <- file.path(work_dir, "genie_mutations.txt")
LOCAL_SAMPLE <- file.path(work_dir, "genie_clinical_sample.txt")

NONSYN_CLASSES <- c(
  "Missense_Mutation", "Nonsense_Mutation",
  "Frame_Shift_Del", "Frame_Shift_Ins",
  "Splice_Site", "Nonstop_Mutation", "Translation_Start_Site"
)

# --- Load MC3 matrices (from stage 00) ---
mc3_rds <- file.path(work_dir, "mc3_binary_matrix.rds")
if (!file.exists(mc3_rds)) stop("stage 00 output missing: ", mc3_rds,
                                 " — run 00_load_mc3.R first")
message("[02_build_matrices] loading MC3 matrices from stage 00 ...")
mc3_matrices <- readRDS(mc3_rds)
mc3_cohorts <- names(mc3_matrices)
message(sprintf("[02_build_matrices]   loaded %d MC3 cohorts: %s",
                length(mc3_cohorts), paste(head(mc3_cohorts, 10), collapse=", ")))

# --- Fetch GENIE files ---
Sys.setenv(AWS_PROFILE = "cbg")
if (!file.exists(LOCAL_MUT) || file.info(LOCAL_MUT)$size < 1e9) {
  message("[02_build_matrices] downloading GENIE data_mutations_extended.txt (1.12 GB) ...")
  system(sprintf(
    "aws s3 cp s3://%s/%s/data_mutations_extended.txt %s --profile cbg",
    S3_BUCKET, GENIE_PREFIX, LOCAL_MUT
  ))
}
if (!file.exists(LOCAL_SAMPLE) || file.info(LOCAL_SAMPLE)$size < 1e7) {
  message("[02_build_matrices] downloading GENIE data_clinical_sample.txt ...")
  system(sprintf(
    "aws s3 cp s3://%s/%s/data_clinical_sample.txt %s --profile cbg",
    S3_BUCKET, GENIE_PREFIX, LOCAL_SAMPLE
  ))
}

# --- Parse clinical sample metadata (has CANCER_TYPE per SAMPLE_ID) ---
# GENIE cBioPortal clinical file has 5 comment header lines. Line 1-4 are
# human-readable label rows (#Patient Identifier etc.); line 5 is the
# CANONICAL machine-readable header with underscore-cased column names
# (PATIENT_ID, SAMPLE_ID, CANCER_TYPE, ...). skip=4 to reach that header.
t0 <- proc.time()
message("[02_build_matrices] parsing GENIE clinical_sample.txt ...")
clin <- fread(LOCAL_SAMPLE, sep = "\t", header = TRUE, skip = 4, showProgress = FALSE)
required_cols <- c("SAMPLE_ID", "CANCER_TYPE")
if (!all(required_cols %in% names(clin))) {
  stop("Missing expected columns in GENIE clinical: ", paste(required_cols, collapse=","),
       "; got: ", paste(names(clin), collapse=","))
}
clin <- clin[, .(SAMPLE_ID, CANCER_TYPE)]
clin[, CANCER_TYPE := ifelse(is.na(CANCER_TYPE) | CANCER_TYPE == "", "Unknown", CANCER_TYPE)]
message(sprintf("[02_build_matrices]   loaded %s samples with %d unique CANCER_TYPE labels (%.1fs)",
                formatC(nrow(clin), big.mark=","), length(unique(clin$CANCER_TYPE)),
                (proc.time() - t0)["elapsed"]))

# --- Parse mutations ---
t0 <- proc.time()
message("[02_build_matrices] parsing GENIE data_mutations_extended.txt (1.12 GB) ...")
mut <- fread(
  LOCAL_MUT,
  sep = "\t",
  header = TRUE,
  select = c("Hugo_Symbol", "Tumor_Sample_Barcode", "Variant_Classification"),
  showProgress = FALSE,
  na.strings = c("", "NA", "N/A", ".", "-"),
  skip = "Hugo_Symbol"  # skip comment lines if any
)
message(sprintf("[02_build_matrices]   loaded %s mutation rows in %.1fs",
                formatC(nrow(mut), big.mark=","), (proc.time() - t0)["elapsed"]))

# --- Filter nonsyn ---
n_before <- nrow(mut)
mut <- mut[Variant_Classification %in% NONSYN_CLASSES]
message(sprintf("[02_build_matrices]   nonsyn filter: %s -> %s rows",
                formatC(n_before, big.mark=","),
                formatC(nrow(mut), big.mark=",")))

# --- Join to cancer type ---
setnames(mut, "Tumor_Sample_Barcode", "SAMPLE_ID")
mut <- merge(mut, clin, by = "SAMPLE_ID", all.x = TRUE)
mut[is.na(CANCER_TYPE), CANCER_TYPE := "Unknown"]

# Dedup (cohort, sample, gene) — one presence per triple
mut_unique <- unique(mut[, .(CANCER_TYPE, SAMPLE_ID, Hugo_Symbol)])
message(sprintf("[02_build_matrices]   unique (cohort, sample, gene) tuples: %s",
                formatC(nrow(mut_unique), big.mark=",")))

# --- Build per-cohort GENIE matrices ---
# Cohorts with < 50 samples are skipped (too small for meaningful stats)
COHORT_MIN_SAMPLES <- 50
genie_matrices <- list()
cohort_sample_counts <- mut_unique[, .(n_samples = uniqueN(SAMPLE_ID)), by = CANCER_TYPE]
setorder(cohort_sample_counts, -n_samples)
message("[02_build_matrices]   top-15 GENIE cohorts by sample count:")
print(head(cohort_sample_counts, 15))

for (co in cohort_sample_counts[n_samples >= COHORT_MIN_SAMPLES]$CANCER_TYPE) {
  sub <- mut_unique[CANCER_TYPE == co]
  samples <- sort(unique(sub$SAMPLE_ID))
  genes <- sort(unique(sub$Hugo_Symbol))
  sample_idx <- match(sub$SAMPLE_ID, samples)
  gene_idx <- match(sub$Hugo_Symbol, genes)
  m <- sparseMatrix(
    i = sample_idx, j = gene_idx, x = 1L,
    dims = c(length(samples), length(genes)),
    dimnames = list(samples, genes)
  )
  m@x <- pmin(m@x, 1L)
  # Key format: "GENIE:<cancer_type>"
  genie_matrices[[paste0("GENIE:", co)]] <- m
}
message(sprintf("[02_build_matrices]   %d GENIE cohorts (>=%d samples)",
                length(genie_matrices), COHORT_MIN_SAMPLES))

# --- Add a GENIE PANCAN (union across all samples/genes) ---
genie_all_samples <- sort(unique(mut_unique$SAMPLE_ID))
genie_all_genes <- sort(unique(mut_unique$Hugo_Symbol))
sample_idx <- match(mut_unique$SAMPLE_ID, genie_all_samples)
gene_idx <- match(mut_unique$Hugo_Symbol, genie_all_genes)
genie_pancan <- sparseMatrix(
  i = sample_idx, j = gene_idx, x = 1L,
  dims = c(length(genie_all_samples), length(genie_all_genes)),
  dimnames = list(genie_all_samples, genie_all_genes)
)
genie_pancan@x <- pmin(genie_pancan@x, 1L)
genie_matrices[["GENIE:PANCAN"]] <- genie_pancan

# --- Rekey MC3 matrices with "MC3:" prefix ---
mc3_rekeyed <- setNames(
  mc3_matrices,
  paste0("MC3:", names(mc3_matrices))
)

# --- Combine: per-source cohorts (v1 discipline: no cross-source alignment) ---
all_matrices <- c(mc3_rekeyed, genie_matrices)

# Log summary
message(sprintf("[02_build_matrices]   TOTAL cohorts: %d (%d MC3 + %d GENIE)",
                length(all_matrices), length(mc3_rekeyed), length(genie_matrices)))

# --- Save ---
out_path <- file.path(work_dir, "matrices_by_cohort.rds")
saveRDS(all_matrices, out_path)
message(sprintf("[02_build_matrices] wrote %s (%.1f MB)",
                out_path, file.info(out_path)$size / 1e6))
message(sprintf("[02_build_matrices] DONE (%.1fs total)",
                (proc.time() - t0)["elapsed"]))
