"""Synthetic-data tests for depmap_demeter_distribution.

Verify:
  1. _parse_gene_symbol correctly extracts symbols from 'SYMBOL (entrez_id)' labels.
  2. compute_summary_stats produces expected fields + correct dependency_class
     classification for three designed distributions (pan-essential, selective,
     non-dependent).
  3. DEMETER2 thresholds (strong=-0.5) are honored, NOT the CRISPR -1.0 threshold.

No S3 access required.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

METHODS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(METHODS_ROOT))

from methods.depmap_demeter_distribution import cli as c


def test_parse_gene_symbol_standard():
    assert c._parse_gene_symbol('"KRAS (3845)"') == "KRAS"
    assert c._parse_gene_symbol("KRAS (3845)") == "KRAS"
    assert c._parse_gene_symbol('"A1BG (1)"') == "A1BG"


def test_parse_gene_symbol_special_chars():
    assert c._parse_gene_symbol("MT-ND6 (4541)") == "MT-ND6"
    assert c._parse_gene_symbol("C1orf112 (55732)") == "C1orf112"


def test_parse_gene_symbol_malformed():
    assert c._parse_gene_symbol("just_a_symbol") is None
    assert c._parse_gene_symbol("KRAS") is None
    assert c._parse_gene_symbol(None) is None


def _build_synthetic_panel(scores_by_lineage: dict) -> tuple[dict, dict]:
    """Build (demeter_by_model, model_metadata) from {lineage: [score, score, ...]}."""
    demeter = {}
    metadata = {}
    next_id = 1
    for lineage, scores in scores_by_lineage.items():
        for s in scores:
            mid = f"ACH-{next_id:06d}"
            demeter[mid] = float(s)
            metadata[mid] = {"ModelID": mid, "OncotreeLineage": lineage,
                              "CCLEName": f"FAKE{next_id}_{lineage.upper()}"}
            next_id += 1
    return demeter, metadata


def test_classify_pan_essential():
    """All cell lines strongly dependent -> common_essential."""
    demeter, meta = _build_synthetic_panel({
        "Lung": [-1.5, -1.4, -1.6, -1.3, -1.5, -1.7, -1.4, -1.5, -1.6, -1.4],
        "Breast": [-1.3, -1.5, -1.4, -1.6, -1.4, -1.5, -1.7, -1.3, -1.4, -1.5],
        "Bowel": [-1.5, -1.4, -1.6, -1.3, -1.5, -1.7, -1.4, -1.5, -1.6, -1.4],
    })
    summary = c.compute_summary_stats(demeter, meta)
    assert summary["rnai_n_cell_lines_evaluated"] == 30
    assert summary["rnai_dependency_class"] == "common_essential"
    assert summary["rnai_fraction_strongly_dependent"] >= 0.85


def test_classify_strongly_selective():
    """Only one lineage strongly dependent -> strongly_selective."""
    demeter, meta = _build_synthetic_panel({
        "Lung": [0.0, 0.05, -0.05, 0.1, -0.1, 0.0, 0.05, 0.0, 0.0, -0.05],
        "Breast": [0.0, 0.05, -0.05, 0.1, -0.1, 0.0, 0.05, 0.0, 0.0, -0.05],
        "Bowel": [-1.2, -1.0, -1.1, -0.9, -1.3, -1.0, -1.1, -1.2, -0.9, -1.0],
    })
    summary = c.compute_summary_stats(demeter, meta)
    assert summary["rnai_dependency_class"] == "strongly_selective"
    # ~33% strongly dependent (Bowel = strongly dependent at -0.5 cutoff; lineages of 0 are not)
    assert 0.20 <= summary["rnai_fraction_strongly_dependent"] <= 0.50
    assert "Bowel" in [t["lineage"] for t in summary["rnai_top_dependent_lineages"]]


def test_classify_non_dependent():
    """No cell lines dependent -> non_dependent."""
    demeter, meta = _build_synthetic_panel({
        "Lung": [0.05, 0.1, 0.0, -0.05, 0.05, 0.0, 0.1, 0.0, -0.05, 0.05],
        "Breast": [-0.1, 0.0, 0.05, 0.1, -0.05, 0.0, 0.05, 0.0, 0.05, -0.1],
        "Bowel": [0.0, 0.05, 0.1, 0.0, -0.05, 0.0, 0.05, 0.1, 0.0, -0.05],
    })
    summary = c.compute_summary_stats(demeter, meta)
    assert summary["rnai_dependency_class"] == "non_dependent"
    assert summary["rnai_fraction_strongly_dependent"] == 0.0


def test_demeter_thresholds_differ_from_chronos():
    """A score of -0.6 should be 'strongly_dependent' on DEMETER2 scale (threshold -0.5)
    but would NOT cross CRISPR's -1.0 threshold. Verify the method honors DEMETER2 thresholds."""
    demeter, meta = _build_synthetic_panel({
        "Lung": [-0.6, -0.7, -0.6, -0.8, -0.6, -0.7, -0.6, -0.7, -0.6, -0.8],
        "Breast": [-0.6, -0.7, -0.6, -0.8, -0.6, -0.7, -0.6, -0.7, -0.6, -0.8],
        "Bowel": [-0.6, -0.7, -0.6, -0.8, -0.6, -0.7, -0.6, -0.7, -0.6, -0.8],
    })
    summary = c.compute_summary_stats(demeter, meta, strong_threshold=-0.5)
    # All 30 lines should be flagged as strongly dependent on DEMETER2 scale
    assert summary["rnai_fraction_strongly_dependent"] == 1.0
    assert summary["rnai_dependency_class"] == "common_essential"
