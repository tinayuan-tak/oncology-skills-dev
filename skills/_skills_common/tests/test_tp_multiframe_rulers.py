"""Tranche #3 — tumor-presence cards carry a SECOND reference-frame ruler (multi-frame).

Each tumor-presence measurement_type now pairs its headline ruler with one orthogonal reading:
  - the 3 distribution cards: pan-cancer allgene-percentile rank  +  within-panel / within-tumor position
  - cptac + tumor-vs-adjacent: their call-cut ruler  +  the pan-cancer allgene-percentile companion
  - single-cell: malignant-detection cut  +  comparator_delta vs the microenvironment compartment
The builder projects every frame whose value is present; interp[0] stays the headline read.
Verdict-INERT / display-only.
"""
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.evidence_salience import SALIENCE_SPECS, build_interpretation  # noqa: E402


def _frames(mt):
    rf = SALIENCE_SPECS[mt].get("reference_frame")
    return rf if isinstance(rf, list) else ([rf] if isinstance(rf, dict) else [])


# measurement_type -> (expected [ (metric, kind), ... ] for the two frames, a summary exercising both)
_MULTIFRAME = {
    "cell_line_rna_expression": (
        [("allgene_percentile", "distance_to_cut"), ("median_log2tpm_panel", "floor_cut_ceiling")],
        {"allgene_percentile": 96.4, "allgene_percentile_class": "top_decile",
         "median_log2tpm_panel": 6.2, "expression_class": "broadly_expressed",
         "p5_log2tpm_panel": 0.1, "p95_log2tpm_panel": 8.0}),
    "tumor_expression_distribution": (
        # 3 frames: pan-cancer rank + within-tumor median (both fire on the main card) + subtype ε²
        # graded_band (fires only on the by-subtype card). This synthetic summary carries all three fields.
        [("allgene_percentile", "distance_to_cut"), ("median_log2tpm", "distance_to_cut"),
         ("subtype_variance_explained", "graded_band")],
        {"allgene_percentile": 99.9, "allgene_percentile_class": "top_1pct",
         "median_log2tpm": 6.1, "tumor_expression_class": "broadly_high",
         "subtype_variance_explained": 0.18, "subtype_effect_size_class": "large_subtype_effect"}),
    "cell_line_protein_abundance": (
        [("allgene_percentile", "distance_to_cut"), ("median_log2_abundance_panel", "floor_cut_ceiling")],
        {"allgene_percentile": 3.8, "allgene_percentile_class": "bottom_decile",
         "median_log2_abundance_panel": -1.2, "protein_expression_class": "low",
         "p5_log2_abundance_panel": -3.0, "p95_log2_abundance_panel": 2.0}),
    "tumor_protein_abundance": (
        [("protein_effect_size", "distance_to_cut"), ("allgene_percentile", "distance_to_cut")],
        {"protein_effect_size": 1.05, "protein_expression_class": "elevated",
         "allgene_percentile": 91.0, "allgene_percentile_class": "top_decile"}),
    "tumor_vs_adjacent_expression": (
        [("log2_fc", "graded_band"), ("allgene_percentile", "distance_to_cut")],
        {"log2_fc": 1.2, "expression_call_class": "elevated",
         "allgene_percentile": 88.0, "allgene_percentile_class": "upper_range"}),
    "sc_tumor_celltype_expression": (
        [("malignant_detection_fraction", "distance_to_cut"),
         ("malignant_detection_fraction", "comparator_delta")],
        {"malignant_detection_fraction": 0.76, "sc_expression_class": "malignant_broadly_detected",
         "top_microenvironment_detection_fraction": 0.30}),
}


def test_each_tp_card_has_two_frames_in_the_expected_order():
    for mt, (expected, _summary) in _MULTIFRAME.items():
        frames = _frames(mt)
        got = [(f.get("value_field"), f.get("kind")) for f in frames]
        assert got == expected, f"{mt}: frames {got} != expected {expected}"


def test_builder_emits_both_rulers_when_both_values_present():
    for mt, (expected, summary) in _MULTIFRAME.items():
        gvs = build_interpretation({}, summary, SALIENCE_SPECS[mt], None)
        got = [(g["metric"], g["frame"]["kind"]) for g in gvs]
        assert got == expected, f"{mt}: emitted {got} != expected {expected}"
        for g in gvs:                       # no bare numbers
            assert g["value"] is not None and g["scale"]


def test_comparator_delta_carries_the_microenvironment_baseline():
    _, summary = _MULTIFRAME["sc_tumor_celltype_expression"]
    gvs = build_interpretation({}, summary, SALIENCE_SPECS["sc_tumor_celltype_expression"], None)
    comp = next(g for g in gvs if g["frame"]["kind"] == "comparator_delta")
    anchors = {a["role"]: a["value"] for a in comp["frame"]["anchors"]}
    assert anchors.get("comparator") == 0.30, "malignant fraction must be gauged vs the microenvironment"
