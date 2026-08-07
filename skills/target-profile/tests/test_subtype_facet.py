"""Subtype-convergence facet — deterministic cross-card assembly (capstone Part 3c integration layer).

Verifies _subtype_facet converges the three subtype-grain panoramas (expression / dependency /
mutation-frequency) BY molecular subtype from synthetic sub_results, and the four verdict cases:
convergent_stratification (>=2 measured axes on one subtype), single_axis_stratification,
no_subtype_signal, subtype_axis_unavailable. Pure dict fixtures — no S3/LLM. Also asserts the facet
is verdict-inert (a facet dict, never a gate verdict)."""
from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import run  # noqa: E402


def _sr(**cards_by_short):
    """short -> {cards:[{card_id, summary}]} from {short: {card_id: summary-with-per_subgroup_metrics}}."""
    out = {}
    for short, card_map in cards_by_short.items():
        out[short] = {"cards": [{"card_id": cid, "summary": s} for cid, s in card_map.items()]}
    return out


def _row(stratum, state="measured", **metric):
    r = {"stratum": stratum, "evidence_state": state, "subgroup_n": 40, "source_cohort": "TCGA"}
    r.update(metric)
    return r


def test_convergent_stratification_two_axes_same_subtype():
    # MSI subtype measured on BOTH dependency AND mutation-frequency → convergent
    sr = _sr(
        dependency={"subgroup-stratified-dependency": {"per_subgroup_metrics": [
            _row("MSI", dependency_class="dependent"), _row("MSS", state="absent")]}},
        genomic_alteration={"subgroup-stratified-mutation-frequency": {"per_subgroup_metrics": [
            _row("MSI", frequency=0.42), _row("MSS", frequency=0.05)]}},
    )
    f = run._subtype_facet(sr)
    assert f["verdict"] == "convergent_stratification"
    assert f["convergent_subtypes"] == ["MSI"]
    assert set(f["per_subtype"]["MSI"]["axes_measured"]) == {"dependency", "mutation_frequency"}
    assert f["per_subtype"]["MSI"]["n_axes_measured"] == 2
    # MSS measured on mutation_frequency only (dependency was absent) → 1 axis, not convergent
    assert f["per_subtype"]["MSS"]["n_axes_measured"] == 1


def test_single_axis_stratification():
    # only one axis carries a measured stratum → single_axis
    sr = _sr(expression={"tumor-rna-distribution-by-subtype": {"per_subgroup_metrics": [
        _row("CMS1", median_log2tpm=6.1), _row("CMS2", state="underpowered")]}})
    f = run._subtype_facet(sr)
    assert f["verdict"] == "single_axis_stratification"
    assert f["convergent_subtypes"] == []
    assert f["per_subtype"]["CMS1"]["n_axes_measured"] == 1


def test_no_subtype_signal_rows_present_but_none_measured():
    # panorama rows exist but every stratum is absent/underpowered → no measured signal
    sr = _sr(dependency={"subgroup-stratified-dependency": {"per_subgroup_metrics": [
        _row("MSI", state="absent"), _row("MSS", state="underpowered")]}})
    f = run._subtype_facet(sr)
    assert f["verdict"] == "no_subtype_signal"
    assert f["axes_available"] == ["dependency"]   # the card WAS present (honest coverage)


def test_subtype_axis_unavailable_no_shard():
    # no subtype-grain card reached at all (no shard for the indication) → coverage gap, not a negative
    sr = _sr(dependency={"subgroup-stratified-dependency": {"per_subgroup_metrics": []}},
             expression={"some-other-card": {"expression_class": "broadly_high"}})
    f = run._subtype_facet(sr)
    assert f["verdict"] == "subtype_axis_unavailable"
    assert f["n_subtypes_evaluated"] == 0


def test_facet_is_verdict_inert_shape():
    # the facet is a descriptive dict with a _disclaimer — never a (verdict, rule) gate tuple
    f = run._subtype_facet(_sr())
    assert isinstance(f, dict)
    assert "_disclaimer" in f and "never mints a nominate" in f["_disclaimer"]
    assert f["verdict"] == "subtype_axis_unavailable"   # empty sub_results → nothing reached


def test_three_axis_convergence_and_metrics_carried():
    sr = _sr(
        expression={"tumor-rna-distribution-by-subtype": {"per_subgroup_metrics": [_row("MSI", median_log2tpm=7.0)]}},
        dependency={"subgroup-stratified-dependency": {"per_subgroup_metrics": [_row("MSI", dependency_class="dependent")]}},
        genomic_alteration={"subgroup-stratified-mutation-frequency": {"per_subgroup_metrics": [_row("MSI", frequency=0.5)]}},
    )
    f = run._subtype_facet(sr)
    assert f["verdict"] == "convergent_stratification"
    assert f["per_subtype"]["MSI"]["n_axes_measured"] == 3
    # metrics carried per axis (bookkeeping keys stripped)
    m = f["per_subtype"]["MSI"]["metrics"]
    assert m["expression"]["median_log2tpm"] == 7.0
    assert m["mutation_frequency"]["frequency"] == 0.5
    assert "subgroup_n" not in m["dependency"]   # bookkeeping stripped
