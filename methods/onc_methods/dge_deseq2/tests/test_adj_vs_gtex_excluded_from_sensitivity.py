"""The adjacent-vs-GTEx diagnostic (cell AG, S2 #695) is mechanically excluded from the
sensitivity/concordance grid — proved byte-identical before/after, not just labelled.

Cell AG is a NORMAL-vs-NORMAL QC contrast (TCGA adjacent-normal vs GTEx normal): it measures
the combined TCGA-vs-GTEx nuisance envelope, so a large effect is the *expected* diagnostic
signal, not a selectivity vote. Like cell Cr (RUVg), it must never feed `assemble_sensitivity`
— it is emitted as its own `adj_vs_gtex.parquet` byproduct and must not appear in
`sensitivity.parquet`, `cells_supporting`, or any concordance column.

Two complementary, cheap, non-vacuous guards (no DESeq2, no S3):

1. `test_assemble_sensitivity_is_byte_identical_with_and_without_ag` (R-subprocess) proves the
   sensitivity frame is a pure function of the `cells` list the driver passes it: computing an
   AG fit alongside cells A/C does NOT change the assembled table, AND — the load-bearing half
   — *adding* AG to the list WOULD change it (a new `log2fc_AG` column, `cells_ran` 2 -> 3). So
   the exclusion is what keeps the table byte-identical; it is not a guard that can never fail
   (cf. the empty-parametrize / vacuous-pass traps). This is the byte-identical-before/after
   proof at the one function that produces `sensitivity.parquet`.

2. `test_driver_wires_ag_as_a_byproduct_not_a_sensitivity_cell` pins the REAL `06_four_cell_driver.R`
   wiring: cell AG is computed and written to `adj_vs_gtex.parquet`, but its result object is
   never placed in the `cells` list nor passed to `assemble_sensitivity`. So a future edit that
   silently promotes AG into the concordance vote fails here.

A full end-to-end driver run (DESeq2 on a synthetic bundle) is deliberately NOT used: it needs
the R/Bioconductor env, is slow, and skips vacuously where that env is absent — the two guards
above are hermetic and always run wherever the artifact they protect is reachable.
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
DRIVER_PATH = METHODS_REPO / "onc_methods" / "dge_deseq2" / "r" / "live" / "06_four_cell_driver.R"


def _resolve_rscript() -> str | None:
    """Prefer the running interpreter's own pixi env (see test_dedupe_one_aliquot_per_case)."""
    candidates = [
        Path(sys.executable).parent / "Rscript",
        METHODS_REPO / ".pixi" / "envs" / "default" / "bin" / "Rscript",
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return shutil.which("Rscript")


RSCRIPT = _resolve_rscript()

# assemble_sensitivity is a base-R function (merge/apply only) — no DESeq2/arrow needed, so this
# runs anywhere an Rscript exists, not only in the full Bioconductor env.
R_SCRIPT = r"""
source(Sys.getenv("FOUR_CELL_LIB_PATH"))

# Synthetic per-cell fits shaped exactly like run_cell()'s output: gene_symbol +
# log2fc_<lab> / padj_<lab> / baseMean_<lab>. No DESeq2 — assemble_sensitivity is pure base R.
mkcell <- function(lab, lfc, padj) {
  d <- data.frame(gene_symbol = c("g1", "g2", "g3"),
                  lfc = lfc, padj = padj, bm = c(10, 20, 30),
                  stringsAsFactors = FALSE)
  names(d) <- c("gene_symbol", paste0("log2fc_", lab),
                paste0("padj_", lab), paste0("baseMean_", lab))
  d
}
fitA  <- mkcell("A",  c( 2.0, -1.0, 0.1), c(0.001, 0.02, 0.90))
fitC  <- mkcell("C",  c( 1.5, -0.8, 0.2), c(0.010, 0.20, 0.50))
# A deliberately LARGE normal-vs-normal effect — the expected AG diagnostic signal.
fitAG <- mkcell("AG", c( 3.0,  2.0, 2.5), c(0.001, 0.001, 0.001))

# The driver passes exactly list(A, C) (cells that ran), whether or not an AG fit was computed.
sens_no_ag_computed  <- assemble_sensitivity(list(A = fitA, C = fitC))
fitAG  # AG exists in the environment now, exactly as in the real driver
sens_ag_computed     <- assemble_sensitivity(list(A = fitA, C = fitC))
stopifnot("sensitivity is byte-identical whether or not AG was computed" =
  identical(sens_no_ag_computed, sens_ag_computed))

# Load-bearing half: the ONLY way AG could corrupt the grid is by joining the cells list, and
# THAT visibly changes the artifact — so the exclusion is not a vacuous no-op guard.
sens_ag_wrongly_added <- assemble_sensitivity(list(A = fitA, C = fitC, AG = fitAG))
stopifnot("adding AG to the cells list DOES change the sensitivity table" =
  !identical(sens_no_ag_computed, sens_ag_wrongly_added))
stopifnot("correct grid carries NO log2fc_AG column" =
  !("log2fc_AG" %in% names(sens_no_ag_computed)))
stopifnot("wrong grid gains a log2fc_AG column" =
  "log2fc_AG" %in% names(sens_ag_wrongly_added))
stopifnot("AG inflates cells_ran from 2 (A+C) to 3" =
  max(sens_no_ag_computed$cells_ran) == 2 && max(sens_ag_wrongly_added$cells_ran) == 3)

cat("ALL_OK\n")
"""


@pytest.mark.skipif(
    RSCRIPT is None,
    reason="No Rscript in the repo pixi env or on PATH; cannot exercise assemble_sensitivity",
)
def test_assemble_sensitivity_is_byte_identical_with_and_without_ag(tmp_path):
    script_path = tmp_path / "run_ag_exclusion.R"
    script_path.write_text(R_SCRIPT)
    result = subprocess.run(
        [RSCRIPT, "--vanilla", str(script_path)],
        capture_output=True,
        text=True,
        env={**os.environ, "FOUR_CELL_LIB_PATH": str(LIB_PATH)},
    )
    assert "ALL_OK" in result.stdout, (
        f"assemble_sensitivity AG-exclusion assertions failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert result.returncode == 0


def _driver_source() -> str:
    return DRIVER_PATH.read_text()


def test_driver_computes_ag_and_writes_it_as_a_byproduct():
    src = _driver_source()
    assert 'run_cell("AG"' in src, "cell AG must be computed via run_cell"
    # AG is written to its own byproduct parquet, not folded into a shared product.
    assert "adj_vs_gtex.parquet" in src
    m = re.search(r"write_contrast\(\s*cellAG.*?adj_vs_gtex\.parquet", src, re.DOTALL)
    assert m, "adj_vs_gtex.parquet must be emitted from cellAG via write_contrast"
    # Sign convention recorded in the parquet, not left to a naming convention (#695 review).
    assert 'positive_group  = "TCGA_adjacent_normal"' in src
    assert 'reference_group = "GTEx_normal"' in src


def test_driver_wires_ag_as_a_byproduct_not_a_sensitivity_cell():
    """The cells list that feeds assemble_sensitivity must NOT contain the AG result."""
    src = _driver_source()

    # The single `cells <- Filter(Negate(is.null), list(...))` assignment is the concordance
    # vote. It must list only A/B/C — never the AG diagnostic.
    cells_assign = re.search(r"cells\s*<-\s*Filter\([^\n]*list\([^)]*\)", src)
    assert cells_assign, "could not locate the `cells <- Filter(..., list(...))` assignment"
    cells_line = cells_assign.group(0)
    assert "cellAG" not in cells_line and "AG =" not in cells_line, (
        f"cell AG leaked into the sensitivity/concordance vote:\n{cells_line}"
    )

    # assemble_sensitivity is only ever called on `cells` — never on a list that includes AG.
    for call in re.findall(r"assemble_sensitivity\(([^)]*)\)", src):
        assert "cellAG" not in call and "AG" not in call, (
            f"assemble_sensitivity must be fed only `cells`; got argument: {call!r}"
        )

    # cellAG is never merged into the assembled `sens` frame either.
    assert not re.search(r"sens\b[^\n]*cellAG", src), "cellAG must not be merged into sens"
