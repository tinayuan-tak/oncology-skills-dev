"""Fail-loud output-QC layer (S3a, github analysis-methods#701).

The four-cell R drivers historically only `message()` counts and NEVER assert, so a
degenerate DESeq2 output — a zero-row parquet, the documented SCLC all-NaN cell-A contrast, a
globally sign-inverted (backwards-wired) contrast — writes SILENTLY. `assert_contrast_qc()`
in `r/live/_four_cell_lib.R` now stops the run on those degeneracies.

THE WHOLE RISK OF THIS STAGE is a QC gate that cannot actually fail — it reads green while
letting a degenerate input slip past, which is worse than no gate. So these tests are
mutation-style: for EACH fatal assertion we build a fixture that is healthy in every respect
EXCEPT the one axis under test, and prove the gate FIRES on it (non-zero exit / stop()), then
prove it PASSES on a healthy fixture (no false alarm). The sign-inversion case additionally
proves the check is load-bearing: the exact same inverted-marker fit PASSES when the panel is
removed, so it is the panel that catches the inversion, not something incidental.

Hermetic: `four_cell_qc_metrics()` / `assert_contrast_qc()` are pure functions of the vectors
`deseq2_fit()` stashes in `attr(fit,"qc")`, so the fixtures are built directly in R with no
DESeq2 run (mirrors test_adj_vs_gtex_excluded_from_sensitivity / test_dedupe_one_aliquot_per_case).
A full end-to-end DESeq2 run is deliberately NOT used: it needs the heavy Bioconductor env, is
slow, and skips vacuously where that env is absent.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

METHODS_REPO = Path(__file__).resolve().parents[3]
LIB_PATH = METHODS_REPO / "onc_methods" / "dge_deseq2" / "r" / "live" / "_four_cell_lib.R"
DRIVER_06 = METHODS_REPO / "onc_methods" / "dge_deseq2" / "r" / "live" / "06_four_cell_driver.R"
DRIVER_07 = METHODS_REPO / "onc_methods" / "dge_deseq2" / "r" / "live" / "07_stratified_four_cell_driver.R"


def _resolve_rscript() -> str | None:
    """Prefer the running interpreter's own pixi env (see the sibling tests' twin helper)."""
    candidates = [
        Path(sys.executable).parent / "Rscript",
        METHODS_REPO / ".pixi" / "envs" / "default" / "bin" / "Rscript",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which("Rscript")


RSCRIPT = _resolve_rscript()

# assert_contrast_qc / four_cell_qc_metrics are base-R (no DESeq2/arrow), so this runs anywhere
# an Rscript exists. Each expectation stop()s on violation, so a red run names the failing case.
R_SCRIPT = r"""
source(Sys.getenv("FOUR_CELL_LIB_PATH"))

# --- tiny expectation framework -------------------------------------------------
# A RED for the wrong reason is worthless: require BOTH the fail-loud tag (so it
# is the QC gate, not an incidental R error) AND a per-case discriminating
# substring (so it is the axis under test that fired, not some other assertion).
expect_fail <- function(expr, name, must_match) {
  msg <- NULL
  fired <- tryCatch({ force(expr); FALSE },
                    error = function(e) { msg <<- conditionMessage(e); TRUE })
  if (!fired) stop(sprintf("EXPECTED the QC gate to FAIL but it passed: %s", name))
  if (!grepl("FAIL-LOUD output-QC", msg, fixed = TRUE))
    stop(sprintf("QC failed for the WRONG reason (not the fail-loud gate) [%s]: %s",
                 name, msg))
  if (!grepl(must_match, msg, fixed = TRUE))
    stop(sprintf("QC failed but not on the expected axis [%s]: wanted '%s', got: %s",
                 name, must_match, msg))
}
expect_ok <- function(expr, name) {
  tryCatch(force(expr), error = function(e)
    stop(sprintf("EXPECTED the QC gate to PASS but it failed: %s -> %s",
                 name, conditionMessage(e))))
}

# Build a per-cell fit frame + its attr(,"qc") input list exactly as deseq2_fit()/run_cell()
# produce them (renamed log2fc_<lab>/padj_<lab>/baseMean_<lab> columns).
mkfit <- function(lab, gene, lfc, padj, pvalue, baseMean,
                  dispersions = rep(0.1, length(gene)),
                  size_factors = c(0.9, 1.0, 1.1, 1.05),
                  n_tumor = 20L, n_normal = 20L) {
  df <- data.frame(gene_symbol = gene, stringsAsFactors = FALSE)
  df[[paste0("log2fc_",   lab)]] <- lfc
  df[[paste0("padj_",     lab)]] <- padj
  df[[paste0("baseMean_", lab)]] <- baseMean
  attr(df, "qc") <- list(
    gene_symbol = gene, pvalue = pvalue, padj = padj, baseMean = baseMean, lfc = lfc,
    dispersions = dispersions, size_factors = size_factors, filter_threshold = 5,
    n_tumor = n_tumor, n_normal = n_normal,
    n_genes_pre = length(gene) + 5L, n_genes_post = length(gene))
  df
}
# Silence the informative emit() output; exercise metrics + assertion together.
gate <- function(fit, lab = "C", panel = NULL) {
  m <- four_cell_qc_metrics(attr(fit, "qc"))
  assert_contrast_qc(fit, m, label = lab, panel = panel,
                     emit = function(...) invisible())
}

# =================================================================================
# 0. HEALTHY fixture passes — including the marker sign check (no false alarm).
# =================================================================================
gh   <- c("MKI67", "TOP2A", "PCNA", "g1", "g2", "g3", "g4", "g5")
lfch <- c( 2.5,     2.2,     1.8,    1.0,  -0.5,  0.2,  -1.2,  0.0)
padjh<- c( 0.001,   0.002,   0.01,   0.20, 0.03, NA,    0.50, NA)
pvlh <- c( 1e-5,    1e-4,    1e-3,   0.10, 0.02, 0.40,  0.30, NA)   # last untested (allzero)
bmh  <- c( 500,     400,     300,    100,  80,   20,    60,   0)    # last baseMean 0
fit_h <- mkfit("C", gh, lfch, padjh, pvlh, bmh)
expect_ok(gate(fit_h, "C", TUMOR_UP_MARKER_PANEL), "healthy fit passes with the marker panel")
expect_ok(gate(fit_h, "C", NULL),                  "healthy fit passes without a panel")

# =================================================================================
# 1. ROW-COUNT > 0 — a zero-row (empty-result) contrast.
# =================================================================================
fit_zero <- mkfit("C", character(0), numeric(0), numeric(0), numeric(0), numeric(0),
                  dispersions = numeric(0))
expect_fail(gate(fit_zero, "C"), "zero-row contrast fires the row-count assertion",
            "zero-row / empty-result")

# 1b. SCHEMA / required columns — a renamed/missing product column.
fit_badcol <- fit_h
names(fit_badcol)[names(fit_badcol) == "padj_C"] <- "PADJ_C"   # wrong name
expect_fail(gate(fit_badcol, "C"), "missing required column fires the schema assertion",
            "missing required column")

# =================================================================================
# 2. ALL-NaN cell (the documented SCLC cell-A degeneracy) — nothing tested.
# =================================================================================
gnan <- c("a", "b", "c", "d")
fit_nan <- mkfit("C", gnan, rep(NA_real_, 4), rep(NA_real_, 4), rep(NA_real_, 4), rep(100, 4))
expect_fail(gate(fit_nan, "C"), "all-NaN cell fires (0 genes tested)", "were tested")

# =================================================================================
# 3. padj/LFC coherence — a gene with finite padj but NA shrunk log2FC.
# =================================================================================
gc  <- c("a", "b", "c", "d", "e", "f")
lfcc<- c(1.0, NA_real_, 2.0, 1.5, -0.3, 0.7)   # gene b: finite padj below, NA lfc
padjc<-c(0.20, 0.010,   0.30, 0.05, 0.40, 0.15)
pvlc <-c(0.10, 0.005,   0.20, 0.02, 0.30, 0.08)
bmc  <-rep(100, 6)
fit_coh <- mkfit("C", gc, lfcc, padjc, pvlc, bmc)
expect_fail(gate(fit_coh, "C"), "finite padj + NA shrunk lfc fires the coherence assertion",
            "incoherence")

# =================================================================================
# 4. Dispersion-fit health — a wholesale failure (all dispersions NA).
# =================================================================================
gd <- c("a", "b", "c", "d", "e", "f")
fit_disp <- mkfit("C", gd, rep(2.0, 6), rep(0.01, 6), rep(0.001, 6), rep(150, 6),
                  dispersions = rep(NA_real_, 6))
expect_fail(gate(fit_disp, "C"), "all-NA dispersions fires the dispersion-fit assertion",
            "dispersions are NA")

# =================================================================================
# 5. Size-factor sanity — a non-positive poscounts size factor.
# =================================================================================
fit_sf <- mkfit("C", gd, rep(2.0, 6), rep(0.01, 6), rep(0.001, 6), rep(150, 6),
                size_factors = c(1.0, 1.2, 0.0, 0.9))   # a zero size factor
expect_fail(gate(fit_sf, "C"), "non-positive size factor fires the normalization assertion",
            "size factor")

# =================================================================================
# 6. p-value histogram — a pathological p=1 spike (NOT a KS test).
# =================================================================================
gp   <- paste0("g", 1:20)
pvlp <- c(rep(1.0, 15), rep(0.001, 5))     # 15/20 = 75% at p>=0.99
padjp<- c(rep(0.90, 15), rep(0.001, 5))    # finite, coherent
lfcp <- c(rep(0.0, 15), rep(2.0, 5))
fit_spike <- mkfit("C", gp, lfcp, padjp, pvlp, rep(100, 20))
expect_fail(gate(fit_spike, "C"), "p=1 spike fires the p-value-histogram assertion",
            "p-value spike")

# =================================================================================
# 7. Sign sanity vs the known-marker panel — a GLOBAL SIGN INVERSION.
#    Load-bearing proof: the SAME inverted fit PASSES with no panel, so the panel
#    is what catches it (mutation check — removing the guard removes the catch).
# =================================================================================
gi  <- c("MKI67", "TOP2A", "PCNA", "CCNB1", "x1", "x2")
lfci<- c(-2.0,    -2.5,    -1.8,   -2.1,    0.5,  -0.2)   # markers DOWN in tumor (backwards)
padji<-c(0.001,   0.001,   0.001,  0.001,   0.30, 0.40)
pvli <-c(1e-4,    1e-4,    1e-4,   1e-4,    0.20, 0.30)
fit_inv <- mkfit("C", gi, lfci, padji, pvli, rep(200, 6))
expect_fail(gate(fit_inv, "C", TUMOR_UP_MARKER_PANEL),
            "global sign inversion fires the marker-panel assertion", "SIGN INVERSION")
expect_ok(gate(fit_inv, "C", NULL),
          "inverted markers PASS with no panel — proves the sign check is load-bearing")

# 7b. Too few panel markers present -> the sign check is SKIPPED, not failed
#     (an indication whose markers were prefiltered out must not red the run).
gf <- c("MKI67", "x1", "x2", "x3")   # only 1 panel marker present (< min 3)
fit_few <- mkfit("C", gf, c(-2.0, 0.5, -0.3, 0.2), rep(0.20, 4), rep(0.10, 4), rep(100, 4))
expect_ok(gate(fit_few, "C", TUMOR_UP_MARKER_PANEL),
          "sign check is skipped (not failed) when too few markers are present")

# =================================================================================
# 8. Stale cache (a fit predating S3a, no qc attr) -> QC is SKIPPED loudly,
#    never a silent fail-open error.
# =================================================================================
fit_stale <- fit_h
attr(fit_stale, "qc") <- NULL
res <- gate(fit_stale, "C", TUMOR_UP_MARKER_PANEL)
stopifnot("stale cache returns FALSE (skipped) and does not stop" = identical(res, FALSE))

# =================================================================================
# 9. NA taxonomy DISTINGUISHES the three padj=NA causes (count + distinguish).
# =================================================================================
gt   <- c("tested", "indep", "allzero", "cooks")
padjt<- c(0.01,     NA,       NA,        NA)
pvlt <- c(0.001,    0.30,     NA,        NA)     # indep: pvalue present; others NA
bmt  <- c(100,      5,        0,         50)     # allzero: baseMean 0; cooks: >0
lfct <- c(2.0,      1.0,      NA,        1.0)
qc_tax <- list(gene_symbol = gt, pvalue = pvlt, padj = padjt, baseMean = bmt, lfc = lfct,
               dispersions = rep(0.1, 4), size_factors = rep(1, 4), filter_threshold = 5,
               n_tumor = 20L, n_normal = 20L, n_genes_pre = 9L, n_genes_post = 4L)
mt <- four_cell_qc_metrics(qc_tax)
stopifnot(
  "indep-filter padj=NA counted"        = mt$na_indep_filter == 1,
  "all-zero/failed padj=NA counted"     = mt$na_allzero == 1,
  "Cook's-outlier padj=NA counted"      = mt$na_cooks == 1,
  "padj=NA total"                       = mt$na_total == 3,
  "taxonomy partitions exhaustively"    = isTRUE(mt$na_taxonomy_exhaustive),
  # indep-filter gene keeps a pvalue -> it counts as tested; only gene 1 is sig.
  "2 genes tested (incl. indep-filter)" = mt$n_tested == 2 && mt$n_sig == 1)

# 9b. Coherence count is measured (finite padj + NA lfc).
qc_coh <- qc_tax
qc_coh$padj    <- c(0.01, 0.02, NA,   NA)
qc_coh$pvalue  <- c(0.001, 0.005, NA, 0.30)
qc_coh$lfc     <- c(2.0,  NA,   NA,   1.0)   # gene 2: finite padj, NA lfc
qc_coh$baseMean<- c(100,  80,   0,    5)
mc <- four_cell_qc_metrics(qc_coh)
stopifnot("finite-padj + NA-lfc coherence violation counted" = mc$n_finite_padj_na_lfc == 1)

cat("ALL_OK\n")
"""


@pytest.mark.skipif(
    RSCRIPT is None,
    reason="No Rscript in the repo pixi env or on PATH; cannot exercise the R QC layer",
)
def test_output_qc_assertions_fire_and_pass(tmp_path):
    script_path = tmp_path / "run_output_qc.R"
    script_path.write_text(R_SCRIPT)
    result = subprocess.run(
        [RSCRIPT, "--vanilla", str(script_path)],
        capture_output=True,
        text=True,
        env={**os.environ, "FOUR_CELL_LIB_PATH": str(LIB_PATH)},
    )
    assert "ALL_OK" in result.stdout, (
        f"output-QC assertions failed (exit {result.returncode}):\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert result.returncode == 0


# --- source-pin the driver wiring (the sign panel is cell-appropriate) -----------
# assert_contrast_qc runs inside run_cell for every cell; but the marker sign check must be
# given to the tumor-vs-normal cells A and C and NOT to the normal-vs-normal cell AG (where
# proliferation markers are not expected up). These pins fail if a future edit drops the panel
# from A/C or hands one to AG. (Cell B — the ComBat re-run — was removed in analysis-methods#727,
# so it is no longer among the panel-bearing cells; test_no_cell_b.py guards its non-return.)


def _src(p: Path) -> str:
    return p.read_text()


def test_driver_06_passes_marker_panel_to_ac_but_not_ag():
    src = _src(DRIVER_06)
    # A tumor-up panel is resolved once and handed to the tumor-vs-normal cells A and C.
    assert "marker_panel_for(" in src, "06 must resolve a marker panel"
    for cell in ("A", "C"):
        m = re.search(rf'run_cell\(\s*"{cell}".*?qc_panel\s*=\s*tumor_panel', src, re.DOTALL)
        assert m, f"cell {cell} must be given qc_panel = tumor_panel in 06"
    # Cell AG (normal-vs-normal) must NOT be given the tumor-up panel.
    ag = re.search(r'run_cell\(\s*"AG".*?\)', src, re.DOTALL)
    assert ag, "could not locate the cell AG run_cell call in 06"
    assert "qc_panel" not in ag.group(0), (
        "cell AG must NOT receive a marker panel — proliferation markers are not expected "
        f"up between two normal cohorts:\n{ag.group(0)}"
    )


def test_driver_07_passes_marker_panel_to_stratified_cells():
    src = _src(DRIVER_07)
    assert "marker_panel_for(" in src, "07 must resolve a marker panel"
    for cell in ("A", "C"):
        m = re.search(rf'run_cell\(\s*"{cell}".*?qc_panel\s*=\s*tumor_panel', src, re.DOTALL)
        assert m, f"stratified cell {cell} must be given qc_panel = tumor_panel in 07"
