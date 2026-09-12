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

from _skills_common.evidence_graph import _build_key_evidence
from _skills_common.evidence_salience import SALIENCE_SPECS, build_interpretation


# ── crispr floor_cut_ceiling (fields live in summary AND capsule n_basis/numeric_anchors) ────────────
def _crispr_summary():
    return {
        "median_chronos_panel": -0.45738519728183746,
        "dep_control_non_essential_floor": -0.038,
        "dep_control_pan_essential_ceiling": -1.499,
        "dep_control_position_class": "between_controls",
    }


def test_crispr_floor_cut_ceiling_ruler_from_summary():
    interp = build_interpretation({}, _crispr_summary(), SALIENCE_SPECS["crispr_lof_dependency"])
    frames = {g["frame"]["kind"]: g for g in interp}
    gv = frames["floor_cut_ceiling"]
    assert gv["metric"] == "median_chronos_panel" and gv["value"] == -0.4574 and gv["scale"] == "chronos"
    assert gv["direction"] == "lower_is_stronger"
    assert gv["position"] == "between_controls"  # READ VERBATIM
    assert gv["position_source"] == "dep_control_position_class"
    roles = {a["role"]: a["value"] for a in gv["frame"]["anchors"]}
    assert roles["floor"] == -0.038 and roles["ceiling"] == -1.499
    assert roles.get("cut") == -0.5  # single-sourced from card thresholds:
    assert gv["frame"]["kind"] == "floor_cut_ceiling"
    # + cohort ruler: the same panel-median gauged against the known-target cohort (Phase 2)
    coh = frames["cohort_percentile"]
    assert coh["metric"] == "median_chronos_panel" and coh["cohort_n"] >= 20
    assert 0.0 <= coh["cohort_percentile"] <= 100.0 and "known targets" in coh["position"]


def test_crispr_ruler_reads_floor_ceiling_from_capsule_when_summary_stripped():
    # the frozen-fixture shape: summary empty, floor/ceiling in n_basis, panel in numeric_anchors
    cap = {
        "card_id": "pan-cancer-crispr-dependency-distribution",
        "numeric_anchors": [{"metric": "median_chronos_panel", "value": -0.4574}],
        "n_basis": {"dep_control_non_essential_floor": -0.038, "dep_control_pan_essential_ceiling": -1.499},
        "categorical_anchors": [{"field": "dep_control_position_class", "value": "between_controls"}],
    }
    interp = build_interpretation(cap, {}, SALIENCE_SPECS["crispr_lof_dependency"])
    assert interp and interp[0]["value"] == -0.4574
    assert interp[0]["position"] == "between_controls"
    roles = {a["role"]: a["value"] for a in interp[0]["frame"]["anchors"]}
    assert roles["floor"] == -0.038 and roles["ceiling"] == -1.499


# ── genomic comparator_delta ─────────────────────────────────────────────────────────────────────────
def _genomic_summary():
    return {
        "median_chronos_hotspot_mutant": -1.7287354469299316,
        "median_chronos_hotspot_wildtype": -0.5864385962486267,
        "delta_chronos_hotspot_mut_vs_wt": -1.142296850681305,
        "hotspot_mannwhitney_q": 1.2467439493977978e-10,
    }


def test_genomic_comparator_delta_ruler():
    interp = build_interpretation({}, _genomic_summary(), SALIENCE_SPECS["mutation_stratified_dependency"])
    gv = next(g for g in interp if g["frame"]["kind"] == "comparator_delta")  # + a fleet cohort ruler
    assert gv["metric"] == "median_chronos_hotspot_mutant" and gv["value"] == -1.729
    assert gv["distance_to_cut"] == -1.142  # SURFACED, not recomputed
    roles = {a["role"]: a["value"] for a in gv["frame"]["anchors"]}
    assert roles["comparator"] == -0.5864
    assert roles.get("cut") == -0.5  # strong_effect_delta from thresholds:
    assert gv["frame"]["kind"] == "comparator_delta"


# ── tumor-presence distance_to_cut (pilot #3; first distance_to_cut consumer) ────────────────────────
def _tumor_vs_adjacent_summary():
    # real MET-COADREAD values (tumor-presence run 2026-09-03)
    return {
        "log2_fc": 1.7318034419423631,
        "q_value": 2.555898149424007e-72,
        "expression_call_class": "strong_upregulation",
    }


def test_tumor_vs_adjacent_distance_to_cut_ruler():
    from _skills_common import display_gloss as dg
    from _skills_common.evidence_salience import contract_threshold

    interp = build_interpretation(
        {},
        _tumor_vs_adjacent_summary(),
        SALIENCE_SPECS["tumor_vs_adjacent_expression"],
        card_id="tumor-rna-vs-adjacent",
    )
    # tumor-vs-adjacent now gauges log2FC on a GRADED BAND (modest 0.5 / strong 1.5); no allgene_percentile
    # in this summary → the appended percentile companion drops out, leaving the one graded_band ruler.
    gv = next(g for g in interp if g["frame"]["kind"] == "graded_band")
    assert gv["metric"] == "log2_fc" and gv["value"] == 1.732 and gv["scale"] == "log2FC"
    assert gv["direction"] == "higher_is_stronger"
    assert gv["position"] == "strong_upregulation"  # band READ VERBATIM
    assert gv["position_source"] == "expression_call_class"
    words = dg.gauge_string(gv)
    assert words.startswith("strong upregulation — ")  # leads with the banded call
    # both cuts single-source from the card thresholds:; assert only when the keys resolve (lockstep window).
    modest = contract_threshold("tumor-rna-vs-adjacent", "modest_upregulation_log2fc")
    strong = contract_threshold("tumor-rna-vs-adjacent", "strong_upregulation_log2fc")
    if modest is not None and strong is not None:
        assert (modest, strong) == (0.5, 1.5)
        cut_vals = sorted(a["value"] for a in gv["frame"]["anchors"] if a["role"] == "cut")
        assert cut_vals == [0.5, 1.5]  # the modest+strong ladder
        assert "past the 1.5 strong cut" in words  # 1.732 clears the strong cut


# ── safety gnomad LOEUF distance_to_cut (first SAFETY-axis reference_frame; LOWER = more constrained) ──
def _gnomad_summary():
    # constrained-gene shape: LOEUF below the 0.45 cut, highly_constrained band
    return {"loeuf_score": 0.32, "pli_score": 0.99, "constraint_class": "highly_constrained", "mis_z_score": 3.1}


def test_gnomad_loeuf_distance_to_cut_ruler():
    from _skills_common import display_gloss as dg
    from _skills_common.evidence_salience import contract_threshold

    interp = build_interpretation(
        {}, _gnomad_summary(), SALIENCE_SPECS["gnomad_lof_constraint"], card_id="gnomad-lof-constraint"
    )
    frames = {g["frame"]["kind"]: g for g in interp}
    gv = frames["distance_to_cut"]
    assert gv["metric"] == "loeuf_score" and gv["value"] == 0.32 and gv["scale"] == "loeuf"
    assert gv["direction"] == "lower_is_stronger"
    assert gv["position"] == "highly_constrained"  # constraint_class READ VERBATIM
    # + cohort ruler: a low LOEUF (0.32, strong LoF) is polarity-signed so it reads HIGH on the cohort
    coh = frames["cohort_percentile"]
    assert coh["metric"] == "loeuf_score" and coh["cohort_n"] >= 20 and coh["cohort_percentile"] >= 50.0
    assert gv["position_source"] == "constraint_class"
    assert gv["frame"]["kind"] == "distance_to_cut"
    # cut single-sources from the card's high_loeuf threshold (already a NAMED threshold — no lockstep)
    cut = contract_threshold("gnomad-lof-constraint", "high_loeuf")
    if cut is not None:
        assert cut == 0.45
        roles = {a["role"]: a["value"] for a in gv["frame"]["anchors"]}
        assert roles.get("cut") == 0.45
    words = dg.gauge_string(gv)
    assert words and "0.45" in words  # the constraint cut is surfaced


def test_build_key_evidence_promotes_gnomad_loeuf_interpretation():
    ke = _build_key_evidence(
        {"measurement_type": "gnomad_lof_constraint", "card_id": "gnomad-lof-constraint"}, _gnomad_summary()
    )
    assert ke and ke.get("interpretation")
    assert ke["interpretation"][0]["metric"] == "loeuf_score"


# ── invariants ───────────────────────────────────────────────────────────────────────────────────────
def test_no_bare_number_scale_present_whenever_value_is():
    summaries = {
        "crispr_lof_dependency": _crispr_summary(),
        "mutation_stratified_dependency": _genomic_summary(),
        "tumor_vs_adjacent_expression": _tumor_vs_adjacent_summary(),
    }
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
    ke = _build_key_evidence(
        {"measurement_type": "crispr_lof_dependency", "card_id": "pan-cancer-crispr-dependency-distribution"},
        _crispr_summary(),
    )
    assert ke and ke.get("interpretation") and ke["interpretation"][0]["metric"] == "median_chronos_panel"


def test_unspecced_type_emits_no_interpretation_byte_stable():
    # a measurement_type without a reference_frame carries no interpretation (goldens stay byte-identical).
    # Use a CATEGORICAL-ONLY spec (effect_field=None → never gaugeable as a numeric ruler): clinvar germline
    # pathogenicity. (rnai_lof_dependency was the old example but now carries a distance_to_cut ruler.)
    ke = _build_key_evidence(
        {"measurement_type": "clinvar_germline_pathogenicity_safety"}, {"n_pathogenic_germline": 3}
    )
    assert not (ke or {}).get("interpretation")


# ── selectivity + surface distance_to_cut rulers (meter rollout; existing named card thresholds) ──────
def test_selectivity_log2fc_distance_to_cut_ruler():
    from _skills_common.evidence_salience import contract_threshold

    interp = build_interpretation(
        {},
        {"log2fc_cell_a": 2.1, "q_value_cell_a": 1e-5, "selectivity_class": "strongly_selective"},
        SALIENCE_SPECS["tumor_vs_normal_selectivity"],
        card_id="tumor-vs-normal-selectivity",
    )
    gv = next(g for g in interp if g["frame"]["kind"] == "distance_to_cut")  # + a fleet cohort ruler
    assert gv["metric"] == "log2fc_cell_a" and gv["value"] == 2.1 and gv["scale"] == "log2FC"
    assert gv["direction"] == "higher_is_stronger"
    assert gv["position"] == "strongly_selective" and gv["position_source"] == "selectivity_class"
    assert gv["frame"]["kind"] == "distance_to_cut"
    if contract_threshold("tumor-vs-normal-selectivity", "modest_selectivity_log2fc") is not None:
        assert {a["role"]: a["value"] for a in gv["frame"]["anchors"]}.get("cut") == 0.5


def test_surface_density_copies_per_cell_distance_to_cut_ruler():
    from _skills_common.evidence_salience import contract_threshold

    interp = build_interpretation(
        {},
        {"absolute_copies_per_cell": 5000, "surface_density_class": "tce_viable"},
        SALIENCE_SPECS["surface_density"],
        card_id="surface-abundance-density",
    )
    # + a fleet cohort ruler once surface_density's atlas column crosses n>=20 (it did at the 297-target
    # re-freeze; it was sparse before). Locate the cut ruler by kind rather than pinning the count.
    gv = next(g for g in interp if g["frame"]["kind"] == "distance_to_cut")
    assert gv["metric"] == "absolute_copies_per_cell" and gv["value"] == 5000 and gv["scale"] == "copies_per_cell"
    assert gv["position"] == "tce_viable" and gv["position_source"] == "surface_density_class"
    if contract_threshold("surface-abundance-density", "tce_viability_copies_per_cell") is not None:
        assert {a["role"]: a["value"] for a in gv["frame"]["anchors"]}.get("cut") == 1000
    # SPARSE field → absent value yields NO bare frame
    assert build_interpretation({}, {}, SALIENCE_SPECS["surface_density"]) == []


def test_percentile_crossing_fraction_distance_to_cut_ruler_no_position():
    from _skills_common.evidence_salience import contract_threshold

    interp = build_interpretation(
        {},
        {"fraction_tumor_above_normal_p95": 0.72},
        SALIENCE_SPECS["tumor_vs_normal_percentile_crossing"],
        card_id="tumor-vs-normal-percentile-crossing",
    )
    gv = next(g for g in interp if g["frame"]["kind"] == "distance_to_cut")  # + a fleet cohort ruler
    assert gv["metric"] == "fraction_tumor_above_normal_p95" and gv["value"] == 0.72 and gv["scale"] == "fraction"
    assert "position" not in gv  # this spec has no categorical
    if contract_threshold("tumor-vs-normal-percentile-crossing", "strong_frac_p95") is not None:
        assert {a["role"]: a["value"] for a in gv["frame"]["anchors"]}.get("cut") == 0.5


# ── sc-tumor malignant detection + measured-potency (cross-repo cut) distance_to_cut rulers ───────────
def test_sc_tumor_malignant_detection_distance_to_cut_ruler():
    from _skills_common.evidence_salience import contract_threshold

    interp = build_interpretation(
        {},
        {"malignant_detection_fraction": 0.68, "sc_expression_class": "malignant_expressed"},
        SALIENCE_SPECS["sc_tumor_celltype_expression"],
        card_id="tumor-scrna-celltype-expression",
    )
    # the card carries a second (comparator_delta) frame too; here we assert the PRIMARY distance_to_cut ruler
    gv = next(g for g in interp if g["frame"]["kind"] == "distance_to_cut")
    assert gv["metric"] == "malignant_detection_fraction" and gv["value"] == 0.68
    assert gv["scale"] == "detection_fraction" and gv["direction"] == "higher_is_stronger"
    assert gv["position"] == "malignant_expressed" and gv["position_source"] == "sc_expression_class"
    # cut already NAMED on main (malignant_broadly_detected_min=0.5) → resolves
    if contract_threshold("tumor-scrna-celltype-expression", "malignant_broadly_detected_min") is not None:
        assert {a["role"]: a["value"] for a in gv["frame"]["anchors"]}.get("cut") == 0.5


def test_measured_potency_distance_to_cut_ruler():
    from _skills_common.evidence_salience import contract_threshold

    interp = build_interpretation(
        {},
        {"best_measured_potency_neglog_m": 7.2, "measured_bioactivity_class": "potent_measured_ligand"},
        SALIENCE_SPECS["measured_potency_tractability"],
        card_id="measured-potency-tractability",
    )
    frames = {g["frame"]["kind"]: g for g in interp}
    gv = frames["distance_to_cut"]
    assert gv["metric"] == "best_measured_potency_neglog_m" and gv["value"] == 7.2 and gv["scale"] == "neglog_M"
    assert gv["position"] == "potent_measured_ligand" and gv["position_source"] == "measured_bioactivity_class"
    assert gv["frame"]["kind"] == "distance_to_cut"
    # + cohort ruler: potency vs the known targets that carry a measured potency
    coh = frames["cohort_percentile"]
    assert coh["metric"] == "best_measured_potency_neglog_m" and coh["cohort_n"] >= 20
    # cut single-sources from the card's potent_neglog_m (contracts #666); assert only once it resolves
    # (green through the cross-repo lockstep window until #666 lands to main)
    cut = contract_threshold("measured-potency-tractability", "potent_neglog_m")
    if cut is not None:
        assert cut == 6.0
        assert {a["role"]: a["value"] for a in gv["frame"]["anchors"]}.get("cut") == 6.0


# ── KNOWN-TARGET COHORT PERCENTILE meters (Phase 2; reads the re-frozen atlas, verdict-INERT) ─────────
def test_cohort_percentile_reader_polarity_and_gate():
    from _skills_common.archetype_core import cohort_percentile

    KEY = "gnomad_lof_constraint::num::loeuf_score"  # lower_is_stronger → atlas stores -loeuf
    # a strongly-constrained target (raw loeuf 0.12 → signed -0.12) sits ABOVE most of the cohort
    strong = cohort_percentile(KEY, -0.12)
    weak = cohort_percentile(KEY, -1.4)
    assert strong and weak and strong["percentile"] > weak["percentile"]
    assert strong["n"] >= 20 and 0.0 <= strong["percentile"] <= 100.0
    # unknown key and None value → no frame (never a bare/over-claimed number)
    assert cohort_percentile("not_a_measurement::num::nope", -0.12) is None
    assert cohort_percentile(KEY, None) is None
    # under-powered cohort is gated
    assert cohort_percentile(KEY, -0.12, min_n=10_000) is None


def test_cohort_percentile_gauge_string_renders():
    from _skills_common.display_gloss import gauge_string

    gv = {
        "frame": {"kind": "cohort_percentile"},
        "value": 0.12,
        "scale": "loeuf",
        "position": "stronger than 98% of 210 known targets",
    }
    s = gauge_string(gv)
    assert "0.12 loeuf" in s and "stronger than 98% of 210 known targets" in s


def test_cohort_meters_are_verdict_inert_display_only():
    # the cohort frame carries no signal/verdict keys — it is a display gauge, never a gate input
    interp = build_interpretation(
        {}, _gnomad_summary(), SALIENCE_SPECS["gnomad_lof_constraint"], card_id="gnomad-lof-constraint"
    )
    coh = {g["frame"]["kind"]: g for g in interp}["cohort_percentile"]
    assert not ({"signal", "verdict", "fired", "recommendation"} & set(coh))


def test_cohort_ruler_fleet_wide_and_liability_phrasing():
    # fleet roll: every metered axis with a populated atlas cohort column gets a cohort ruler.
    # a higher_is_worse axis (normal-tissue breadth) must NOT be mislabeled "stronger" — it's a liability.
    interp = build_interpretation({}, {"highest_tissue_median": 7.5}, SALIENCE_SPECS["normal_tissue_rna_breadth"], None)
    coh = {g["frame"]["kind"]: g for g in interp}.get("cohort_percentile")
    assert coh is not None, "normal_tissue_rna_breadth should carry a cohort ruler (fleet roll)"
    assert "higher-liability than" in coh["position"] and "stronger than" not in coh["position"]
    # a stronger-is-better axis keeps the 'stronger than' phrasing
    interp2 = build_interpretation({}, {"rnai_median_dep_score": -0.8}, SALIENCE_SPECS["rnai_lof_dependency"], None)
    coh2 = {g["frame"]["kind"]: g for g in interp2}.get("cohort_percentile")
    assert coh2 is not None and "stronger than" in coh2["position"]


# the card-data ruler kinds an axis can draw itself — everything the governance test admits EXCEPT
# cohort_percentile, which is the fleet-appended atlas ruler and never a card's own frame.
_DISPLAY_RULER_KINDS = frozenset(
    {"percentile", "floor_cut_ceiling", "comparator_delta", "distance_to_cut", "graded_band", "count_of_total"}
)


def test_atlas_numeric_optout_axes_get_no_cohort_ruler_but_keep_their_own():
    """The fleet roll appends a cohort_percentile to every metered axis, keyed off the PRIMARY frame's atlas
    numeric — so an axis that opts OUT of the atlas numeric (atlas_numeric: False) must not get one. Such a
    frame would be dead by construction (the atlas column it reads is never built, so cohort_percentile
    returns None and build_interpretation drops it), and pinning it keeps a vacuous frame out of the registry.
    The axis's OWN ruler must survive — that is the whole point of the opt-out.

    (2026-09-12) This test used to assert every opt-out frame was specifically `distance_to_cut`. That was
    an accident of the only two axes that had opted out, not the invariant: the opt-out governs whether an
    ATLAS NUMERIC is minted, which is orthogonal to which display ruler the axis draws. immune_context opts
    out with a `graded_band` (it bands median_cd8_fraction on the card's pan-cancer Q1/Q3 cuts, and its
    value is target-INDEPENDENT so it must not become an atlas coordinate). Pinning the kind would have
    forced a wrong frame kind to satisfy a test. What is asserted instead is the actual property — no cohort
    ruler, and the axis still draws at least one ruler of its own."""
    optouts = [
        (mt, s)
        for mt, s in SALIENCE_SPECS.items()
        if isinstance(s.get("reference_frame"), (dict, list))
        and (
            (s["reference_frame"][0] if isinstance(s["reference_frame"], list) else s["reference_frame"]).get(
                "atlas_numeric"
            )
            is False
        )
    ]
    assert optouts, "no atlas_numeric: False axis left — the opt-out went inert"
    for mt, spec in optouts:
        rf = spec["reference_frame"]
        frames = rf if isinstance(rf, list) else [rf]
        kinds = [f.get("kind") for f in frames]
        assert "cohort_percentile" not in kinds, f"{mt}: got a cohort ruler off an atlas column that is never built"
        assert kinds, f"{mt}: opt-out stripped the axis of every frame"
        # every surviving frame is a real DISPLAY ruler (not a null kind, not a cohort ruler by another name)
        assert all(k in _DISPLAY_RULER_KINDS for k in kinds), f"{mt}: unexpected frame kinds {kinds}"
