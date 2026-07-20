"""Synthetic-data tests for hpa_normal_tissue_liability (no S3).

Validates: (1) breadth classifier (Protein tissue distribution → class); (2)
specific-intensity parsing incl. multi-tissue + malformed; (3) essential-tissue
flagging over HPA's closed vocabulary; (4) the "broad gene, empty specific list"
case (essential flag absent is NOT reassurance — breadth carries liability);
(5) data_unavailable (gene absent / no call) vs graceful read failure; (6) card
contract fields. Classifier + parser are pure; the lookup uses a tiny synthetic TSV.
"""
from __future__ import annotations

import sys
from pathlib import Path

METHODS_REPO = Path("/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods")
sys.path.insert(0, str(METHODS_REPO))
from methods.hpa_normal_tissue_liability import cli as hc  # noqa: E402
from methods.hpa_normal_tissue_liability import read as hc_read  # noqa: E402


# --- breadth classifier (pure) --------------------------------------------

def test_breadth_classifier_bands():
    assert hc.classify_breadth("Detected in all") == "broad_normal_expression"
    assert hc.classify_breadth("Detected in many") == "broad_normal_expression"
    assert hc.classify_breadth("Detected in some") == "moderate_normal_expression"
    assert hc.classify_breadth("Detected in single") == "restricted_normal_expression"
    assert hc.classify_breadth("Not detected") == "not_detected_in_normal"
    assert hc.classify_breadth(None) == "data_unavailable"
    assert hc.classify_breadth("nan") == "data_unavailable"


def test_breadth_classifier_case_insensitive():
    assert hc.classify_breadth("DETECTED IN ALL") == "broad_normal_expression"


# --- specific-intensity parsing (pure) ------------------------------------

def test_parse_multi_tissue_intensity():
    parsed = hc.parse_specific_tissues("intestine: 2.3e5;lymphoid tissue: 1.1e4")
    names = {p["tissue"] for p in parsed}
    assert names == {"intestine", "lymphoid tissue"}
    assert parsed[0]["intensity"] == 230000.0


def test_parse_empty_and_malformed():
    assert hc.parse_specific_tissues(None) == []
    assert hc.parse_specific_tissues("nan") == []
    # malformed part (no colon) is skipped, valid part kept
    parsed = hc.parse_specific_tissues("garbage;liver: 500")
    assert [p["tissue"] for p in parsed] == ["liver"]


# --- essential-tissue flagging (synthetic row) ----------------------------

def _row(dist, intensity, spec="Tissue enriched"):
    return {hc.HPA_DIST_COL: dist, hc.HPA_SPEC_COL: spec, hc.HPA_INTENSITY_COL: intensity}


def test_essential_tissue_flagged():
    s = hc.compute_summary("X", _row("Detected in single", "heart muscle: 5e5"))
    assert s["n_essential_tissues_with_expression"] == 1
    assert s["essential_tissues_flagged"] == ["heart muscle"]
    assert "essential_tissue" in s["safety_tissue_flags"]
    # scalar categorical the rule matches with `equals` (rules engine is categorical-only)
    assert s["essential_tissue_flag"] == "present"


def test_essential_tissue_flag_absent_when_no_essential():
    s = hc.compute_summary("X", _row("Detected in some", "skin: 3e5"))
    assert s["essential_tissue_flag"] == "absent"
    # broad gene with empty specific list is also absent (breadth carries liability)
    s2 = hc.compute_summary("X", _row("Detected in all", None))
    assert s2["essential_tissue_flag"] == "absent"


def test_gi_flag_separate_from_essential():
    s = hc.compute_summary("X", _row("Detected in some", "intestine: 5e5;stomach: 2e5"))
    assert "gi_tract" in s["safety_tissue_flags"]
    assert s["n_essential_tissues_with_expression"] == 0   # GI not in essential set


def test_broad_gene_empty_specific_list_still_broad():
    """The documented gotcha: a 'Detected in all' gene may have an EMPTY specific-
    tissue list (nothing is tissue-specific). essential=0 is NOT reassurance — the
    breadth class carries the liability, and the 'broad' flag fires."""
    s = hc.compute_summary("X", _row("Detected in all", None))
    assert s["normal_tissue_breadth_class"] == "broad_normal_expression"
    assert s["n_essential_tissues_with_expression"] == 0
    assert "broad" in s["safety_tissue_flags"]


def test_non_essential_named_tissue_no_essential_flag():
    s = hc.compute_summary("X", _row("Detected in single", "skin: 3e5"))
    assert s["n_essential_tissues_with_expression"] == 0
    assert s["n_specific_tissues"] == 1


# --- data_unavailable + lookup --------------------------------------------

def _write_hpa_tsv(tmp_path):
    p = tmp_path / "hpa_mini.tsv"
    cols = [hc.HPA_GENE_COL, hc.HPA_DIST_COL, hc.HPA_SPEC_COL, hc.HPA_INTENSITY_COL]
    rows = [
        ["EGFR", "Detected in all", "Low tissue specificity", ""],
        ["TACSTD2", "Detected in many", "Tissue enhanced", "lung: 2.2e7;salivary gland: 2.4e6"],
        ["MLANA", "Not detected", "Not detected", ""],
    ]
    with open(p, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in rows:
            fh.write("\t".join(r) + "\n")
    return str(p)


def test_lookup_broad_gene(tmp_path):
    s = hc.load_and_classify("EGFR", hpa_path=_write_hpa_tsv(tmp_path))
    assert s["normal_tissue_breadth_class"] == "broad_normal_expression"


def test_lookup_essential_tissue_gene(tmp_path):
    s = hc.load_and_classify("TACSTD2", hpa_path=_write_hpa_tsv(tmp_path))
    assert "lung" in s["essential_tissues_flagged"]     # TROP2 essential-tissue liability
    assert s["normal_tissue_breadth_class"] == "broad_normal_expression"


def test_gene_absent_is_data_unavailable(tmp_path):
    s = hc.load_and_classify("NOPE", hpa_path=_write_hpa_tsv(tmp_path))
    assert s["normal_tissue_breadth_class"] == "data_unavailable"


def test_card_contract_fields_present(tmp_path):
    s = hc.load_and_classify("MLANA", hpa_path=_write_hpa_tsv(tmp_path))
    for f in ("normal_tissue_breadth_class", "hpa_tissue_distribution",
              "hpa_tissue_specificity", "n_essential_tissues_with_expression",
              "essential_tissues_flagged", "n_specific_tissues", "specific_tissues",
              "safety_tissue_flags", "method_version"):
        assert f in s, f"missing card-contract field: {f}"


# --- graceful degradation --------------------------------------------------

def test_read_target_summary_graceful_on_failure(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("s3 down")
    monkeypatch.setattr(hc, "load_and_classify", _boom)
    out = hc_read.read_target_summary(target="EGFR")
    assert out["normal_tissue_breadth_class"] == "data_unavailable"
    assert out["_live_read_error"] == "hpa_normal_tissue_read_failed"
