"""mutation_landscape_class — the DepMap cell-line variant-class landscape label (drives Tier-2 rules).

PR-C3 pins the n-honesty boundaries around the classifier:
  - n_mutated == 0                         -> no_mutations   (a genuine MEASURED negative)
  - 1 <= n_mutated < min_mutated (5)       -> underpowered   (coverage gap — too few lines)
  - n_mutated >= 5 but zero CODING variants -> underpowered  (no signal to classify; NOT false `mixed`)
  - n_mutated >= 5 with coding variants     -> missense_dominant / lof_dominant / mixed
And the dominant-class argmax tie-break -> `mixed` (never let dict order pick missense over an equal lof).
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.depmap_mutation_type_counts.cli import compute_summary_stats  # noqa: E402


def _rows(spec):
    """spec: list of (ModelID, VariantInfo). Builds MAF-style target_rows."""
    return [{"ModelID": mid, "VariantInfo": vi} for mid, vi in spec]


def _summary(spec, n_total=1000):
    return compute_summary_stats(_rows(spec), {}, n_cell_lines_total=n_total)


def test_no_mutations_is_measured_negative():
    # Zero mutated cell lines → no_mutations (a genuine measured negative, NOT underpowered).
    s = _summary([])
    assert s["mut_n_cell_lines_mutated"] == 0
    assert s["mutation_landscape_class"] == "no_mutations"


def test_underpowered_below_min_mutated():
    # 3 mutated cell lines (< min_mutated 5) → underpowered (coverage gap), NOT no_mutations.
    spec = [(f"M{i}", "missense_variant") for i in range(3)]
    s = _summary(spec)
    assert s["mut_n_cell_lines_mutated"] == 3
    assert s["mutation_landscape_class"] == "underpowered"
    assert s["mut_dominant_mutation_class"] == "none"


def test_underpowered_when_zero_coding_variants():
    # 8 mutated cell lines but ALL are synonymous/non-coding → zero coding signal to classify.
    # Previously this fell through to `mixed` (a false dual-role signal); now underpowered.
    spec = [(f"M{i}", "synonymous_variant") for i in range(8)]
    s = _summary(spec)
    assert s["mut_n_cell_lines_mutated"] == 8
    assert s["mutation_landscape_class"] == "underpowered"


def test_missense_dominant_when_powered():
    spec = [(f"M{i}", "missense_variant") for i in range(10)]
    s = _summary(spec)
    assert s["mutation_landscape_class"] == "missense_dominant"
    assert s["mut_dominant_mutation_class"] == "missense"


def test_lof_dominant_when_powered():
    spec = [(f"M{i}", "stop_gained") for i in range(10)]
    s = _summary(spec)
    assert s["mutation_landscape_class"] == "lof_dominant"
    assert s["mut_dominant_mutation_class"] == "lof"


def test_dominant_class_tie_is_mixed():
    # 5 missense + 5 LOF (equal counts) → the argmax tie must resolve to `mixed`, never silently
    # pick missense via dict-insertion order.
    spec = [(f"Mm{i}", "missense_variant") for i in range(5)] + [(f"Ml{i}", "stop_gained") for i in range(5)]
    s = _summary(spec)
    assert s["mut_dominant_mutation_class"] == "mixed"


def test_at_min_mutated_is_powered():
    # Exactly 5 mutated clears the floor.
    spec = [(f"M{i}", "missense_variant") for i in range(5)]
    s = _summary(spec)
    assert s["mut_n_cell_lines_mutated"] == 5
    assert s["mutation_landscape_class"] == "missense_dominant"
