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


def _tmp_registry(tmp_path):
    """Write a minimal subtype_crosswalk.yaml with an MSI_H↔CMS1 association (DepMap dep ↔ TCGA expr,
    a cohort bridge) so the association tier can be exercised hermetically."""
    voc = tmp_path / "vocabularies"
    voc.mkdir(parents=True, exist_ok=True)
    (voc / "subtype_crosswalk.yaml").write_text(
        "schema_version: 1\nindications:\n"
        "  - canonical_code: COADREAD\n"
        "    axes:\n"
        "      - {axis: msi_status, strata: [MSI_H, MSS], cohorts: [tcga, depmap]}\n"
        "      - {axis: molecular_subtype, strata: [CMS1, CMS2], cohorts: [tcga]}\n"
        "    associations:\n"
        "      - {from: MSI_H, to: CMS1, relationship: enriched_in, note: 'MSI-H enriched in CMS1'}\n"
    )
    return tmp_path


def test_associated_stratification_bridges_msi_dependency_and_cms_expression(tmp_path):
    # MSI_H measured on the DEPENDENCY axis; CMS1 measured on the EXPRESSION axis. Different stratum
    # ids → NO same-id convergence. But the registry links MSI_H enriched_in CMS1 → associated tier.
    reg = _tmp_registry(tmp_path)
    sr = _sr(
        dependency={"subgroup-stratified-dependency": {"per_subgroup_metrics": [
            _row("MSI_H", dependency_class="dependent")]}},
        expression={"tumor-rna-distribution-by-subtype": {"per_subgroup_metrics": [
            _row("CMS1", median_log2tpm=7.0)]}},
    )
    f = run._subtype_facet(sr, indication="COADREAD", contracts_repo=reg)
    assert f["convergent_subtypes"] == []                    # NOT same-id convergence
    assert f["verdict"] == "associated_stratification"
    assert len(f["associated_subtypes"]) == 1
    a = f["associated_subtypes"][0]
    assert a["from"] == "MSI_H" and a["to"] == "CMS1" and a["relationship"] == "enriched_in"
    # MSI_H cohorts [tcga, depmap] overlap CMS1 [tcga] → NOT a disjoint cohort bridge (correct: the
    # association could be traced within TCGA). cohort_bridge only fires on DISJOINT cohort sets.
    assert a["cohort_bridge"] is False


def test_cohort_bridge_true_when_strata_cohorts_disjoint(tmp_path):
    # A registry where the two associated strata live on DISJOINT cohorts → cohort_bridge True.
    voc = (tmp_path / "vocabularies"); voc.mkdir(parents=True)
    (voc / "subtype_crosswalk.yaml").write_text(
        "schema_version: 1\nindications:\n"
        "  - canonical_code: SCLC\n"
        "    axes:\n"
        "      - {axis: napy, strata: [SCLC_A], cohorts: [depmap]}\n"
        "      - {axis: target_high, strata: [DLL3_high], cohorts: [george_2015]}\n"
        "    associations:\n"
        "      - {from: DLL3_high, to: SCLC_A, relationship: enriched_in, note: DLL3 is ASCL1-driven}\n")
    sr = _sr(
        dependency={"subgroup-stratified-dependency": {"per_subgroup_metrics": [_row("SCLC_A", dependency_class="dependent")]}},
        expression={"tumor-rna-distribution-by-subtype": {"per_subgroup_metrics": [_row("DLL3_high", median_log2tpm=8.0)]}},
    )
    f = run._subtype_facet(sr, indication="SCLC", contracts_repo=tmp_path)
    assert f["verdict"] == "associated_stratification"
    assert f["associated_subtypes"][0]["cohort_bridge"] is True   # depmap ↔ george_2015 disjoint


def test_association_not_claimed_when_same_axis(tmp_path):
    # If MSI_H and CMS1 were BOTH only on expression (same axis), the pair is NOT a cross-axis bridge.
    reg = _tmp_registry(tmp_path)
    sr = _sr(expression={"tumor-rna-distribution-by-subtype": {"per_subgroup_metrics": [
        _row("MSI_H", median_log2tpm=6.0), _row("CMS1", median_log2tpm=7.0)]}})
    f = run._subtype_facet(sr, indication="COADREAD", contracts_repo=reg)
    # both measured on the SAME (expression) axis → no cross-axis association → single_axis
    assert f["associated_subtypes"] == []
    assert f["verdict"] == "single_axis_stratification"


def test_same_id_convergence_wins_over_association(tmp_path):
    # If MSI_H itself converges on 2 axes, verdict is the STRONG convergent_stratification, not associated.
    reg = _tmp_registry(tmp_path)
    sr = _sr(
        dependency={"subgroup-stratified-dependency": {"per_subgroup_metrics": [_row("MSI_H", dependency_class="dependent")]}},
        genomic_alteration={"subgroup-stratified-mutation-frequency": {"per_subgroup_metrics": [_row("MSI_H", frequency=0.4)]}},
        expression={"tumor-rna-distribution-by-subtype": {"per_subgroup_metrics": [_row("CMS1", median_log2tpm=7.0)]}},
    )
    f = run._subtype_facet(sr, indication="COADREAD", contracts_repo=reg)
    assert f["verdict"] == "convergent_stratification"
    assert "MSI_H" in f["convergent_subtypes"]


def test_no_registry_degrades_to_exact_match(tmp_path):
    # No crosswalk on disk → association tier empty, facet still works (exact-match only).
    empty = tmp_path / "no_vocab"
    empty.mkdir()
    sr = _sr(
        dependency={"subgroup-stratified-dependency": {"per_subgroup_metrics": [_row("MSI_H", dependency_class="dependent")]}},
        expression={"tumor-rna-distribution-by-subtype": {"per_subgroup_metrics": [_row("CMS1", median_log2tpm=7.0)]}},
    )
    f = run._subtype_facet(sr, indication="COADREAD", contracts_repo=empty)
    assert f["associated_subtypes"] == []
    assert f["verdict"] == "single_axis_stratification"      # two 1-axis strata, no bridge


def test_convergence_reachable_in_production_sub_results_shape():
    # PRODUCTION shape (regression for the dead-2/3-axes bug): _run_sub_skills resolves the
    # dependency + mutation-frequency subtype cards under the single 'subtype_fit' short — NOT
    # under 'dependency'/'genomic_alteration' — while the expression subtype card lives under
    # 'expression'. The facet must still converge across all three axes.
    sr = _sr(
        subtype_fit={
            "subgroup-stratified-dependency": {"per_subgroup_metrics": [_row("MSI", dependency_class="dependent")]},
            "subgroup-stratified-mutation-frequency": {"per_subgroup_metrics": [_row("MSI", frequency=0.4)]},
        },
        expression={"tumor-rna-distribution-by-subtype": {"per_subgroup_metrics": [_row("MSI", median_log2tpm=7.0)]}},
    )
    f = run._subtype_facet(sr)
    assert f["verdict"] == "convergent_stratification"
    assert "MSI" in f["convergent_subtypes"]
    assert f["per_subtype"]["MSI"]["n_axes_measured"] == 3


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
