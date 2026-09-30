"""One-aliquot-per-case dedup (S-fix, github analysis-methods#691).

`dedupe_one_aliquot_per_case()` in `r/live/_four_cell_lib.R` restores the dedup the legacy
loader had (00_load_counts.R:127-158) but the two PRODUCTION loaders (00_load_recount3.R,
00_load_xena_toil.R) lost: a case (patient) contributing more than one file/sample within a
single group violates DESeq2's per-sample independence and inflates significance
(pseudo-replication). These tests exercise the shared pure function directly — hermetic, no
S3, no DESeq2 — mirroring the module's pure-function test style (test_coadread_breadth_dedup.py).

Run via `Rscript` since the function under test is R, not Python.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

METHODS_REPO = Path(__file__).resolve().parents[3]
LIB_PATH = METHODS_REPO / "onc_methods" / "dge_deseq2" / "r" / "live" / "_four_cell_lib.R"


def _resolve_rscript() -> str | None:
    """Prefer the running interpreter's own pixi env; see test_byte_identity's twin helper.

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
    reason="No Rscript in the repo pixi env or on PATH; cannot exercise the R dedup function",
)

# Each R block is a self-contained stopifnot() assertion; script exits nonzero (via stopifnot's
# error) on the first failure, printing R's own error text — so a red run tells you exactly which
# case failed rather than a single opaque assertion.
R_SCRIPT = r"""
source(Sys.getenv("DEDUP_LIB_PATH"))

# 1. No duplicate cases: passthrough unchanged, original order preserved.
ids  <- c("b", "a", "c")
case <- setNames(c("P1", "P2", "P3"), ids)
out <- dedupe_one_aliquot_per_case(ids, case)
stopifnot("passthrough" = identical(out, ids))

# 2. Duplicate case, default order key (the ids themselves, ascending): the
# alphabetically-first id sharing a case wins; original relative order of the
# SURVIVORS is preserved.
ids  <- c("id2", "id1", "id3")
case <- setNames(c("P1", "P1", "P2"), ids)   # id1 & id2 are the same case
out <- dedupe_one_aliquot_per_case(ids, case)
stopifnot("dedup keeps alphabetically-first id" = identical(out, c("id1", "id3")))

# 3. Explicit order_key overrides the id-alphabetical tie-break.
ids <- c("A", "B")
case <- setNames(c("P1", "P1"), ids)
order_key <- setNames(c(2, 1), ids)   # B has the smaller key -> B wins
out <- dedupe_one_aliquot_per_case(ids, case, order_key_by_id = order_key)
stopifnot("order_key_by_id picks the smaller-key id" = identical(out, "B"))

# 4. Safety valve: case linkage unavailable for EVERY id -> no-op, not a collapse to 1.
ids <- c("A", "B", "C")
case <- setNames(rep(NA_character_, 3), ids)
out <- dedupe_one_aliquot_per_case(ids, case)
stopifnot("all-NA case linkage is a no-op" = identical(out, ids))

# 5. Partial NA: an NA-case id is never deduped against another NA-case id
# (each is its own unique key), only real case matches collapse.
ids  <- c("A", "B", "C", "D")
case <- setNames(c(NA_character_, NA_character_, "P1", "P1"), ids)
out <- dedupe_one_aliquot_per_case(ids, case)
stopifnot("NA-case ids are each kept; only the real duplicate (D) drops" =
  identical(out, c("A", "B", "C")))

# 6. Empty input.
out <- dedupe_one_aliquot_per_case(character(0), setNames(character(0), character(0)))
stopifnot("empty input" = identical(out, character(0)))

# 7. Three-way duplicate collapses to exactly one, by order key.
ids  <- c("f3", "f1", "f2")
case <- setNames(rep("P1", 3), ids)
out <- dedupe_one_aliquot_per_case(ids, case)
stopifnot("three-way duplicate keeps exactly the smallest-key id" = identical(out, "f1"))

cat("ALL_OK\n")
"""


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    script_path = tmp_path / "run_dedup_tests.R"
    script_path.write_text(R_SCRIPT)
    env = {"DEDUP_LIB_PATH": str(LIB_PATH)}
    import os

    return subprocess.run(
        [RSCRIPT, "--vanilla", str(script_path)],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
    )


def test_dedupe_one_aliquot_per_case_cases(tmp_path):
    result = _run(tmp_path)
    assert "ALL_OK" in result.stdout, (
        f"dedup R assertions failed (exit {result.returncode}):\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert result.returncode == 0
