#!/usr/bin/env Rscript
# Stage 00 — parse TCGA MC3 MAF to binary alteration matrix.
#
# Reads:
#   s3://onc-compbio/data-catalog/sources/synapse/tcga-mc3-public/
#     mc3.v0.2.8.PUBLIC.maf.gz (753 MB gz)
#
# Writes:
#   <work_dir>/mc3_binary_matrix.rds
#   <work_dir>/mc3_sample_cohort_map.rds
#
# Filter:
#   Variant_Classification %in% c('Missense_Mutation', 'Nonsense_Mutation',
#     'Frame_Shift_Del', 'Frame_Shift_Ins', 'Splice_Site',
#     'Nonstop_Mutation', 'Translation_Start_Site')
#   (nonsynonymous coding events; drops silent/UTR/intron/intergenic)
#
# Cohort labeling:
#   TCGA study code extracted from Tumor_Sample_Barcode (TCGA-<TSS>-...)
#   via the sample-to-project mapping — but simpler v1 uses the
#   `project_short_name` column if present, else derives from barcode.

options(warn = 2, error = function() { traceback(3); quit(status = 1) })

suppressPackageStartupMessages({
  library(optparse)
  library(data.table)
})

# --- CLI ---
option_list <- list(
  make_option("--work-dir", type = "character", default = NULL,
              help = "Working directory for intermediate .rds files")
)
opts <- parse_args(OptionParser(option_list = option_list))
if (is.null(opts$`work-dir`)) stop("--work-dir required")
work_dir <- opts$`work-dir`
dir.create(work_dir, recursive = TRUE, showWarnings = FALSE)

# --- Config ---
S3_BUCKET <- "onc-compbio"
S3_KEY <- "data-catalog/sources/synapse/tcga-mc3-public/mc3.v0.2.8.PUBLIC.maf.gz"
LOCAL_MAF <- file.path(work_dir, "mc3.v0.2.8.PUBLIC.maf.gz")

NONSYN_CLASSES <- c(
  "Missense_Mutation", "Nonsense_Mutation",
  "Frame_Shift_Del", "Frame_Shift_Ins",
  "Splice_Site", "Nonstop_Mutation", "Translation_Start_Site"
)

# --- Fetch MC3 MAF from S3 (idempotent local cache) ---
if (!file.exists(LOCAL_MAF) || file.info(LOCAL_MAF)$size < 1e8) {
  message("[00_load_mc3] downloading MC3 MAF from S3...")
  Sys.setenv(AWS_PROFILE = "cbg")
  cmd <- sprintf(
    "aws s3 cp s3://%s/%s %s --profile cbg",
    S3_BUCKET, S3_KEY, LOCAL_MAF
  )
  system(cmd, intern = FALSE)
  if (!file.exists(LOCAL_MAF)) {
    stop("MC3 download failed. Check AWS_PROFILE=cbg + S3 access.")
  }
} else {
  message("[00_load_mc3] using cached MC3 MAF at ", LOCAL_MAF)
}

# --- Read MC3 MAF with data.table::fread ---
# MC3 v0.2.8 does NOT have `project_short_name` — cohort labeling
# derives from Tumor_Sample_Barcode's TSS (Tissue Source Site) code
# via the standard TCGA barcode format:
#   TCGA-<TSS>-<Participant>-<Sample>-<Portion>-<Plate>-<Center>
# Different TSS codes belong to the same TCGA study (e.g., BRCA has
# TSS codes A2, AN, AR, ...). Map TSS -> study via a builtin lookup.
t0 <- proc.time()
message("[00_load_mc3] reading MC3 MAF (753 MB gz) with data.table::fread ...")
mc3 <- fread(
  LOCAL_MAF,
  sep = "\t",
  header = TRUE,
  select = c(
    "Hugo_Symbol",
    "Tumor_Sample_Barcode",
    "Variant_Classification"
  ),
  showProgress = FALSE,
  na.strings = c("", "NA", "N/A", ".", "-")
)
message(sprintf("[00_load_mc3]   loaded %s rows in %.1fs",
                formatC(nrow(mc3), big.mark = ","), (proc.time() - t0)["elapsed"]))

# --- Filter to nonsynonymous coding events ---
n_before <- nrow(mc3)
mc3 <- mc3[Variant_Classification %in% NONSYN_CLASSES]
message(sprintf("[00_load_mc3]   nonsyn filter: %s -> %s rows (%.1f%% retained)",
                formatC(n_before, big.mark = ","),
                formatC(nrow(mc3), big.mark = ","),
                100 * nrow(mc3) / n_before))

# --- TSS-to-study mapping (canonical TCGA table) ---
# Source: https://gdc.cancer.gov/resources-tcga-users/tcga-code-tables/tissue-source-site-codes
# Truncated to studies with meaningful mutation counts in MC3.
TSS_TO_STUDY <- c(
  "02"="GBM", "06"="GBM", "12"="GBM", "14"="GBM", "16"="GBM", "19"="GBM",
  "26"="GBM", "27"="GBM", "28"="GBM", "32"="GBM", "41"="GBM", "74"="GBM",
  "76"="GBM", "81"="GBM", "87"="GBM",
  "08"="SARC", "3B"="SARC", "K1"="SARC", "MB"="SARC", "SI"="SARC",
  "09"="OV", "10"="OV", "13"="OV", "20"="OV", "23"="OV", "24"="OV",
  "25"="OV", "29"="OV", "30"="OV", "31"="OV", "36"="OV", "3P"="OV",
  "57"="OV", "58"="OV", "59"="OV", "61"="OV", "63"="OV", "OI"="OV",
  "OY"="OV",
  "18"="LUSC", "21"="LUSC", "22"="LUSC", "33"="LUSC", "34"="LUSC",
  "39"="LUSC", "43"="LUSC", "51"="LUSC", "52"="LUSC", "56"="LUSC",
  "60"="LUSC", "63"="LUSC", "66"="LUSC", "68"="LUSC", "6A"="LUSC",
  "77"="LUSC", "79"="LUSC", "85"="LUSC", "90"="LUSC", "94"="LUSC",
  "96"="LUSC", "98"="LUSC", "L3"="LUSC", "LA"="LUSC", "MF"="LUSC",
  "NC"="LUSC", "NK"="LUSC", "O1"="LUSC", "O2"="LUSC", "XC"="LUSC",
  "17"="LUAD", "35"="LUAD", "38"="LUAD", "44"="LUAD", "49"="LUAD",
  "50"="LUAD", "53"="LUAD", "55"="LUAD", "62"="LUAD", "64"="LUAD",
  "67"="LUAD", "69"="LUAD", "71"="LUAD", "73"="LUAD", "75"="LUAD",
  "78"="LUAD", "80"="LUAD", "83"="LUAD", "86"="LUAD", "91"="LUAD",
  "93"="LUAD", "95"="LUAD", "97"="LUAD", "99"="LUAD", "J2"="LUAD",
  "L4"="LUAD", "L9"="LUAD", "MN"="LUAD", "MP"="LUAD", "NB"="LUAD",
  "NJ"="LUAD", "S2"="LUAD", "T6"="LUAD",
  "37"="LGG", "CS"="LGG", "DB"="LGG", "DH"="LGG", "DU"="LGG",
  "E1"="LGG", "F6"="LGG", "FG"="LGG", "FN"="LGG", "HT"="LGG",
  "HW"="LGG", "IK"="LGG", "P5"="LGG", "QH"="LGG", "R8"="LGG",
  "RY"="LGG", "S9"="LGG", "TM"="LGG", "TQ"="LGG", "VM"="LGG",
  "VV"="LGG", "VW"="LGG", "WH"="LGG", "WY"="LGG",
  "A1"="BRCA", "A2"="BRCA", "A7"="BRCA", "A8"="BRCA", "AC"="BRCA",
  "AN"="BRCA", "AO"="BRCA", "AQ"="BRCA", "AR"="BRCA", "B6"="BRCA",
  "BH"="BRCA", "C8"="BRCA", "D8"="BRCA", "E2"="BRCA", "E9"="BRCA",
  "EW"="BRCA", "GI"="BRCA", "GM"="BRCA", "HN"="BRCA", "JL"="BRCA",
  "LD"="BRCA", "LL"="BRCA", "LQ"="BRCA", "MS"="BRCA", "OL"="BRCA",
  "PE"="BRCA", "PL"="BRCA", "S3"="BRCA", "UL"="BRCA", "UU"="BRCA",
  "V7"="BRCA", "W8"="BRCA", "WT"="BRCA", "XX"="BRCA", "Z7"="BRCA",
  "3L"="COAD", "4N"="COAD", "4T"="COAD", "5M"="COAD", "A6"="COAD",
  "AA"="COAD", "AD"="COAD", "AM"="COAD", "AU"="COAD", "AY"="COAD",
  "AZ"="COAD", "CA"="COAD", "CK"="COAD", "CM"="COAD", "D5"="COAD",
  "DM"="COAD", "F4"="COAD", "G4"="COAD", "NH"="COAD", "QG"="COAD",
  "QL"="COAD", "RU"="COAD", "SS"="COAD", "T9"="COAD", "WS"="COAD",
  "AF"="READ", "AG"="READ", "AH"="READ", "BM"="READ", "CI"="READ",
  "CL"="READ", "DC"="READ", "DT"="READ", "DY"="READ", "EF"="READ",
  "EI"="READ", "F5"="READ", "G5"="READ",
  "3C"="SKCM", "BF"="SKCM", "D3"="SKCM", "D9"="SKCM", "DA"="SKCM",
  "EB"="SKCM", "EE"="SKCM", "ER"="SKCM", "FR"="SKCM", "FS"="SKCM",
  "FW"="SKCM", "GF"="SKCM", "GN"="SKCM", "HR"="SKCM", "IG"="SKCM",
  "OD"="SKCM", "QB"="SKCM", "RP"="SKCM", "W3"="SKCM", "WE"="SKCM",
  "XV"="SKCM", "Z2"="SKCM",
  # Additional major studies:
  "05"="LAML", "AB"="LAML",
  "40"="KIRC", "42"="KIRC", "48"="KIRC", "54"="KIRC", "70"="KIRC",
  "82"="KIRC", "84"="KIRC", "89"="KIRC", "9L"="KIRC", "A3"="KIRC",
  "AK"="KIRC", "AS"="KIRC", "B0"="KIRC", "B2"="KIRC", "B4"="KIRC",
  "B8"="KIRC", "BP"="KIRC", "CB"="KIRC", "CJ"="KIRC", "CW"="KIRC",
  "CZ"="KIRC", "DV"="KIRC", "EU"="KIRC", "G6"="KIRC", "G7"="KIRC",
  "GK"="KIRC", "GL"="KIRC", "MM"="KIRC", "MW"="KIRC", "P4"="KIRC",
  "T7"="KIRC",
  "IB"="PAAD", "3A"="PAAD", "F2"="PAAD", "FB"="PAAD", "H6"="PAAD",
  "HV"="PAAD", "HZ"="PAAD", "IS"="PAAD", "L1"="PAAD", "LB"="PAAD",
  "M8"="PAAD", "OE"="PAAD", "PZ"="PAAD", "Q3"="PAAD", "RB"="PAAD",
  "RL"="PAAD", "RV"="PAAD", "S4"="PAAD", "US"="PAAD", "XD"="PAAD",
  "XN"="PAAD", "YB"="PAAD", "YH"="PAAD", "YY"="PAAD", "Z5"="PAAD"
)

# Extract TSS = chars 6-7 of Tumor_Sample_Barcode
# Format: TCGA-XX-YYYY-...
mc3[, TSS := substr(Tumor_Sample_Barcode, 6, 7)]
mc3[, cohort := TSS_TO_STUDY[TSS]]
mc3[is.na(cohort) | cohort == "", cohort := "OTHER_TSS"]
message(sprintf("[00_load_mc3]   TSS-to-study mapping: %d studies + %d rows with unmapped TSS",
                length(unique(mc3[cohort != "OTHER_TSS"]$cohort)),
                sum(mc3$cohort == "OTHER_TSS")))

# --- Build binary sample x gene matrix (per cohort + PANCAN) ---
# For each unique (sample, gene) — if any nonsyn variant, 1 else 0.
# Store per-cohort matrices; a PANCAN pooled matrix is the union.
# Using sparse Matrix to keep memory bounded (~10k samples × ~20k genes).

suppressPackageStartupMessages({
  library(Matrix)
})

# Deduplicate to unique (cohort, sample, gene)
mc3_unique <- unique(mc3[, .(cohort, Tumor_Sample_Barcode, Hugo_Symbol)])
message(sprintf("[00_load_mc3]   unique (cohort, sample, gene) tuples: %s",
                formatC(nrow(mc3_unique), big.mark = ",")))

# Build matrices per cohort
cohorts <- sort(unique(mc3_unique$cohort))
message(sprintf("[00_load_mc3]   %d TCGA cohorts: %s", length(cohorts),
                paste(cohorts, collapse = ", ")))

matrix_by_cohort <- list()
sample_cohort_map <- data.table(sample = character(), cohort = character())

for (co in cohorts) {
  sub <- mc3_unique[cohort == co]
  samples <- sort(unique(sub$Tumor_Sample_Barcode))
  genes <- sort(unique(sub$Hugo_Symbol))
  sample_idx <- match(sub$Tumor_Sample_Barcode, samples)
  gene_idx <- match(sub$Hugo_Symbol, genes)
  # Build sparse binary matrix
  m <- sparseMatrix(
    i = sample_idx,
    j = gene_idx,
    x = 1L,
    dims = c(length(samples), length(genes)),
    dimnames = list(samples, genes)
  )
  # Deduplicate: any nonzero -> 1
  m@x <- pmin(m@x, 1L)
  matrix_by_cohort[[co]] <- m
  sample_cohort_map <- rbind(
    sample_cohort_map,
    data.table(sample = samples, cohort = co)
  )
  message(sprintf(
    "[00_load_mc3]     %s: %d samples x %d genes (%s nonzero cells)",
    co, length(samples), length(genes),
    formatC(length(m@x), big.mark = ",")
  ))
}

# --- Also build PANCAN matrix (union across cohorts) ---
all_samples <- sort(unique(mc3_unique$Tumor_Sample_Barcode))
all_genes <- sort(unique(mc3_unique$Hugo_Symbol))
sample_idx <- match(mc3_unique$Tumor_Sample_Barcode, all_samples)
gene_idx <- match(mc3_unique$Hugo_Symbol, all_genes)
pancan <- sparseMatrix(
  i = sample_idx, j = gene_idx, x = 1L,
  dims = c(length(all_samples), length(all_genes)),
  dimnames = list(all_samples, all_genes)
)
pancan@x <- pmin(pancan@x, 1L)
matrix_by_cohort[["PANCAN"]] <- pancan
message(sprintf(
  "[00_load_mc3]   PANCAN: %d samples x %d genes",
  length(all_samples), length(all_genes)
))

# --- Save ---
out_matrices <- file.path(work_dir, "mc3_binary_matrix.rds")
out_cohort_map <- file.path(work_dir, "mc3_sample_cohort_map.rds")

saveRDS(matrix_by_cohort, out_matrices)
saveRDS(sample_cohort_map, out_cohort_map)
message(sprintf("[00_load_mc3] wrote %s (%.1f MB)",
                out_matrices, file.info(out_matrices)$size / 1e6))
message(sprintf("[00_load_mc3] wrote %s", out_cohort_map))
message(sprintf("[00_load_mc3] DONE (%.1fs total)", (proc.time() - t0)["elapsed"]))
