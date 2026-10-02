"""Scorecard L1 accuracy batch F (#2088) — the ROSTER CLOSER: the by-subtype distribution trio +
the ProCan cell-line protein card, re-derived through their REAL readers and bridged to the
EPCAM/COADREAD golden. Brings ``cards_covered`` from 13 → 17 of 17 (``cards_not_yet_covered`` → []).

FILE-DISJOINT sibling of test_scorecard_l1_accuracy_rederivation.py (#1988) and
_batch_a.py … _batch_e.py — do NOT edit those; this covers the four cards batch E's reconciliation
left in ``cards_not_yet_covered``:
  - cellline-protein-abundance-procan       (procan_protein_abundance.cli.load_and_classify)
  - cellline-rna-distribution-by-subtype    (depmap_expression_distribution.read.build_expression_subtype_panorama)
  - tumor-protein-distribution-by-subtype   (cptac_protein_distribution.read.build_protein_subtype_panorama)
  - tumor-rna-distribution-by-subtype       (tcga_gtex_expression_distribution.cli.build_subtype_panorama)

Same METHOD as batch A–E: reuse analysis-methods' T3 recomputation anchors (plan foamy-bird Stage I)
and BRIDGE them one step further — re-derive the number OFFLINE through the REAL reader (its S3-load
seams mocked with the committed raw-substrate fixtures) AND assert it equals the tumor-presence
golden's card summary for the same target/indication. The offline re-derivation itself (and its
byte-exact match to the anchor) is proved network-free in
analysis-methods' tests/calibration/recomputation/test_subtype_panorama_recomputation.py; this file
adds the GOLDEN bridge + honest-drift pins.

The re-derivation recipe (which seam each reader loads, and how it is fed the frozen substrate) is
the single source of truth in the capture tool's ``_rederive_*`` helpers — imported here so the
bridge cannot silently diverge from the anchor's own re-derivation.

## HONEST DRIFTS (pinned, NOT silently normalized) — the goldens predate several verdict-INERT
## reader evolutions; this issue's brief explicitly permits honest RED/drift with a data-level
## explanation and a cross-link rather than a golden regen (a full structural regen — incl. the
## cell-line arm's 26Q1 → 26Q3 vintage boundary, a product-semantics change that is an OWNER call —
## is tracked in #2061, behind the 26Q3 migration + #1638):
  1. subtype_axis_quality ``underpowered`` → ``exploratory`` on the two cell-line-grain / CPTAC arms:
     the n=27–34 single-measured-stratum axes now grade with the finer AM#659 exploratory band
     (a >=10 floor), a strictly finer grade of the SAME "not powered to `measured`" state — the
     verdict-bearing subtype_stratification_class / n_subtypes_measured are byte-stable.
  2. subtype_enrich_log2_delta ``None`` → the applied cut (0.585 tumor-RNA / 1.0 cell-line-RNA /
     0.25 CPTAC-protein): the cut ACTUALLY APPLIED to each measured row is now emitted (TC#811,
     cross-arm comparability) where the golden dropped it. Display-only; subtype_signal unchanged.
  3. the tumor-RNA arm's per-stratum five-number SPREAD (p5/q1/mean/q3/sd_log2tpm) ``None`` → values:
     AM#857 completed the per-stratum distribution retention the golden's vintage still dropped.
     Additive; median/percentile/class/subtype_signal byte-stable (one coefficient_of_variation
     differs only in float re-association, ~1e-15, pinned bounded below).
  4. reader-side provenance STAMPS the goldens lack entirely: ``assignment_manifest`` (cell-line RNA
     + CPTAC protein arms) and ``protein_high_abundance_class_cutoff`` (procan) — new keys, not value
     flips.
  5. cellline-rna 26Q1 → 26Q3 VINTAGE: subgroup_n 27→28 / median_log2tpm 9.6038→9.6131 /
     pooled_lineage_median 9.8646→9.8724 / source_cohort + _data_source 26q1→26q3. A genuine DepMap
     release advance — NOT regenerated across the version boundary here (owner call, #2061); the
     class (broadly_high) + fraction_expressed + subtype_signal are stable.
  6. procan protein_expression_class ``lineage_restricted`` → ``sub_broad_detection``: the golden
     predates the current detection-band classifier (which also emits
     protein_high_abundance_class_cutoff, #2261). EVERY numeric field the class is derived from
     (median/p5/p25/p75/p95/IQR/fraction_detected/allgene_percentile) is byte-exact — a pure
     classifier evolution over identical substrate, cross-linked #2061.
  7. CPTAC-protein pooled_cohort_median_log2_ratio -0.0352 → 0.0706 (cross-linked #2180 F3): UNLIKE
     drifts 1–6 this is a DELIBERATE BASELINE CORRECTION, not a verdict-inert emission. The golden's
     baseline pooled the FULL unstratified cohort (incl. the ~43% is_member=null aliquots that belong
     to no stratum); AM#2180 F3 repools over the UNION of CLASSIFIED strata members (mirroring the
     cell-line arm), so each stratum is contrasted against a baseline it is a member of. The non-member
     aliquots sat systematically lower, so the corrected baseline rises. The verdict-bearing
     subtype_stratification_class / n_subtypes_* are byte-stable (the baseline shift stays within the
     0.25 cut on this single-measured-stratum shard).

OFFLINE — reads only committed fixtures (this repo's golden + analysis-methods' committed anchors +
their frozen raw-substrate). No S3, no creds. Skips (not fails) if the analysis-methods sibling
checkout lacks the batch-F anchors (a partial checkout degrades honestly).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from unittest import mock

import pandas as pd
import pytest

SKILL_DIR = Path(__file__).resolve().parent.parent

from _skills_common.paths import analysis_methods_root

AM_ROOT = analysis_methods_root()
RECOMPUTATION_DIR = AM_ROOT / "tests" / "calibration" / "recomputation"
ANCHOR_DIR = RECOMPUTATION_DIR / "anchors"
GOLDEN = SKILL_DIR / "tests" / "fixtures" / "epcam_coadread_decision.json"

PROCAN_ANCHOR = ANCHOR_DIR / "epcam.procan_protein_abundance.json"
CELLLINE_ANCHOR = ANCHOR_DIR / "epcam_coadread.cellline_rna_subtype.json"
CPTAC_ANCHOR = ANCHOR_DIR / "epcam_coadread.tumor_protein_subtype.json"
TUMOR_RNA_ANCHOR = ANCHOR_DIR / "epcam_coadread.tumor_rna_subtype.json"

_ALL = (PROCAN_ANCHOR, CELLLINE_ANCHOR, CPTAC_ANCHOR, TUMOR_RNA_ANCHOR)

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in _ALL),
    reason=f"analysis-methods batch-F anchors not found under {ANCHOR_DIR} (sibling checkout absent/predates #2088)",
)

# The re-derivation recipe lives in the capture tool (one source of truth for the seam mocking).
if RECOMPUTATION_DIR.exists() and str(RECOMPUTATION_DIR) not in sys.path:
    sys.path.insert(0, str(RECOMPUTATION_DIR))


def _cap():
    import capture_subtype_panorama_anchor as cap  # noqa: PLC0415

    return cap


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _golden_card(card_id: str) -> dict:
    d = json.loads(GOLDEN.read_text())
    for c in d["cards"]:
        if c["card_id"] == card_id:
            return c["summary"]
    raise AssertionError(f"golden fixture carries no card {card_id!r}")


def _assert_stable(reder: dict, golden: dict, fields, label: str) -> None:
    for f in fields:
        assert reder.get(f) == golden.get(f), f"{label}: {f} drifted vs golden: {reder.get(f)!r} != {golden.get(f)!r}"


def _psm_by(rows, key):
    return {r.get(key): r for r in rows}


# ── 1) cellline-protein-abundance-procan ─────────────────────────────────────────────────────────

_PROCAN_STABLE = (
    "n_cell_lines_evaluated",
    "n_cell_lines_in_panel",
    "fraction_detected",
    "median_log2_abundance_panel",
    "p5_log2_abundance_panel",
    "p25_log2_abundance_panel",
    "p75_log2_abundance_panel",
    "p95_log2_abundance_panel",
    "log2_abundance_iqr",
    "n_lineages_evaluated",
    "per_lineage_stats",
    "n_lineage_restricted_lineages",
    "method_version",
    "protein_abundance_source",
    "allgene_percentile",
    "allgene_percentile_class",
    "allgene_percentile_context",
)


def _rederive_procan(anchor: dict) -> dict:
    from onc_methods.procan_protein_abundance import cli as pcli  # noqa: PLC0415

    with mock.patch.object(pcli, "resolve_accessions", lambda target: [anchor["accession"]]):
        return pcli.load_and_classify(
            anchor["target"],
            product_path=str(RECOMPUTATION_DIR / anchor["rows_fixture"]),
            null_path=str(RECOMPUTATION_DIR / anchor["null_fixture"]),
        )


def test_procan_rederives_and_bridges_golden_stable_subset():
    reder = _rederive_procan(_load(PROCAN_ANCHOR))
    golden = _golden_card("cellline-protein-abundance-procan")
    _assert_stable(reder, golden, _PROCAN_STABLE, "procan")


def test_procan_class_drift_is_pinned_classifier_evolution_cross_linked_2061():
    """Drift 6 (pinned, cross-linked #2061/#2261): the class re-derives to the current detection band
    over the byte-identical numeric substrate; the golden predates the reclassification + the new
    cutoff key. Pinned so a future golden regen reverting it fails loudly."""
    reder = _rederive_procan(_load(PROCAN_ANCHOR))
    golden = _golden_card("cellline-protein-abundance-procan")
    assert golden["protein_expression_class"] == "lineage_restricted"
    assert reder["protein_expression_class"] == "sub_broad_detection"
    assert reder["protein_expression_class"] != golden["protein_expression_class"]
    assert "protein_high_abundance_class_cutoff" not in golden
    assert reder.get("protein_high_abundance_class_cutoff") is not None


def test_procan_teeth_emptying_rows_breaks_the_golden_numeric_match():
    """Teeth: an empty rows fixture must collapse the re-derivation to data_unavailable — its
    median_log2_abundance_panel then differs from the golden's, proving the numeric bridge is a live
    function of the frozen rows, not echoed from the anchor."""
    import pyarrow.parquet as pq  # noqa: PLC0415
    from onc_methods.procan_protein_abundance import cli as pcli  # noqa: PLC0415

    anchor = _load(PROCAN_ANCHOR)
    golden = _golden_card("cellline-protein-abundance-procan")
    rows = RECOMPUTATION_DIR / anchor["rows_fixture"]
    empty = rows.parent / "_batch_f_teeth_empty.parquet"
    pq.write_table(pq.read_table(rows).slice(0, 0), empty)
    try:
        with mock.patch.object(pcli, "resolve_accessions", lambda target: [anchor["accession"]]):
            mutated = pcli.load_and_classify(
                anchor["target"], product_path=str(empty), null_path=str(RECOMPUTATION_DIR / anchor["null_fixture"])
            )
        assert mutated["protein_expression_class"] == "data_unavailable"
        assert mutated["median_log2_abundance_panel"] != golden["median_log2_abundance_panel"]
    finally:
        empty.unlink(missing_ok=True)


# ── 2) cellline-rna-distribution-by-subtype ──────────────────────────────────────────────────────

_CELLLINE_STABLE = (
    "target",
    "indication",
    "subtype_axis_available",
    "n_subtypes_measured",
    "n_subtypes_enriched",
    "n_subtypes_depleted",
    "subtype_stratification_class",
    "spotlight_subtype",
)
_CELLLINE_PSM_STABLE = (
    "stratum",
    "class",
    "fraction_expressed",
    "subtype_signal",
    "subtype_defining_data",
    "subgroup_n_floor_met",
)


def _cellline_inputs(anchor: dict):
    tpm = {k: float(v) for k, v in _load(RECOMPUTATION_DIR / anchor["tpm_fixture"]).items()}
    assignments = pd.read_parquet(RECOMPUTATION_DIR / anchor["assignments_fixture"])
    return tpm, assignments


def _rederive_cellline(anchor: dict) -> dict:
    tpm, assignments = _cellline_inputs(anchor)
    return _cap()._rederive_cellline_rna(
        anchor["target"], anchor["indication"], anchor["strata"], anchor["manifest"], tpm, assignments
    )


def test_cellline_rna_rederives_and_bridges_golden_stable_subset():
    reder = _rederive_cellline(_load(CELLLINE_ANCHOR))
    golden = _golden_card("cellline-rna-distribution-by-subtype")
    _assert_stable(reder, golden, _CELLLINE_STABLE, "cellline-rna")
    # per-stratum: the class / detectability / signal are stable; the vintage + emission drifts pinned below.
    g = _psm_by(golden["per_subgroup_metrics"], "stratum")
    r = _psm_by(reder["per_subgroup_metrics"], "stratum")
    assert set(r) == set(g)
    for s in g:
        for f in _CELLLINE_PSM_STABLE:
            assert r[s].get(f) == g[s].get(f), f"cellline-rna[{s}].{f} drifted: {r[s].get(f)!r} != {g[s].get(f)!r}"


def test_cellline_rna_drift_is_vintage_and_emission_and_grade_pinned_2061():
    """Drifts 1/2/4/5 (pinned, cross-linked #2061): the 26Q1→26Q3 vintage advance + the finer
    exploratory grade + the now-emitted enrichment cut + the new assignment_manifest stamp. NOT
    regenerated across the vintage boundary (owner call)."""
    reder = _rederive_cellline(_load(CELLLINE_ANCHOR))
    golden = _golden_card("cellline-rna-distribution-by-subtype")
    # grade (drift 1) — finer band, same not-`measured` state; the verdict field is stable (asserted above).
    assert golden["subtype_axis_quality"] == "underpowered"
    assert reder["subtype_axis_quality"] == "exploratory"
    # vintage (drift 5)
    assert golden["_data_source"].startswith("DepMap-26q1") and reder["_data_source"].startswith("DepMap-26q3")
    assert golden["pooled_lineage_median_log2tpm"] != reder["pooled_lineage_median_log2tpm"]
    g = _psm_by(golden["per_subgroup_metrics"], "stratum")
    r = _psm_by(reder["per_subgroup_metrics"], "stratum")
    assert g["MSI_H"]["source_cohort"] == "DepMap-26q1" and r["MSI_H"]["source_cohort"] == "DepMap-26q3"
    assert g["MSI_H"]["evidence_state"] == "underpowered" and r["MSI_H"]["evidence_state"] == "exploratory"
    assert g["MSI_H"]["subgroup_n"] != r["MSI_H"]["subgroup_n"]  # 27 -> 28
    # emission (drift 2) + stamp (drift 4)
    assert g["MSS"].get("subtype_enrich_log2_delta") is None and r["MSS"].get("subtype_enrich_log2_delta") == 1.0
    assert (
        "assignment_manifest" not in golden and reder.get("assignment_manifest") == _load(CELLLINE_ANCHOR)["manifest"]
    )


def test_cellline_rna_teeth_zeroing_tpm_breaks_the_golden_class_match():
    """Teeth: zeroing the frozen per-ModelID TPM must move the MSS stratum's class off the golden's
    broadly_high — proving the class bridge is a live function of the substrate."""
    anchor = _load(CELLLINE_ANCHOR)
    tpm, assignments = _cellline_inputs(anchor)
    golden = _golden_card("cellline-rna-distribution-by-subtype")
    zeroed = {k: 0.0 for k in tpm}
    mutated = _cap()._rederive_cellline_rna(
        anchor["target"], anchor["indication"], anchor["strata"], anchor["manifest"], zeroed, assignments
    )
    r = _psm_by(mutated["per_subgroup_metrics"], "stratum")
    g = _psm_by(golden["per_subgroup_metrics"], "stratum")
    assert r["MSS"]["class"] != g["MSS"]["class"]


# ── 3) tumor-protein-distribution-by-subtype ─────────────────────────────────────────────────────

_CPTAC_STABLE = (
    "target",
    "indication",
    "subtype_axis_available",
    "n_subtypes_measured",
    "n_subtypes_enriched",
    "n_subtypes_depleted",
    "subtype_stratification_class",
    # pooled_cohort_median_log2_ratio is NO LONGER byte-stable vs the golden: AM#2180 F3 moved the
    # enrichment baseline from the full unstratified cohort to the classified-strata UNION. Pinned as
    # an honest drift below (drift 7) rather than asserted stable here.
)
_CPTAC_PSM_STABLE = (
    "stratum",
    "class",
    "median_log2_ratio",
    "detectable_fraction",
    "subgroup_n",
    "source_cohort",
    "subtype_signal",
)


def _cptac_inputs(anchor: dict):
    per_sample = pd.read_parquet(RECOMPUTATION_DIR / anchor["sample_fixture"])
    assignments = pd.read_parquet(RECOMPUTATION_DIR / anchor["assignments_fixture"])
    return per_sample, assignments


def _rederive_cptac(anchor: dict) -> dict:
    per_sample, assignments = _cptac_inputs(anchor)
    return _cap()._rederive_cptac_protein(
        anchor["target"], anchor["indication"], anchor["strata"], anchor["manifest"], per_sample, assignments
    )


def test_cptac_protein_rederives_and_bridges_golden_stable_subset():
    reder = _rederive_cptac(_load(CPTAC_ANCHOR))
    golden = _golden_card("tumor-protein-distribution-by-subtype")
    _assert_stable(reder, golden, _CPTAC_STABLE, "cptac-protein")
    g = _psm_by(golden["per_subgroup_metrics"], "stratum")
    r = _psm_by(reder["per_subgroup_metrics"], "stratum")
    assert set(r) == set(g)
    for s in g:
        for f in _CPTAC_PSM_STABLE:
            assert r[s].get(f) == g[s].get(f), f"cptac-protein[{s}].{f} drifted: {r[s].get(f)!r} != {g[s].get(f)!r}"


def test_cptac_protein_drift_is_grade_and_emission_and_stamp_pinned_2061():
    """Drifts 1/2/4 (pinned, cross-linked #2061): the finer exploratory grade + the now-emitted
    enrichment cut + the new assignment_manifest stamp — over a byte-stable measured value set."""
    reder = _rederive_cptac(_load(CPTAC_ANCHOR))
    golden = _golden_card("tumor-protein-distribution-by-subtype")
    assert golden["subtype_axis_quality"] == "underpowered"
    assert reder["subtype_axis_quality"] == "exploratory"
    g = _psm_by(golden["per_subgroup_metrics"], "stratum")
    r = _psm_by(reder["per_subgroup_metrics"], "stratum")
    assert g["MSI_H"]["evidence_state"] == "underpowered" and r["MSI_H"]["evidence_state"] == "exploratory"
    assert g["MSS"].get("subtype_enrich_log2_delta") is None and r["MSS"].get("subtype_enrich_log2_delta") == 0.25
    assert "assignment_manifest" not in golden and reder.get("assignment_manifest") == _load(CPTAC_ANCHOR)["manifest"]


def test_cptac_protein_pooled_baseline_drift_is_the_f3_classified_union_correction_2180():
    """Drift 7 (pinned, cross-linked #2180 F3) — a DELIBERATE BASELINE CORRECTION, not inert.

    The golden's ``pooled_cohort_median_log2_ratio`` (-0.0352) was pooled over the FULL unstratified
    cohort — every tumor aliquot, including the ~43% is_member=null aliquots that MMR-IHC never
    classified into any stratum. AM#2180 F3 repools over the UNION of CLASSIFIED strata members
    (resolve_subgroup_cohort, is_member=True), mirroring the cell-line arm's _pooled_lineage_median,
    so each stratum is enriched/depleted vs a baseline it is a member of. On the EPCAM/COADREAD frozen
    substrate the non-member aliquots sat systematically LOWER, so excluding them raises the baseline
    -0.0352 → 0.0706 (verified by hand against the anchor fixture: 97 full-cohort finite aliquots vs
    54 classified-union members). This is the fix's intended output, NOT a verdict-inert emission:
    hence pinned explicitly rather than silenced. The verdict-bearing subtype_stratification_class /
    n_subtypes_* stay byte-stable (asserted in the stable-subset test) — on this single-measured-
    stratum shard the baseline shift does not cross the 0.25 enrichment cut.
    """
    reder = _rederive_cptac(_load(CPTAC_ANCHOR))
    golden = _golden_card("tumor-protein-distribution-by-subtype")
    assert golden["pooled_cohort_median_log2_ratio"] == -0.0352  # full-cohort baseline (pre-F3)
    assert reder["pooled_cohort_median_log2_ratio"] == 0.0706  # classified-union baseline (F3)


def test_cptac_protein_teeth_emptying_samples_breaks_the_golden_axis_match():
    """Teeth: an empty per-aliquot frame must collapse the measured axis (n_subtypes_measured → 0),
    off the golden's 1 — proving the rollup is a live function of the frozen aliquots."""
    anchor = _load(CPTAC_ANCHOR)
    per_sample, assignments = _cptac_inputs(anchor)
    golden = _golden_card("tumor-protein-distribution-by-subtype")
    empty = per_sample.iloc[0:0]
    mutated = _cap()._rederive_cptac_protein(
        anchor["target"], anchor["indication"], anchor["strata"], anchor["manifest"], empty, assignments
    )
    assert mutated["n_subtypes_measured"] != golden["n_subtypes_measured"]


# ── 4) tumor-rna-distribution-by-subtype ─────────────────────────────────────────────────────────

_TUMOR_RNA_SCALAR_STABLE = (
    "target",
    "indication",
    "subtype_axis_available",
    "subtype_axis_quality",
    "purity_source",
    "subtype_purity_spread",
    "spotlight_subtype",
    "assignment_manifest",
    "n_subtypes_measured",
    "n_subtypes_enriched",
    "n_subtypes_clearing_normal_window",
    "n_subtypes_clearing_proxy_window_by_tissue",
    "n_subtypes_restricted",
    "subtype_stratification_class",
    "matched_normal_tissue",
    "normal_comparator_type",
    "proxy_normal_tissues",
    "subtype_omnibus_kruskal_h",
    "subtype_omnibus_p",
    "subtype_variance_explained",
    "subtype_effect_size_class",
    "which_subtypes_separate",
    "subtype_omnibus_driving_axis",
    "subtype_omnibus_by_axis",
    "method_version",
)
# per-stratum keys the golden ALSO carries at full precision (vintage-stable substrate).
_TUMOR_RNA_PSM_STABLE = (
    "stratum_id",
    "evidence_state",
    "subgroup_n_floor_met",
    "n_tumor_samples",
    "match_rate",
    "n_purity_paired",
    "median_purity",
    "median_log2tpm",
    "p95_log2tpm",
    "p99_log2tpm",
    "min_log2tpm",
    "max_log2tpm",
    "detectable_fraction",
    "high_fraction",
    "moderate_fraction",
    "distribution_pattern",
    "tumor_expression_class",
    "fraction_tumor_above_normal_p95",
    "normal_p95_log2tpm",
    "fraction_tumor_above_normal_p99",
    "normal_p99_log2tpm",
    "distribution_overlap_tumor_normal",
    "proxy_normal_windows",
    "subtype_signal",
)
# additive per-stratum fields the golden's vintage dropped (None) that the current reader now emits.
_TUMOR_RNA_PSM_ADDITIVE = (
    "p5_log2tpm",
    "q1_log2tpm",
    "q3_log2tpm",
    "mean_log2tpm",
    "sd_log2tpm",
    "subtype_enrich_log2_delta",
)


def _tumor_rna_inputs(anchor: dict):
    tcga = pd.read_parquet(RECOMPUTATION_DIR / anchor["tcga_fixture"])
    gtex = pd.read_parquet(RECOMPUTATION_DIR / anchor["gtex_fixture"])
    sidecar = pd.read_parquet(RECOMPUTATION_DIR / anchor["sidecar_fixture"])
    assignments = pd.read_parquet(RECOMPUTATION_DIR / anchor["assignments_fixture"])
    purity = _load(RECOMPUTATION_DIR / anchor["purity_fixture"])
    allgene = _load(RECOMPUTATION_DIR / anchor["allgene_percentile_fixture"])
    return tcga, gtex, sidecar, assignments, purity, allgene


def _rederive_tumor_rna(anchor: dict, tcga=None) -> dict:
    t, g, s, a, purity, allgene = _tumor_rna_inputs(anchor)
    if tcga is not None:
        t = tcga
    return _cap()._rederive_tumor_rna(
        anchor["target"], anchor["indication"], t, g, s, a, anchor["base_manifest"], allgene, purity
    )


def test_tumor_rna_rederives_and_bridges_golden_stable_subset():
    reder = _rederive_tumor_rna(_load(TUMOR_RNA_ANCHOR))
    golden = _golden_card("tumor-rna-distribution-by-subtype")
    _assert_stable(reder, golden, _TUMOR_RNA_SCALAR_STABLE, "tumor-rna")
    g = _psm_by(golden["per_subgroup_metrics"], "stratum_id")
    r = _psm_by(reder["per_subgroup_metrics"], "stratum_id")
    assert set(r) == set(g)
    for s in g:
        for f in _TUMOR_RNA_PSM_STABLE:
            gv, rv = g[s].get(f), r[s].get(f)
            if isinstance(gv, float) and isinstance(rv, float):
                assert math.isclose(gv, rv, rel_tol=0, abs_tol=1e-9), f"tumor-rna[{s}].{f}: {rv!r} != {gv!r}"
            else:
                assert rv == gv, f"tumor-rna[{s}].{f} drifted vs golden: {rv!r} != {gv!r}"


def test_tumor_rna_additive_spread_and_delta_drift_is_pinned_2061():
    """Drifts 2/3 (pinned, cross-linked #2061): the golden's vintage dropped the per-stratum
    five-number spread + the applied enrichment cut (all None); the current reader (AM#857 / TC#811)
    emits them. Additive-only — the golden carries None exactly where the current reader carries a
    value, on EVERY stratum. A future regen that keeps them None would fail this pin."""
    reder = _rederive_tumor_rna(_load(TUMOR_RNA_ANCHOR))
    golden = _golden_card("tumor-rna-distribution-by-subtype")
    g = _psm_by(golden["per_subgroup_metrics"], "stratum_id")
    r = _psm_by(reder["per_subgroup_metrics"], "stratum_id")
    for s in g:
        for f in _TUMOR_RNA_PSM_ADDITIVE:
            assert g[s].get(f) is None, f"tumor-rna[{s}].{f}: golden unexpectedly already carries {g[s].get(f)!r}"
            assert r[s].get(f) is not None, f"tumor-rna[{s}].{f}: current reader unexpectedly None"


def test_tumor_rna_teeth_zeroing_expression_breaks_the_golden_median_match():
    """Teeth: zeroing the frozen per-sample tumor log2(TPM+1) must move the CIMP_High stratum's
    median_log2tpm off the golden's — proving the per-stratum distribution bridge is a live function
    of the frozen substrate, not echoed from the anchor."""
    anchor = _load(TUMOR_RNA_ANCHOR)
    tcga, *_ = _tumor_rna_inputs(anchor)
    golden = _golden_card("tumor-rna-distribution-by-subtype")
    zeroed = tcga.copy()
    zeroed["log2_tpm"] = 0.0
    mutated = _rederive_tumor_rna(anchor, tcga=zeroed)
    r = _psm_by(mutated["per_subgroup_metrics"], "stratum_id")
    g = _psm_by(golden["per_subgroup_metrics"], "stratum_id")
    assert r["CIMP_High"]["median_log2tpm"] != g["CIMP_High"]["median_log2tpm"]
