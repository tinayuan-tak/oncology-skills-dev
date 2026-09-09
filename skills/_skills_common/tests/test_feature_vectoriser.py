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


def test_numeric_specs_track_reference_frame_value_fields():
    specs = numeric_feature_specs()
    # every reference_frame axis contributes exactly its value_field
    rf_axes = {mt for mt, s in SALIENCE_SPECS.items() if s.get("reference_frame")}
    assert set(specs) == rf_axes and len(specs) >= 5
    # LOEUF is lower_is_stronger; selectivity log2fc is higher_is_stronger (sanity on the registry)
    assert specs.get("gnomad_lof_constraint") == ("loeuf_score", "lower_is_stronger")


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
    return SALIENCE_SPECS[mt]["reference_frame"]["value_field"]


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


def test_harvest_polarity_applied_in_build():
    lo = _spec_field("gnomad_lof_constraint")  # lower_is_stronger → negated in the feature
    pkg = {"cards": [{"measurement_type": "gnomad_lof_constraint", "summary": {lo: 0.31}}], "synthesis": {}}
    fv = build_feature_vector({}, numeric_values_from_package(pkg))
    assert fv["gnomad_lof_constraint::num::loeuf_score"] == -0.31
    assert fv["gnomad_lof_constraint::num::loeuf_score::mask"] == 1.0
