"""Per-contrast QC report bundle (S3b, github analysis-methods#702).

For every DE performed, the R drivers emit a QC bundle (figures/*.png + a metrics
row) beside that contrast's parquet. THE WHOLE RISK OF THIS STAGE is a figure/
bundle test that reads green because the bundle silently came out EMPTY (zero
figures, a header-only metrics row). So these tests never merely check "a bundle
dir exists":

  * they reconcile the figure COUNT against what the synthetic inputs support,
    and assert every figure is present and > a byte floor (not a 0-byte stub);
  * they assert the metrics row's enumerated columns are POPULATED (not NA);
  * they prove the ``attr(fit,"fig")`` capture is load-bearing — the SAME fit
    with the fig attr removed emits exactly the 4 result-diagnostic figures and
    drops the 5 sample-level / dispersion figures (a mutation-style delta), so a
    future edit that stops capturing figure inputs is caught by the count, not
    absorbed;
  * they prove ``emit_qc_bundle`` FAILS LOUD (stop) on a fit that can produce
    zero figures, so an empty bundle is a hard failure rather than a pass.

Hermetic: ``emit_qc_bundle`` / the renderers are pure functions of the attributes
``deseq2_fit`` stashes (attr(fit,"qc") from S3a + attr(fit,"fig") from S3b), so
the fixtures are built directly in R with no DESeq2 run (mirrors
test_output_qc_assertions). A full end-to-end run is deliberately NOT used.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

METHODS_REPO = Path(__file__).resolve().parents[3]
LIB_PATH = METHODS_REPO / "onc_methods" / "dge_deseq2" / "r" / "live" / "_four_cell_lib.R"
FIG_PATH = METHODS_REPO / "onc_methods" / "dge_deseq2" / "r" / "live" / "_qc_figures.R"

# The figures a healthy fit WITH a fig attr must produce (no tcga_tss covariate
# in the fixture, so pca_tcga_tss is intentionally absent).
RESULT_FIGURES = {"ma_plot.png", "pvalue_hist.png", "volcano.png", "indep_filter.png"}
FIG_ATTR_FIGURES = {
    "disp_ests.png",
    "pca_group.png",
    "pca_source.png",
    "sample_distance.png",
    "libsize_sizefactor.png",
}
ALL_FIGURES = RESULT_FIGURES | FIG_ATTR_FIGURES

# Enumerated per-contrast summary columns (#702) that must be non-empty for a
# healthy contrast — the "header-only metrics row" trap.
POPULATED_METRIC_COLS = [
    "n_tumor",
    "n_normal",
    "genes_pre_filter",
    "genes_post_filter",
    "n_sig_fdr05",
    "n_sig_fdr10",
    "median_abs_lfc_sig",
    "size_factor_min",
    "size_factor_max",
    "n_figures",
]


def _resolve_rscript() -> str | None:
    candidates = [
        Path(sys.executable).parent / "Rscript",
        METHODS_REPO / ".pixi" / "envs" / "default" / "bin" / "Rscript",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which("Rscript")


RSCRIPT = _resolve_rscript()

# Builds a healthy synthetic fit (attr qc + attr fig), emits the bundle WITH and
# WITHOUT the fig attr into $OUT_DIR/{with_fig,no_fig}, and proves the zero-figure
# guard fires. Prints ALL_OK only if the in-R invariants hold; the Python side
# then independently reconciles the file counts/sizes and the metrics row.
R_SCRIPT = r"""
source(Sys.getenv("FOUR_CELL_LIB_PATH"))
source(Sys.getenv("QC_FIGURES_PATH"))
out_dir <- Sys.getenv("OUT_DIR")

set.seed(42)
ng <- 200L        # genes in the fit / qc + dispersion vectors
ns <- 12L         # samples (>= 3 for PCA); 6 positive ("tumor") + 6 reference
genes <- paste0("g", seq_len(ng))

baseMean <- 10^runif(ng, 0.5, 4)
lfc      <- rnorm(ng, 0, 1.2)
pvalue   <- runif(ng)
pvalue[1:20] <- 10^-runif(20, 3, 8)          # a real signal head
padj     <- p.adjust(pvalue, method = "BH")
padj[sample(seq_len(ng), 30)] <- NA          # some filtered / cooks
disp_gene_est <- pmax(rnorm(ng, 0.1, 0.03), 1e-3)
disp_fit      <- rep(0.1, ng)
disp_final    <- pmax(rnorm(ng, 0.1, 0.02), 1e-3)
size_factors  <- runif(ns, 0.7, 1.4)
lib_size      <- as.numeric(round(size_factors * 2e7))

# VST on 40 top-var genes x 12 samples with genuine group separation, plus a
# secondary axis correlated with `source` so PCA-by-source is meaningful.
nv <- 40L
grp    <- rep(c("tumor", "normal"), each = ns / 2)
src    <- rep(c("TCGA", "GTEx"), times = ns / 2)
vst <- matrix(rnorm(nv * ns, 8, 1), nrow = nv, ncol = ns,
              dimnames = list(paste0("v", seq_len(nv)), paste0("s", seq_len(ns))))
vst[1:15, grp == "tumor"] <- vst[1:15, grp == "tumor"] + 3     # group axis
vst[16:25, src == "GTEx"] <- vst[16:25, src == "GTEx"] + 2     # source axis
sample_meta <- data.frame(group = grp, source = src,
                          SMRIN = runif(ns, 6, 9),
                          row.names = paste0("s", seq_len(ns)),
                          stringsAsFactors = FALSE)

mkfit <- function(lab) {
  df <- data.frame(gene_symbol = genes, stringsAsFactors = FALSE)
  df[[paste0("log2fc_",   lab)]] <- lfc
  df[[paste0("padj_",     lab)]] <- padj
  df[[paste0("baseMean_", lab)]] <- baseMean
  attr(df, "qc") <- list(
    gene_symbol = genes, pvalue = pvalue, padj = padj, baseMean = baseMean, lfc = lfc,
    dispersions = disp_final, size_factors = size_factors, filter_threshold = 8,
    n_tumor = 6L, n_normal = 6L, n_genes_pre = ng + 50L, n_genes_post = ng)
  attr(df, "fig") <- list(
    vst = vst, n_top_var = nv, baseMean = baseMean,
    disp_gene_est = disp_gene_est, disp_fit = disp_fit, disp_final = disp_final,
    lib_size = lib_size, sample_meta = sample_meta)
  df
}

fit <- mkfit("C")
q <- function(...) invisible()   # silence emit()

row_full <- emit_qc_bundle(fit, file.path(out_dir, "with_fig"), "C",
                           indication = "COADREAD", substrate = "recount3", emit = q)
stopifnot("with-fig row is one row" = nrow(row_full) == 1,
          "with-fig n_figures matches rendered" =
            row_full$n_figures == length(strsplit(row_full$figures, ";")[[1]]))

# Same fit, fig attr removed -> only the result diagnostics remain (load-bearing).
fit_nofig <- fit
attr(fit_nofig, "fig") <- NULL
row_nofig <- emit_qc_bundle(fit_nofig, file.path(out_dir, "no_fig"), "C",
                            indication = "COADREAD", substrate = "recount3", emit = q)
stopifnot(
  "removing the fig attr drops exactly the sample-level+disp figures" =
    (row_full$n_figures - row_nofig$n_figures) == 5L,
  "no-fig keeps the 4 result diagnostics" = row_nofig$n_figures == 4L)

# Zero-figure guard: a fit whose qc is present but carries empty vectors can
# render no figure at all -> emit_qc_bundle must stop() loud, not write an empty
# bundle and return.
fit_empty <- data.frame(gene_symbol = character(0), log2fc_C = numeric(0),
                        padj_C = numeric(0), baseMean_C = numeric(0),
                        stringsAsFactors = FALSE)
attr(fit_empty, "qc") <- list(
  gene_symbol = character(0), pvalue = numeric(0), padj = numeric(0),
  baseMean = numeric(0), lfc = numeric(0), dispersions = numeric(0),
  size_factors = numeric(0), filter_threshold = NA_real_,
  n_tumor = 0L, n_normal = 0L, n_genes_pre = 0L, n_genes_post = 0L)
fired <- tryCatch({ emit_qc_bundle(fit_empty, file.path(out_dir, "empty"), "C",
                                   emit = q); FALSE },
                  error = function(e) grepl("ZERO figures", conditionMessage(e)))
stopifnot("empty-producing fit fails loud with a ZERO-figures message" = isTRUE(fired))

# A fit with NO qc attr at all (a pre-S3a cache) -> skipped, returns NULL,
# never stop()s.
fit_stale <- fit
attr(fit_stale, "qc") <- NULL
attr(fit_stale, "qc_metrics") <- NULL
res_stale <- emit_qc_bundle(fit_stale, file.path(out_dir, "stale"), "C", emit = q)
stopifnot("stale (no qc) cache is skipped, not failed" = is.null(res_stale))

cat("ALL_OK\n")
"""


@pytest.mark.skipif(RSCRIPT is None, reason="No Rscript in the pixi env or on PATH")
def test_qc_bundle_emits_reconciled_figures_and_metrics(tmp_path):
    script_path = tmp_path / "run_qc_bundle.R"
    script_path.write_text(R_SCRIPT)
    out_dir = tmp_path / "bundles"
    out_dir.mkdir()
    result = subprocess.run(
        [RSCRIPT, "--vanilla", str(script_path)],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "FOUR_CELL_LIB_PATH": str(LIB_PATH),
            "QC_FIGURES_PATH": str(FIG_PATH),
            "OUT_DIR": str(out_dir),
        },
    )
    assert "ALL_OK" in result.stdout, (
        f"R QC-bundle invariants failed (exit {result.returncode}):\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert result.returncode == 0

    # --- independently reconcile the with-fig bundle on disk (the empty-bundle trap) ---
    with_fig = out_dir / "with_fig"
    fig_dir = with_fig / "figures"
    assert fig_dir.is_dir(), "with-fig bundle has no figures/ dir"
    pngs = sorted(p.name for p in fig_dir.glob("*.png"))
    assert set(pngs) == ALL_FIGURES, f"with-fig figure set mismatch: got {pngs}, expected {sorted(ALL_FIGURES)}"
    for p in fig_dir.glob("*.png"):
        assert p.stat().st_size >= 800, f"{p.name} is undersized ({p.stat().st_size} bytes) — an empty stub"

    # --- metrics row: present, one row, enumerated columns populated (not NA) ---
    metrics_csv = with_fig / "metrics.csv"
    assert metrics_csv.is_file(), "with-fig bundle has no metrics.csv"
    import csv

    with metrics_csv.open() as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 1, f"metrics.csv must have exactly one row, got {len(rows)}"
    row = rows[0]
    assert int(row["n_figures"]) == len(ALL_FIGURES), (
        f"metrics n_figures={row['n_figures']} disagrees with {len(ALL_FIGURES)} PNGs on disk"
    )
    for col in POPULATED_METRIC_COLS:
        assert col in row, f"metrics row missing column {col}"
        val = row[col].strip()
        assert val not in ("", "NA", "NaN"), f"metrics column {col} is empty/NA ({val!r}) — header-only trap"

    # --- the no-fig bundle emitted exactly the 4 result diagnostics ---
    no_fig_pngs = sorted(p.name for p in (out_dir / "no_fig" / "figures").glob("*.png"))
    assert set(no_fig_pngs) == RESULT_FIGURES, f"no-fig bundle should be the 4 result diagnostics, got {no_fig_pngs}"

    # --- the zero-figure and stale bundles did NOT leave a metrics.csv ---
    assert not (out_dir / "empty" / "metrics.csv").exists(), "a zero-figure fit must not write a metrics row"
    assert not (out_dir / "stale" / "metrics.csv").exists(), "a stale (no-qc) fit must not write a metrics row"
