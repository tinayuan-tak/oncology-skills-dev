"""Finding #1 regression: a non_essential-shape distribution must classify non_dependent, not the old
broadly_dependent fallback (an over-call). Pure-function unit tests of _classify_dependency."""

from __future__ import annotations
import importlib.util, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
CLI = REPO / "methods" / "depmap_chronos_distribution" / "cli.py"


def _load():
    spec = importlib.util.spec_from_file_location("chr_cli_b", CLI)
    m = importlib.util.module_from_spec(spec)
    sys.modules["chr_cli_b"] = m
    spec.loader.exec_module(m)
    return m


cli = _load()


def test_non_essential_shape_is_non_dependent_not_broadly():
    # #1: in the selective FRACTION band but unimodal / median>-0.5 → non_dependent (was broadly_dependent).
    assert cli._classify_dependency(0.06, 0.10, "non_essential", n_cell_lines_evaluated=1500) == "non_dependent"
    assert cli._classify_dependency(0.30, -0.20, "non_essential", n_cell_lines_evaluated=1500) == "non_dependent"


def test_positive_and_negative_controls_unchanged():
    assert (
        cli._classify_dependency(0.20, -0.40, "bimodal_selective", n_cell_lines_evaluated=1500) == "strongly_selective"
    )
    assert (
        cli._classify_dependency(0.30, -0.90, "shifted_dependent", n_cell_lines_evaluated=1500) == "broadly_dependent"
    )
    assert cli._classify_dependency(0.90, -1.9, "pan_essential", n_cell_lines_evaluated=1500) == "common_essential"
    assert cli._classify_dependency(0.01, 0.10, "non_essential", n_cell_lines_evaluated=1500) == "non_dependent"
