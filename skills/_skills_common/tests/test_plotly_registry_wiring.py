"""Dynamic-dashboard Phase B — the figure registry emits interactive Plotly specs alongside SVGs.

Pure unit tests (no S3, no method internals) for the two additive pieces in _figure_emitters:
  - `_plotly_from` — the best-effort wrapper that calls a method's `emit_plotly_specs`, tags each
    returned descriptor `dynamic: True`, and degrades to [] when the method has no Plotly emitter
    yet or the call raises (SVGs stay the guaranteed artifact).
  - `_dge_cell_contrasts` — extracts the 4-cell sensitivity contrasts the tumor-vs-normal SVG forest
    draws, straight off the summary (no recompute), so the interactive forest shows the SAME cells.
"""

from __future__ import annotations

import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent  # skills/_skills_common
sys.path.insert(0, str(SKILL_DIR))  # _skills_common on path → _figure_emitters

import _figure_emitters as fe  # noqa: E402


class _FakeModule:
    __name__ = "fake_method"

    @staticmethod
    def emit_plotly_specs(*args):
        return [
            {"id": "waterfall", "path": "figure_waterfall.plotly.json", "type": "plotly"},
            {"id": "hist", "path": "figure_hist.plotly.json", "type": "plotly"},
        ]


class _RaisingModule:
    __name__ = "boom_method"

    @staticmethod
    def emit_plotly_specs(*args):
        raise RuntimeError("plotly not installed")


class _NoPlotlyModule:
    __name__ = "legacy_method"
    # deliberately has NO emit_plotly_specs


def test_plotly_from_tags_dynamic_and_passes_through_descriptors():
    out = fe._plotly_from(_FakeModule, "emit_plotly_specs", "arg1", "arg2")
    assert len(out) == 2
    assert all(d["dynamic"] is True for d in out)  # renderer prefers these when present
    assert {d["id"] for d in out} == {"waterfall", "hist"}
    assert all(d["type"] == "plotly" for d in out)


def test_plotly_from_is_graceful_when_emitter_absent():
    """A method that hasn't grown a Plotly emitter contributes nothing — not an error."""
    assert fe._plotly_from(_NoPlotlyModule, "emit_plotly_specs") == []


def test_plotly_from_swallows_errors_svgs_are_the_guarantee():
    assert fe._plotly_from(_RaisingModule, "emit_plotly_specs") == []


def test_dge_cell_contrasts_extracts_present_cells_in_forest_order():
    summary = {
        "log2fc_cell_a": 1.2,
        "q_value_cell_a": 1e-5,
        "log2fc_cell_b": 1.4,
        "q_value_cell_b": 1e-6,
        # cell C absent, cell D NaN → both skipped (mirrors the SVG forest)
        "log2fc_cell_d": float("nan"),
        "q_value_cell_d": 0.2,
    }
    rows = fe._dge_cell_contrasts(summary)
    assert [r["label"] for r in rows] == ["tumor vs TCGA adj (raw)", "tumor vs TCGA adj (ComBat)"]
    assert [r["log2_fc"] for r in rows] == [1.2, 1.4]
    assert rows[0]["q_value"] == 1e-5


def test_dge_cell_contrasts_empty_when_no_cells():
    assert fe._dge_cell_contrasts({}) == []
