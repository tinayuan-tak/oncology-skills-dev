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
  n_genes_pre <- nrow(mat)
  mat <- prefilter(mat)
  n_genes_post <- nrow(mat)
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
  # --- attach the raw QC inputs the output-QC layer (S3a #701) alone needs -----
  # The tidy `out` frame keeps only gene_symbol/log2FC/padj/baseMean, so the
  # signals the fail-loud gate reads (the UNSHRUNK Wald p-value used for the
  # padj=NA taxonomy, gene-wise dispersions, poscounts size factors, the
  # independent-filtering threshold, per-group n) survive ONLY if captured here,
  # where the dds / res_un objects are still in scope. Stored as an ATTRIBUTE so
  # the public columns — hence every emitted parquet — stay byte-identical (cells
  # A/B/C products are unchanged; write_parquet writes columns, not R attrs).
  # `four_cell_qc_metrics()` + `assert_contrast_qc()` (below) consume this list;
  # both are pure functions of these vectors, so they are testable without DESeq2.
  attr(out, "qc") <- list(
    gene_symbol      = rownames(res),
    pvalue           = res_un$pvalue,          # unshrunk Wald p (NA taxonomy)
    padj             = res_un$padj,
    baseMean         = res_un$baseMean,
    lfc              = res$log2FoldChange,     # apeglm-shrunk (coherence check)
    dispersions      = tryCatch(as.numeric(dispersions(dds)),
                                error = function(e) NA_real_),
    size_factors     = tryCatch({
                          sf <- sizeFactors(dds)
                          if (is.null(sf)) NULL else as.numeric(sf)
                        }, error = function(e) NULL),
    filter_threshold = tryCatch(as.numeric(S4Vectors::metadata(res_un)$filterThreshold),
                                error = function(e) NA_real_),
    n_tumor          = sum(cd$group == "tumor"),
    n_normal         = sum(cd$group == "normal"),
    n_genes_pre      = n_genes_pre,
    n_genes_post     = n_genes_post
  )
  # --- attach the figure inputs the S3b QC bundle (_qc_figures.R) needs --------
  # The result-diagnostic figures (MA / p-hist / volcano / indep-filter) read
  # attr(fit,"qc") above; the sample-level trio (PCA / sample-distance /
  # library-size) and the three-component plotDispEsts need the VST matrix + the
  # dispersion trend + per-sample metadata, which live only on the dds here.
  # Captured as attr(out,"fig") — like the qc attr, an R attribute, so the
  # emitted parquet columns stay byte-identical (write_parquet drops attrs). Only
  # the top-N most-variable genes' VST is kept so the cache stays light; PCA and
  # the sample-distance heatmap both use the top-variable subset by convention.
  # Any failure here is non-fatal: the fig attr is a diagnostic sidecar, never a
  # product input, so a VST hiccup must not fail a fit whose parquet is valid.
  fig <- tryCatch({
    vsd <- tryCatch(vst(dds, blind = FALSE),
                    error = function(e) varianceStabilizingTransformation(dds, blind = FALSE))
    vm  <- SummarizedExperiment::assay(vsd)
    n_top <- min(500L, nrow(vm))
    rv  <- matrixStats::rowVars(vm)
    top <- order(rv, decreasing = TRUE)[seq_len(n_top)]
    vm_top <- vm[top, , drop = FALSE]
    md <- data.frame(group = as.character(cd$group), stringsAsFactors = FALSE,
                     row.names = colnames(mat))
    for (cov in c("source", "tcga_tss", "SMRIN")) {
      if (cov %in% colnames(cd)) md[[cov]] <- cd[[cov]]
    }
    list(
      vst           = vm_top,
      n_top_var     = n_top,
      baseMean      = res_un$baseMean,
      disp_gene_est = tryCatch(as.numeric(S4Vectors::mcols(dds)$dispGeneEst),
                               error = function(e) NULL),
      disp_fit      = tryCatch(as.numeric(S4Vectors::mcols(dds)$dispFit),
                               error = function(e) NULL),
      disp_final    = tryCatch(as.numeric(dispersions(dds)), error = function(e) NULL),
      lib_size      = colSums(mat),
      sample_meta   = md
    )
  }, error = function(e) {
    message("[four_cell_lib]   attr(fit,\"fig\") capture failed (",
            conditionMessage(e), ") — S3b sample-level figures will be skipped")
    NULL
  })
  attr(out, "fig") <- fig
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

# Run the fail-loud output-QC gate (S3a #701) on a completed per-cell fit and
# stamp the metrics record onto it for the provenance sidecar. Shared by the
# fresh-fit and cache-reuse paths so a re-run reusing a cached fit is QC'd too
# (a fit cached before S3a has no qc attr -> the gate skips loudly, never fails
# open silently). `qc_panel = NULL` disables the marker sign check (cell AG).
.four_cell_qc_gate <- function(fit, label, flog, qc_panel = NULL,
                               qc_indication = NULL) {
  metrics <- four_cell_qc_metrics(attr(fit, "qc"))
  assert_contrast_qc(fit, metrics, label = label, panel = qc_panel,
                     indication = qc_indication, emit = flog)
  attr(fit, "qc_metrics") <- metrics
  fit
}

# Run one cell (fit DESeq2 on a sample subset). Parameterised on out_dir / min_n
# / flog (previously globals inside 06); label-suffixed cache .rds lets a
# resumed / re-run cohort reuse a completed fit.
run_cell <- function(label, mat, cd, out_dir, min_n, flog,
                     combat_batch = NULL, preserve_group = TRUE,
                     qc_panel = NULL, qc_indication = NULL) {
  n_t <- sum(cd$group == "tumor"); n_n <- sum(cd$group == "normal")
  cache_path <- file.path(out_dir, sprintf("_cell_%s.rds", label))
  if (file.exists(cache_path)) {
    flog(sprintf("cell %s: reusing cached fit at %s", label, cache_path))
    fit <- readRDS(cache_path)
    return(.four_cell_qc_gate(fit, label, flog, qc_panel, qc_indication))
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
  # Fail loud on a degenerate fit BEFORE it is cached or written downstream — a
  # stop() here exits the driver non-zero instead of persisting a silent
  # zero-row / all-NaN / sign-inverted product.
  fit <- .four_cell_qc_gate(fit, label, flog, qc_panel, qc_indication)
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

# ============================================================================
# Fail-loud output-QC layer (S3a, github analysis-methods#701)
# ----------------------------------------------------------------------------
# The R drivers historically only message() counts and NEVER assert, so a
# degenerate DESeq2 output — a zero-row parquet, the documented SCLC all-NaN
# A/B cell, a globally sign-inverted (backwards-wired) contrast — writes
# SILENTLY. This layer stops the run on those degeneracies instead. It is split
# into two PURE functions (no DESeq2 objects, only the vectors deseq2_fit
# stashed in attr(fit,"qc")) so both are exercised hermetically by synthetic
# fixtures, including the load-bearing proof that each assertion actually FIRES
# on a degenerate input (a QC gate that cannot fail is worse than none).

# Pan-cancer tumor-UP marker panel: genes robustly up-regulated in tumor vs
# normal across essentially every solid-tumor indication (cell-cycle /
# proliferation core). Used ONLY as a global-sign-inversion tripwire — NOT to
# validate biology and NOT applied to the normal-vs-normal cell AG. `+1` == the
# marker is expected UP in the positive ("tumor") group of a tumor-vs-normal
# contrast (cells A/B/C sign convention: log2FC > 0 == up in tumor).
TUMOR_UP_MARKER_PANEL <- c(
  MKI67 = 1, TOP2A = 1, PCNA = 1, CCNB1 = 1, CCNB2 = 1, CDK1 = 1,
  BIRC5 = 1, AURKA = 1, BUB1 = 1, CENPF = 1, FOXM1 = 1, UBE2C = 1
)

# Resolve the known-marker panel for an indication. Today every solid-tumor
# indication uses the pan-cancer proliferation tripwire; the argument is the
# hook a future indication-specific panel registers against. Returns a named
# numeric vector gene_symbol -> expected sign, or NULL to disable the check.
marker_panel_for <- function(indication = NULL) {
  TUMOR_UP_MARKER_PANEL
}

# Default fail-loud thresholds. Exposed as a function so tests can perturb one
# knob without redefining the rest, and so the drivers document the values in
# one place. Deliberately LOOSE where healthy biology is variable (a cross-cohort
# cell C legitimately has abundant DE and large effects) and TIGHT only on the
# unambiguous degeneracies.
qc_thresholds <- function() {
  list(
    min_rows              = 1L,    # zero-row parquet
    max_coherence_viol    = 0L,    # finite padj but NA shrunk LFC
    max_frac_p1_spike     = 0.5,   # >50% of tested genes piled at p>=0.99
    min_sign_markers      = 3L,    # need >=3 panel markers present to judge sign
    min_sign_concordance  = 0.5,   # < majority concordant == global inversion
    n_tested_warn_floor   = 1000L  # SOFT: implausibly few tested genes (warn only)
  )
}

# Compute the QC metrics record from the attr(fit,"qc") input list. PURE: takes
# vectors, returns a summary list — no DESeq2, no I/O. `qc = NULL` (e.g. an
# old cached fit predating S3a) yields list(available = FALSE); the assertion
# then skips loudly rather than failing open silently.
four_cell_qc_metrics <- function(qc) {
  if (is.null(qc)) return(list(available = FALSE))

  padj <- qc$padj; pval <- qc$pvalue; bm <- qc$baseMean; lfc <- qc$lfc
  n_genes <- length(padj)

  padj_na <- is.na(padj)
  pval_na <- is.na(pval)

  # padj=NA taxonomy — three DISJOINT, exhaustive causes (DESeq2 semantics):
  #   (1) independent filtering: gene WAS tested (pvalue present) but its low
  #       baseMean fell below the optimized filter, so padj is set NA.
  #   (2) all-zero / failed fit:  baseMean 0 (or NA) -> never fit, pvalue NA.
  #   (3) Cook's-distance outlier: baseMean > 0 (was fit) but an extreme count
  #       flagged the gene, so DESeq2 dropped its pvalue -> padj NA.
  na_indep_filter <- sum(padj_na & !pval_na)
  na_allzero      <- sum(padj_na & pval_na & (is.na(bm) | bm == 0))
  na_cooks        <- sum(padj_na & pval_na & !is.na(bm) & bm > 0)
  na_total        <- sum(padj_na)
  # Self-consistency of the partition (guards a future DESeq2 semantics change).
  na_taxonomy_exhaustive <- (na_indep_filter + na_allzero + na_cooks) == na_total

  n_tested <- sum(!pval_na)
  n_sig    <- sum(!padj_na & padj < 0.05)
  # Secondary FDR band + effect size of the significant set (S3b summary row).
  n_sig_010 <- sum(!padj_na & padj < 0.10)
  abs_lfc_sig <- abs(lfc[!padj_na & padj < 0.05])
  median_abs_lfc_sig <- if (any(is.finite(abs_lfc_sig)))
    stats::median(abs_lfc_sig[is.finite(abs_lfc_sig)]) else NA_real_

  # padj/LFC coherence: padj comes from the UNSHRUNK res_un, log2FC from the
  # apeglm-shrunk res. A gene tested to a finite padj must carry a finite shrunk
  # LFC; finite-padj-with-NA-LFC is an incoherent pairing (a real defect). The
  # reverse (NA padj, finite LFC) is EXPECTED — filtered genes still get a shrunk
  # estimate — so it is recorded but not asserted.
  finite_padj      <- !padj_na
  n_finite_padj_na_lfc <- sum(finite_padj & is.na(lfc))

  # p-value histogram: the informative pathologies are a p=1 SPIKE (broken null /
  # all-outlier fit) and a CONSERVATIVE HUMP (over-dispersion). A blanket KS test
  # is anti-conservative when DE is abundant, so it is deliberately NOT used.
  pv <- pval[!pval_na]
  frac_p1_spike <- if (length(pv)) mean(pv >= 0.99) else NA_real_
  frac_p_exact1 <- if (length(pv)) mean(pv == 1)    else NA_real_
  # hump ratio: high-tail density [0.9,1] relative to mid density [0.4,0.6].
  mid  <- if (length(pv)) mean(pv >= 0.4 & pv <= 0.6) else NA_real_
  high <- if (length(pv)) mean(pv >= 0.9)             else NA_real_
  hump_ratio <- if (isTRUE(mid > 0)) high / mid else NA_real_

  disp <- qc$dispersions
  frac_disp_na <- if (length(disp)) mean(is.na(disp)) else NA_real_
  all_disp_na  <- length(disp) > 0 && all(is.na(disp))
  max_disp     <- if (length(disp) && any(!is.na(disp))) max(disp, na.rm = TRUE) else NA_real_

  sf <- qc$size_factors
  sf_available <- !is.null(sf) && length(sf) > 0
  sf_nonfinite <- sf_available && any(!is.finite(sf))
  sf_nonpos    <- sf_available && any(sf[is.finite(sf)] <= 0)
  sf_range_ratio <- if (sf_available && any(is.finite(sf)) &&
                        min(sf[is.finite(sf)]) > 0)
                      max(sf[is.finite(sf)]) / min(sf[is.finite(sf)]) else NA_real_
  sf_min <- if (sf_available && any(is.finite(sf))) min(sf[is.finite(sf)]) else NA_real_
  sf_max <- if (sf_available && any(is.finite(sf))) max(sf[is.finite(sf)]) else NA_real_

  list(
    available              = TRUE,
    n_genes                = n_genes,
    n_tested               = n_tested,
    n_sig                  = n_sig,
    n_sig_010              = n_sig_010,
    median_abs_lfc_sig     = median_abs_lfc_sig,
    na_total               = na_total,
    na_indep_filter        = na_indep_filter,
    na_allzero             = na_allzero,
    na_cooks               = na_cooks,
    na_taxonomy_exhaustive = na_taxonomy_exhaustive,
    frac_padj_na           = if (n_genes) na_total / n_genes else NA_real_,
    all_padj_na            = n_genes > 0 && na_total == n_genes,
    all_lfc_na             = length(lfc) > 0 && all(is.na(lfc)),
    n_finite_padj_na_lfc   = n_finite_padj_na_lfc,
    frac_p1_spike          = frac_p1_spike,
    frac_p_exact1          = frac_p_exact1,
    hump_ratio             = hump_ratio,
    frac_disp_na           = frac_disp_na,
    all_disp_na            = all_disp_na,
    max_disp               = max_disp,
    sf_available           = sf_available,
    sf_nonfinite           = sf_nonfinite,
    sf_nonpos              = sf_nonpos,
    sf_range_ratio         = sf_range_ratio,
    sf_min                 = sf_min,
    sf_max                 = sf_max,
    n_tumor                = qc$n_tumor,
    n_normal               = qc$n_normal,
    n_genes_pre            = qc$n_genes_pre,
    n_genes_post           = qc$n_genes_post,
    filter_threshold       = qc$filter_threshold
  )
}

# Fail loud on a degenerate contrast. `fit` is the per-cell tidy frame (used for
# the row-count + required-column schema check and the per-gene sign panel);
# `metrics` is the four_cell_qc_metrics() record; `label` names the cell (A/B/C/
# AG); `panel` is a gene->sign vector or NULL (NULL disables the sign check, as
# for the normal-vs-normal cell AG). Raises via stop() — an unhandled stop() in a
# driver exits non-zero, which is exactly "the run stops instead of writing
# silently". Returns invisibly TRUE when all checks pass, FALSE when QC was
# skipped (no inputs). The FATAL set is deliberately narrow: only the unambiguous
# degeneracies the issue enumerates; the softer signals (NA taxonomy breakdown,
# dispersion pile, conservative hump, n-tested band) are reported, not enforced.
assert_contrast_qc <- function(fit, metrics, label = "", panel = NULL,
                               indication = NULL, thresholds = qc_thresholds(),
                               emit = message) {
  tag  <- sprintf("[qc:%s]", label)
  fail <- function(...) stop(tag, " FAIL-LOUD output-QC: ", ..., call. = FALSE)

  if (isFALSE(metrics$available)) {
    emit(paste0(tag, " no QC inputs on this fit (a cache predating S3a?) — QC ",
                "SKIPPED; rerun without the _cell_*.rds cache to QC it"))
    return(invisible(FALSE))
  }

  # (1) row-count > 0 + schema / required columns.
  if (nrow(fit) < thresholds$min_rows) {
    fail(sprintf("%d rows (< %d) — a zero-row / empty-result contrast",
                 nrow(fit), thresholds$min_rows))
  }
  required <- c("gene_symbol", paste0("log2fc_", label),
                paste0("padj_", label), paste0("baseMean_", label))
  missing_cols <- setdiff(required, names(fit))
  if (length(missing_cols)) {
    fail("missing required column(s): ", paste(missing_cols, collapse = ", "))
  }

  # (2) all-NaN cell (the documented SCLC A/B degeneracy) — nothing usable.
  if (metrics$n_tested == 0) {
    fail("0 of ", metrics$n_genes, " genes were tested (every p-value NA) — ",
         "the all-NaN cell degeneracy")
  }
  if (isTRUE(metrics$all_padj_na)) {
    fail("every gene has padj=NA — all-NaN cell (no significant-call is possible)")
  }
  if (isTRUE(metrics$all_lfc_na)) {
    fail("every gene has NA shrunk log2FC — apeglm shrinkage failed globally")
  }

  # (3) padj/LFC coherence.
  if (metrics$n_finite_padj_na_lfc > thresholds$max_coherence_viol) {
    fail(sprintf(paste0("%d genes have a finite padj but NA shrunk log2FC — ",
                        "padj(res_un) / LFC(apeglm) incoherence"),
                 metrics$n_finite_padj_na_lfc))
  }

  # (4) dispersion-fit health (fatal only on a wholesale failure).
  if (isTRUE(metrics$all_disp_na)) {
    fail("all gene-wise dispersions are NA — the dispersion fit failed")
  }

  # (5) size-factor sanity (poscounts): a factor must be finite and > 0.
  if (isTRUE(metrics$sf_available) && (metrics$sf_nonfinite || metrics$sf_nonpos)) {
    fail("non-finite or non-positive poscounts size factor(s) — normalization failed")
  }

  # (6) p-value histogram: a pathological p=1 spike (NOT a KS test).
  if (isTRUE(is.finite(metrics$frac_p1_spike)) &&
      metrics$frac_p1_spike > thresholds$max_frac_p1_spike) {
    fail(sprintf(paste0("p-value spike: %.0f%% of %d tested genes at p>=0.99 ",
                        "(> %.0f%%) — pathological null / broken fit"),
                 100 * metrics$frac_p1_spike, metrics$n_tested,
                 100 * thresholds$max_frac_p1_spike))
  }

  # (7) sign sanity vs a per-indication known-marker panel (NOT a global stat).
  #     Guards a globally sign-inverted contrast. Skipped when the panel is NULL
  #     (cell AG) or too few markers survived the prefilter to judge.
  if (!is.null(panel) && length(panel)) {
    lfc_col <- paste0("log2fc_", label)
    present <- intersect(names(panel), fit$gene_symbol)
    if (length(present)) {
      lfcv <- fit[[lfc_col]][match(present, fit$gene_symbol)]
      keep <- is.finite(lfcv)
      present <- present[keep]; lfcv <- lfcv[keep]
    }
    if (length(present) >= thresholds$min_sign_markers) {
      concordance <- mean(sign(lfcv) == sign(panel[present]))
      if (concordance < thresholds$min_sign_concordance) {
        fail(sprintf(paste0("known-marker sign concordance %.2f (< %.2f) over %d ",
                            "markers {%s} — likely a GLOBAL SIGN INVERSION ",
                            "(contrast wired backwards)"),
                     concordance, thresholds$min_sign_concordance,
                     length(present), paste(present, collapse = ",")))
      }
    } else {
      emit(sprintf(paste0("%s sign panel: only %d marker(s) present (< %d) — ",
                          "sign check skipped"),
                   tag, length(present), thresholds$min_sign_markers))
    }
  }

  # Non-fatal reporting of the softer signals (visible in the run log / prov).
  if (!isTRUE(metrics$na_taxonomy_exhaustive)) {
    emit(sprintf(paste0("%s WARN: padj=NA taxonomy does not partition ",
                        "exhaustively (indep=%d allzero=%d cooks=%d total=%d) ",
                        "— DESeq2 NA semantics may have changed"),
                 tag, metrics$na_indep_filter, metrics$na_allzero,
                 metrics$na_cooks, metrics$na_total))
  }
  if (isTRUE(metrics$n_tested < thresholds$n_tested_warn_floor)) {
    emit(sprintf(paste0("%s WARN: only %d genes tested (< %d) post-prefilter ",
                        "— unusually thin for a bulk cohort"),
                 tag, metrics$n_tested, thresholds$n_tested_warn_floor))
  }
  emit(sprintf(paste0("%s QC OK: %d genes | %d tested | %d sig(padj<0.05) | ",
                      "padj=NA %d (indep %d / cooks %d / allzero %d) | ",
                      "p>=0.99 %.1f%% | n_tumor %d n_normal %d"),
               tag, metrics$n_genes, metrics$n_tested, metrics$n_sig,
               metrics$na_total, metrics$na_indep_filter, metrics$na_cooks,
               metrics$na_allzero,
               100 * (if (is.finite(metrics$frac_p1_spike)) metrics$frac_p1_spike else 0),
               as.integer(metrics$n_tumor %||% -1L),
               as.integer(metrics$n_normal %||% -1L)))
  invisible(TRUE)
}
