"""Synthetic-data tests for hpa_normal_tissue_liability (no S3).

Validates: (1) breadth classifier (Protein tissue distribution → class); (2)
specific-intensity parsing incl. multi-tissue + malformed; (3) essential-tissue
flagging over HPA's closed vocabulary; (4) the "broad gene, empty specific list"
case (essential flag absent is NOT reassurance — breadth carries liability);
(5) data_unavailable (gene absent / no call) vs graceful read failure; (6) card
contract fields. Classifier + parser are pure; the lookup uses a tiny synthetic TSV.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Portable repo root: was hardcoded to the author's /home/sagemaker-user checkout, so every
# path guard below read as "data missing" on a CI runner or in a worktree.
METHODS_REPO = Path(__file__).resolve().parents[3]
# Portable sibling root: `_load_takeda_style()` does `sys.path.insert(<root>/plot_styles)` and then an
# UNGUARDED `import takeda_palette`, so a root that does not exist raises ModuleNotFoundError. The figure
# test below passed on runners only because ~20 other modules resolve this root from the env var the
# workflow exports, and one of them imports takeda_palette earlier in the session -- leaving it in
# sys.modules for this test to hit. That is an ordering accident: run this file alone and it fails.
TARGET_CONTRACTS = os.environ.get("TARGET_CONTRACTS_ROOT") or str(
    METHODS_REPO.parent / "rnd-computational-biology-oncology-target-contracts"
)
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


# --- the missing-cell contract (polars pilot, 2026-09-16) ------------------
# A missing HPA cell arrives as `None` from polars but arrived as float `nan` from pandas, whose
# str() is "nan". BOTH must read as absent, because compute_summary is public: the live reader now
# hands it None, while fixtures and any pandas-built frame still hand it nan. These tests exist so
# neither half can be deleted as "dead code" without a RED — under the live polars path alone the
# nan half is unreachable, which is exactly what makes it look deletable.


def test_missing_cell_absent_for_both_null_shapes():
    for blank in (None, float("nan"), "nan"):
        assert hc._is_absent(blank) is True, f"{blank!r} must read as absent"
        assert hc.classify_breadth(blank) == "data_unavailable", f"{blank!r}"
        assert hc.parse_specific_tissues(blank) == [], f"{blank!r}"
    # a PRESENT value must not be swallowed by the absence guard
    assert hc._is_absent("Detected in all") is False
    assert hc._is_absent("liver: 500") is False


def test_summary_identical_across_null_shapes():
    """polars-None and pandas-nan rows must produce byte-identical card summaries — this is the
    property that lets the reader swap libraries without moving a single card field."""
    from_polars = hc.compute_summary("X", _row(None, None, spec=None))
    from_pandas = hc.compute_summary("X", _row(float("nan"), float("nan"), spec=float("nan")))
    assert from_polars == from_pandas
    # and the absent row must degrade to the coverage-gap answer, never a reassuring one
    assert from_polars["normal_tissue_breadth_class"] == "data_unavailable"
    assert from_polars["essential_tissue_flag"] == "unknown"
    assert from_polars["hpa_tissue_distribution"] is None
    assert from_polars["hpa_tissue_specificity"] is None


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


def test_essential_tissue_flag_trichotomy_2026_08_24():
    # MEASURED narrow distribution, no essential enrichment → genuine measured-negative `absent`.
    s = hc.compute_summary("X", _row("Detected in some", "skin: 3e5"))
    assert s["essential_tissue_flag"] == "absent"
    # `Detected in all` guarantees every essential organ is expressed even with an EMPTY enrichment
    # list → `present` (fix: previously read `absent` and the essential-bite killer under-fired).
    s2 = hc.compute_summary("X", _row("Detected in all", None))
    assert s2["essential_tissue_flag"] == "present"
    assert "essential_from_broad_detection" in s2["safety_tissue_flags"]
    # `Detected in many` with no essential enrichment → we can't assert the essentials are spared →
    # `unknown` (a data gap, NOT reassurance).
    s3 = hc.compute_summary("X", _row("Detected in many", None))
    assert s3["essential_tissue_flag"] == "unknown"
    # gene absent from HPA → `unknown`, distinct from a measured `absent`.
    s4 = hc.compute_summary("X", None)
    assert s4["essential_tissue_flag"] == "unknown"


def test_gi_flag_separate_from_essential():
    """`gi_tract` is a NARRATIVE LABEL over GI_TISSUES = {intestine, stomach}; the essential set is the
    canonical vital-organ crosswalk. They are DIFFERENT CONCEPTS that now OVERLAP — before 2026-09-18
    this test asserted the essential count was 0 "GI not in essential set", which the `gut` promotion
    made false: `intestine` is the HPA anchor for the canonical `gut` organ, so it is in BOTH.

    The overlap is deliberate, so the separation claim is re-stated on the member that shows it
    WITHOUT depending on the overlap: `stomach` is in GI_TISSUES and is NOT an essential organ (the
    SCALAR ANCHOR for `gut` is the intestinal part; stomach/esophagus/appendix are documented
    non-anchors). A stomach-only gene therefore gets the label and a ZERO essential count — which is
    the thing the original test meant to prove, now provable rather than incidental."""
    both = hc.compute_summary("X", _row("Detected in some", "intestine: 5e5;stomach: 2e5"))
    assert "gi_tract" in both["safety_tissue_flags"]
    # OVERLAP, pinned: intestine IS essential since the gut promotion. Not 0 any more, and not a bug.
    assert both["n_essential_tissues_with_expression"] == 1

    # SEPARATION, on a GI tissue that is deliberately NOT an anchor: label fires, essential does not.
    stomach_only = hc.compute_summary("X", _row("Detected in some", "stomach: 2e5"))
    assert "gi_tract" in stomach_only["safety_tissue_flags"]
    assert stomach_only["n_essential_tissues_with_expression"] == 0
    # Anti-vacuity: the two arms must actually DIFFER, or this proves nothing about separation.
    assert both["n_essential_tissues_with_expression"] != stomach_only["n_essential_tissues_with_expression"]


def test_broad_gene_empty_specific_list_still_broad():
    """The documented gotcha: a 'Detected in all' gene may have an EMPTY specific-tissue
    ENRICHMENT list. The enrichment count stays 0, but (2026-08-24 fix) the essential_tissue_flag
    now reads `present` from the broad distribution — the breadth carries the liability into the
    verdict, not just into a narrative flag."""
    s = hc.compute_summary("X", _row("Detected in all", None))
    assert s["normal_tissue_breadth_class"] == "broad_normal_expression"
    assert s["n_essential_tissues_with_expression"] == 0  # enrichment count (unchanged)
    assert s["essential_tissue_flag"] == "present"  # but the flag now fires (fix)
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
    assert "lung" in s["essential_tissues_flagged"]  # TROP2 essential-tissue liability
    assert s["normal_tissue_breadth_class"] == "broad_normal_expression"


def test_gene_absent_is_data_unavailable(tmp_path):
    s = hc.load_and_classify("NOPE", hpa_path=_write_hpa_tsv(tmp_path))
    assert s["normal_tissue_breadth_class"] == "data_unavailable"


def test_card_contract_fields_present(tmp_path):
    s = hc.load_and_classify("MLANA", hpa_path=_write_hpa_tsv(tmp_path))
    for f in (
        "normal_tissue_breadth_class",
        "hpa_tissue_distribution",
        "hpa_tissue_specificity",
        "n_essential_tissues_with_expression",
        "essential_tissues_flagged",
        "n_specific_tissues",
        "specific_tissues",
        "safety_tissue_flags",
        "method_version",
    ):
        assert f in s, f"missing card-contract field: {f}"


# --- graceful degradation --------------------------------------------------


def test_read_target_summary_graceful_on_failure(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("s3 down")

    monkeypatch.setattr(hc, "load_and_classify", _boom)
    out = hc_read.read_target_summary(target="EGFR")
    assert out["normal_tissue_breadth_class"] == "data_unavailable"
    assert out["_live_read_error"] == "hpa_normal_tissue_read_failed"
    # SOURCE-unread fallback must NOT emit a MEASURED-negative `absent` (false reassurance);
    # it is `unknown`, matching cli.compute_summary(row=None). (B4-2/SA-2 fix)
    assert out["essential_tissue_flag"] == "unknown"


# --- figure emission (viz-coverage backfill 2026-07-20) ------------------


def test_emit_normal_tissue_bar_writes_svg(tmp_path):
    """The bar emitter writes an SVG from a summary dict. Covers the with-tissues
    path + the empty-specific-list (broad / not-detected) placeholder path."""
    import pytest

    pytest.importorskip("matplotlib")
    TC = TARGET_CONTRACTS
    summ = {
        "normal_tissue_breadth_class": "broad_normal_expression",
        "specific_tissues": [{"tissue": "lung", "intensity": 2.2e7}, {"tissue": "salivary gland", "intensity": 2.4e6}],
        "essential_tissues_flagged": ["lung"],
    }
    p = hc.emit_normal_tissue_bar(summ, "TACSTD2", tmp_path / "trop2", TC)
    assert p.exists() and p.stat().st_size > 0
    # empty specific list → informative breadth panel, still an SVG
    p2 = hc.emit_normal_tissue_bar(
        {
            "normal_tissue_breadth_class": "not_detected_in_normal",
            "specific_tissues": [],
            "essential_tissues_flagged": [],
        },
        "MLANA",
        tmp_path / "mlana",
        TC,
    )
    assert p2.exists()
