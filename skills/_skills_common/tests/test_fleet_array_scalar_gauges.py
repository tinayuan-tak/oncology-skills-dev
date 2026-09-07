"""Fleet array-scalar gauges — rulers on the array-magnitude cards that DO carry a top-level decisive
scalar (the per-row detail lives in an array, but a card-level best/strongest scalar summarises it):

  chemical_genetic_concordance : best_spearman_r_crispr        graded_band (weak 0.10 / strong 0.30)
  dependency_predictability    : pearson_r_squared_rf          distance_to_cut (high-conf 0.16)
  prism_compound_activity      : median_log2auc_across_compounds distance_to_cut (clinically-active -0.10)
  combinatorial_ko_dependency  : strongest_partner_mean_gi     distance_to_cut (constitutive -0.25)
  drug_anchored_combination    : strongest_co_target_shift      graded_band (supported -0.25 / strong -0.50)
  drug_anchored_resistance     : strongest_mediator_shift       graded_band (supported 0.25 / strong 0.50)

(mutation_cooccurrence + pathway_activity_context are intentionally NOT gauged — no top-level magnitude
scalar; the class band is their ruler.) Verdict-INERT / display-only.
"""

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.evidence_salience import SALIENCE_SPECS, build_interpretation, contract_threshold  # noqa: E402

# mt -> (value_field, kind, a summary exercising it, expected resolved cut anchor value(s))
_GAUGES = {
    "chemical_genetic_concordance": (
        "best_spearman_r_crispr",
        "graded_band",
        {"best_spearman_r_crispr": 0.42, "crispr_prism_concordance_class": "strongly_concordant"},
        [0.10, 0.30],
    ),
    "dependency_predictability": (
        "pearson_r_squared_rf",
        "distance_to_cut",
        {"pearson_r_squared_rf": 0.28, "predictability_class": "predictable"},
        [0.16],
    ),
    "prism_compound_activity": (
        "median_log2auc_across_compounds",
        "distance_to_cut",
        {"median_log2auc_across_compounds": -0.22, "prism_activity_class": "clinically_active"},
        [-0.10],
    ),
    "combinatorial_ko_dependency": (
        "strongest_partner_mean_gi",
        "distance_to_cut",
        {"strongest_partner_mean_gi": -0.4, "combinatorial_dependency_class": "conditional_dependency"},
        [-0.25],
    ),
    "drug_anchored_combination": (
        "strongest_co_target_shift",
        "graded_band",
        {"strongest_co_target_shift": -0.6, "combination_opportunity_class": "strong_combination"},
        [-0.25, -0.50],
    ),
    "drug_anchored_resistance": (
        "strongest_mediator_shift",
        "graded_band",
        {"strongest_mediator_shift": 0.35, "resistance_emergence_class": "supported_resistance"},
        [0.25, 0.50],
    ),
}


def _frame(mt):
    rf = SALIENCE_SPECS[mt].get("reference_frame")
    return rf[0] if isinstance(rf, list) and rf else rf


def test_each_array_scalar_axis_has_its_ruler():
    for mt, (vf, kind, _summary, _cuts) in _GAUGES.items():
        rf = _frame(mt)
        assert rf, f"{mt}: no reference_frame"
        assert rf["value_field"] == vf and rf["kind"] == kind, f"{mt}: wrong value_field/kind"
        assert SALIENCE_SPECS[mt].get("direction"), f"{mt}: gauge needs a direction"


def test_builder_gauges_the_scalar_and_reads_position():
    for mt, (vf, kind, summary, _cuts) in _GAUGES.items():
        gv = build_interpretation({}, summary, SALIENCE_SPECS[mt], None)
        g = next((x for x in gv if x["metric"] == vf), None)
        assert g is not None and g["scale"], f"{mt}: {vf} not gauged"
        assert g["frame"]["kind"] == kind
        # position is the resolver class READ VERBATIM
        assert g.get("position") == summary.get(_frame(mt)["position_field"])


def test_cuts_single_source_from_the_card_thresholds():
    for mt, (vf, kind, summary, expected_cuts) in _GAUGES.items():
        gv = build_interpretation({}, summary, SALIENCE_SPECS[mt], None)
        g = next(x for x in gv if x["metric"] == vf)
        cuts = sorted(a["value"] for a in g["frame"]["anchors"] if a["role"] == "cut")
        # only assert when the contracts checkout resolved them (skips cleanly in isolated CI)
        if cuts:
            assert cuts == sorted(expected_cuts), f"{mt}: cut anchors {cuts} != {sorted(expected_cuts)}"


def test_uncovered_array_axes_stay_class_only():
    # these have no top-level magnitude scalar → intentionally no reference_frame (class band is the ruler)
    for mt in ("mutation_cooccurrence", "pathway_activity_context"):
        assert not SALIENCE_SPECS[mt].get("reference_frame"), f"{mt}: should stay class-only"
        assert SALIENCE_SPECS[mt].get("categorical"), f"{mt}: needs a categorical band to be gaugeable"
