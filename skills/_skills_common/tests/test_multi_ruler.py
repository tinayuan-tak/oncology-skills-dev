"""Multi-ruler support: a card's reference_frame may be a LIST of frames (build_interpretation iterates).

One card often carries >1 orthogonal reading — e.g. a distribution card gauged BOTH on its pan-cancer rank
AND on its within-panel position. The schema already types key_evidence.interpretation as a LIST; this
verifies the builder projects every frame, drops frames whose value is absent, and stays back-compatible
with a single dict frame. Verdict-INERT / display-only.
"""
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.evidence_salience import build_interpretation  # noqa: E402

_PERCENTILE_FRAME = {"kind": "distance_to_cut", "value_field": "allgene_percentile", "scale": "percentile",
                     "position_field": "allgene_percentile_class"}
_PANEL_FRAME = {"kind": "floor_cut_ceiling", "value_field": "median_log2tpm_panel", "scale": "log2tpm",
                "position_field": "expression_class",
                "anchors": [{"role": "floor", "field": "p5_log2tpm_panel", "label": "p5"},
                            {"role": "ceiling", "field": "p95_log2tpm_panel", "label": "p95"}]}


def _spec(*frames):
    return {"direction": "higher_is_stronger", "reference_frame": list(frames)}


def test_list_frame_projects_every_measured_ruler():
    summary = {"allgene_percentile": 96.4, "allgene_percentile_class": "top_decile",
               "median_log2tpm_panel": 6.2, "expression_class": "broadly_expressed",
               "p5_log2tpm_panel": 0.1, "p95_log2tpm_panel": 8.0}
    gv = build_interpretation({}, summary, _spec(_PERCENTILE_FRAME, _PANEL_FRAME))
    assert len(gv) == 2, f"expected two rulers, got {[g['metric'] for g in gv]}"
    assert [g["metric"] for g in gv] == ["allgene_percentile", "median_log2tpm_panel"]  # order preserved
    assert gv[0]["position"] == "top_decile" and gv[1]["position"] == "broadly_expressed"
    # the floor/ceiling anchors resolved from the summary
    assert {a["role"]: a["value"] for a in gv[1]["frame"]["anchors"]} == {"floor": 0.1, "ceiling": 8.0}


def test_frame_with_absent_value_drops_out_but_others_survive():
    # only the pan-cancer rank is measured; the panel median is absent → one ruler, no null-fill
    summary = {"allgene_percentile": 88.1, "allgene_percentile_class": "upper_range"}
    gv = build_interpretation({}, summary, _spec(_PERCENTILE_FRAME, _PANEL_FRAME))
    assert len(gv) == 1 and gv[0]["metric"] == "allgene_percentile"


def test_single_dict_frame_is_backward_compatible():
    summary = {"allgene_percentile": 45.0, "allgene_percentile_class": "mid_range"}
    gv = build_interpretation({}, summary, {"direction": "higher_is_stronger", "reference_frame": _PERCENTILE_FRAME})
    assert len(gv) == 1 and gv[0]["metric"] == "allgene_percentile"


def test_no_frame_and_empty_list_both_yield_no_rulers():
    assert build_interpretation({}, {"allgene_percentile": 5.0}, {"direction": "higher_is_stronger"}) == []
    assert build_interpretation({}, {"allgene_percentile": 5.0}, _spec()) == []
