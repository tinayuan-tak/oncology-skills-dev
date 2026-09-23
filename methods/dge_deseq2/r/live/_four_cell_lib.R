#!/usr/bin/env Rscript
# _four_cell_lib.R — shared compute for the four-cell tumor-vs-normal DEG.
#
# Sourced by BOTH 06_four_cell_driver.R (whole-cohort) and
# 07_stratified_four_cell_driver.R (per-subgroup). Extracting the cell helpers
# + sensitivity-concordance assembly here guarantees that a per-stratum log2FC
# is produced by the IDENTICAL pipeline (DESeq2 NB-GLM + apeglm shrinkage,
# poscounts size factors, the same prefilter) as the whole-cohort log2FC — so
# the two are on the same scale and the card's trust-anchor semantics
# (cells_supporting / cells_ran, selectivity_class) carry over unchanged to the
# subgroup panorama. This file defines functions ONLY; it runs no code and
# reads no CLI args, so sourcing it is side-effect-free.
#
# Every function is a pure move of the corresponding block that lived inline in
# 06_four_cell_driver.R prior to 2026-08-18; run_cell was parameterised on
# out_dir / min_n / flog (previously closed-over globals) so it is reusable.

`%||%` <- function(a, b) if (!is.null(a) && length(a) && !is.na(a[1])) a else b

# --- one-aliquot-per-case dedup (S-fix, github analysis-methods#691) --------
# Shared by 00_load_recount3.R and 00_load_xena_toil.R so both TCGA-sourcing
# loaders apply the SAME policy the legacy loader had (00_load_counts.R:127-158,
# dedup_policy = "one_per_case_group_first_by_file_id"): a case (patient) that
# contributes more than one file/sample within a single group (tumor OR normal)
# — technical-replicate vials, biological aliquots from the same tumor block —
# violates DESeq2's per-sample independence assumption. Keep exactly one
# aliquot per case, chosen deterministically by ordering on `order_key` (the
# legacy policy's tie-break was ascending GDC file_id) and taking the first.
#
# `ids`: the candidate sample identifiers for ONE group (e.g. tumor_ids). Order
# in the returned vector matches the INPUT order (only a subset is dropped) so
# callers that rely on `ids` order elsewhere are unaffected.
# `case_id_by_id`: named vector/list, id -> case/patient identifier (may be NA
#   where linkage is unknown for that id).
# `order_key_by_id`: named vector/list, id -> deterministic tie-break key
#   (ascending). Defaults to `ids` themselves (alphabetical) when NULL.
#
# Safety valve: if case linkage is unavailable for EVERY id (e.g. the
# metadata schema is missing the submitter-id column), dedup is a no-op — the
# alternative (dedup on an all-NA key) would collapse the entire group to one
# sample, which is a far worse failure than the pseudo-replication this guards
# against.
dedupe_one_aliquot_per_case <- function(ids, case_id_by_id, order_key_by_id = NULL,
                                        label = "") {
  if (length(ids) == 0) return(ids)
  case_ids <- unname(case_id_by_id[ids])
  if (all(is.na(case_ids))) {
    message("[dedupe_one_aliquot_per_case] ", label,
            ": case linkage unavailable for all ", length(ids),
            " sample(s) — dedup skipped")
    return(ids)
  }
  order_key <- if (is.null(order_key_by_id)) ids else unname(order_key_by_id[ids])
  ord <- order(order_key, na.last = TRUE)
  # A NA case_id gets a per-id unique key so it is never treated as a
  # duplicate of another NA-case sample.
  case_key <- ifelse(is.na(case_ids), paste0("__no_case_id__", ids), case_ids)
  keep <- logical(length(ids))
  keep[ord] <- !duplicated(case_key[ord])
  n_dropped <- sum(!keep)
  if (n_dropped > 0) {
    message("[dedupe_one_aliquot_per_case] ", label, ": deduped ", n_dropped,
            " of ", length(ids),
            " sample(s) (one aliquot per case; first by order key)")
  }
  ids[keep]
}

# --- Xena/Toil expected_count de-transform (S1b, github analysis-methods#694) --
# The UCSC Toil hub ships the gene matrix as log2(expected_count + 1), NOT raw
# integer counts (recorded in the source manifest xena-toil-tcga-target-gtex-*).
# DESeq2's NB-GLM requires INTEGER counts, so 00_load_xena_toil.R must invert
# the transform before the four-cell driver ever sees the matrix. This is a pure
# function so the invariant a future edit must not break — round-trip, clamped
# at 0, integer storage — is unit-tested (test_xena_log2_to_counts.py) rather
# than trusted to a comment.
#
# INVARIANT: for any non-negative integer count n, log2(n + 1) round-trips
# exactly: round(2^log2(n+1) - 1) == n. Values are clamped at 0 (a floating
# point undershoot or a NA cannot become a negative or missing count) and stored
# as integer (`storage.mode <- "integer"`), the one type DESeq2 accepts.
#
# Operates on `x` directly (element-wise `2^x - 1`) rather than as.numeric(x), so
# a matrix keeps BOTH its dims AND its dimnames: the loader relies on
# colnames(counts) (the sample ids) surviving this transform to build coldata.
# `as.numeric()` would flatten those away — a subtle regression the dimnames
# assertions in test_xena_log2_to_counts.py now guard against.
#
# `x`: numeric matrix (or vector) of log2(expected_count + 1) values.
# returns: an integer matrix/vector of the same shape (dimnames preserved), all values >= 0.
xena_log2_to_counts <- function(x) {
  counts <- round(2^x - 1)
  counts[is.na(counts) | counts < 0] <- 0
  storage.mode(counts) <- "integer"
  counts
}

# Pre-filter low-count genes on a per-cell sample subset. recount3 G026 carries
# ~64K genes, a large fraction of which are lncRNA/pseudogene with near-zero
# counts — these inflate DESeq2's dispersion-fit time (O(genes)) without adding
# testable signal. Require >=10 counts in >=25% of samples (DESeq2 vignette's
# independent-filtering spirit; stricter than the >=3-sample floor so dispersion
# fitting stays tractable at cohort scale). Also drop the smallest-group floor.
# KNOWN TRADE-OFF (2026-08-13 review): the >=10-counts-in->=25%-of-samples floor is a perf/robustness
# filter, but it also DROPS a bimodal subset-restricted antigen expressed in <25% of the combined
# tumour+normal set (~ a rare-subpopulation surface target) from that cell -> it reads not_informative,
# so this axis under-detects exactly the patient-subset antigens a per-sample percentile view (Q2 card)
# is better suited to surface. Acceptable for the bulk selectivity call; noted so it is not mistaken
# for a measured absence. NOTE (2026-08-18): in a per-subgroup fit the denominator is the STRATUM's
# sample count, so the 25%-of-samples floor is relative to the (smaller) stratum — a gene expressed in
# a stratum-specific subpopulation is MORE likely to clear it here than in the whole-cohort fit.
prefilter <- function(mat) {
  min_samples <- max(3L, ceiling(0.25 * ncol(mat)))
  keep <- rowSums(mat >= 10) >= min_samples
  mat[keep, , drop = FALSE]
}

# DESeq2 fit + apeglm shrinkage for a two-level `group` factor
# (reference = "normal", so log2FC > 0 == up in tumor). Returns a tidy frame
# with gene_symbol, log2FoldChange, padj, baseMean.
#
# sfType="poscounts": DESeq2's default median-of-ratios size-factor estimator
# needs each retained gene to be nonzero in EVERY sample (to compute the
# geometric mean). At 1,500+ samples across ~30K recount3 loci, essentially
# every gene has at least one zero. Anders/Huber's "poscounts" estimator uses
# only positive counts per gene and is the field-standard fix for large-N
# cohorts; setting it everywhere gives cell-consistent normalization semantics.
# `with_svalue`: additionally report the apeglm s-value (Stephens 2017) against
# the null |log2FC| <= log2(1.5). The apeglm MAP point estimate of log2FC is
# unchanged by lfcThreshold — it only changes the reported error quantity — so
# the shrunken `log2FoldChange` column is identical whether or not s-values are
# requested; `padj` continues to come from the standard Wald `results()` call
# (padj stays the verdict driver; s-values are additive — plan B3). Cells A/C/Cr
# request it; cell B (a within-TCGA robustness re-run) does not.
deseq2_fit <- function(mat, cd, with_svalue = FALSE) {
  cd$group <- factor(cd$group, levels = c("normal", "tumor"))
  mat <- prefilter(mat)
  storage.mode(mat) <- "integer"
  # Study covariate for POOLED multi-study indications (NSCLC=LUAD+LUSC, COADREAD=COAD+READ):
  # adjust the tumor-vs-normal effect for study so a pooled contrast is not confounded by the
  # study mix. Applied ONLY when BOTH groups span >1 study level (cells A/B, where tumor AND
  # adjacent each include both studies -> full-rank). NOT the GTEx contrast (cell C): GTEx normal
  # is a single study in group=normal, so `study` is confounded with `group` there -> stays ~ group.
  # group is the last term so lfcShrink(coef="group_tumor_vs_normal") is unaffected. Self-guards
  # identically in the per-subgroup driver (07). Ported from main's 06 study-covariate PR 2026-08-18.
  use_study <- ("study" %in% colnames(cd)) &&
    min(tapply(as.character(cd$study), cd$group, function(s) length(unique(s)))) > 1
  if (use_study) {
    cd$study <- factor(cd$study)
    design <- ~ study + group
    message(sprintf("[four_cell_lib]   study-adjusted design (~ study + group); %d studies",
                    nlevels(cd$study)))
  } else {
    design <- ~ group
  }
  dds <- DESeqDataSetFromMatrix(countData = mat, colData = cd, design = design)
  dds <- DESeq(dds, parallel = TRUE, quiet = TRUE, sfType = "poscounts")
  res_un <- results(dds, contrast = c("group", "tumor", "normal"), alpha = 0.05)
  res <- if (with_svalue) {
    # lfcThreshold => apeglm reports the s-value against the null |LFC| <= thr.
    lfcShrink(dds, coef = "group_tumor_vs_normal", type = "apeglm",
              lfcThreshold = log2(1.5), svalue = TRUE,
              parallel = TRUE, res = res_un, quiet = TRUE)
  } else {
    # Exact v1 call path — untouched so cells A/B/C stay byte-identical.
    lfcShrink(dds, coef = "group_tumor_vs_normal", type = "apeglm",
              parallel = TRUE, res = res_un, quiet = TRUE)
  }
  out <- data.frame(gene_symbol   = rownames(res),
                    log2FoldChange = res$log2FoldChange,
                    padj           = res_un$padj,
                    baseMean       = res_un$baseMean,
                    stringsAsFactors = FALSE)
  if (with_svalue) out$svalue <- res$svalue
  out
}

# --- RUVg cross-cohort correction (cell Cr) ---------------------------------
# Curated housekeeping panel (Eisenberg & Levanon 2013, "human housekeeping
# genes revisited" — a subset of the most stably-expressed, plus canonical
# normalizers). Used to CROSS-CHECK the empirical control set and as a FALLBACK
# for tiny cohorts where the first-pass DE ranking is unstable. HGNC symbols,
# matching the loader's gene_symbol row keys.
HK_GENES <- c(
  "ACTB", "GAPDH", "B2M", "HPRT1", "PGK1", "PPIA", "RPL13A", "RPLP0", "TBP",
  "GUSB", "TFRC", "YWHAZ", "SDHA", "UBC", "RPS18", "RPL37A", "EEF1A1", "PSMB4",
  "REEP5", "VPS29", "C1orf43", "CHMP2A", "EMC7", "GPI", "VCP", "SNRPD3"
)

# Empirical negative-control genes for RUVg (Risso et al. 2014, RUVSeq). Genes
# with the WEAKEST tumor-vs-normal evidence in a naive `~group` first pass are
# the least condition-associated, so their residual variation estimates the
# unwanted (batch/quality) factors. Returns the control row names + a strategy
# record for provenance. `hk_genes` present in the matrix are always unioned in
# as a stability anchor; for tiny cohorts (< min_first_pass samples per group)
# the first-pass ranking is skipped and expressed HK genes are used directly.
empirical_controls <- function(mat, group, n_control = 5000L,
                               hk_genes = HK_GENES, min_first_pass = 10L) {
  group <- factor(group, levels = c("normal", "tumor"))
  n_min <- min(table(group))
  hk_present <- intersect(hk_genes, rownames(mat))
  if (n_min < min_first_pass) {
    ctrl <- hk_present
    return(list(idx = ctrl, strategy = "housekeeping-only (tiny cohort)",
                n_control = length(ctrl), n_empirical = 0L,
                n_hk_present = length(hk_present),
                n_hk_in_control = length(hk_present)))
  }
  cd0 <- data.frame(group = group)
  dds0 <- DESeqDataSetFromMatrix(mat, cd0, ~ group)
  dds0 <- suppressMessages(DESeq(dds0, parallel = TRUE, quiet = TRUE,
                                 sfType = "poscounts"))
  res0 <- results(dds0, contrast = c("group", "tumor", "normal"))
  # Largest p-value == least evidence of DE == best empirical control. Untested
  # genes (NA p) count as "no evidence" so they are eligible controls.
  pv <- res0$pvalue; pv[is.na(pv)] <- 1
  ord <- order(pv, decreasing = TRUE)
  n_control <- min(as.integer(n_control), nrow(mat))
  ctrl_emp <- rownames(mat)[ord[seq_len(n_control)]]
  ctrl <- union(ctrl_emp, hk_present)   # anchor with expressed HK genes
  list(idx = ctrl,
       strategy = sprintf("empirical top-%d least-DE (naive ~group) ∪ %d HK genes",
                          n_control, length(hk_present)),
       n_control = length(ctrl), n_empirical = length(ctrl_emp),
       n_hk_present = length(hk_present),
       n_hk_in_control = length(intersect(hk_present, ctrl_emp)))
}

# RUVg-corrected cross-cohort fit (cell Cr). Estimates k factors of unwanted
# variation from the empirical control genes, binds W_1..W_k into colData, and
# fits `~ W_1 + ... + W_k + group` with group last (so
# lfcShrink(coef="group_tumor_vs_normal") is unaffected — same invariant as the
# `study` covariate in deseq2_fit). RIN/ischemic are NOT design terms: the
# symmetry probe (rin_symmetry_probe.json) found RIN is GTEx-only and therefore
# collinear with `group` (non-identifiable) — they ride as diagnostic-only
# colData columns, never here. poscounts size factors; apeglm shrinkage with an
# lfcThreshold=log2(1.5) s-value. Returns the tidy frame plus a `ruv` attribute
# (k, control strategy, W matrix) for provenance.
ruvg_fit <- function(mat, cd, k = 2L, n_control = 5000L, hk_genes = HK_GENES) {
  cd$group <- factor(cd$group, levels = c("normal", "tumor"))
  mat <- prefilter(mat)
  storage.mode(mat) <- "integer"
  ctrl <- empirical_controls(mat, cd$group, n_control = n_control,
                             hk_genes = hk_genes)
  stopifnot(length(ctrl$idx) > k)
  ruv <- RUVg(mat, cIdx = ctrl$idx, k = as.integer(k))
  W <- ruv$W
  colnames(W) <- paste0("W_", seq_len(ncol(W)))
  cd <- cbind(cd, W)
  w_terms <- colnames(W)
  design <- stats::as.formula(paste("~", paste(c(w_terms, "group"), collapse = " + ")))
  message(sprintf("[four_cell_lib]   RUVg design (%s); k=%d, %d control genes (%s)",
                  paste(c(w_terms, "group"), collapse = " + "), k,
                  ctrl$n_control, ctrl$strategy))
  dds <- DESeqDataSetFromMatrix(countData = mat, colData = cd, design = design)
  dds <- DESeq(dds, parallel = TRUE, quiet = TRUE, sfType = "poscounts")
  res_un <- results(dds, contrast = c("group", "tumor", "normal"), alpha = 0.05)
  res <- lfcShrink(dds, coef = "group_tumor_vs_normal", type = "apeglm",
                   lfcThreshold = log2(1.5), svalue = TRUE,
                   parallel = TRUE, res = res_un, quiet = TRUE)
  out <- data.frame(gene_symbol    = rownames(res),
                    log2FoldChange = res$log2FoldChange,
                    padj           = res_un$padj,
                    svalue         = res$svalue,
                    baseMean       = res_un$baseMean,
                    stringsAsFactors = FALSE)
  attr(out, "ruv") <- list(k = as.integer(k), control_strategy = ctrl$strategy,
                           n_control = ctrl$n_control,
                           n_empirical = ctrl$n_empirical,
                           n_hk_present = ctrl$n_hk_present,
                           n_hk_in_control = ctrl$n_hk_in_control,
                           W = W)
  out
}

# ComBat-seq batch correction. See 06_four_cell_driver.R history for the full
# rationale (preserve_group semantics, ESCA integer-overflow clip).
combat_correct <- function(mat, batch, group, preserve_group = TRUE) {
  mat <- as.matrix(mat); storage.mode(mat) <- "integer"
  tb <- table(batch)
  ok <- batch %in% names(tb)[tb >= 2]
  if (!all(ok)) {
    message("[four_cell_lib]     dropping ", sum(!ok),
            " samples in singleton batches before ComBat_seq")
  }
  bfac <- droplevels(factor(batch[ok]))
  run <- function(grp) ComBat_seq(counts = mat[, ok, drop = FALSE],
                                  batch = bfac, group = grp)
  adj <- NULL
  if (preserve_group) {
    adj <- tryCatch(run(group[ok]), error = function(e) {
      message("[four_cell_lib]     ComBat_seq group-preservation failed (",
              conditionMessage(e), "); retrying without group protection")
      NULL
    })
  }
  if (is.null(adj)) adj <- run(NULL)
  adj <- round(adj)
  adj[adj < 0] <- 0
  adj[adj > .Machine$integer.max] <- .Machine$integer.max
  storage.mode(adj) <- "integer"
  list(counts = adj, keep = ok)
}

# Run one cell (fit DESeq2 on a sample subset). Parameterised on out_dir / min_n
# / flog (previously globals inside 06); label-suffixed cache .rds lets a
# resumed / re-run cohort reuse a completed fit.
run_cell <- function(label, mat, cd, out_dir, min_n, flog,
                     combat_batch = NULL, preserve_group = TRUE) {
  n_t <- sum(cd$group == "tumor"); n_n <- sum(cd$group == "normal")
  cache_path <- file.path(out_dir, sprintf("_cell_%s.rds", label))
  if (file.exists(cache_path)) {
    flog(sprintf("cell %s: reusing cached fit at %s", label, cache_path))
    return(readRDS(cache_path))
  }
  if (n_t < min_n || n_n < min_n) {
    flog(sprintf("cell %s SKIPPED (n_tumor=%d, n_normal=%d < %d)",
                 label, n_t, n_n, min_n))
    return(NULL)
  }
  if (!is.null(combat_batch)) {
    flog(sprintf("cell %s: ComBat_seq(batch=%s, preserve_group=%s) START",
                 label, combat_batch, preserve_group))
    cc <- combat_correct(mat, cd[[combat_batch]], cd$group,
                         preserve_group = preserve_group)
    mat <- cc$counts; cd <- cd[cc$keep, , drop = FALSE]
    flog(sprintf("cell %s: ComBat_seq DONE; %d samples remain", label, ncol(mat)))
  }
  flog(sprintf("cell %s: DESeq2 START (n_tumor=%d, n_normal=%d, n_genes_pre=%d)",
               label, sum(cd$group=="tumor"), sum(cd$group=="normal"), nrow(mat)))
  fit <- deseq2_fit(mat, cd)
  names(fit)[names(fit) == "log2FoldChange"] <- paste0("log2fc_", label)
  names(fit)[names(fit) == "padj"]           <- paste0("padj_", label)
  names(fit)[names(fit) == "baseMean"]        <- paste0("baseMean_", label)
  saveRDS(fit, cache_path)
  flog(sprintf("cell %s: DESeq2 DONE (%d genes, cached at %s)",
               label, nrow(fit), cache_path))
  fit
}

# Assemble the per-gene sensitivity-concordance frame from a named list of
# per-cell fits (cells that ran, e.g. list(A=cellA, C=cellC)). This is the exact
# block that lived inline in 06 after the cells ran — moved verbatim so the
# whole-cohort and per-subgroup products share concordance semantics. Returns a
# gene-sorted data.frame with cells_ran / cells_supporting / dominant_direction
# / sig_all_cells / discordant / per-cell log2fc+padj / max_abs_log2fc.
assemble_sensitivity <- function(cells) {
  if (length(cells) == 0) stop("assemble_sensitivity: no cells ran")
  merged <- Reduce(function(x, y) merge(x, y, by = "gene_symbol", all = TRUE), cells)

  lab_ran   <- names(cells)
  lfc_cols  <- paste0("log2fc_", lab_ran)
  padj_cols <- paste0("padj_",   lab_ran)

  lfc_mat  <- as.matrix(merged[, lfc_cols,  drop = FALSE])
  padj_mat <- as.matrix(merged[, padj_cols, drop = FALSE])

  sig_mat  <- !is.na(padj_mat) & padj_mat < 0.05
  sign_mat <- sign(lfc_mat); sign_mat[is.na(sign_mat)] <- 0

  sig_lfc <- lfc_mat; sig_lfc[!sig_mat] <- 0
  dom_score <- rowSums(sig_lfc, na.rm = TRUE)
  dominant_direction <- ifelse(dom_score > 0, "up",
                        ifelse(dom_score < 0, "down", "none"))

  dom_sign <- ifelse(dominant_direction == "up", 1,
              ifelse(dominant_direction == "down", -1, 0))
  supporting <- rowSums(sig_mat & (sign_mat == dom_sign), na.rm = TRUE)

  cells_ran_per_gene <- rowSums(!is.na(padj_mat))
  sig_all <- (supporting == cells_ran_per_gene) & (cells_ran_per_gene > 0)

  any_up   <- rowSums(sig_mat & sign_mat > 0, na.rm = TRUE) > 0
  any_down <- rowSums(sig_mat & sign_mat < 0, na.rm = TRUE) > 0
  discordant <- any_up & any_down

  sens <- data.frame(
    gene_symbol        = merged$gene_symbol,
    cells_ran          = cells_ran_per_gene,
    cells_supporting   = supporting,
    dominant_direction = dominant_direction,
    sig_all_cells      = sig_all,
    discordant         = discordant,
    stringsAsFactors = FALSE
  )
  for (l in lab_ran) {
    sens[[paste0("log2fc_", l)]] <- merged[[paste0("log2fc_", l)]]
    sens[[paste0("padj_",   l)]] <- merged[[paste0("padj_",   l)]]
  }
  sens$max_abs_log2fc <- apply(abs(lfc_mat), 1, max, na.rm = TRUE)
  sens$max_abs_log2fc[!is.finite(sens$max_abs_log2fc)] <- NA_real_
  sens[order(sens$gene_symbol), ]
}
