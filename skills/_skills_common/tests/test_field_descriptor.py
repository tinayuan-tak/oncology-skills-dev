"""field_descriptor — the join of SALIENCE_SPECS (structure) + display_gloss (semantics) is DERIVED, so
the tests assert it cannot drift from its two sources, plus the classification/measuredness contract.

No exact field counts are pinned (that would couple every test to a SALIENCE_SPECS addition, which already
carries its own fleet obligations); the guards are structural and derived-consistency instead.
"""

from __future__ import annotations

from _skills_common import field_descriptor as fd
from _skills_common.evidence_salience import SALIENCE_SPECS


def test_catalog_covers_every_measurement_type():
    cat = fd.descriptor_catalog()
    assert set(cat) == set(SALIENCE_SPECS)
    assert sum(len(v) for v in cat.values()) > 300  # floor, not a pin


def test_derived_no_spec_field_is_dropped_or_mistyped():
    """Every declared slot in every SALIENCE_SPECS entry must appear in that mt's descriptors with the
    matching role. This is the "cannot disagree with the source" guard: the join re-expresses the spec,
    it does not curate a second copy."""
    for mt, spec in SALIENCE_SPECS.items():
        d = fd.descriptors_for(mt)
        for slot, role in (
            ("effect_field", fd.ROLE_EFFECT),
            ("significance_field", fd.ROLE_SIGNIFICANCE),
            ("omnibus_field", fd.ROLE_OMNIBUS),
            ("n_field", fd.ROLE_N),
            ("label_field", fd.ROLE_LABEL),
            ("strata_array", fd.ROLE_STRATA),
        ):
            f = spec.get(slot)
            if f:
                assert f in d, f"{mt}: {slot}={f} missing from descriptors"
                # first-writer-wins: the role holds unless an earlier scalar slot already claimed the name
                assert d[f]["role"] in (role, fd.ROLE_EFFECT, fd.ROLE_SIGNIFICANCE), f"{mt}:{f} role {d[f]['role']}"
        for f in spec.get("categorical") or ():
            assert d.get(f, {}).get("role") == fd.ROLE_CATEGORICAL
        for f in spec.get("extra_scalars") or ():
            assert f in d


def test_every_descriptor_is_well_formed():
    for mt, fields in fd.descriptor_catalog().items():
        for field, d in fields.items():
            assert d["field"] == field
            assert d["role"] in fd.ROLES
            assert isinstance(d["label"], str) and d["label"]
            # direction only on the axis-bearing roles
            if d["role"] not in (fd.ROLE_EFFECT, fd.ROLE_FRAME_VALUE):
                assert d["direction"] is None
            # atlas_live iff frame_value
            assert d["atlas_live"] == (d["role"] == fd.ROLE_FRAME_VALUE)


def test_numeric_semantic_layer_is_complete():
    """Every NUMERIC-role salience field already has a curated (label, units) in METRIC_GLOSS — this
    mirrors the existing test_display_gloss_coverage gate from the descriptor's side. A non-empty gap
    here means a numeric field was added to a spec without its gloss entry."""
    assert fd.coverage_report()["numeric_fields_without_gloss"] == []


def test_worked_anchor_median_chronos():
    d = fd.describe_field("median_chronos", "crispr_lof_dependency")
    assert d["role"] == fd.ROLE_EFFECT
    assert d["units"] == "CHRONOS"
    assert d["direction"] == "lower_is_stronger"
    assert d["direction_phrase"] == "lower = stronger"
    assert d["significance_field"] == "q_value"  # the effect carries the pointer to its own q
    assert d["atlas_live"] is False


def test_reference_frame_value_field_is_flagged_atlas_live():
    """A reference_frame value_field is atlas-live (mints frozen columns) — it must be flagged so the
    substrate DESCRIBES it and never reshapes it."""
    d = fd.describe_field("median_chronos_panel", "crispr_lof_dependency")
    assert d is not None and d["role"] == fd.ROLE_FRAME_VALUE
    assert d["atlas_live"] is True


def test_classify_envelope_and_unclassified():
    assert fd.classify_field("method_version") == fd.ROLE_ENVELOPE
    assert fd.classify_field("_private_key") == fd.ROLE_ENVELOPE
    assert fd.classify_field("median_chronos") == fd.ROLE_EFFECT
    assert fd.classify_field("a_field_no_spec_declares") == fd.ROLE_UNCLASSIFIED


def test_measured_reuses_is_measured_rule():
    base = {"field": "x"}
    assert fd.stamp_measured(base, 0.0)["measured"] is True  # a measured zero is MEASURED
    assert fd.stamp_measured(base, False)["measured"] is True
    assert fd.stamp_measured(base, None)["measured"] is False
    assert fd.stamp_measured(base, float("nan"))["measured"] is False
    assert fd.stamp_measured(base, "data_unavailable")["measured"] is False


def test_describe_summary_stamps_role_and_measured():
    summary = {
        "median_chronos": -1.18,  # effect, measured
        "q_value": None,  # significance, NOT measured
        "method_version": "0.1.0",  # envelope
        "some_novel_field": 3,  # unclassified
    }
    out = fd.describe_summary(summary, "crispr_lof_dependency")
    assert out["median_chronos"]["role"] == fd.ROLE_EFFECT and out["median_chronos"]["measured"] is True
    assert out["q_value"]["role"] == fd.ROLE_SIGNIFICANCE and out["q_value"]["measured"] is False
    assert out["method_version"]["role"] == fd.ROLE_ENVELOPE
    assert out["some_novel_field"]["role"] == fd.ROLE_UNCLASSIFIED


def test_coverage_report_surfaces_a_nonempty_work_queue():
    """The report is not a gate; its job is to name the per-field work queue. A summary carrying a
    non-spec field must show up as unclassified — a zero would mean the classifier is fabricating roles."""
    rep = fd.coverage_report([{"median_chronos": -1.0, "totally_undeclared_field": 1, "target": "KRAS"}])
    assert "totally_undeclared_field" in rep["unclassified_fields"]
    assert rep["n_unclassified"] >= 1
    assert rep["emitted_role_counts"].get(fd.ROLE_ENVELOPE, 0) >= 1  # target -> envelope


def test_catalog_is_deterministic():
    assert fd.descriptor_catalog() == fd.descriptor_catalog()


def test_every_descriptor_carries_a_source_class_and_all_are_instrument_today():
    """Epistemic provenance is a first-class descriptor field. Every salience measurement_type is
    instrument-derived (the LLM-lit skills emit grounded_findings, not salience effect fields), so all
    descriptors are `instrument` today — a MEASURED fact, guarded here so a future non-instrument type is
    a deliberate, reviewed addition rather than a silent reclassification."""
    for fields in fd.descriptor_catalog().values():
        for d in fields.values():
            assert d["source_class"] in fd.SOURCE_CLASSES
            assert d["source_class"] == fd.SOURCE_INSTRUMENT
    rep = fd.coverage_report()
    assert rep["source_class_counts"] == {fd.SOURCE_INSTRUMENT: rep["n_descriptor_fields"]}


def test_source_class_for_defaults_to_instrument():
    assert fd.source_class_for("a_type_with_no_override") == fd.SOURCE_INSTRUMENT
    assert fd.source_class_for(None) == fd.SOURCE_INSTRUMENT
