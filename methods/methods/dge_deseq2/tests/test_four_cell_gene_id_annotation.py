"""The four-cell driver carries the loader's gene_id / gene_stem onto every emitted
parquet as ADDITIVE annotation columns (analysis-methods#835, #761 S1) WITHOUT
touching the verdict-bearing columns.

This is the verdict-NEUTRAL first step of the #761 gene-id re-key epic: the loader
rowdata (gene_symbol, gene_id versioned ENSG.N, gene_stem unversioned) is left-joined
onto the assembled sensitivity frame and each contrast frame by gene_symbol, so a
downstream consumer can key on the stable Ensembl id — but the rowsum collapse and
every parquet filter still key on gene_symbol, so gene_symbol / log2FoldChange / padj
stay byte-identical.

Two complementary, cheap, non-vacuous guards (no DESeq2, no S3):

1. `test_annotate_gene_ids_populates_and_is_verdict_neutral` (R-subprocess) EXTRACTS the
   REAL `annotate_gene_ids()` definition from `06_four_cell_driver.R` (not a copy) and
   exercises it: the new gene_id/gene_stem columns are POPULATED non-NA and correct for
   present symbols; the verdict columns (gene_symbol/log2FoldChange/padj) are IDENTICAL
   before/after; a symbol ABSENT from rowdata gets NA (so the guard has teeth — the
   join is a real lookup, not a broadcast); and a NULL/short rowdata still yields the two
   columns as all-NA (schema stable across substrates/vintages).

2. `test_driver_annotates_both_sens_and_contrast_frames` pins the REAL driver wiring:
   `annotate_gene_ids` is applied to the assembled `sens` frame AND inside `write_contrast`
   (so both `sensitivity.parquet` and the contrast parquets gain the columns), and the
   join still keys on gene_symbol via `match()`.

A full end-to-end driver run (DESeq2 on a synthetic bundle) is deliberately NOT used: it
needs the R/Bioconductor env, is slow, and skips vacuously where that env is absent —
the guards above are hermetic and run wherever the artifact they protect is reachable.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

METHODS_REPO = Path(__file__).resolve().parents[3]
DRIVER_PATH = METHODS_REPO / "methods" / "dge_deseq2" / "r" / "live" / "06_four_cell_driver.R"


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


def _driver_source() -> str:
    return DRIVER_PATH.read_text()


def _extract_annotate_fn(src: str) -> str:
    """Pull the top-level `annotate_gene_ids <- function(df) { ... }` block verbatim.

    The function is a top-level definition, so its closing brace is a bare `}` at column 0
    — scan from the def line to that line. Exercising the extracted text (not a rewritten
    copy) keeps this a real test of the shipped function.
    """
    lines = src.splitlines()
    start = next(
        (i for i, ln in enumerate(lines) if ln.startswith("annotate_gene_ids <- function(df)")),
        None,
    )
    assert start is not None, "annotate_gene_ids definition not found in 06_four_cell_driver.R"
    end = next((j for j in range(start + 1, len(lines)) if lines[j] == "}"), None)
    assert end is not None, "could not find the closing brace of annotate_gene_ids"
    return "\n".join(lines[start : end + 1])


R_TEMPLATE = r"""
__ANNOTATE_FN__

ok <- function(cond, msg) if (!isTRUE(cond)) stop(msg)

# Synthetic per-gene frame shaped like the assembled sens / a contrast df.
df <- data.frame(
  gene_symbol    = c("KRAS", "TP53", "GHOST"),   # GHOST is absent from rowdata
  log2FoldChange = c(2.0, -1.5, 0.3),
  padj           = c(1e-8, 2e-3, 0.9),
  stringsAsFactors = FALSE)
verdict_before <- df[, c("gene_symbol", "log2FoldChange", "padj")]

# rowdata as the loaders emit it (one row per gene_symbol; versioned id + stem).
rowdata <- data.frame(
  gene_symbol = c("TP53", "KRAS", "EGFR"),
  gene_id     = c("ENSG00000141510.16", "ENSG00000133703.13", "ENSG00000146648.18"),
  gene_stem   = c("ENSG00000141510", "ENSG00000133703", "ENSG00000146648"),
  stringsAsFactors = FALSE)

out <- annotate_gene_ids(df)

# 1. new columns exist
ok(all(c("gene_id", "gene_stem") %in% names(out)), "gene_id/gene_stem columns missing")

# 2. verdict columns byte-identical (additive-only)
ok(identical(out[, c("gene_symbol", "log2FoldChange", "padj")], verdict_before),
   "verdict columns changed by annotate_gene_ids")

# 3. present symbols POPULATED non-NA and mapped by gene_symbol (order preserved)
ok(out$gene_id[out$gene_symbol == "KRAS"] == "ENSG00000133703.13", "KRAS gene_id wrong")
ok(out$gene_stem[out$gene_symbol == "KRAS"] == "ENSG00000133703", "KRAS gene_stem wrong")
ok(out$gene_id[out$gene_symbol == "TP53"] == "ENSG00000141510.16", "TP53 gene_id wrong")
ok(all(!is.na(out$gene_id[out$gene_symbol %in% c("KRAS", "TP53")])),
   "present-symbol gene_id must be non-NA")

# 4. TEETH: a symbol absent from rowdata gets NA (real lookup, not a broadcast)
ok(is.na(out$gene_id[out$gene_symbol == "GHOST"]), "absent symbol must map to NA gene_id")

# 5. schema stable when rowdata is NULL / lacks columns
rowdata <- NULL
out2 <- annotate_gene_ids(df)
ok(all(c("gene_id", "gene_stem") %in% names(out2)), "columns must exist even w/o rowdata")
ok(all(is.na(out2$gene_id)) && all(is.na(out2$gene_stem)),
   "null rowdata must yield all-NA gene_id/gene_stem")
ok(identical(out2[, c("gene_symbol", "log2FoldChange", "padj")], verdict_before),
   "verdict columns changed on the null-rowdata path")

cat("ALL_OK\n")
"""


@pytest.mark.skipif(
    RSCRIPT is None,
    reason="No Rscript in the repo pixi env or on PATH; cannot exercise annotate_gene_ids",
)
def test_annotate_gene_ids_populates_and_is_verdict_neutral(tmp_path):
    fn_src = _extract_annotate_fn(_driver_source())
    script_path = tmp_path / "run_annotate.R"
    script_path.write_text(R_TEMPLATE.replace("__ANNOTATE_FN__", fn_src))
    result = subprocess.run(
        [RSCRIPT, "--vanilla", str(script_path)],
        capture_output=True,
        text=True,
    )
    assert "ALL_OK" in result.stdout, (
        f"annotate_gene_ids assertions failed (exit {result.returncode}):\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    assert result.returncode == 0


def test_driver_annotates_both_sens_and_contrast_frames():
    src = _driver_source()
    # Applied to the assembled sensitivity frame.
    assert re.search(r"sens\s*<-\s*annotate_gene_ids\(sens\)", src), (
        "annotate_gene_ids must be applied to the assembled `sens` frame"
    )
    # Applied inside write_contrast (so the contrast parquets gain the columns too).
    assert re.search(r"df\s*<-\s*annotate_gene_ids\(df\)", src), (
        "annotate_gene_ids must be applied to the contrast `df` in write_contrast"
    )
    # Join keys on gene_symbol (the collapse/filter key), preserving row order via match().
    assert "match(df$gene_symbol, rowdata$gene_symbol)" in src, (
        "the gene_id join must key on gene_symbol via match() (order-preserving)"
    )
