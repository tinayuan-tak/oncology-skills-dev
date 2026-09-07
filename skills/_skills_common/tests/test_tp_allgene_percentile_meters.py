"""Tumor-presence pan-cancer allgene-percentile rulers (tranche #1).

The three tumor-presence DISTRIBUTION measurement_types (cell-line RNA, tumor RNA, cell-line protein)
previously carried no salience spec — their decisive pan-cancer rank (allgene_percentile) was emitted
BARE. Each now carries a distance_to_cut reference_frame gauging that rank against the card's
allgene_top_decile cut, with the resolver band (allgene_percentile_class) read verbatim as the position.
Verdict-INERT / display-only.
"""

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.evidence_salience import (  # noqa: E402
    SALIENCE_SPECS,
    build_interpretation,
    contract_threshold,
)

# measurement_type -> (card_id, a representative summary carrying the rank + its band)
_TP_PERCENTILE_METERS = {
    "cell_line_rna_expression": (
        "cellline-rna-distribution",
        {"allgene_percentile": 96.4, "allgene_percentile_class": "top_decile"},
    ),
    "tumor_expression_distribution": (
        "tumor-rna-distribution",
        {"allgene_percentile": 88.1, "allgene_percentile_class": "upper_range"},
    ),
    "cell_line_protein_abundance": (
        "cellline-protein-abundance",
        {"allgene_percentile": 45.0, "allgene_percentile_class": "mid_range"},
    ),
}


def _frames(mt):
    """The spec's reference_frame normalized to a list (it may be a dict or a list of frames)."""
    rf = SALIENCE_SPECS[mt].get("reference_frame")
    return rf if isinstance(rf, list) else ([rf] if isinstance(rf, dict) else [])


def _percentile_frame(mt):
    return next((f for f in _frames(mt) if f.get("value_field") == "allgene_percentile"), None)


def test_each_distribution_axis_has_a_wellformed_percentile_ruler():
    for mt, (card_id, _summary) in _TP_PERCENTILE_METERS.items():
        spec = SALIENCE_SPECS.get(mt)
        assert spec, f"{mt}: no salience spec (the ruler needs one)"
        rf = _percentile_frame(mt)
        assert rf and rf["kind"] == "distance_to_cut", f"{mt}: missing pan-cancer percentile frame"
        assert rf["scale"], f"{mt}: percentile frame needs a scale"
        assert rf["position_field"] == "allgene_percentile_class", f"{mt}: position must be the resolver band"
        assert rf["cut"]["card_id"] == card_id and rf["cut"]["threshold"] == "allgene_top_decile"
        assert spec.get("direction") == "higher_is_stronger", f"{mt}: gauge needs an orienting direction"


def test_ruler_gauges_the_rank_reads_position_verbatim_and_resolves_the_cut():
    for mt, (card_id, summary) in _TP_PERCENTILE_METERS.items():
        spec = SALIENCE_SPECS[mt]
        gvs = build_interpretation({}, summary, spec, card_id)
        # the pan-cancer rank ruler is one of the frames (a secondary within-distribution frame may also be
        # present, but its value is absent from this rank-only summary so it drops out → the rank stands)
        g = next((x for x in gvs if x["metric"] == "allgene_percentile"), None)
        assert g is not None, f"{mt}: pan-cancer rank ruler not emitted from {summary}"
        assert g["value"] == summary["allgene_percentile"] and g["scale"], f"{mt}: no bare number"
        assert g["position"] == summary["allgene_percentile_class"]  # READ VERBATIM
        if contract_threshold(card_id, "allgene_top_decile") is not None:  # only with contracts checked out
            cut = {a["role"]: a["value"] for a in g["frame"]["anchors"]}.get("cut")
            assert cut == 90.0, f"{mt}: allgene_top_decile should single-source to 90 (got {cut})"


def test_absent_rank_yields_no_bare_frame():
    for mt in _TP_PERCENTILE_METERS:
        # a distribution card with no allgene_percentile (e.g. the by-subtype sibling) emits no ruler
        assert build_interpretation({}, {"allgene_percentile_class": "top_decile"}, SALIENCE_SPECS[mt]) == [], (
            f"{mt}: emitted a frame with a position but no value"
        )
