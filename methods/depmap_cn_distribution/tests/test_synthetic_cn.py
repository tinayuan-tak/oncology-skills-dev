"""Synthetic-data tests for depmap_cn_distribution.

Verify:
  1. Each copy_number_class value is reachable with appropriate inputs:
     broadly_neutral (KRAS-like, mutation-driven), recurrently_amplified (MYC-like),
     recurrently_deleted (CDKN2A-like), mixed (both recurrent in different lineages),
     data_unavailable (no data).
  2. Threshold boundaries: a value of exactly 1.5 should NOT be flagged as focal_amp
     (the threshold is strictly greater than 1.5).
  3. _parse_gene_symbol + _find_target_col handle the 'SYMBOL (entrez_id)' format.
  4. _classify_cn's recurrent thresholds + dominance ratio behave correctly.

No S3 access required.
"""

from __future__ import annotations
import sys
from pathlib import Path


METHODS_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(METHODS_ROOT))

from methods.depmap_cn_distribution import cli as c


def test_parse_gene_symbol_standard():
    assert c._parse_gene_symbol("KRAS (3845)") == "KRAS"
    assert c._parse_gene_symbol("MYC (4609)") == "MYC"
    assert c._parse_gene_symbol("MT-ND6 (4541)") == "MT-ND6"


def test_parse_gene_symbol_malformed():
    assert c._parse_gene_symbol("just_a_symbol") is None
    assert c._parse_gene_symbol("KRAS") is None
    assert c._parse_gene_symbol(None) is None


def test_find_target_col():
    cols = ["ModelConditionID", "IsDefaultEntryForMC", "KRAS (3845)", "MET (4233)"]
    assert c._find_target_col(cols, "KRAS") == "KRAS (3845)"
    assert c._find_target_col(cols, "MET") == "MET (4233)"
    assert c._find_target_col(cols, "MYC") is None  # not in cols


def _synth(lineages_with_cn: dict) -> tuple[dict, dict]:
    """Build (cn_by_model, model_metadata) from {lineage: [cn, cn, ...]}."""
    cn = {}
    meta = {}
    next_id = 1
    for lineage, values in lineages_with_cn.items():
        for v in values:
            mid = f"ACH-{next_id:06d}"
            cn[mid] = float(v)
            meta[mid] = {"ModelID": mid, "OncotreeLineage": lineage, "CCLEName": f"CL{next_id}_{lineage.upper()}"}
            next_id += 1
    return cn, meta


def test_broadly_neutral_kras_like():
    """KRAS-like: mutation-driven, mostly diploid. broadly_neutral is the CORRECT call."""
    cn, meta = _synth(
        {
            "Lung": [1.0, 1.02, 0.98, 1.05, 1.01, 0.99, 1.03, 1.04, 0.97, 1.0],
            "Bowel": [1.01, 0.99, 1.0, 1.02, 0.98, 1.03, 1.0, 0.99, 1.01, 1.02],
            "Breast": [0.96, 1.0, 1.04, 1.0, 1.02, 0.98, 1.0, 1.01, 1.03, 0.97],
        }
    )
    s = c.compute_summary_stats(cn, meta, assay_used="wes")
    assert s["copy_number_class"] == "broadly_neutral"
    assert s["cn_assay_used"] == "wes"
    # Sanity: amp + del fractions are both negligible
    assert s["cn_recurrent_amplification_score"] < 0.05
    assert s["cn_recurrent_deletion_score"] < 0.05


def test_recurrently_amplified_myc_like():
    """MYC-like: focal amp in 30%+ of lines; recurrently_amplified."""
    cn, meta = _synth(
        {
            "Liver": [2.5, 3.0, 2.2, 1.8, 5.0, 1.9, 2.4, 6.0, 2.1, 3.5],
            "Breast": [2.0, 1.7, 2.3, 2.5, 1.6, 1.9, 2.1, 1.8, 2.0, 2.4],
            "Other": [1.0, 1.1, 0.95, 1.0, 1.05, 1.0, 0.98, 1.02, 1.0, 1.0],
        }
    )
    s = c.compute_summary_stats(cn, meta, assay_used="wes")
    assert s["copy_number_class"] == "recurrently_amplified"
    assert s["cn_recurrent_amplification_score"] >= 0.20


def test_recurrently_deleted_cdkn2a_like():
    """CDKN2A-like: deep deletion in 30%+ of lines; recurrently_deleted."""
    cn, meta = _synth(
        {
            "Pleura": [0.3, 0.4, 0.2, 0.5, 0.0, 0.3, 0.4, 0.5, 0.2, 0.3],
            "Lung": [0.7, 0.85, 0.9, 0.75, 0.8, 0.88, 0.9, 0.85, 0.78, 0.82],
            "Other": [1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0, 1.0],
        }
    )
    s = c.compute_summary_stats(cn, meta, assay_used="wes")
    assert s["copy_number_class"] == "recurrently_deleted"
    assert s["cn_recurrent_deletion_score"] >= 0.20


def test_mixed_both_recurrent_balanced():
    """Both amp and del recurrent (different lineages), balanced ratio → mixed."""
    cn, meta = _synth(
        {
            "AmpLineage1": [3.0, 4.0, 5.0, 3.5, 2.8, 6.0, 4.5, 3.2, 5.5, 4.0],
            "AmpLineage2": [3.0, 2.5, 4.0, 5.0, 3.5, 2.8, 4.5, 3.0, 5.0, 3.5],
            "DelLineage1": [0.4, 0.3, 0.5, 0.6, 0.4, 0.3, 0.5, 0.4, 0.3, 0.5],
            "DelLineage2": [0.7, 0.8, 0.6, 0.5, 0.85, 0.7, 0.75, 0.9, 0.8, 0.7],
        }
    )
    s = c.compute_summary_stats(cn, meta, assay_used="wes")
    # Both should be recurrent; balanced ratio (50% amp + 50% del across 40 lines = 0.5/0.5)
    # So neither beats the other by 2x → 'mixed'
    assert s["copy_number_class"] == "mixed"


def test_data_unavailable_empty():
    """Empty CN dict -> data_unavailable."""
    s = c.compute_summary_stats({}, {})
    assert s["copy_number_class"] == "data_unavailable"
    assert s["cn_distribution_shape"] == "unclassified"
    assert s["cn_n_cell_lines_evaluated"] == 0


def test_threshold_boundary_focal_amp_strict():
    """A value of exactly 1.5 should be 'shallow_amp', not 'focal_amp' (boundary is STRICT '>')."""
    # All values exactly at 1.5
    cn, meta = _synth({"Lung": [1.5] * 30})
    s = c.compute_summary_stats(cn, meta, assay_used="wes")
    # 1.5 is the upper bound of shallow_amp range (1.07 < CN <= 1.5)
    assert s["cn_fraction_shallow_amplification"] == 1.0
    assert s["cn_fraction_focal_amplification"] == 0.0


def test_classify_cn_dominant_amp():
    """When amp fraction >= 2x del fraction, both recurrent → recurrently_amplified."""
    # amp=0.6, del=0.25 → 0.6 >= 2*0.25 = 0.5 ✓ → dominant amp
    cls = c._classify_cn(fraction_amp=0.6, fraction_del=0.25)
    assert cls == "recurrently_amplified"


def test_classify_cn_dominant_del():
    """When del fraction >= 2x amp fraction, both recurrent → recurrently_deleted."""
    cls = c._classify_cn(fraction_amp=0.25, fraction_del=0.6)
    assert cls == "recurrently_deleted"


def test_modelid_bridge_via_modelcondition_not_model():
    """Regression: the MC-ID → ModelID bridge lives in ModelCondition.csv, NOT
    Model.csv. The 26Q1 Model.csv carries only ModelID + lineage; ModelConditionID
    is intentionally separate (one ModelID can have many MC-IDs across conditions).
    The loader must fetch ModelCondition.csv as the bridge or per-line lineage
    attribution will fail (all cell lines fall into 'unknown' lineage)."""
    # This test exists to document the contract rather than execute it (S3 access
    # is required for the actual load_cn_files call). The implementation guard is
    # in cli.py: load_cn_files fetches BOTH Model.csv AND ModelCondition.csv, and
    # builds mc_to_model from ModelCondition.csv (not Model.csv).
    import inspect

    src = inspect.getsource(c.load_cn_files)
    assert "ModelCondition.csv" in src, "load_cn_files must fetch ModelCondition.csv as the MC-ID bridge"
    assert "mc_to_model" in src, "load_cn_files must build mc_to_model dict for the bridge"
