"""Subtype-convergence facet — deterministic cross-card assembly (capstone Part 3c integration layer).

Verifies _subtype_facet converges the three subtype-grain panoramas (expression / dependency /
mutation-frequency) BY molecular subtype from synthetic sub_results, and the four verdict cases:
convergent_stratification (>=2 measured axes on one subtype), single_axis_stratification,
no_subtype_signal, subtype_axis_unavailable. Pure dict fixtures — no S3/LLM. Also asserts the facet
is verdict-inert (a facet dict, never a gate verdict)."""
from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

run = load_run_py(Path(__file__).resolve().parents[1], "tp_run_subtype_facet")


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


def _sr_spine(**rows_by_short):
    """sub_results carrying the subtype rows on the skill_report[] SPINE (claim_chips_by_subtype), no cards."""
    return {short: {"synthesis_facet": {"skill_report": {"claim_chips_by_subtype": rows}}}
            for short, rows in rows_by_short.items()}


def test_convergence_read_from_skill_report_spine():
    # SAME MSI convergence as the card test, but the rows ride the skill_report spine (no cards at all).
    sr = _sr_spine(
        dependency=[_row("MSI", dependency_class="dependent"), _row("MSS", state="absent")],
        genomic_alteration=[_row("MSI", frequency=0.42), _row("MSS", frequency=0.05)],
    )
    f = run._subtype_facet(sr)
    assert f["verdict"] == "convergent_stratification"
    assert f["convergent_subtypes"] == ["MSI"]
    # the per-axis spine is EXPOSED for the renderer / roll-up provenance
    assert set(f["claim_chips_by_subtype"]) == {"dependency", "mutation_frequency"}
    assert f["claim_chips_by_subtype"]["dependency"][0]["stratum"] == "MSI"


def test_spine_preferred_over_card_rows():
    # a skill carrying BOTH → the spine sub-vector wins (cards are only a fallback for the subtype tier).
    sr = {"dependency": {
        "synthesis_facet": {"skill_report": {"claim_chips_by_subtype": [_row("MSI", dependency_class="dependent")]}},
        "cards": [{"card_id": "subgroup-stratified-dependency",
                   "summary": {"per_subgroup_metrics": [_row("MSS", state="absent")]}}]}}
    f = run._subtype_facet(sr)
    assert "MSI" in f["per_subtype"] and "MSS" not in f["per_subtype"]   # read the spine, not the card


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


def _row_id(stratum_id, state="measured", **metric):
    """A per_subgroup_metrics record keyed on `stratum_id` — the field the REAL
    tumor-rna-distribution-by-subtype reader (tcga_gtex_expression_distribution) emits, unlike the
    `stratum`-keyed panorama rows the other fixtures use."""
    r = {"stratum_id": stratum_id, "evidence_state": state, "subgroup_n": 40, "source_cohort": "TCGA"}
    r.update(metric)
    return r


def test_expression_axis_keyed_on_stratum_id_participates_in_convergence():
    # REGRESSION (stratum_id join): the expression subtype reader emits `stratum_id`, not `stratum`.
    # _subtype_stratum_key previously ignored stratum_id, so every expression row returned a None key
    # and the expression axis silently dropped from the facet — convergence ran on dependency+mutation
    # only. Here MSI_H is measured on expression (stratum_id) AND dependency (stratum): must converge.
    sr = _sr(
        expression={"tumor-rna-distribution-by-subtype": {"per_subgroup_metrics": [
            _row_id("MSI_H", median_log2tpm=6.1)]}},
        dependency={"subgroup-stratified-dependency": {"per_subgroup_metrics": [
            _row("MSI_H", dependency_class="dependent")]}},
    )
    f = run._subtype_facet(sr)
    assert f["verdict"] == "convergent_stratification"
    assert f["convergent_subtypes"] == ["MSI_H"]
    assert set(f["per_subtype"]["MSI_H"]["axes_measured"]) == {"expression", "dependency"}
    # stratum_id is a bookkeeping key — it must NOT leak into the carried expression metric
    assert "stratum_id" not in f["per_subtype"]["MSI_H"]["metrics"].get("expression", {})


def test_expression_only_stratum_id_row_is_identified_single_axis():
    # An expression-only stratum_id row is now IDENTIFIED (single_axis), not dropped to no_subtype_signal.
    sr = _sr(expression={"tumor-rna-distribution-by-subtype": {"per_subgroup_metrics": [
        _row_id("CMS1", median_log2tpm=6.1)]}})
    f = run._subtype_facet(sr)
    assert f["verdict"] == "single_axis_stratification"
    assert "CMS1" in f["per_subtype"]
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


def _prod_shape_with_reports():
    """PRODUCTION sub_results shape for the back-fill: the dependency + mutation-frequency subtype cards
    resolve CENTRALLY under `subtype_fit`, the expression subtype card under `expression`; each OWNING
    short carries a skill_report with an UNFILLED claim_chips_by_subtype slot (as it does in the composed
    fan-out before the back-fill)."""
    def _rep():   # a minimal skill_report carrier with the reserved (None) subtype slot
        return {"synthesis_facet": {"skill_report": {"claim_chips_by_subtype": None}}}
    return {
        "expression": {**_rep(), "cards": [{"card_id": "tumor-rna-distribution-by-subtype",
                       "summary": {"per_subgroup_metrics": [_row("MSI", median_log2tpm=7.0)]}}]},
        "dependency": _rep(),
        "genomic_alteration": _rep(),
        "subtype_fit": {"cards": [
            {"card_id": "subgroup-stratified-dependency",
             "summary": {"per_subgroup_metrics": [_row("MSI", dependency_class="dependent")]}},
            {"card_id": "subgroup-stratified-mutation-frequency",
             "summary": {"per_subgroup_metrics": [_row("MSI", frequency=0.4)]}},
        ]},
    }


def test_backfill_populates_owning_skill_reports_from_centralized_tier():
    # After the back-fill each owning short's skill_report carries ITS axis's subtype rows — sourced from
    # the centralized subtype_fit tier (dependency + mutation-frequency) and its own card (expression).
    sr = _prod_shape_with_reports()
    run._backfill_subtype_spine(sr)
    def _spine(short):
        return sr[short]["synthesis_facet"]["skill_report"]["claim_chips_by_subtype"]
    assert _spine("expression")[0]["stratum"] == "MSI" and "median_log2tpm" in _spine("expression")[0]
    assert _spine("dependency")[0]["dependency_class"] == "dependent"
    assert _spine("genomic_alteration")[0]["frequency"] == 0.4


def test_backfill_is_byte_identical_to_the_card_fallback_facet():
    # The facet computed AFTER the back-fill (spine-first branch fires) equals the facet from the raw
    # card-fallback shape — the back-fill only relocates the SAME rows onto the per-skill spine.
    before = run._subtype_facet(_prod_shape_with_reports())          # card fallback path
    sr = _prod_shape_with_reports()
    run._backfill_subtype_spine(sr)
    after = run._subtype_facet(sr)                                   # spine-first path
    assert after == before
    assert after["verdict"] == "convergent_stratification" and after["per_subtype"]["MSI"]["n_axes_measured"] == 3


def test_backfill_idempotent_and_leaves_prefilled_vectors():
    # A short already carrying its own sub-vector is left untouched (idempotent); a second pass is a no-op.
    sr = _prod_shape_with_reports()
    own = [_row("MSS", dependency_class="dependent")]
    sr["dependency"]["synthesis_facet"]["skill_report"]["claim_chips_by_subtype"] = own
    run._backfill_subtype_spine(sr)
    assert sr["dependency"]["synthesis_facet"]["skill_report"]["claim_chips_by_subtype"] is own  # untouched
    snapshot = run._subtype_facet(sr)
    run._backfill_subtype_spine(sr)                                  # second pass
    assert run._subtype_facet(sr) == snapshot


def test_backfill_noop_without_subtype_scope():
    # No subtype rows resolve (no subtype_fit tier, no expression subtype card) → nothing written, the
    # reserved None slot stays None (byte-identical to a non-subtypes run).
    sr = {"dependency": {"synthesis_facet": {"skill_report": {"claim_chips_by_subtype": None}}}}
    run._backfill_subtype_spine(sr)
    assert sr["dependency"]["synthesis_facet"]["skill_report"]["claim_chips_by_subtype"] is None


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
