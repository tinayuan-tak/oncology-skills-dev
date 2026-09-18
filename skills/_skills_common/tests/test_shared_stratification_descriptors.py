"""Emission PR 5 — the shared subtype-arm descriptor group.

The subtype-panorama fields are common to every by-subtype card and carry the SAME meaning across
measurement types (cell_line_rna_expression / tumor_protein_abundance / tumor_expression_distribution).
Describing them per-spec would count them once PER measurement_type (the SUM); this describes them
ONCE by name (a shared vocabulary keyed like ENVELOPE_FIELDS) — the UNION. Verdict-inert (display).
"""

from __future__ import annotations

from _skills_common import field_descriptor as fd

SHARED = {
    "subtype_stratification_class": "categorical",
    "subtype_axis_quality": "categorical",
    "subtype_axis_available": "categorical",
    "n_subtypes_measured": "n",
    "n_subtypes_enriched": "n",
    "n_subtypes_depleted": "n",
    "per_subgroup_metrics": "strata",
}


def test_shared_fields_classify_to_expected_roles():
    for field, role in SHARED.items():
        assert fd.classify_field(field) == role, field


def test_roles_are_valid_vocabulary():
    assert set(SHARED.values()) <= set(fd.ROLES)


def test_union_not_sum_role_is_measurement_type_invariant():
    # the SAME field classifies to the SAME role regardless of measurement_type — so it is one
    # described field (union), not one-per-mt (sum). This is what makes it a shared vocabulary.
    for field, role in SHARED.items():
        for mt in ("cell_line_rna_expression", "tumor_protein_abundance", "tumor_expression_distribution", None):
            assert fd.classify_field(field, mt) == role, (field, mt)


def test_shared_map_is_exactly_the_seven():
    assert set(fd._SHARED_FIELD_ROLES) == set(SHARED)
    assert len(fd._SHARED_FIELD_ROLES) == 7


def test_numeric_shared_fields_carry_units_categorical_do_not():
    assert fd.describe_field("n_subtypes_measured")["units"] == "count"
    assert fd.describe_field("subtype_stratification_class")["units"] is None
    assert fd.describe_field("per_subgroup_metrics")["role"] == "strata"


def test_describe_summary_describes_shared_fields_not_unclassified():
    # a by-subtype card summary carrying the shared fields must describe them, not leave them unclassified.
    summary = {"subtype_stratification_class": "stratified", "n_subtypes_measured": 4, "per_subgroup_metrics": []}
    desc = fd.describe_summary(summary, "cell_line_rna_expression")
    assert desc["subtype_stratification_class"]["role"] == "categorical"
    assert desc["n_subtypes_measured"]["role"] == "n"
    assert desc["per_subgroup_metrics"]["role"] == "strata"
    assert all(d["role"] != "unclassified" for d in desc.values())


def test_shared_descriptor_carries_provenance_flag():
    # descriptors sourced from the shared vocabulary are tagged, so a consumer can tell them from a
    # per-spec descriptor (they are NOT part of any measurement_type's SALIENCE_SPEC).
    assert fd.describe_field("subtype_axis_quality").get("shared_stratification") is True


def test_unclassified_still_nonzero_not_fabricated():
    # ER7 mirror: describing 7 real fields must not empty the work queue. classify a field with no
    # descriptor anywhere and confirm it is still unclassified (the classifier is not fabricating).
    assert fd.classify_field("a_field_with_no_home_at_all_xyz") == "unclassified"
