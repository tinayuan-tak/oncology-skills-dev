"""feature_vectoriser — the richer atlas feature substrate (numeric + mask families + ordinal delegation).

Pins: numeric features derive from the SALIENCE_SPECS reference_frame value_fields (one registry for meters
AND atlas numerics); polarity-signing makes each numeric monotone-with-strength; and the explicit mask keeps
a measured-zero DISTINCT from an unmeasured axis (the EGFR failure mode). Verdict-INERT, pure, deterministic.
"""

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parents[2]
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.archetype_core import claim_features  # noqa: E402
from _skills_common.evidence_salience import SALIENCE_SPECS  # noqa: E402
from _skills_common.feature_vectoriser import (  # noqa: E402
    build_feature_vector,
    numeric_feature_specs,
    numeric_features,
)


def _primary_frame(mt):
    """The PRIMARY (first) reference_frame of a spec — the one the atlas numeric is keyed off."""
    rf = SALIENCE_SPECS[mt].get("reference_frame")
    return rf[0] if isinstance(rf, list) and rf else (rf if isinstance(rf, dict) else None)


def _optout_axes():
    """Axes whose primary frame declares `atlas_numeric: False` — display ruler, no atlas feature."""
    return {
        mt
        for mt, s in SALIENCE_SPECS.items()
        if s.get("reference_frame") and (_primary_frame(mt) or {}).get("atlas_numeric") is False
    }


def test_numeric_specs_track_reference_frame_value_fields():
    specs = numeric_feature_specs()
    # every reference_frame axis contributes exactly its value_field, MINUS the declared opt-outs
    rf_axes = {mt for mt, s in SALIENCE_SPECS.items() if s.get("reference_frame")}
    assert set(specs) == rf_axes - _optout_axes() and len(specs) >= 5
    # LOEUF is lower_is_stronger; selectivity log2fc is higher_is_stronger (sanity on the registry)
    assert specs.get("gnomad_lof_constraint") == ("loeuf_score", "lower_is_stronger")


def test_atlas_numeric_optout_is_excluded_from_the_atlas_but_keeps_its_ruler():
    """The ruler registry and the atlas-numeric registry were ONE registry with no opt-out, so a card could
    not get a display ruler without also minting an atlas feature that _DIR_SIGN would then sign wrongly.
    Both halves are pinned here, because dropping either makes the flag look inert:
      (a) the opted-out axis emits NO `::num::` feature and NO mask, and
      (b) it STILL carries a well-formed reference_frame (the ruler is displayed, not deleted).
    Measured cases: a mutation-SHAPE fraction (high missense = driver for an oncogene, passenger for a TSG,
    so no fixed polarity exists) and a driver q-value (≈0 for every gene that has one → degenerate column,
    the ::mask already carries all the information)."""
    optout = _optout_axes()
    assert optout, "no axis declares atlas_numeric: False — the flag went inert, or the specs regressed"
    specs = numeric_feature_specs()
    for mt in optout:
        assert mt not in specs, f"{mt}: atlas_numeric False but still minting an atlas numeric"
        frame = _primary_frame(mt)
        # (b) the ruler survives — value_field + scale + a cut to gauge against, and a direction to orient it
        assert frame.get("value_field") and frame.get("scale"), f"{mt}: opt-out lost its display ruler"
        assert isinstance(frame.get("cut"), dict) or frame.get("cuts"), f"{mt}: ruler has nothing to gauge against"
        assert SALIENCE_SPECS[mt].get("direction"), f"{mt}: ruler has no direction to orient the gauge"


def test_atlas_numeric_optout_emits_no_feature_even_when_the_value_is_harvested():
    """The opt-out must hold at PROJECTION time too, not only in the registry: handing numeric_features the
    opted-out axis's real value must add nothing to the vector (otherwise a harvester that finds the number
    would smuggle the wrongly-signed column back in)."""
    for mt in _optout_axes():
        field = _primary_frame(mt)["value_field"]
        feats = numeric_features({mt: {field: 0.5}})
        assert f"{mt}::num::{field}" not in feats
        assert f"{mt}::num::{field}::mask" not in feats
        assert not any(k.startswith(f"{mt}::num::") for k in feats), f"{mt}: leaked a numeric key"


def test_numeric_polarity_sign_and_mask():
    # lower_is_stronger (loeuf) → value is NEGATED so smaller LOEUF becomes a LARGER feature (more supportive)
    f = numeric_features({"gnomad_lof_constraint": {"loeuf_score": 0.3}})
    assert f["gnomad_lof_constraint::num::loeuf_score"] == -0.3
    assert f["gnomad_lof_constraint::num::loeuf_score::mask"] == 1.0
    # higher_is_stronger keeps sign
    g = numeric_features({"tumor_vs_normal_selectivity": {"log2fc_cell_a": 2.0}})
    assert g["tumor_vs_normal_selectivity::num::log2fc_cell_a"] == 2.0


def test_measured_zero_is_distinct_from_unmeasured():
    # measured 0.0 → present (mask=1, value 0.0 after sign); ABSENT → None + mask 0 (the EGFR fix)
    present = numeric_features({"tumor_vs_normal_selectivity": {"log2fc_cell_a": 0.0}})
    assert present["tumor_vs_normal_selectivity::num::log2fc_cell_a"] == 0.0
    assert present["tumor_vs_normal_selectivity::num::log2fc_cell_a::mask"] == 1.0
    absent = numeric_features({})  # axis not measured at all
    assert absent["tumor_vs_normal_selectivity::num::log2fc_cell_a"] is None
    assert absent["tumor_vs_normal_selectivity::num::log2fc_cell_a::mask"] == 0.0


def test_nan_and_nonnumeric_are_unmeasured():
    f = numeric_features({"gnomad_lof_constraint": {"loeuf_score": float("nan")}})
    assert f["gnomad_lof_constraint::num::loeuf_score"] is None
    assert f["gnomad_lof_constraint::num::loeuf_score::mask"] == 0.0
    b = numeric_features({"gnomad_lof_constraint": {"loeuf_score": "n/a"}})
    assert b["gnomad_lof_constraint::num::loeuf_score"] is None


def test_every_reference_frame_axis_emits_a_key_even_when_absent():
    # feature_order stability: a key per declared axis regardless of measurement (missingness explicit)
    f = numeric_features({})
    for mt, (field, _dir) in numeric_feature_specs().items():
        assert f"{mt}::num::{field}" in f and f"{mt}::num::{field}::mask" in f


def test_build_merges_ordinal_and_numeric_without_touching_ordinal_encoding():
    cvs = {"genomic_alteration": {"SNV": {"signal": "strong", "corroboration": "high"}}}
    nums = {"gnomad_lof_constraint": {"loeuf_score": 0.3}}
    fv = build_feature_vector(cvs, nums)
    # ordinal keys are byte-identical to the shared claim_features (delegation, not reimplementation)
    for k, v in claim_features(cvs).items():
        assert fv[k] == v
    # numeric family present alongside
    assert fv["gnomad_lof_constraint::num::loeuf_score"] == -0.3


def test_deterministic():
    cvs = {"selectivity": {"WIN": {"signal": "strong", "corroboration": "moderate"}}}
    nums = {"surface_density": {"absolute_copies_per_cell": 5000}}
    assert build_feature_vector(cvs, nums) == build_feature_vector(cvs, nums)


# ── numeric harvester over a composed evidence_package (build_atlas's per-run input) ──────────────────
from _skills_common.feature_vectoriser import numeric_values_from_package  # noqa: E402


def _spec_field(mt):
    # reference_frame may be a dict OR a list of frames (multi-ruler); the atlas numeric keys off the
    # PRIMARY (first) frame's value_field — mirror feature_vectoriser.numeric_feature_specs.
    rf = SALIENCE_SPECS[mt]["reference_frame"]
    primary = rf[0] if isinstance(rf, list) else rf
    return primary["value_field"]


def test_harvest_reads_all_three_numeric_locations():
    # gnomad_lof_constraint's value_field in a card SUMMARY; a dependency value_field in an atom.values;
    # another in a capsule n_basis — all three should be harvested (the reason the harvester is multi-source).
    lo = _spec_field("gnomad_lof_constraint")  # loeuf_score
    dep = _spec_field("crispr_lof_dependency")  # median_chronos_panel (lives in atom/n_basis, not summary)
    pkg = {
        "cards": [{"measurement_type": "gnomad_lof_constraint", "summary": {lo: 0.31}}],
        "synthesis": {
            "claim_vectors": {"dependency": {"claim_vector": {"DEP": {"evidence_atom": {"values": {dep: -0.46}}}}}},
            "evidence_capsules": {
                "safety": {"capsules": {"gene-burden-safety": {"n_basis": {"some_other_metric": 1.0}}}}
            },
        },
    }
    nv = numeric_values_from_package(pkg)
    assert nv.get("gnomad_lof_constraint", {}).get(lo) == 0.31  # from card summary
    assert nv.get("crispr_lof_dependency", {}).get(dep) == -0.46  # from atom.values (summary miss)


def test_harvest_absent_axis_is_omitted_then_masked():
    nv = numeric_values_from_package({"cards": [], "synthesis": {}})
    assert nv == {}  # nothing measured
    # build_feature_vector then emits every metered axis's key as None + mask 0 (missingness explicit)
    fv = build_feature_vector({}, nv)
    for mt, (vf, _d) in numeric_feature_specs().items():
        assert fv[f"{mt}::num::{vf}"] is None and fv[f"{mt}::num::{vf}::mask"] == 0.0


def test_harvest_from_sub_results_mirrors_package():
    """RUNTIME harvester reads the SAME two sources from sub_results (r['cards'].summary +
    synthesis_facet.claim_vector atom.values) that the package harvester reads — so offline==runtime."""
    from _skills_common.feature_vectoriser import numeric_values_from_sub_results

    lo = _spec_field("gnomad_lof_constraint")
    dep = _spec_field("crispr_lof_dependency")
    pkg = {
        "cards": [{"measurement_type": "gnomad_lof_constraint", "summary": {lo: 0.31}}],
        "synthesis": {
            "claim_vectors": {"dependency": {"claim_vector": {"DEP": {"evidence_atom": {"values": {dep: -0.46}}}}}}
        },
    }
    sub_results = {
        "safety": {
            "cards": [{"measurement_type": "gnomad_lof_constraint", "summary": {lo: 0.31}}],
            "synthesis_facet": {"claim_vector": {}},
        },
        "dependency": {
            "cards": [],
            "synthesis_facet": {"claim_vector": {"DEP": {"evidence_atom": {"values": {dep: -0.46}}}}},
        },
    }
    assert numeric_values_from_sub_results(sub_results) == numeric_values_from_package(pkg)
    assert numeric_values_from_sub_results(sub_results)["gnomad_lof_constraint"][lo] == 0.31


# ── card ATTRIBUTION of the harvest (2026-09-12): measurement_type is not unique across cards ─────────
def test_every_metered_axis_names_a_source_card():
    """The harvest can only be attributed if each metered axis's primary frame names the card its cut comes
    from. Ratchet: 32/32 do today — a new metered spec without a `cut.card_id` (or `cuts[].card_id`) would
    fall back to a same-measurement_type sibling and silently re-open the clobbering this fixes."""
    from _skills_common.feature_vectoriser import numeric_source_cards

    specs, named = numeric_feature_specs(), numeric_source_cards()
    missing = sorted(set(specs) - set(named))
    assert not missing, f"metered axes whose primary frame names no card_id: {missing}"


def test_harvest_prefers_the_frame_named_card_over_a_same_measurement_type_sibling():
    """tumor_protein_abundance is carried by BOTH tumor-protein-abundance-cptac (which holds
    protein_effect_size, and is the card its ruler is cut against) and tumor-protein-distribution-by-subtype
    (which does not). The by-subtype card comes LAST in the real package, so the old {mt: summary} index
    clobbered the value and the axis harvested 0/223 over the corpus — dropped as sparse at build, leaving an
    orphan ::mask in the frozen atlas. The named card must win regardless of position."""
    vf = _spec_field("tumor_protein_abundance")  # protein_effect_size
    pkg = {
        "cards": [
            {
                "card_id": "tumor-protein-abundance-cptac",
                "measurement_type": "tumor_protein_abundance",
                "summary": {vf: 0.57},
            },
            {
                "card_id": "tumor-protein-distribution-by-subtype",
                "measurement_type": "tumor_protein_abundance",
                "summary": {"n_subtypes_measured": 3},
            },
        ],
        "synthesis": {},
    }
    assert numeric_values_from_package(pkg)["tumor_protein_abundance"][vf] == 0.57
    # falsifier: with ONLY the by-subtype card the axis is honestly unmeasured (not silently 0)
    thin = {"cards": [pkg["cards"][1]], "synthesis": {}}
    assert "tumor_protein_abundance" not in numeric_values_from_package(thin)


def test_harvest_falls_back_to_a_sibling_arm_when_the_named_card_is_absent():
    """The named arm not running is NOT the same as unmeasured: a sibling card of the same measurement_type
    that measured the same quantity is still admissible (ProCan when the Gygi panel is absent), as are cards
    that carry no card_id at all (older/synthetic packages)."""
    vf = _spec_field("cell_line_protein_abundance")  # allgene_percentile
    pkg = {
        "cards": [
            {
                "card_id": "cellline-protein-abundance-procan",
                "measurement_type": "cell_line_protein_abundance",
                "summary": {vf: 71.0},
            },
        ],
        "synthesis": {},
    }
    assert numeric_values_from_package(pkg)["cell_line_protein_abundance"][vf] == 71.0


def test_flat_atom_fallback_is_refused_for_a_value_field_several_axes_share():
    """atom.values and capsule n_basis are FLAT, card-less maps. `allgene_percentile` is the primary
    value_field of 3 axes (tumor RNA, cell-line RNA, cell-line protein), so a bare atom entry cannot be
    attributed to one of them — taking it imported another axis's percentile for 17 of the 223 corpus
    targets. Refused here; the unshared fields (loeuf_score, …) still use the fallback."""
    shared = _spec_field("tumor_expression_distribution")  # allgene_percentile
    assert shared == _spec_field("cell_line_rna_expression")  # the collision is real, not hypothetical
    pkg = {
        "cards": [],
        "synthesis": {"claim_vectors": {"x": {"claim_vector": {"A": {"evidence_atom": {"values": {shared: 88.0}}}}}}},
    }
    nv = numeric_values_from_package(pkg)
    assert nv == {}, f"a shared value_field must not be attributed from a flat map: {nv}"
    # falsifier: the SAME flat source still resolves an UNSHARED field
    lo = _spec_field("gnomad_lof_constraint")
    pkg2 = {
        "cards": [],
        "synthesis": {"claim_vectors": {"x": {"claim_vector": {"A": {"evidence_atom": {"values": {lo: 0.4}}}}}}},
    }
    assert numeric_values_from_package(pkg2)["gnomad_lof_constraint"][lo] == 0.4


def test_harvest_polarity_applied_in_build():
    lo = _spec_field("gnomad_lof_constraint")  # lower_is_stronger → negated in the feature
    pkg = {"cards": [{"measurement_type": "gnomad_lof_constraint", "summary": {lo: 0.31}}], "synthesis": {}}
    fv = build_feature_vector({}, numeric_values_from_package(pkg))
    assert fv["gnomad_lof_constraint::num::loeuf_score"] == -0.31
    assert fv["gnomad_lof_constraint::num::loeuf_score::mask"] == 1.0
