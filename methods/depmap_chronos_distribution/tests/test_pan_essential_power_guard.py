"""H fix: pan-essential admissibility floor in the dependency classifier (2026-07-20).

A >=85% strongly-dependent fraction on an underpowered panel (< PAN_ESSENTIAL_MIN_PANEL_N)
must classify as `common_essential_underpowered` (routes to insufficient downstream), NOT
`common_essential` (which fires the pan-essential VETO). Symmetric to the shipped
non_dependent_underpowered guard at the other veto-producing end.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")))
from methods.depmap_chronos_distribution.cli import (  # noqa: E402
    _classify_dependency,
    PAN_ESSENTIAL_MIN_PANEL_N,
)


def test_pan_essential_on_adequate_panel_is_common_essential():
    assert _classify_dependency(0.90, -1.2, "pan_essential", n_cell_lines_evaluated=1500) == "common_essential"


def test_pan_essential_on_underpowered_panel_is_underpowered():
    assert (
        _classify_dependency(0.90, -1.2, "pan_essential", n_cell_lines_evaluated=PAN_ESSENTIAL_MIN_PANEL_N - 1)
        == "common_essential_underpowered"
    )


def test_floor_boundary_inclusive():
    # exactly at the floor is adequate (>= floor → trusted)
    assert (
        _classify_dependency(0.90, -1.2, "pan_essential", n_cell_lines_evaluated=PAN_ESSENTIAL_MIN_PANEL_N)
        == "common_essential"
    )


def test_missing_panel_size_does_not_downgrade():
    # None panel size (defensive) → keep common_essential, don't fabricate underpowered
    assert _classify_dependency(0.90, -1.2, "pan_essential", n_cell_lines_evaluated=None) == "common_essential"
