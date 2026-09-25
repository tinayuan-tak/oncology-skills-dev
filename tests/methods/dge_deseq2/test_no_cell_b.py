"""Guard: cell B (ComBat-seq) stays removed from the four-cell DEG pipeline (analysis-methods#727).

Cell B was the ComBat-seq re-run of cell A on the SAME tumour-vs-adjacent samples — a robustness
re-run, not an independent comparator — and its ComBat step inflated/sign-flipped log2FC. It was
removed entirely in #727. These pins go RED if any layer re-introduces it, so a future edit cannot
silently resurrect the double-counted vote or the corrupted magnitude. Each layer is checked at the
narrowest place it would reappear: the classifier's comparator families, the per-stratum column map,
the pan-cancer union schema, and the R driver's active cell list.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

dge = importlib.import_module("methods.dge_deseq2.read")
dps = importlib.import_module("methods.dge_deseq2.derive_pancan_stack")

R_LIVE = REPO / "methods" / "dge_deseq2" / "r" / "live"


def test_only_two_comparator_families_and_neither_is_cell_b():
    # The classifier's denominator is exactly the two INDEPENDENT families: adjacent (A) + GTEx (C).
    fams = (dge._ADJACENT_CELLS, dge._GTEX_CELLS)
    assert dge._ADJACENT_CELLS == (("log2fc_cell_a", "q_value_cell_a"),)
    assert dge._GTEX_CELLS == (("log2fc_cell_c", "q_value_cell_c"),)
    all_cells = {lfc for fam in fams for (lfc, _q) in fam}
    assert all_cells == {"log2fc_cell_a", "log2fc_cell_c"}
    assert not any("cell_b" in c for c in all_cells)


def test_stratum_cell_map_has_no_cell_b():
    keys = set(dge._STRATUM_CELL_MAP)
    vals = set(dge._STRATUM_CELL_MAP.values())
    assert not any(k.endswith("_B") for k in keys), keys
    assert not any(v.endswith("_cell_b") for v in vals), vals


def test_pancan_union_schema_carries_only_cells_a_and_c():
    cols = set(dps._UNION_COLUMNS)
    assert "log2fc_B" not in cols and "padj_B" not in cols
    lfc_cells = {c.rsplit("_", 1)[-1] for c in dps._UNION_COLUMNS if c.startswith("log2fc_") and c != "max_abs_log2fc"}
    assert lfc_cells == {"A", "C"}, lfc_cells


def test_classifier_ignores_a_legacy_cell_b_column():
    # A not-yet-rebuilt product can still carry log2fc_cell_b. With cells A and C both flat, a stray
    # sig-up cell B must NOT manufacture support or a selective band. Flips if B re-enters a family.
    row = {
        "dominant_direction": "up",
        "discordant": False,
        "log2fc_cell_a": 0.1,
        "q_value_cell_a": 0.90,
        "log2fc_cell_c": 0.1,
        "q_value_cell_c": 0.90,
        "log2fc_cell_b": 5.0,
        "q_value_cell_b": 1e-12,
        "max_abs_log2fc": 5.0,
    }
    assert dge._independent_support(row, "up") == (0, 2)
    assert dge._classify_selectivity_from_sensitivity(row) == "not_informative"


def test_r_driver_has_no_active_cell_b_compute():
    # The active four-cell driver must not call run_cell("B", ...) or the ComBat helper. (Comments
    # explaining the #727 removal are allowed; an executable re-introduction is not.)
    driver = (R_LIVE / "06_four_cell_driver.R").read_text()
    strat = (R_LIVE / "07_stratified_four_cell_driver.R").read_text()
    lib = (R_LIVE / "_four_cell_lib.R").read_text()
    assert 'run_cell("B"' not in driver
    assert 'run_cell("B"' not in strat
    # combat_correct() was deleted with cell B — no combat machinery survives in the shared lib.
    assert "combat" not in lib.lower()
