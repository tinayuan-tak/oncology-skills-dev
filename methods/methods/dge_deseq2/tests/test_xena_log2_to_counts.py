"""Xena/Toil log2(count+1) de-transform invariant (S1b, github analysis-methods#694).

`xena_log2_to_counts()` in `r/live/_four_cell_lib.R` inverts the transform the UCSC Toil hub
ships the gene matrix in — log2(expected_count + 1) — back to the INTEGER counts DESeq2's
NB-GLM requires. `00_load_xena_toil.R` calls it before the four-cell driver ever sees the
matrix, so if a future edit broke the round-trip (e.g. dropped the `- 1`, forgot the clamp, or
left the result floating-point) DESeq2 would silently model wrong counts. These tests exercise
the shared pure function directly — hermetic, no S3, no DESeq2 — mirroring the module's
pure-function R test style (test_dedupe_one_aliquot_per_case.py).

The three properties that matter, per the S1b plan review:
  - round-trip: for any non-negative integer count n, round(2^log2(n+1) - 1) == n exactly;
  - non-negativity: a floating-point undershoot or a NA can never become a negative/missing count;
  - integer storage: the result is integer-typed (the one type DESeq2 accepts).

Run via `Rscript` since the function under test is R, not Python.
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
    """Prefer the running interpreter's own pixi env; see test_dedupe_one_aliquot_per_case's twin.

    A /tmp worktree has no .pixi/ of its own (copying the multi-GB env onto the overlay is the
    ENOSPC trap), so anchoring to METHODS_REPO alone would resolve to nothing when this test is
    driven by a worktree's own pixi env — sys.executable is the reliable anchor either way.
    """
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
    reason="No Rscript in the repo pixi env or on PATH; cannot exercise the R de-transform function",
)

# Each R block is a self-contained stopifnot() assertion; the script exits nonzero (via
# stopifnot's error) on the first failure, printing R's own error text — so a red run names the
# exact property that broke rather than a single opaque assertion.
R_SCRIPT = r"""
source(Sys.getenv("XENA_LIB_PATH"))

# 1. Round-trip on a matrix of encoded non-negative integer counts. log2(n+1) is what Toil
# ships; xena_log2_to_counts must recover n EXACTLY across a wide dynamic range (0 .. ~2^30,
# which covers any real RNA-seq gene count).
n <- c(0L, 1L, 2L, 3L, 9L, 42L, 1000L, 65535L, 1000000L, 1073741823L)
encoded <- matrix(log2(as.numeric(n) + 1), nrow = 2)   # shape is preserved, values round-trip
out <- xena_log2_to_counts(encoded)
stopifnot("round-trip recovers the exact integer counts" =
  identical(as.integer(out), n))
stopifnot("shape is preserved" = identical(dim(out), dim(encoded)))

# 2. Integer storage: DESeq2 rejects a double count matrix.
stopifnot("result is integer-typed" = identical(storage.mode(out), "integer"))

# 2b. Dimnames MUST survive the transform. The loader keys coldata off
# colnames(counts) (the sample ids) AFTER this call, so dropping dimnames here
# empties the sample list and the whole load crashes ("differing number of rows:
# 0, 1"). This is the exact regression an as.numeric()-based implementation
# introduced; it round-tripped values fine, so only a dimnames check catches it.
labeled <- matrix(log2(c(1, 2, 3, 4) + 1), nrow = 2,
                  dimnames = list(c("gene1", "gene2"), c("sampleA", "sampleB")))
out <- xena_log2_to_counts(labeled)
stopifnot("rownames preserved" = identical(rownames(out), c("gene1", "gene2")))
stopifnot("colnames (sample ids) preserved" = identical(colnames(out), c("sampleA", "sampleB")))
stopifnot("labeled values still round-trip" =
  identical(as.integer(out), c(1L, 2L, 3L, 4L)))

# 3. Non-negativity clamp: a tiny floating-point UNDERSHOOT of 0 (2^x - 1 slightly negative)
# must clamp to 0, not round to -1 or stay negative.
undershoot <- log2(1) - 1e-12   # encodes ~0 but 2^x - 1 is a hair below 0
out <- xena_log2_to_counts(undershoot)
stopifnot("sub-zero undershoot clamps to 0" = identical(out, 0L))

# 4. NA in -> 0 out (never a missing count reaching DESeq2).
out <- xena_log2_to_counts(c(log2(6), NA_real_, log2(1)))
stopifnot("NA becomes 0, real values round-trip" = identical(out, c(5L, 0L, 0L)))

# 5. A vector input (no dim) stays a plain integer vector, not a 1-col matrix.
out <- xena_log2_to_counts(log2(c(0, 7, 3) + 1))
stopifnot("vector in -> vector out" = is.null(dim(out)))
stopifnot("vector round-trips" = identical(out, c(0L, 7L, 3L)))

# 6. Empty input is a no-op that stays integer.
out <- xena_log2_to_counts(numeric(0))
stopifnot("empty input" = identical(out, integer(0)))

cat("ALL_OK\n")
"""


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    script_path = tmp_path / "run_xena_log2_tests.R"
    script_path.write_text(R_SCRIPT)
    env = {"XENA_LIB_PATH": str(LIB_PATH)}
    return subprocess.run(
        [RSCRIPT, "--vanilla", str(script_path)],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
    )


def test_xena_log2_to_counts_invariants(tmp_path):
    result = _run(tmp_path)
    assert "ALL_OK" in result.stdout, (
        f"xena_log2_to_counts R assertions failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert result.returncode == 0
