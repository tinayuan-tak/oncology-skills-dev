"""Shared helpers + constants for the compose-dashboard figure-emitter package.

Extracted from the former ~1363-line `_figure_emitters.py` monolith (figure-consolidation
Stage 4). The emitter functions now live in tier modules (_dependency / _expression /
_protein_safety / _genomic); the thin card_id->emitter registry lives in `_registry.py`;
the package `__init__` re-exports the public surface (emit_figures_for_card,
CARD_FIGURE_EMITTERS, _plotly_from, _dge_cell_contrasts).
"""

from __future__ import annotations
import os

import sys
from pathlib import Path  # noqa: F401


METHODS_REPO = Path(os.environ.get("ANALYSIS_METHODS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods"))
TARGET_CONTRACTS = Path(os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts"))




def _ensure_methods_path() -> None:
    """Idempotent: put methods repo on sys.path so `methods.<x>.cli` resolves."""
    if str(METHODS_REPO) not in sys.path:
        sys.path.insert(0, str(METHODS_REPO))




def _has_live_read_error(summary: dict) -> bool:
    return isinstance(summary, dict) and "_live_read_error" in summary




def _plotly_from(module, fn_name: str, *args) -> list[dict]:
    """Best-effort call of a method's `emit_plotly_specs` (dynamic-dashboard Phase A/B).

    The method builds `.plotly.json` interactive specs SIBLING to the matplotlib SVGs, from the
    SAME in-memory series the SVGs use (no drift). This is purely additive: a method that has not
    yet grown a Plotly emitter (fn_name absent) contributes no descriptors, and any error is
    swallowed — the SVGs remain the guaranteed artifact. Returned descriptors carry a `dynamic:
    True` flag so the renderer can prefer the interactive spec when present, SVG otherwise.
    """
    fn = getattr(module, fn_name, None)
    if fn is None:
        return []
    try:
        specs = fn(*args) or []
    except Exception as e:  # noqa: BLE001
        import sys as _sys
        print(f"[compose-dashboard:figures] plotly spec emission skipped "
              f"({getattr(module, '__name__', module)}.{fn_name}): {type(e).__name__}: {e}",
              file=_sys.stderr)
        return []
    return [{**s, "dynamic": True} for s in specs]




# The 4-cell sensitivity contrasts the tumor-vs-normal-selectivity SVG forest draws (Cell A/B/C/D).
# Kept in step with dge_deseq2.emit.emit_tumor_vs_normal_selectivity_4panel's `cells` list so the
# interactive forest shows the SAME contrasts (no recompute — read straight off the summary).
_DGE_SENSITIVITY_CELLS = [
    ("tumor vs TCGA adj (raw)", "log2fc_cell_a", "q_value_cell_a"),
    ("tumor vs TCGA adj (ComBat)", "log2fc_cell_b", "q_value_cell_b"),
    ("tumor vs GTEx (raw joint)", "log2fc_cell_c", "q_value_cell_c"),
    ("tumor vs GTEx (ComBat)", "log2fc_cell_d", "q_value_cell_d"),
]




def _dge_cell_contrasts(summary: dict) -> list[dict]:
    rows = []
    for label, lfc_k, q_k in _DGE_SENSITIVITY_CELLS:
        lfc = summary.get(lfc_k)
        if lfc is None or lfc != lfc:   # skip absent / NaN cells (matches the SVG)
            continue
        rows.append({"label": label, "log2_fc": float(lfc), "q_value": summary.get(q_k)})
    return rows
