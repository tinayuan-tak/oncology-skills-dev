"""GTEx cell-line screen (#734, dge_deseq2 arc #690).

`drop_gtex_cell_lines()` in `r/live/_four_cell_lib.R` removes recount3's immortalized
cell-line pseudo-tissues from a GTEx metadata table before its samples enter the
tumor-vs-normal "normal" arm. recount3 bundles cell lines under a tissue project's SMTS
umbrella: "Cells - EBV-transformed lymphocytes" in BLOOD (~19%), "Cells - Cultured
fibroblasts" in SKIN (~27%), "Cells - Leukemia cell line (CML)" (the K-562 line) in
BONE_MARROW. Contrasting a tumor against those lines contaminates the normal arm; the
loader historically applied no screen. It matters most for LAML, whose ONLY normal is
GTEx blood (no TCGA adjacent normal).

These tests exercise the shared pure function directly via Rscript — hermetic, no S3, no
DESeq2 — mirroring test_dedupe_one_aliquot_per_case.py. The load-bearing cases are the
FAIL-CLOSED behaviour when SMTSD is absent (must stop(), not pass cell lines through) and
that a real cell-line SMTSD is actually dropped (a screen that cannot fire is worse than
none).
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

pytestmark = pytest.mark.skipif(
    RSCRIPT is None,
    reason="No Rscript in the repo pixi env or on PATH; cannot exercise the R cell-line screen",
)

# Each block is a self-contained stopifnot(); the script exits nonzero on the first failure
# and prints R's own error text, so a red tells you exactly which case failed.
R_SCRIPT = r"""
source(Sys.getenv("CELL_LINE_LIB_PATH"))

md <- function(smtsd, ids = NULL) {
  if (is.null(ids)) ids <- paste0("s", seq_along(smtsd))
  data.frame(external_id = ids, SMTS = "Blood", SMTSD = smtsd,
             stringsAsFactors = FALSE)
}

# 1. No cell lines: passthrough unchanged (all whole blood).
out <- drop_gtex_cell_lines(md(rep("Whole Blood", 4)), "BLOOD")
stopifnot("no-cell-line passthrough" = nrow(out) == 4L)

# 2. BLOOD mix: EBV-transformed lymphocytes dropped, whole blood kept, order preserved.
m <- md(c("Whole Blood", "Cells - EBV-transformed lymphocytes", "Whole Blood",
          "Cells - EBV-transformed lymphocytes"),
        ids = c("wb1", "lcl1", "wb2", "lcl2"))
out <- drop_gtex_cell_lines(m, "BLOOD")
stopifnot("EBV LCLs dropped, whole blood kept" = identical(out$external_id, c("wb1", "wb2")))
stopifnot("no cell-line SMTSD survives" =
  !any(startsWith(out$SMTSD, "Cells - ")))

# 3. SKIN mix: cultured fibroblasts dropped.
m <- md(c("Skin - Sun Exposed (Lower leg)", "Cells - Cultured fibroblasts",
          "Skin - Not Sun Exposed (Suprapubic)"))
out <- drop_gtex_cell_lines(m, "SKIN")
stopifnot("cultured fibroblasts dropped" = nrow(out) == 2L)

# 4. The K-562 leukemia line ("Cells - Leukemia cell line (CML)") is caught by the same prefix.
m <- md(c("Cells - Leukemia cell line (CML)", "Whole Blood"))
out <- drop_gtex_cell_lines(m, "BONE_MARROW")
stopifnot("K-562 CML line dropped" = identical(out$SMTSD, "Whole Blood"))

# 5. FAIL-CLOSED: metadata lacking SMTSD must stop(), never pass through.
no_smtsd <- data.frame(external_id = c("a", "b"), SMTS = "Blood", stringsAsFactors = FALSE)
err <- tryCatch({ drop_gtex_cell_lines(no_smtsd, "BLOOD"); "NO_ERROR" },
                error = function(e) conditionMessage(e))
stopifnot("missing SMTSD fails closed" = grepl("lacks an SMTSD", err))

# 6. NA SMTSD is treated as NOT a cell line (kept) — an NA prefix test must not drop it.
m <- md(c("Whole Blood", NA_character_, "Cells - EBV-transformed lymphocytes"),
        ids = c("wb", "unknown", "lcl"))
out <- drop_gtex_cell_lines(m, "BLOOD")
stopifnot("NA SMTSD kept; only the real cell line dropped" =
  identical(out$external_id, c("wb", "unknown")))

# 7. All-cell-line input collapses to zero rows (does not error, just empties).
out <- drop_gtex_cell_lines(md(rep("Cells - Cultured fibroblasts", 3)), "SKIN")
stopifnot("all cell lines -> empty" = nrow(out) == 0L)

cat("ALL_OK\n")
"""


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    script_path = tmp_path / "run_cell_line_tests.R"
    script_path.write_text(R_SCRIPT)
    env = {"CELL_LINE_LIB_PATH": str(LIB_PATH)}
    return subprocess.run(
        [RSCRIPT, "--vanilla", str(script_path)],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
    )


def test_drop_gtex_cell_lines_cases(tmp_path):
    result = _run(tmp_path)
    assert "ALL_OK" in result.stdout, (
        f"cell-line screen R assertions failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert result.returncode == 0
