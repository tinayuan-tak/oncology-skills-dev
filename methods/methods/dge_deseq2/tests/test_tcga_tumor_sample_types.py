"""TCGA tumor sample-type selection (#734, dge_deseq2 arc #690).

`is_tcga_tumor_sample_type()` in `r/live/_four_cell_lib.R` decides which recount3 TCGA
samples enter the four-cell "tumor" arm. The load-bearing facts, encoded as assertions:

  * "Primary Tumor" is a tumor (every solid cohort).
  * "Primary Blood Derived Cancer - Peripheral Blood" is a tumor — TCGA-LAML has ONLY this
    label and zero "Primary Tumor" rows, so without it LAML's tumor arm is empty and the run
    dies. This is the reason the function exists.
  * "Metastatic" / "Additional Metastatic" / "Recurrent Tumor" are NOT tumors here. This is
    load-bearing for the SKCM re-materialization: SKCM's shipped verdict used its 103
    Primary-Tumor samples only, and admitting its 368 Metastatic samples would move the tumor
    arm and confound the cell-line-filter verdict diff.
  * "Solid Tissue Normal" is not a tumor; NA is not a tumor.

Hermetic Rscript exercise of the pure function, no S3 / DESeq2 — mirrors
test_drop_gtex_cell_lines.py and test_dedupe_one_aliquot_per_case.py.
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

pytestmark = pytest.mark.skipif(
    RSCRIPT is None,
    reason="No Rscript in the repo pixi env or on PATH; cannot exercise the R tumor classifier",
)

R_SCRIPT = r"""
source(Sys.getenv("CELL_LINE_LIB_PATH"))

# 1. Solid-cohort tumor is a tumor; adjacent normal is not.
stopifnot("Primary Tumor is tumor" = is_tcga_tumor_sample_type("Primary Tumor"))
stopifnot("Solid Tissue Normal is not tumor" =
  !is_tcga_tumor_sample_type("Solid Tissue Normal"))

# 2. LAML's liquid-tumor label IS a tumor (the reason the function exists).
stopifnot("LAML peripheral-blood cancer is tumor" =
  is_tcga_tumor_sample_type("Primary Blood Derived Cancer - Peripheral Blood"))

# 3. Metastatic / recurrent are DELIBERATELY excluded (SKCM re-materialize invariant).
stopifnot("Metastatic excluded" = !is_tcga_tumor_sample_type("Metastatic"))
stopifnot("Additional Metastatic excluded" =
  !is_tcga_tumor_sample_type("Additional Metastatic"))
stopifnot("Recurrent Tumor excluded" = !is_tcga_tumor_sample_type("Recurrent Tumor"))

# 4. NA is not a tumor (never selected on a missing label).
stopifnot("NA is not tumor" = !is_tcga_tumor_sample_type(NA_character_))

# 5. Vectorized: mixed SKCM-like vector selects only Primary Tumor rows.
v <- c("Primary Tumor", "Metastatic", "Metastatic", "Solid Tissue Normal", "Primary Tumor")
stopifnot("vectorized SKCM mask" =
  identical(is_tcga_tumor_sample_type(v), c(TRUE, FALSE, FALSE, FALSE, TRUE)))

# 6. Vectorized: an all-LAML vector is all-tumor.
laml <- rep("Primary Blood Derived Cancer - Peripheral Blood", 4)
stopifnot("vectorized LAML mask" = all(is_tcga_tumor_sample_type(laml)))

cat("ALL_OK\n")
"""


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    script_path = tmp_path / "run_tumor_type_tests.R"
    script_path.write_text(R_SCRIPT)
    env = {"CELL_LINE_LIB_PATH": str(LIB_PATH)}
    return subprocess.run(
        [RSCRIPT, "--vanilla", str(script_path)],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
    )


def test_tcga_tumor_sample_type_classifier(tmp_path):
    result = _run(tmp_path)
    assert "ALL_OK" in result.stdout, (
        f"tumor sample-type R assertions failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert result.returncode == 0
