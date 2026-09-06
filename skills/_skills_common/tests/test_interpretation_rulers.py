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


# ── tumor-presence distance_to_cut (pilot #3; first distance_to_cut consumer) ────────────────────────
def _tumor_vs_adjacent_summary():
    # real MET-COADREAD values (tumor-presence run 2026-09-03)
    return {"log2_fc": 1.7318034419423631, "q_value": 2.555898149424007e-72,
            "expression_call_class": "strong_upregulation"}


def test_tumor_vs_adjacent_distance_to_cut_ruler():
    from _skills_common import display_gloss as dg
    from _skills_common.evidence_salience import contract_threshold

    interp = build_interpretation({}, _tumor_vs_adjacent_summary(),
                                  SALIENCE_SPECS["tumor_vs_adjacent_expression"],
                                  card_id="tumor-rna-vs-adjacent")
    assert len(interp) == 1
    gv = interp[0]
    assert gv["metric"] == "log2_fc" and gv["value"] == 1.732 and gv["scale"] == "log2FC"
    assert gv["direction"] == "higher_is_stronger"
    assert gv["position"] == "strong_upregulation"                    # band READ VERBATIM
    assert gv["position_source"] == "expression_call_class"
    assert gv["frame"]["kind"] == "distance_to_cut"
    words = dg.gauge_string(gv)
    assert words.startswith("strong upregulation — ")                 # leads with the banded call
    # the cut single-sources from the card thresholds:; assert it only when the (contracts-first) key
    # resolves, so this stays green through the cross-repo lockstep window.
    cut = contract_threshold("tumor-rna-vs-adjacent", "modest_upregulation_log2fc")
    if cut is not None:
        assert cut == 0.5
        roles = {a["role"]: a["value"] for a in gv["frame"]["anchors"]}
        assert roles.get("cut") == 0.5
        assert "past the 0.5 cut" in words                            # 1.732 >= 0.5 → past (higher_is_stronger)


# ── safety gnomad LOEUF distance_to_cut (first SAFETY-axis reference_frame; LOWER = more constrained) ──
def _gnomad_summary():
    # constrained-gene shape: LOEUF below the 0.45 cut, highly_constrained band
    return {"loeuf_score": 0.32, "pli_score": 0.99, "constraint_class": "highly_constrained",
            "mis_z_score": 3.1}


def test_gnomad_loeuf_distance_to_cut_ruler():
    from _skills_common import display_gloss as dg
    from _skills_common.evidence_salience import contract_threshold

    interp = build_interpretation({}, _gnomad_summary(), SALIENCE_SPECS["gnomad_lof_constraint"],
                                  card_id="gnomad-lof-constraint")
    assert len(interp) == 1
    gv = interp[0]
    assert gv["metric"] == "loeuf_score" and gv["value"] == 0.32 and gv["scale"] == "loeuf"
    assert gv["direction"] == "lower_is_stronger"
    assert gv["position"] == "highly_constrained"                     # constraint_class READ VERBATIM
    assert gv["position_source"] == "constraint_class"
    assert gv["frame"]["kind"] == "distance_to_cut"
    # cut single-sources from the card's high_loeuf threshold (already a NAMED threshold — no lockstep)
    cut = contract_threshold("gnomad-lof-constraint", "high_loeuf")
    if cut is not None:
        assert cut == 0.45
        roles = {a["role"]: a["value"] for a in gv["frame"]["anchors"]}
        assert roles.get("cut") == 0.45
    words = dg.gauge_string(gv)
    assert words and "0.45" in words                                  # the constraint cut is surfaced


def test_build_key_evidence_promotes_gnomad_loeuf_interpretation():
    ke = _build_key_evidence({"measurement_type": "gnomad_lof_constraint",
                              "card_id": "gnomad-lof-constraint"}, _gnomad_summary())
    assert ke and ke.get("interpretation")
    assert ke["interpretation"][0]["metric"] == "loeuf_score"


# ── invariants ───────────────────────────────────────────────────────────────────────────────────────
def test_no_bare_number_scale_present_whenever_value_is():
    summaries = {"crispr_lof_dependency": _crispr_summary(),
                 "mutation_stratified_dependency": _genomic_summary(),
                 "tumor_vs_adjacent_expression": _tumor_vs_adjacent_summary()}
    for mt, summ in summaries.items():
        for gv in build_interpretation({}, summ, SALIENCE_SPECS[mt], card_id="tumor-rna-vs-adjacent"):
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
