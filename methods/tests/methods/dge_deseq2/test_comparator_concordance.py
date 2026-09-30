"""_comparator_concordance (slice 4) — do the two INDEPENDENT tumor-vs-normal comparator families
(TCGA-adjacent cell A vs GTEx cell C) agree?

cells_supporting collapses cross-comparator agreement to a COUNT; this derived categorical exposes
whether TCGA-adjacent and GTEx concur — the robustness the multi-cell design exists to produce.
Pins the three outcomes (concordant / discordant / single_comparator; sub-significant cells don't
count). Each family is now a SINGLE cell (the ComBat cell B was removed in analysis-methods#727),
so a family can no longer self-disagree. Hermetic — pure dict inputs, no S3.
"""

from __future__ import annotations

import importlib
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]

read = importlib.import_module("onc_methods.dge_deseq2.read")
cc = read._comparator_concordance


def _row(a=None, qa=None, c=None, qc=None):
    return {
        "log2fc_cell_a": a,
        "q_value_cell_a": qa,
        "log2fc_cell_c": c,
        "q_value_cell_c": qc,
    }


def test_concordant_both_families_same_direction():
    assert cc(_row(a=2.0, qa=1e-4, c=1.8, qc=1e-3)) == "concordant"  # adj up + gtex up
    assert cc(_row(a=-2.0, qa=1e-4, c=-1.5, qc=1e-3)) == "concordant"  # adj down + gtex down


def test_discordant_families_opposite_direction():
    assert cc(_row(a=2.0, qa=1e-4, c=-1.5, qc=1e-3)) == "discordant"  # the field-effect failure mode


def test_single_comparator_when_one_family_not_significant():
    # GTEx cell C present but not significant → can't assess cross-comparator agreement
    assert cc(_row(a=2.0, qa=1e-4, c=0.1, qc=0.9)) == "single_comparator"
    # only the GTEx family present (no A) → single
    assert cc(_row(c=1.8, qc=1e-3)) == "single_comparator"
    # nothing significant → single
    assert cc(_row(a=0.1, qa=0.8, c=0.1, qc=0.9)) == "single_comparator"


def test_legacy_cell_b_columns_are_ignored():
    # A stray log2fc_cell_b/q_value_cell_b from an OLD product must NOT enter the adjacent family
    # (which is cell A only since #727): here A is n.s. and C is up → only one family → single.
    row = _row(a=0.1, qa=0.8, c=1.8, qc=1e-3)
    row["log2fc_cell_b"] = 2.0
    row["q_value_cell_b"] = 1e-4
    assert cc(row) == "single_comparator"


def test_empty_or_none_row_is_single_comparator():
    assert cc(None) == "single_comparator"
    assert cc({}) == "single_comparator"


def test_field_wired_into_selectivity_summary_shape():
    """The reader's summary dict must carry comparator_concordance (both v3 + v2 paths add it).
    We can't hit S3 here, but we can assert the classifier is referenced in the return assembly."""
    src = (REPO / "onc_methods" / "dge_deseq2" / "read" / "__init__.py").read_text()
    assert src.count('"comparator_concordance"') >= 2, (
        "comparator_concordance must be emitted in BOTH the v3 primary and v2 fallback returns"
    )
