"""The OPT-IN gene_stem re-key the S4 verdict backtest measures (#761 S4).

`collapse_counts_by_stem` (in `_four_cell_lib.R`) is the ALTERNATIVE collapse the
backtest shadows: instead of summing every Ensembl id that shares a `gene_symbol`
(the shipped default, which also DROPS symbol-less genes), it collapses on the
unversioned Ensembl `gene_stem` — each stem keeps its OWN row and symbol-less
genes are RETAINED (gene_symbol NA). It is verdict-AFFECTING and therefore
opt-in and scratch-only; the default `--collapse-key gene_symbol` path in
`00_load_recount3.R` is left byte-identical, so this only ADDS a capability.

Two complementary hermetic guards (no DESeq2, no S3), mirroring
`test_four_cell_gene_id_annotation.py`:

1. `test_collapse_counts_by_stem_*` (R-subprocess) EXTRACTS the REAL
   `collapse_counts_by_stem` definition and exercises it: distinct stems stay
   separate (NOT summed), a symbol-less stem is retained with gene_symbol NA,
   versioned duplicates of ONE stem are summed, and a 0-row input FAILS LOUD.
2. `test_load_recount3_wires_collapse_key` (always-run source regex) pins that
   00_load_recount3.R exposes `--collapse-key` (default gene_symbol), routes the
   gene_stem branch through the shared helper, and leaves the default
   symbol-collapse branch intact — so a full R env is not required to protect the
   wiring.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

METHODS_REPO = Path(__file__).resolve().parents[3]
R_LIVE = METHODS_REPO / "methods" / "dge_deseq2" / "r" / "live"
LIB_PATH = R_LIVE / "_four_cell_lib.R"
LOADER_PATH = R_LIVE / "00_load_recount3.R"


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


def _extract_collapse_fn(src: str) -> str:
    """Pull the top-level `collapse_counts_by_stem <- function(...) { ... }` verbatim.

    Top-level def → its closing brace is a bare `}` at column 0. Exercising the
    extracted text (not a rewrite) keeps this a real test of the shipped helper."""
    lines = src.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if ln.startswith("collapse_counts_by_stem <- function(")),
        None,
    )
    assert start is not None, "collapse_counts_by_stem definition not found in _four_cell_lib.R"
    end = next((j for j in range(start + 1, len(lines)) if lines[j] == "}"), None)
    assert end is not None, "could not find the closing brace of collapse_counts_by_stem"
    return "\n".join(lines[start : end + 1])


R_TEMPLATE = r"""
__COLLAPSE_FN__

ok <- function(cond, msg) if (!isTRUE(cond)) stop(msg)

# --- scenario 1: distinct stems (incl. a symbol-less gene) stay separate -----
# Three versioned ids with DISTINCT stems. KRAS/TP53 have symbols; the third
# stem is ABSENT from ens2hgnc (symbol-less) → must be RETAINED with NA symbol.
counts <- matrix(as.integer(c(10,20, 30,40, 50,60)), nrow = 3, byrow = TRUE)
rownames(counts) <- c("ENSG00000133703.13", "ENSG00000141510.16", "ENSG00000999999.1")
common_genes <- rownames(counts)
ens2hgnc <- c(ENSG00000133703 = "KRAS", ENSG00000141510 = "TP53")  # 3rd stem absent

res <- collapse_counts_by_stem(counts, common_genes, ens2hgnc)

ok(nrow(res$counts) == 3, "distinct stems must NOT be summed (3 in, 3 out)")
ok(identical(rownames(res$counts),
             c("ENSG00000133703", "ENSG00000141510", "ENSG00000999999")),
   "counts rownames must be the unversioned gene_stem")
ok(identical(res$rowdata$gene_stem,
             c("ENSG00000133703", "ENSG00000141510", "ENSG00000999999")),
   "rowdata gene_stem wrong")
ok(identical(res$rowdata$gene_id, common_genes), "rowdata must retain the versioned gene_id")
ok(res$rowdata$gene_symbol[res$rowdata$gene_stem == "ENSG00000133703"] == "KRAS",
   "KRAS symbol lost")
# TEETH: symbol-less stem RETAINED (a row exists) but its gene_symbol is NA.
ok("ENSG00000999999" %in% res$rowdata$gene_stem, "symbol-less stem must be RETAINED")
ok(is.na(res$rowdata$gene_symbol[res$rowdata$gene_stem == "ENSG00000999999"]),
   "symbol-less stem must carry NA gene_symbol")
# counts untouched for a retained row (no summation across distinct stems).
ok(all(res$counts["ENSG00000133703", ] == c(10L, 20L)), "distinct-stem counts altered")

# --- scenario 2: two versioned ids of the SAME stem are SUMMED ---------------
counts2 <- matrix(as.integer(c(1,2, 3,4, 100,100)), nrow = 3, byrow = TRUE)
rownames(counts2) <- c("ENSG00000133703.13", "ENSG00000133703.14", "ENSG00000141510.16")
res2 <- collapse_counts_by_stem(counts2, rownames(counts2), ens2hgnc)
ok(nrow(res2$counts) == 2, "duplicate stems must collapse to one row")
ok(all(res2$counts["ENSG00000133703", ] == c(4L, 6L)), "duplicate-stem counts must be SUMMED")

# --- scenario 3: an empty input FAILS LOUD (degenerate re-key) ---------------
empty <- matrix(integer(0), nrow = 0, ncol = 2)
err <- tryCatch({collapse_counts_by_stem(empty, character(0), ens2hgnc); NA},
                error = function(e) conditionMessage(e))
ok(is.character(err) && grepl("0 genes", err), "empty collapse must stop() loudly")

cat("ALL_OK\n")
"""


@pytest.mark.skipif(
    RSCRIPT is None,
    reason="No Rscript in the repo pixi env or on PATH; cannot exercise collapse_counts_by_stem",
)
def test_collapse_counts_by_stem_keeps_stems_separate_and_fails_loud(tmp_path):
    fn_src = _extract_collapse_fn(LIB_PATH.read_text())
    script_path = tmp_path / "run_collapse.R"
    script_path.write_text(R_TEMPLATE.replace("__COLLAPSE_FN__", fn_src))
    result = subprocess.run([RSCRIPT, "--vanilla", str(script_path)], capture_output=True, text=True)
    assert "ALL_OK" in result.stdout, (
        f"collapse_counts_by_stem assertions failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert result.returncode == 0


def test_load_recount3_wires_collapse_key():
    src = LOADER_PATH.read_text()
    # --collapse-key option exists and DEFAULTS to the shipped, byte-identical path.
    assert re.search(r'make_option\(\s*"--collapse-key"', src), "--collapse-key option missing"
    assert re.search(r'"--collapse-key".*?default\s*=\s*"gene_symbol"', src, re.S), (
        "--collapse-key must default to 'gene_symbol' (byte-identical to production)"
    )
    # The value is validated against the closed set.
    assert re.search(r'collapse_key\s*%in%\s*c\("gene_symbol",\s*"gene_stem"\)', src), (
        "collapse_key must be validated against {gene_symbol, gene_stem}"
    )
    # The gene_stem branch routes through the shared pure helper.
    assert re.search(r'if\s*\(collapse_key\s*==\s*"gene_stem"\)', src), (
        "the re-key must be gated behind collapse_key == 'gene_stem'"
    )
    assert "collapse_counts_by_stem(counts_mat, common_genes, ens2hgnc)" in src, (
        "the gene_stem branch must call the shared collapse_counts_by_stem helper"
    )
    # The DEFAULT branch still performs the shipped symbol collapse (unchanged).
    assert re.search(r"counts_mat\s*<-\s*rowsum\(counts_mat,\s*gene_symbol\)", src), (
        "the default gene_symbol collapse (rowsum by gene_symbol) must be preserved"
    )
