"""cells_ran / cells_tested / sig_all_cells fit-vs-filter semantics (github analysis-methods#863(a)).

DESeq2 independent filtering is PER-CONTRAST, so a boundary gene is routinely padj=NA in one
comparator but tested in the other. The pre-#863 fusion counted `cells_ran = rowSums(!is.na(padj))`,
which conflated "the cell's fit RAN this gene but independent-filtering set padj=NA" with "the cell
never fit this gene at all". A gene significant in cell C ONLY because cell A NA-filtered it then
scored cells_ran=1 / cells_supporting=1 -> sig_all_cells=TRUE — indistinguishable in the shipped
parquet from a gene confirmed in BOTH comparators.

The fix reads "fit ran for this gene in this cell" off the per-cell baseMean (present iff the gene
was in that contrast's tested universe), so a ran-but-filtered gene now reads cells_ran=2 and, being
significant in only one of the two ran cells, sig_all_cells=FALSE. This is the load-bearing mutation
test: a DELIBERATELY NA-filtered (padj=NA, baseMean present) gene must NOT count as didn't-run.

Hermetic — assemble_sensitivity is pure base R (merge/rowSums only), no DESeq2/arrow/S3 needed, so
this runs anywhere an Rscript exists (mirrors test_adj_vs_gtex_excluded_from_sensitivity.py).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

METHODS_REPO = Path(__file__).resolve().parents[3]
LIB_PATH = METHODS_REPO / "methods" / "dge_deseq2" / "r" / "live" / "_four_cell_lib.R"


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

# Three genes probe the three distinct fit/filter states:
#   g_filtered   ran in BOTH A and C (both carry a baseMean) but padj_A=NA (independent-filtered);
#                significant in C only. NEW semantics: cells_ran=2, cells_tested=1, supporting=1,
#                sig_all_cells=FALSE. OLD semantics would have given cells_ran=1 / sig_all=TRUE.
#   g_absent_A   NOT in cell A's fit at all (merge-fills baseMean_A=NA) -> the ONLY didn't-run case;
#                significant in C. cells_ran=1, supporting=1, sig_all_cells=TRUE (a legit single-cell call).
#   g_both       significant + same direction in BOTH -> cells_ran=2, supporting=2, sig_all_cells=TRUE.
R_SCRIPT = r"""
source(Sys.getenv("FOUR_CELL_LIB_PATH"))

mkcell <- function(lab, df) {
  names(df) <- c("gene_symbol", paste0("log2fc_", lab),
                 paste0("padj_", lab), paste0("baseMean_", lab))
  df
}

# Cell A fit: g_absent_A is deliberately ABSENT (never fit); g_filtered has a finite shrunk LFC and
# a real baseMean but padj=NA (the DESeq2 independent-filtering signature: fit ran, gene not called).
fitA <- mkcell("A", data.frame(
  gene_symbol = c("g_filtered", "g_both"),
  lfc         = c( 1.8,          2.0),
  padj        = c( NA_real_,     0.001),   # g_filtered: padj=NA but the FIT RAN (baseMean present)
  bm          = c( 15,           40),
  stringsAsFactors = FALSE))

fitC <- mkcell("C", data.frame(
  gene_symbol = c("g_filtered", "g_absent_A", "g_both"),
  lfc         = c( 2.2,          1.5,          1.9),
  padj        = c( 0.001,        0.001,        0.002),
  bm          = c( 30,           25,           35),
  stringsAsFactors = FALSE))

sens <- assemble_sensitivity(list(A = fitA, C = fitC))
rownames(sens) <- sens$gene_symbol

# --- the load-bearing mutation: a ran-but-filtered gene must NOT read as didn't-run ---
stopifnot("g_filtered ran in BOTH cells (baseMean present in A even though padj_A is NA)" =
  sens["g_filtered", "cells_ran"] == 2)
stopifnot("g_filtered was TESTED (non-NA padj) in only cell C" =
  sens["g_filtered", "cells_tested"] == 1)
stopifnot("g_filtered is supported by only the one cell that called it" =
  sens["g_filtered", "cells_supporting"] == 1)
stopifnot("g_filtered is NOT sig_all_cells: it ran in 2 cells, confirmed in 1 (was TRUE pre-#863)" =
  sens["g_filtered", "sig_all_cells"] == FALSE)

# --- a genuinely absent gene is the ONLY didn't-run case: it counts as ran in 1 cell ---
stopifnot("g_absent_A ran in only cell C (absent from cell A's fit universe)" =
  sens["g_absent_A", "cells_ran"] == 1)
stopifnot("g_absent_A is a legit single-cell call -> sig_all_cells TRUE" =
  sens["g_absent_A", "sig_all_cells"] == TRUE)

# --- a gene confirmed in both comparators is unchanged (still the gold-standard call) ---
stopifnot("g_both ran in 2 cells" = sens["g_both", "cells_ran"] == 2)
stopifnot("g_both supported by 2 cells" = sens["g_both", "cells_supporting"] == 2)
stopifnot("g_both is sig_all_cells" = sens["g_both", "sig_all_cells"] == TRUE)

# --- the new schema carries an explicit per-gene tested count distinct from cells_ran ---
stopifnot("cells_tested column is emitted" = "cells_tested" %in% names(sens))

cat("ALL_OK\n")
"""


@pytest.mark.skipif(
    RSCRIPT is None,
    reason="No Rscript in the repo pixi env or on PATH; cannot exercise assemble_sensitivity",
)
def test_ran_but_filtered_gene_counts_as_ran_not_didnt_run(tmp_path):
    script_path = tmp_path / "run_cells_ran_semantics.R"
    script_path.write_text(R_SCRIPT)
    result = subprocess.run(
        [RSCRIPT, "--vanilla", str(script_path)],
        capture_output=True,
        text=True,
        env={**os.environ, "FOUR_CELL_LIB_PATH": str(LIB_PATH)},
    )
    assert "ALL_OK" in result.stdout, (
        f"cells_ran fit-vs-filter semantics assertions failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert result.returncode == 0
