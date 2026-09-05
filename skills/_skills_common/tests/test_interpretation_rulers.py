"""evidence_graph key_evidence.interpretation[] — the Stage-2 typed reference-frame rulers.

Asserts build_interpretation projects the pilot SALIENCE_SPECS reference_frames from the summary/capsule
(NAMING fields, never recomputing), reads ordinal position VERBATIM, single-sources the cut from the card
thresholds:, and degrades gracefully (absent value -> [], no bare number). Also that _build_key_evidence
promotes it onto key_evidence and that an UN-spec'd type stays byte-stable (no interpretation).
"""
import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.evidence_salience import SALIENCE_SPECS, build_interpretation
from _skills_common.evidence_graph import _build_key_evidence


# ── crispr floor_cut_ceiling (fields live in summary AND capsule n_basis/numeric_anchors) ────────────
def _crispr_summary():
    return {"median_chronos_panel": -0.45738519728183746,
            "dep_control_non_essential_floor": -0.038, "dep_control_pan_essential_ceiling": -1.499,
            "dep_control_position_class": "between_controls"}


def test_crispr_floor_cut_ceiling_ruler_from_summary():
    interp = build_interpretation({}, _crispr_summary(), SALIENCE_SPECS["crispr_lof_dependency"])
    assert len(interp) == 1
    gv = interp[0]
    assert gv["metric"] == "median_chronos_panel" and gv["value"] == -0.4574 and gv["scale"] == "chronos"
    assert gv["direction"] == "lower_is_stronger"
    assert gv["position"] == "between_controls"                       # READ VERBATIM
    assert gv["position_source"] == "dep_control_position_class"
    roles = {a["role"]: a["value"] for a in gv["frame"]["anchors"]}
    assert roles["floor"] == -0.038 and roles["ceiling"] == -1.499
    assert roles.get("cut") == -0.5                                   # single-sourced from card thresholds:
    assert gv["frame"]["kind"] == "floor_cut_ceiling"


def test_crispr_ruler_reads_floor_ceiling_from_capsule_when_summary_stripped():
    # the frozen-fixture shape: summary empty, floor/ceiling in n_basis, panel in numeric_anchors
    cap = {"card_id": "pan-cancer-crispr-dependency-distribution",
           "numeric_anchors": [{"metric": "median_chronos_panel", "value": -0.4574}],
           "n_basis": {"dep_control_non_essential_floor": -0.038, "dep_control_pan_essential_ceiling": -1.499},
           "categorical_anchors": [{"field": "dep_control_position_class", "value": "between_controls"}]}
    interp = build_interpretation(cap, {}, SALIENCE_SPECS["crispr_lof_dependency"])
    assert interp and interp[0]["value"] == -0.4574
    assert interp[0]["position"] == "between_controls"
    roles = {a["role"]: a["value"] for a in interp[0]["frame"]["anchors"]}
    assert roles["floor"] == -0.038 and roles["ceiling"] == -1.499


# ── genomic comparator_delta ─────────────────────────────────────────────────────────────────────────
def _genomic_summary():
    return {"median_chronos_hotspot_mutant": -1.7287354469299316,
            "median_chronos_hotspot_wildtype": -0.5864385962486267,
            "delta_chronos_hotspot_mut_vs_wt": -1.142296850681305,
            "hotspot_mannwhitney_q": 1.2467439493977978e-10}


def test_genomic_comparator_delta_ruler():
    interp = build_interpretation({}, _genomic_summary(), SALIENCE_SPECS["mutation_stratified_dependency"])
    assert len(interp) == 1
    gv = interp[0]
    assert gv["metric"] == "median_chronos_hotspot_mutant" and gv["value"] == -1.729
    assert gv["distance_to_cut"] == -1.142                            # SURFACED, not recomputed
    roles = {a["role"]: a["value"] for a in gv["frame"]["anchors"]}
    assert roles["comparator"] == -0.5864
    assert roles.get("cut") == -0.5                                   # strong_effect_delta from thresholds:
    assert gv["frame"]["kind"] == "comparator_delta"


# ── invariants ───────────────────────────────────────────────────────────────────────────────────────
def test_no_bare_number_scale_present_whenever_value_is():
    for mt in ("crispr_lof_dependency", "mutation_stratified_dependency"):
        summ = _crispr_summary() if mt.startswith("crispr") else _genomic_summary()
        for gv in build_interpretation({}, summ, SALIENCE_SPECS[mt]):
            if gv.get("value") is not None:
                assert gv.get("scale"), f"{mt}: value emitted without a scale (bare number)"


def test_absent_value_yields_empty_no_null_fill():
    assert build_interpretation({}, {}, SALIENCE_SPECS["crispr_lof_dependency"]) == []
    assert build_interpretation({}, {}, SALIENCE_SPECS["mutation_stratified_dependency"]) == []


def test_deterministic_repeat_build_is_identical():
    a = build_interpretation({}, _crispr_summary(), SALIENCE_SPECS["crispr_lof_dependency"])
    b = build_interpretation({}, _crispr_summary(), SALIENCE_SPECS["crispr_lof_dependency"])
    assert a == b


def test_build_key_evidence_promotes_interpretation():
    ke = _build_key_evidence({"measurement_type": "crispr_lof_dependency",
                              "card_id": "pan-cancer-crispr-dependency-distribution"}, _crispr_summary())
    assert ke and ke.get("interpretation") and ke["interpretation"][0]["metric"] == "median_chronos_panel"


def test_unspecced_type_emits_no_interpretation_byte_stable():
    # a measurement_type without a reference_frame carries no interpretation (goldens stay byte-identical)
    ke = _build_key_evidence({"measurement_type": "rnai_lof_dependency"},
                             {"rnai_median_dep_score": -0.8})
    assert not (ke or {}).get("interpretation")
