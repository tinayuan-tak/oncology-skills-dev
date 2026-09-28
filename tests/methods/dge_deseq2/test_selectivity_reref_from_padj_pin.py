"""Pin: the tumor-vs-normal selectivity VERDICT re-derives from per-cell padj/log2fc, and is
insulated from the product's fusion columns `sig_all_cells` / `cells_ran` (github analysis-methods#863).

#863(a) changes the R fusion so `sig_all_cells` / `cells_ran` carry corrected fit-vs-filter
semantics. That change is verdict-neutral BY CONSTRUCTION only if the reader never lets those
product columns drive `selectivity_class` — it must keep computing the class from the per-cell
comparator fields (`log2fc_cell_a/c`, `q_value_cell_a/c`, `dominant_direction`), as
`_classify_selectivity_from_sensitivity` has since FIX 4. This test pins that insulation so a
future edit that starts trusting the product's `sig_all_cells` cannot slip in unnoticed: mutating
ONLY those two columns must leave the class byte-stable.

Hermetic — pure dict inputs into the classifier, no S3 / no live read.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

read = importlib.import_module("methods.dge_deseq2.read")
classify = read._classify_selectivity_from_sensitivity


def _row(**overrides):
    # A clean two-family strong call: TCGA-adjacent (A) and GTEx (C) both significant, up, |lfc|>=1.5.
    row = {
        "dominant_direction": "up",
        "log2fc_cell_a": 2.4,
        "q_value_cell_a": 1e-6,
        "log2fc_cell_c": 2.1,
        "q_value_cell_c": 1e-5,
        "discordant": False,
        # The fusion columns whose semantics #863 corrects — deliberately set to the values the
        # OLD (buggy) fusion would have produced for a ran-but-filtered gene.
        "sig_all_cells": True,
        "cells_ran": 1,
        "cells_supporting": 1,
    }
    row.update(overrides)
    return row


def test_class_is_stable_when_only_the_fusion_columns_are_mutated():
    """Flipping sig_all_cells and cells_ran (the #863(a) columns) must not move the verdict."""
    baseline = classify(_row())
    # Mutate ONLY the fusion columns to their corrected-#863 values; per-cell fields untouched.
    mutated = classify(_row(sig_all_cells=False, cells_ran=2, cells_supporting=1))
    assert baseline == mutated == "strong_tumor_selective", (
        f"selectivity_class must re-derive from per-cell padj/log2fc, independent of the product's "
        f"sig_all_cells/cells_ran (baseline={baseline!r}, mutated={mutated!r})"
    )


def test_verdict_tracks_the_per_cell_padj_not_the_fusion_columns():
    """Making cell C non-significant (per-cell padj) DOES move the verdict even while the product's
    sig_all_cells still (wrongly) claims TRUE — proving padj, not the fusion column, is load-bearing."""
    both_sig = classify(_row())
    c_not_sig = classify(_row(q_value_cell_c=0.9, sig_all_cells=True, cells_ran=2))
    assert both_sig == "strong_tumor_selective"
    # Losing the second family's significance must demote away from a two-family strong call, even
    # though sig_all_cells is left asserting TRUE — the per-cell q-value is what the reader trusts.
    assert c_not_sig != "strong_tumor_selective", (
        f"a non-significant cell-C per-cell q must change the class regardless of sig_all_cells (got {c_not_sig!r})"
    )
