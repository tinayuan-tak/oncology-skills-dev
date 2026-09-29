#!/usr/bin/env Rscript
# Stage 02 — MSstatsTMT tumor-vs-normal group comparison on pre-summarized
# CPTAC tmt10.tsv data.
#
# Design decision (2026-07-10): CPTAC tmt10.tsv values are already gene-level
# log2 pool-normalized abundance. MSstatsTMT's proteinSummarization step is
# built to reduce peptide-level PSMs → protein-level values, and running it
# on already-summarized data is (a) a no-op statistically and (b) painfully
# slow (~2 min/plex × 17 plexes × 10 cohorts = 5.7 hours).
#
# The fast + correct path is to construct the `ProteinLevelData` list slot
# directly from tmt10.tsv values and feed it to `groupComparisonTMT`. The
# latter applies a per-protein linear mixed model with plex (Mixture) as
# a random effect + limma-eBayes moderation on the variances — that's the
# statistically-rigorous step that must not be skipped.
#
# Reads:
#   <work_dir>/<cohort>_msstats_input.feather (from stage 01)
# Writes:
#   <work_dir>/<cohort>_msstats_results.tsv
#     columns: cohort | gene_symbol | logFC | SE | pvalue | adj.pvalue |
#              med_log2_tumor | med_log2_normal | n_tumor | n_normal | issue

options(error = function() { traceback(3); quit(status = 1) })

suppressPackageStartupMessages({
  library(optparse)
  library(arrow)
  library(dplyr)
  library(tidyr)
  library(MSstatsTMT)
})

option_list <- list(
  make_option("--work-dir", type = "character", default = NULL),
  make_option("--cohort",   type = "character", default = NULL),
  make_option("--min-normal", type = "integer", default = 5,
              help = "Skip cohorts with fewer than this many normal aliquots [default %default]")
)
opts <- parse_args(OptionParser(option_list = option_list))
if (is.null(opts$`work-dir`) || is.null(opts$cohort)) {
  stop("--work-dir and --cohort required")
}
work_dir <- opts$`work-dir`
cohort <- opts$cohort

in_path <- file.path(work_dir, paste0(cohort, "_msstats_input.feather"))
if (!file.exists(in_path)) {
  stop(sprintf("Input not found: %s (run stage 01 first)", in_path))
}
t0 <- proc.time()
message(sprintf("[02_msstats %s] reading %s", cohort, basename(in_path)))
long <- as.data.frame(read_feather(in_path))

# Recover log2 abundance from Intensity (stage 01 exponentiated) — for the
# ProteinLevelData shape MSstatsTMT expects, values are on log2 scale directly.
long$Abundance <- log2(long$Intensity)

# Pre-flight power check
n_tumor <- length(unique(long$BioReplicate[long$Condition == "Tumor"]))
n_normal <- length(unique(long$BioReplicate[long$Condition == "Normal"]))
message(sprintf("[02_msstats %s] n_tumor=%d n_normal=%d n_proteins=%d n_rows=%d",
                cohort, n_tumor, n_normal,
                length(unique(long$ProteinName)), nrow(long)))
if (n_normal < opts$`min-normal`) {
  message(sprintf("[02_msstats %s] SKIP: n_normal (%d) < min-normal (%d)",
                  cohort, n_normal, opts$`min-normal`))
  skip_row <- data.frame(
    cohort = cohort, gene_symbol = NA_character_,
    logFC = NA_real_, SE = NA_real_, pvalue = NA_real_, adj.pvalue = NA_real_,
    med_log2_tumor = NA_real_, med_log2_normal = NA_real_,
    n_tumor = n_tumor, n_normal = n_normal, issue = "skipped_low_n"
  )
  out_path <- file.path(work_dir, paste0(cohort, "_msstats_results.tsv"))
  write.table(skip_row, out_path, sep = "\t", quote = FALSE, row.names = FALSE)
  quit(status = 0)
}

# Construct ProteinLevelData directly. MSstatsTMT::groupComparisonTMT
# requires columns: Mixture | TechRepMixture | Run | Channel | Protein |
# Abundance | BioReplicate | Condition. Everything except Abundance must
# be a factor for the internal lmer() call.
pld <- data.frame(
  Mixture = factor(long$Mixture),
  TechRepMixture = factor(long$TechRepMixture),
  Run = factor(long$Run),
  Channel = factor(long$Channel),
  Protein = factor(long$ProteinName),
  Abundance = as.numeric(long$Abundance),
  BioReplicate = as.character(long$BioReplicate),
  Condition = factor(long$Condition),
  stringsAsFactors = FALSE
)
# Drop any Inf / NaN abundances (from log2(0) or negative intensities that
# proteinSummarization would have censored)
pld <- pld[is.finite(pld$Abundance), ]
message(sprintf("[02_msstats %s] ProteinLevelData rows after Inf/NaN filter: %d",
                cohort, nrow(pld)))

# Build the summarized list object groupComparisonTMT consumes. FeatureLevelData
# is not used by groupComparisonTMT — a stub with the required cols suffices.
data_for_gc <- list(
  FeatureLevelData = data.frame(
    ProteinName = factor(character(0)),
    PSM = factor(character(0)),
    censored = logical(0),
    predicted = numeric(0),
    log2Intensity = numeric(0),
    Run = character(0), Channel = character(0),
    BioReplicate = character(0),
    Condition = factor(character(0)),
    Mixture = character(0), TechRepMixture = character(0),
    PeptideSequence = character(0), Charge = character(0)
  ),
  ProteinLevelData = pld
)

# Build contrast Tumor − Normal. Condition factor levels are alphabetical by
# default (Normal, Tumor) so it's important to lock the levels order.
conditions <- levels(pld$Condition)
message(sprintf("[02_msstats %s] Conditions in ProteinLevelData: %s",
                cohort, paste(conditions, collapse = ", ")))
if (!all(c("Tumor", "Normal") %in% conditions)) {
  stop(sprintf("[%s] Missing Tumor or Normal condition: %s",
               cohort, paste(conditions, collapse = ", ")))
}
contrast_matrix <- matrix(0, nrow = 1, ncol = length(conditions),
                          dimnames = list("Tumor_vs_Normal", conditions))
contrast_matrix[1, "Tumor"] <- 1
contrast_matrix[1, "Normal"] <- -1

message(sprintf("[02_msstats %s] groupComparisonTMT (moderated=TRUE) ...", cohort))
gc_t0 <- proc.time()
gc <- MSstatsTMT::groupComparisonTMT(
  data = data_for_gc,
  contrast.matrix = contrast_matrix,
  moderated = TRUE,
  adj.method = "BH",
  remove_norm_channel = FALSE,
  remove_empty_channel = FALSE,
  save_fitted_models = FALSE,
  use_log_file = FALSE
)
message(sprintf("[02_msstats %s] groupComparisonTMT done in %.1fs",
                cohort, (proc.time() - gc_t0)["elapsed"]))

res <- gc$ComparisonResult
message(sprintf("[02_msstats %s] Result rows: %d", cohort, nrow(res)))

# Per-condition median log2 abundance from ProteinLevelData
med <- pld %>%
  group_by(Protein, Condition) %>%
  summarise(med_log2 = median(Abundance, na.rm = TRUE), .groups = "drop") %>%
  pivot_wider(names_from = Condition, values_from = med_log2,
              names_prefix = "med_log2_")

res$Protein <- as.character(res$Protein)
med$Protein <- as.character(med$Protein)
res <- dplyr::left_join(res, med, by = "Protein")

# `issue` — 2026-09-12 (W4). The former `ifelse(is.na(res$log2FC), "no_estimate", "ok")` MISSED the
# dominant unestimable case and labelled it "ok". groupComparisonTMT does NOT return NA for a protein
# quantified in only one condition: it returns log2FC = +/-Inf (and NA pvalue/adj.pvalue/SE), flagged in
# its OWN `issue` column as `oneConditionMissing`. `is.na(Inf)` is FALSE, so 1,618 rows of the shipped
# v1.2.0 product (BRCA 1,613 of 10,491 = 15.4%; GBM 5) were stamped "ok" here and then labelled
# `not_significant` downstream — a claim of "tested, no difference" about an unestimable ratio.
# Fix: carry MSstatsTMT's own issue verbatim when it has one, and make the locally-computed fallback
# test FINITENESS rather than NA. Order matters: upstream wins, because it distinguishes
# oneConditionMissing from completeMissing and we must not flatten that.
upstream_issue <- if ("issue" %in% names(res)) as.character(res$issue) else rep(NA_character_, nrow(res))
local_issue <- ifelse(is.na(res$log2FC), "no_estimate",
                      ifelse(is.finite(res$log2FC), "ok", "one_condition_missing"))
issue_col <- ifelse(!is.na(upstream_issue) & nzchar(upstream_issue), upstream_issue, local_issue)

n_unest <- sum(!is.na(res$log2FC) & !is.finite(res$log2FC))
if (n_unest > 0) {
  message(sprintf("[02_msstats %s] UNESTIMABLE contrasts (log2FC=+/-Inf, one condition missing): %d of %d",
                  cohort, n_unest, nrow(res)))
}

out <- data.frame(
  cohort = cohort,
  gene_symbol = res$Protein,
  logFC = res$log2FC,
  SE = res$SE,
  pvalue = res$pvalue,
  adj.pvalue = res$adj.pvalue,
  med_log2_tumor = res$med_log2_Tumor,
  med_log2_normal = res$med_log2_Normal,
  n_tumor = n_tumor,
  n_normal = n_normal,
  issue = issue_col,
  stringsAsFactors = FALSE
)

out_path <- file.path(work_dir, paste0(cohort, "_msstats_results.tsv"))
write.table(out, out_path, sep = "\t", quote = FALSE, row.names = FALSE)
message(sprintf("[02_msstats %s] wrote %s (%d rows, total %.1fs)",
                cohort, basename(out_path), nrow(out),
                (proc.time() - t0)["elapsed"]))
