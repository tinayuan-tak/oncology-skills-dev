#!/usr/bin/env Rscript
# _qc_figures.R — per-contrast QC report bundle for the four-cell DESeq2 compute
# (S3b, github analysis-methods#702; sibling of the S3a fail-loud assertion layer
# in _four_cell_lib.R).
#
# S3a stopped the run on a DEGENERATE contrast; S3b makes every NON-degenerate
# contrast INDEPENDENTLY INSPECTABLE: for every DE performed (per substrate x
# indication x cell A/B/C/AG) it emits a per-run QC bundle — a figures/ dir of
# diagnostic PNGs plus a machine-readable metrics row — stored alongside that
# contrast's parquet. A separate cross-indication index (scripts, tested there)
# concatenates the per-run metrics rows.
#
# DESIGN (mirrors S3a's attr(fit,"qc") pattern so it is BYTE-IDENTITY-SAFE and
# HERMETICALLY TESTABLE):
#   * deseq2_fit() stashes the figure inputs the diagnostics need but the tidy
#     parquet columns drop — the top-variable-gene VST matrix, the dispersion
#     trend triplet (gene-est / fitted / final) + baseMean, per-sample library
#     sizes, and a sample-metadata frame (group + whatever covariates are
#     present: source / tcga_tss batch / SMRIN) — as attr(out,"fig"). Attributes
#     do NOT serialize to parquet, so every emitted contrast parquet stays
#     byte-identical (the S3a invariant, re-used).
#   * The renderers below are PURE functions of explicit vectors/matrices (no
#     DESeq2 object, no dds), so the whole bundle is driven by a synthetic fit in
#     the tests — no full DESeq2 run — exactly like test_output_qc_assertions.
#   * Base graphics only (grDevices png(type="cairo")): NO ggplot2 / pheatmap
#     dependency is added, and nothing here can perturb the fit.
#
# Result diagnostics (MA / p-value histogram / volcano / independent-filtering
# threshold) render from attr(fit,"qc") ALONE, so even a fit cached before S3b
# (no "fig" attr) still gets them; the sample-level trio (PCA / sample-distance /
# library-size) and the full three-component plotDispEsts need attr(fit,"fig"),
# so on a pre-S3b cache they are skipped LOUDLY (never fail open) — same rule as
# S3a's pre-qc-attr cache skip.

suppressWarnings(suppressMessages({
  # RColorBrewer is a light, always-present palette helper in this pixi env; a
  # base fallback keeps the renderers usable without it.
  .have_brewer <- requireNamespace("RColorBrewer", quietly = TRUE)
}))

# Minimum plausible size (bytes) of a real cairo PNG. A device that opened but
# drew nothing still emits a valid ~1-3KB header+background; a truly failed write
# is 0 bytes / absent. emit_qc_bundle() asserts every rendered figure clears this
# so "the bundle silently came out empty" is a hard failure, not a green test.
QC_FIG_MIN_BYTES <- 800L

# Palette for a small set of discrete groups. Deterministic so figures are stable.
.qc_group_colors <- function(levels) {
  n <- length(levels)
  if (n == 0) return(character(0))
  pal <- if (.have_brewer && n >= 3 && n <= 8) {
    RColorBrewer::brewer.pal(n, "Set1")
  } else {
    grDevices::palette.colors(max(n, 2), palette = "Okabe-Ito")[seq_len(n)]
  }
  stats::setNames(pal, levels)
}

# Open a cairo PNG device, evaluate the drawing expression, and ALWAYS close the
# device (on.exit) so a drawing error cannot leave a dangling device open across
# the rest of the bundle. Returns the path invisibly.
.qc_render_png <- function(path, draw, width = 1000L, height = 800L, res = 120L) {
  grDevices::png(filename = path, width = width, height = height, res = res,
                 type = "cairo")
  on.exit(grDevices::dev.off(), add = TRUE)
  draw()
  invisible(path)
}

`.qc_finite` <- function(x) x[is.finite(x)]

# ---------------------------------------------------------------------------
# Model-diagnostic figures
# ---------------------------------------------------------------------------

# plotDispEsts equivalent (three-component): gene-wise estimate (black), fitted
# trend (red), final MAP dispersion (blue), on log-log axes vs baseMean.
fig_disp_ests <- function(baseMean, disp_gene_est, disp_fit, disp_final, path,
                          title = "Dispersion estimates") {
  ok <- is.finite(baseMean) & baseMean > 0
  if (!any(ok)) stop("fig_disp_ests: no positive baseMean values to plot")
  .qc_render_png(path, function() {
    graphics::plot(baseMean[ok], pmax(disp_gene_est[ok], 1e-8), log = "xy",
                   pch = 16, cex = 0.35, col = grDevices::adjustcolor("black", 0.4),
                   xlab = "mean of normalized counts", ylab = "dispersion",
                   main = title)
    fo <- order(baseMean[ok])
    if (any(is.finite(disp_fit[ok]))) {
      graphics::lines(baseMean[ok][fo], disp_fit[ok][fo], col = "red", lwd = 2)
    }
    if (any(is.finite(disp_final[ok]))) {
      graphics::points(baseMean[ok], disp_final[ok], pch = 16, cex = 0.3,
                       col = grDevices::adjustcolor("dodgerblue", 0.4))
    }
    graphics::legend("bottomleft", bty = "n",
                     legend = c("gene-est", "fitted", "final (MAP)"),
                     col = c("black", "red", "dodgerblue"),
                     pch = c(16, NA, 16), lwd = c(NA, 2, NA))
  })
}

# Independent-filtering threshold: ECDF of baseMean with a vertical line at the
# optimized filter threshold and the count of genes filtered out below it.
fig_indep_filter <- function(baseMean, padj, pvalue, filter_threshold, path,
                             title = "Independent-filtering threshold") {
  bm <- .qc_finite(baseMean)
  if (!length(bm)) stop("fig_indep_filter: no finite baseMean values")
  # Genes set NA by independent filtering = tested (finite pvalue) but padj NA.
  n_filt <- sum(is.na(padj) & !is.na(pvalue))
  .qc_render_png(path, function() {
    graphics::plot(stats::ecdf(log10(bm + 1)), main = title,
                   xlab = "log10(baseMean + 1)", ylab = "cumulative fraction of genes",
                   pch = ".", col = "grey30")
    if (is.finite(filter_threshold) && filter_threshold > 0) {
      graphics::abline(v = log10(filter_threshold + 1), col = "red", lwd = 2, lty = 2)
      graphics::legend("bottomright", bty = "n",
                       legend = c(sprintf("filter threshold = %.3g", filter_threshold),
                                  sprintf("%d genes filtered (padj=NA, indep.)", n_filt)),
                       col = c("red", NA), lwd = c(2, NA), lty = c(2, NA))
    }
  })
}

# ---------------------------------------------------------------------------
# Result-diagnostic figures
# ---------------------------------------------------------------------------

# MA plot on the apeglm-shrunk log2FC. x = mean expression, y = shrunk LFC,
# significant genes (padj < alpha) highlighted.
fig_ma <- function(baseMean, lfc, padj, path, alpha = 0.05,
                   title = "MA plot (apeglm-shrunk)") {
  ok <- is.finite(baseMean) & baseMean > 0 & is.finite(lfc)
  if (!any(ok)) stop("fig_ma: no plottable (finite baseMean & LFC) genes")
  sig <- ok & !is.na(padj) & padj < alpha
  .qc_render_png(path, function() {
    graphics::plot(baseMean[ok], lfc[ok], log = "x", pch = 16, cex = 0.35,
                   col = grDevices::adjustcolor("grey40", 0.4),
                   xlab = "mean of normalized counts", ylab = "log2 fold change (shrunk)",
                   main = title)
    if (any(sig)) {
      graphics::points(baseMean[sig], lfc[sig], pch = 16, cex = 0.4,
                       col = grDevices::adjustcolor("red", 0.6))
    }
    graphics::abline(h = 0, col = "blue", lwd = 1.5)
    graphics::legend("topright", bty = "n",
                     legend = c(sprintf("sig (padj<%.2g): %d", alpha, sum(sig)),
                                sprintf("not sig: %d", sum(ok) - sum(sig))),
                     col = c("red", "grey40"), pch = 16)
  })
}

# Raw p-value histogram. The informative pathologies (a p=1 spike, a conservative
# hump) read straight off this; S3a already fails loud on the extreme spike.
fig_pvalue_hist <- function(pvalue, path, title = "Raw p-value histogram") {
  pv <- pvalue[!is.na(pvalue)]
  if (!length(pv)) stop("fig_pvalue_hist: no non-NA p-values")
  .qc_render_png(path, function() {
    graphics::hist(pv, breaks = seq(0, 1, by = 0.025), col = "grey70",
                   border = "white", xlab = "raw Wald p-value",
                   main = sprintf("%s (n tested = %d)", title, length(pv)))
  })
}

# Volcano: shrunk LFC vs -log10(padj). padj == 0 is capped to the smallest finite
# positive padj so the point plots instead of vanishing at +Inf.
fig_volcano <- function(lfc, padj, path, alpha = 0.05,
                        title = "Volcano (LFC vs -log10 padj)") {
  ok <- is.finite(lfc) & !is.na(padj)
  if (!any(ok)) stop("fig_volcano: no genes with finite LFC and non-NA padj")
  p <- padj[ok]
  pos <- p[p > 0]
  floor_p <- if (length(pos)) min(pos) else .Machine$double.eps
  p[p <= 0] <- floor_p
  y <- -log10(p)
  x <- lfc[ok]
  sig <- p < alpha
  .qc_render_png(path, function() {
    graphics::plot(x, y, pch = 16, cex = 0.35,
                   col = grDevices::adjustcolor("grey40", 0.4),
                   xlab = "log2 fold change (shrunk)", ylab = "-log10(padj)",
                   main = title)
    if (any(sig)) {
      graphics::points(x[sig], y[sig], pch = 16, cex = 0.4,
                       col = grDevices::adjustcolor("red", 0.6))
    }
    graphics::abline(h = -log10(alpha), col = "blue", lwd = 1, lty = 2)
    graphics::legend("topleft", bty = "n",
                     legend = sprintf("sig (padj<%.2g): %d", alpha, sum(sig)),
                     col = "red", pch = 16)
  })
}

# ---------------------------------------------------------------------------
# Sample-level figures (need attr(fit,"fig"): VST + per-sample metadata)
# ---------------------------------------------------------------------------

# PCA on the top-variable-gene VST matrix (genes x samples), colored by `groups`.
fig_pca <- function(vst_mat, groups, path, color_label = "group",
                    title = NULL) {
  if (is.null(vst_mat) || ncol(vst_mat) < 3) {
    stop("fig_pca: need >= 3 samples for a PCA")
  }
  groups <- as.character(groups)
  # prcomp expects samples as rows; center per gene, no scaling (VST is on a
  # comparable scale across genes already).
  pc <- stats::prcomp(t(vst_mat), center = TRUE, scale. = FALSE)
  ve <- (pc$sdev^2) / sum(pc$sdev^2)
  lv <- sort(unique(groups))
  cols <- .qc_group_colors(lv)
  ttl <- title %||% sprintf("PCA on VST (top %d var genes) by %s",
                            nrow(vst_mat), color_label)
  .qc_render_png(path, function() {
    graphics::plot(pc$x[, 1], pc$x[, 2], pch = 16, cex = 0.9,
                   col = cols[groups],
                   xlab = sprintf("PC1 (%.1f%%)", 100 * ve[1]),
                   ylab = sprintf("PC2 (%.1f%%)", 100 * ve[2]),
                   main = ttl)
    graphics::legend("topright", bty = "n", legend = lv, col = cols[lv], pch = 16)
  })
}

# Sample-to-sample Euclidean distance on the top-variable VST, clustered heatmap.
fig_sample_distance <- function(vst_mat, groups, path,
                                title = "Sample-to-sample distance (VST)") {
  if (is.null(vst_mat) || ncol(vst_mat) < 2) {
    stop("fig_sample_distance: need >= 2 samples")
  }
  d <- as.matrix(stats::dist(t(vst_mat)))
  groups <- as.character(groups)
  lv <- sort(unique(groups))
  cols <- .qc_group_colors(lv)
  side <- cols[groups]
  .qc_render_png(path, function() {
    stats::heatmap(d, symm = TRUE, RowSideColors = side, ColSideColors = side,
                   margins = c(6, 6), main = title,
                   col = grDevices::hcl.colors(64, "Blues", rev = TRUE),
                   labRow = NA, labCol = NA)
    graphics::legend("topright", bty = "n", legend = lv, fill = cols[lv],
                     cex = 0.8)
  }, width = 1100L, height = 1000L)
}

# Per-sample library size + poscounts size factor (colored by group), with an
# optional RIN overlay where SMRIN is loaded.
fig_libsize_sizefactor <- function(lib_size, size_factors, groups, rin = NULL,
                                   path, title = "Library size & size factors") {
  if (!length(lib_size)) stop("fig_libsize_sizefactor: no library sizes")
  groups <- as.character(groups)
  lv <- sort(unique(groups))
  cols <- .qc_group_colors(lv)
  have_rin <- !is.null(rin) && any(is.finite(rin))
  .qc_render_png(path, function() {
    graphics::par(mfrow = c(if (have_rin) 1 else 1, if (have_rin) 2 else 1),
                  mar = c(4.5, 4.5, 3, 1))
    graphics::plot(lib_size, size_factors, log = "x", pch = 16, cex = 0.9,
                   col = cols[groups], xlab = "library size (total counts)",
                   ylab = "poscounts size factor",
                   main = title)
    graphics::legend("topleft", bty = "n", legend = lv, col = cols[lv], pch = 16)
    if (have_rin) {
      graphics::plot(rin, size_factors, pch = 16, cex = 0.9, col = cols[groups],
                     xlab = "RIN (SMRIN)", ylab = "poscounts size factor",
                     main = "Size factor vs RIN")
    }
  }, width = if (have_rin) 1400L else 900L, height = 700L)
}

# ---------------------------------------------------------------------------
# Summary row + bundle orchestrator
# ---------------------------------------------------------------------------

# Build the one-row per-contrast metrics table from the S3a metrics record.
# PURE: takes the four_cell_qc_metrics() list, returns a 1-row data.frame with
# the columns #702 enumerates. n_figures / figures are stamped by emit_qc_bundle.
four_cell_summary_row <- function(metrics, label, indication = NA_character_,
                                  substrate = NA_character_,
                                  n_figures = NA_integer_, figures = NA_character_) {
  if (isFALSE(metrics$available)) {
    stop("four_cell_summary_row: metrics record is unavailable (no qc inputs)")
  }
  data.frame(
    indication          = as.character(indication),
    substrate           = as.character(substrate),
    cell                = as.character(label),
    n_tumor             = as.integer(metrics$n_tumor %||% NA_integer_),
    n_normal            = as.integer(metrics$n_normal %||% NA_integer_),
    genes_pre_filter    = as.integer(metrics$n_genes_pre %||% NA_integer_),
    genes_post_filter   = as.integer(metrics$n_genes_post %||% NA_integer_),
    n_filtered_indep    = as.integer(metrics$na_indep_filter %||% NA_integer_),
    n_filtered_cooks    = as.integer(metrics$na_cooks %||% NA_integer_),
    n_sig_fdr05         = as.integer(metrics$n_sig %||% NA_integer_),
    n_sig_fdr10         = as.integer(metrics$n_sig_010 %||% NA_integer_),
    median_abs_lfc_sig  = as.numeric(metrics$median_abs_lfc_sig %||% NA_real_),
    size_factor_min     = as.numeric(metrics$sf_min %||% NA_real_),
    size_factor_max     = as.numeric(metrics$sf_max %||% NA_real_),
    size_factor_ratio   = as.numeric(metrics$sf_range_ratio %||% NA_real_),
    n_tested            = as.integer(metrics$n_tested %||% NA_integer_),
    n_figures           = as.integer(n_figures),
    figures             = as.character(figures),
    stringsAsFactors = FALSE
  )
}

# Emit the per-contrast QC bundle (figures/ + metrics.csv) for ONE completed
# fit into `bundle_dir`. PURE function of the fit's attributes:
#   attr(fit,"qc")         — result diagnostics (always; from S3a)
#   attr(fit,"qc_metrics") — the S3a metrics record (recomputed if absent)
#   attr(fit,"fig")        — sample-level + full-dispersion inputs (S3b)
#
# The anti-"empty-bundle" discipline: every figure the available inputs SUPPORT
# is planned; each is rendered then asserted present and >= QC_FIG_MIN_BYTES; an
# individual renderer error is caught and recorded (a bad PCA must not kill a
# production run after the parquet is safely written) but a bundle that produces
# ZERO figures stop()s loud. The returned row carries n_figures so the tests (and
# the cross-indication index) can reconcile the COUNT, not merely "a dir exists".
emit_qc_bundle <- function(fit, bundle_dir, label, indication = NA_character_,
                           substrate = NA_character_, alpha = 0.05,
                           emit = message) {
  qc <- attr(fit, "qc")
  metrics <- attr(fit, "qc_metrics") %||% four_cell_qc_metrics(qc)
  tag <- sprintf("[qc-bundle:%s]", label)
  if (is.null(qc) || isFALSE(metrics$available)) {
    emit(paste0(tag, " no QC inputs on this fit (a cache predating S3a?) — ",
                "QC bundle SKIPPED; rerun without the _cell_*.rds cache to emit it"))
    return(invisible(NULL))
  }
  fig_dir <- file.path(bundle_dir, "figures")
  dir.create(fig_dir, showWarnings = FALSE, recursive = TRUE)

  rendered <- character(0)
  failed   <- character(0)
  # `plan` names a figure and the thunk that draws it; a NULL thunk means the
  # inputs for that figure are absent (skipped, not failed).
  attempt <- function(name, thunk) {
    if (is.null(thunk)) return(invisible())
    path <- file.path(fig_dir, name)
    res <- tryCatch({ thunk(path); TRUE },
                    error = function(e) { emit(sprintf("%s WARN: figure %s failed: %s",
                                                       tag, name, conditionMessage(e)));
                                          FALSE })
    sz <- if (file.exists(path)) file.info(path)$size else -1
    if (isTRUE(res) && is.finite(sz) && sz >= QC_FIG_MIN_BYTES) {
      rendered <<- c(rendered, name)
    } else {
      failed <<- c(failed, name)
      if (isTRUE(res)) {
        emit(sprintf("%s WARN: figure %s is empty/undersized (%d bytes < %d)",
                     tag, name, as.integer(sz), QC_FIG_MIN_BYTES))
      }
    }
  }

  # --- result diagnostics (from qc alone) ---
  attempt("ma_plot.png",
          function(p) fig_ma(qc$baseMean, qc$lfc, qc$padj, p, alpha = alpha))
  attempt("pvalue_hist.png",
          function(p) fig_pvalue_hist(qc$pvalue, p))
  attempt("volcano.png",
          function(p) fig_volcano(qc$lfc, qc$padj, p, alpha = alpha))
  attempt("indep_filter.png",
          function(p) fig_indep_filter(qc$baseMean, qc$padj, qc$pvalue,
                                       qc$filter_threshold, p))

  # --- model + sample-level diagnostics (need attr(fit,"fig")) ---
  fg <- attr(fit, "fig")
  if (is.null(fg)) {
    emit(paste0(tag, " no attr(fit,\"fig\") (a cache predating S3b?) — the ",
                "sample-level trio + full plotDispEsts are SKIPPED (result ",
                "diagnostics still emitted)"))
  } else {
    attempt("disp_ests.png",
            if (!is.null(fg$disp_gene_est))
              function(p) fig_disp_ests(fg$baseMean, fg$disp_gene_est, fg$disp_fit,
                                        fg$disp_final, p) else NULL)
    vst <- fg$vst; sm <- fg$sample_meta
    have_vst <- !is.null(vst) && !is.null(sm) && ncol(vst) >= 3
    attempt("pca_group.png",
            if (have_vst) function(p) fig_pca(vst, sm$group, p, "group") else NULL)
    # Extra PCA colorings for whatever covariates the cell carries (cross-cohort
    # source, ComBat batch): only when the column exists and has >1 level.
    for (cov in c("source", "tcga_tss")) {
      has_cov <- have_vst && !is.null(sm[[cov]]) &&
        length(unique(stats::na.omit(sm[[cov]]))) > 1
      local({
        cv <- cov
        attempt(sprintf("pca_%s.png", cv),
                if (has_cov) function(p) fig_pca(vst, sm[[cv]], p, cv) else NULL)
      })
    }
    attempt("sample_distance.png",
            if (have_vst && ncol(vst) >= 2)
              function(p) fig_sample_distance(vst, sm$group, p) else NULL)
    attempt("libsize_sizefactor.png",
            if (!is.null(fg$lib_size) && !is.null(qc$size_factors) &&
                length(fg$lib_size) == length(qc$size_factors))
              function(p) fig_libsize_sizefactor(fg$lib_size, qc$size_factors,
                                                 sm$group, rin = sm$SMRIN, p) else NULL)
  }

  if (length(rendered) == 0) {
    stop(sprintf("%s FAIL-LOUD: QC bundle produced ZERO figures (failed: %s) — ",
                 tag, paste(failed, collapse = ", ")),
         "an empty bundle is a defect, not a pass", call. = FALSE)
  }

  row <- four_cell_summary_row(metrics, label, indication = indication,
                               substrate = substrate,
                               n_figures = length(rendered),
                               figures = paste(rendered, collapse = ";"))
  utils::write.csv(row, file.path(bundle_dir, "metrics.csv"), row.names = FALSE)
  emit(sprintf("%s wrote %d figure(s) + metrics.csv to %s%s",
               tag, length(rendered), bundle_dir,
               if (length(failed)) sprintf(" (%d failed: %s)",
                                           length(failed), paste(failed, collapse = ",")) else ""))
  invisible(row)
}
