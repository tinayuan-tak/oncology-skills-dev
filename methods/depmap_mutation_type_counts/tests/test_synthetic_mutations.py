"""Synthetic tests for depmap_mutation_type_counts.

Verify:
  1. VEP compound class resolution returns the highest-severity term.
  2. Category mapping handles every VEP term we care about.
  3. Each landscape_class is reachable: missense_dominant (KRAS-like),
     lof_dominant (NF1-like), mixed (TP53-like), no_mutations (<5 lines).

No S3 access required.
"""

from __future__ import annotations

import sys
from pathlib import Path

METHODS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(METHODS_ROOT))

from methods.depmap_mutation_type_counts import cli as c


def test_resolve_dominant_variant_class_single():
    assert c._resolve_dominant_variant_class("missense_variant") == "missense_variant"
    assert c._resolve_dominant_variant_class("stop_gained") == "stop_gained"


def test_resolve_dominant_variant_class_compound():
    """Compound 'stop_gained&frameshift_variant' should resolve to stop_gained
    (severity 4) since it's higher-severity than frameshift_variant (severity 5).
    """
    assert c._resolve_dominant_variant_class("stop_gained&frameshift_variant") == "stop_gained"
    # missense + splice_region → missense (severity 11) beats splice_region (13)
    assert c._resolve_dominant_variant_class("missense_variant&splice_region_variant") == "missense_variant"


def test_resolve_dominant_variant_class_handles_unknowns():
    assert c._resolve_dominant_variant_class("") is None
    assert c._resolve_dominant_variant_class(None) is None
    assert (
        c._resolve_dominant_variant_class("unknown_vep_term") == "unknown_vep_term"
    )  # still returns the only candidate


def test_category_mapping_canonical():
    assert c._category_for_class("missense_variant") == "missense"
    assert c._category_for_class("stop_gained") == "nonsense"
    assert c._category_for_class("frameshift_variant") == "frameshift"
    assert c._category_for_class("splice_acceptor_variant") == "splice"
    assert c._category_for_class("splice_donor_variant") == "splice"
    assert c._category_for_class("splice_region_variant") == "splice"
    assert c._category_for_class("inframe_insertion") == "inframe_indel"
    assert c._category_for_class("inframe_deletion") == "inframe_indel"
    assert c._category_for_class("synonymous_variant") == "synonymous"
    assert c._category_for_class("5_prime_UTR_variant") == "other"
    assert c._category_for_class("intron_variant") == "other"


def _build_mutation_rows(rows: list[dict]) -> list:
    """Helper: each row should have keys ModelID + VariantInfo (+ optional ProteinChange)."""
    return [
        {"ModelID": r["model"], "HugoSymbol": "TEST", "VariantInfo": r["vep"], "ProteinChange": r.get("protein", "p.X")}
        for r in rows
    ]


def test_missense_dominant_kras_like():
    """KRAS-like: 95% missense → missense_dominant."""
    rows = _build_mutation_rows(
        [{"model": f"ACH-{i:06d}", "vep": "missense_variant"} for i in range(95)]
        + [{"model": f"ACH-{i:06d}", "vep": "stop_gained"} for i in range(95, 100)]
    )
    meta = {f"ACH-{i:06d}": {"ModelID": f"ACH-{i:06d}", "OncotreeLineage": "Lung"} for i in range(100)}
    s = c.compute_summary_stats(rows, meta, n_cell_lines_total=1500)
    assert s["mutation_landscape_class"] == "missense_dominant"
    assert s["mut_dominant_mutation_class"] == "missense"
    assert s["mut_n_cell_lines_mutated"] == 100
    assert s["mut_fraction_missense"] >= 0.70


def test_lof_dominant_nf1_like():
    """NF1-like: ~70% LOF (nonsense + frameshift + splice) → lof_dominant."""
    rows = _build_mutation_rows(
        [{"model": f"ACH-{i:06d}", "vep": "stop_gained"} for i in range(30)]
        + [{"model": f"ACH-{i:06d}", "vep": "frameshift_variant"} for i in range(30, 60)]
        + [{"model": f"ACH-{i:06d}", "vep": "splice_acceptor_variant"} for i in range(60, 70)]
        + [{"model": f"ACH-{i:06d}", "vep": "missense_variant"} for i in range(70, 100)]
    )
    meta = {f"ACH-{i:06d}": {"ModelID": f"ACH-{i:06d}", "OncotreeLineage": "Bone"} for i in range(100)}
    s = c.compute_summary_stats(rows, meta, n_cell_lines_total=1500)
    assert s["mutation_landscape_class"] == "lof_dominant"
    assert s["mut_dominant_mutation_class"] == "lof"
    assert s["mut_fraction_lof"] >= 0.50


def test_mixed_tp53_like():
    """TP53-like: 60% missense + 40% LOF → not >= 70% missense AND not >=50% LOF → 'mixed'."""
    rows = _build_mutation_rows(
        [{"model": f"ACH-{i:06d}", "vep": "missense_variant"} for i in range(60)]
        + [{"model": f"ACH-{i:06d}", "vep": "stop_gained"} for i in range(60, 100)]
    )
    meta = {f"ACH-{i:06d}": {"ModelID": f"ACH-{i:06d}", "OncotreeLineage": "Lung"} for i in range(100)}
    s = c.compute_summary_stats(rows, meta, n_cell_lines_total=1500)
    # 60% missense (below 70% threshold) + 40% LOF (below 50% threshold) → mixed
    assert s["mutation_landscape_class"] == "mixed"
    assert s["mut_fraction_missense"] == 0.60
    assert s["mut_fraction_lof"] == 0.40


def test_no_mutations_below_threshold():
    """Only 3 mutated cell lines → no_mutations call."""
    rows = _build_mutation_rows(
        [
            {"model": "ACH-000001", "vep": "missense_variant"},
            {"model": "ACH-000002", "vep": "missense_variant"},
            {"model": "ACH-000003", "vep": "missense_variant"},
        ]
    )
    meta = {f"ACH-{i:06d}": {"ModelID": f"ACH-{i:06d}", "OncotreeLineage": "Lung"} for i in range(1, 4)}
    s = c.compute_summary_stats(rows, meta, n_cell_lines_total=1500)
    assert s["mutation_landscape_class"] == "no_mutations"
    assert s["mut_dominant_mutation_class"] == "none"


def test_empty_rows_returns_no_mutations():
    s = c.compute_summary_stats([], {}, n_cell_lines_total=1500)
    assert s["mutation_landscape_class"] == "no_mutations"
    assert s["mut_n_cell_lines_mutated"] == 0
    assert s["mut_total_mutations"] == 0


def test_per_lineage_aggregation():
    """Verify lineage aggregation counts distinct cell lines per lineage."""
    rows = _build_mutation_rows(
        [
            {"model": "ACH-000001", "vep": "missense_variant"},
            {"model": "ACH-000002", "vep": "missense_variant"},
            {"model": "ACH-000003", "vep": "missense_variant"},
            {"model": "ACH-000001", "vep": "stop_gained"},  # second mutation in same line
            {"model": "ACH-000004", "vep": "frameshift_variant"},
            {"model": "ACH-000005", "vep": "missense_variant"},
            {"model": "ACH-000006", "vep": "missense_variant"},
        ]
    )
    meta = {
        "ACH-000001": {"OncotreeLineage": "Lung"},
        "ACH-000002": {"OncotreeLineage": "Lung"},
        "ACH-000003": {"OncotreeLineage": "Lung"},
        "ACH-000004": {"OncotreeLineage": "Bowel"},
        "ACH-000005": {"OncotreeLineage": "Bowel"},
        "ACH-000006": {"OncotreeLineage": "Bowel"},
    }
    s = c.compute_summary_stats(rows, meta, n_cell_lines_total=1500)
    lung = next((l for l in s["mut_top_mutated_lineages"] if l["lineage"] == "Lung"), None)
    bowel = next((l for l in s["mut_top_mutated_lineages"] if l["lineage"] == "Bowel"), None)
    assert lung is not None and bowel is not None
    assert lung["n_mutated_lines"] == 3  # 3 distinct lines despite ACH-000001 mutated twice
    assert lung["n_observations"] == 4  # 4 observations
    assert bowel["n_mutated_lines"] == 3
