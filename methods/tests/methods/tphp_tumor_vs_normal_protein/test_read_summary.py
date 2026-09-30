"""Credential-less tests for the TPHP tumor-vs-adjacent-normal PROTEIN reader.

No S3: a synthetic local per-cohort parquet (the derived product's schema — gene_symbol, uniprot_ac,
cohort, tissue, n_tumor, n_normal, median_log2_tumor, median_log2_normal, log2_fc, p_value, q_value,
effect) is read via the `product_path` offline seam. Pins:
  * the emitted summary carries EVERY field the tumor-vs-normal-protein-abundance-tphp card declares
    (the reader-real-field-names drift class the tumor-selectivity replay exists to catch);
  * the CPTAC-ALIGNED field names (protein_effect_size / protein_bh_q_value) the tumor-selectivity
    run.py `_rna_protein_tvn_concordance` projection consumes are present + carry the product values;
  * INDICATION_TO_TPHP_COHORT resolves an OncoTree/TCGA code → the matching free-text cohort;
  * a supplied-but-UNMAPPED indication → data_unavailable (never leaks another cohort's contrast);
  * no-indication → the largest-|effect_size| cohort row (pan-cancer / target-only);
  * a gene with NO rows → data_unavailable (a genuine coverage gap, absence discipline);
  * a genuine 404-class fault → data_unavailable + _live_read_error (never crashes the compose path);
  * a transient/creds error is RE-RAISED (never masked as an empty protein footprint).
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pandas as pd
import pytest

read = importlib.import_module("onc_methods.tphp_tumor_vs_normal_protein.read")

# The fields the tumor-vs-normal-protein-abundance-tphp card declares in outputs.summary_fields — the
# reader MUST emit all of them (the drift guard). Kept explicit so a card/reader divergence fails HERE.
_CARD_SUMMARY_FIELDS = {
    "cohort",
    "tissue",
    "protein_expression_class",
    "protein_effect_size",
    "protein_median_log2_tumor",
    "protein_median_log2_normal",
    "protein_p_value",
    "protein_bh_q_value",
    "n_tumor_samples",
    "n_normal_samples",
    "uniprot_ac",
    "stat_test_used",
    "method_version",
}
_EFFECT_VOCAB = {"strong_up", "modest_up", "unchanged", "modest_down", "strong_down", "data_unavailable"}

# v2 fields the reader emits that the CARD DOES NOT DECLARE YET (added by the contracts leg). Held
# separately from _CARD_SUMMARY_FIELDS so a reader/card divergence stays visible rather than being
# absorbed into the subset assertion.
_V2_DECLARATION_FIELDS = {
    "n_tumor_samples_total",
    "n_normal_samples_total",
    "protein_detection_rate_tumor",
    "protein_detection_rate_normal",
    "protein_detection_complete",
    "normal_arm_source",
    "cohort_pick_basis",
}

_COLS = [
    "gene_symbol",
    "uniprot_ac",
    "cohort",
    "tissue",
    "normal_arm_source",
    "n_tumor",
    "n_normal",
    "n_tumor_total",
    "n_normal_total",
    "detection_rate_tumor",
    "detection_rate_normal",
    "detection_complete",
    "median_log2_tumor",
    "median_log2_normal",
    "log2_fc",
    "p_value",
    "q_value",
    "effect",
]


def _row(
    gene,
    cohort,
    tissue,
    log2_fc,
    effect,
    q=0.001,
    n_tumor=40,
    n_normal=6,
    med_t=None,
    med_n=None,
    uac="P40199",
    n_tumor_total=None,
    n_normal_total=None,
    normal_arm_source="body_atlas_same_organism_part",
):
    """One product row. Detection defaults to COMPLETE (arm totals == detected counts) so a test that
    wants censoring has to ask for it explicitly — the censored state is the interesting one to pin."""
    med_n = 5.0 if med_n is None else med_n
    med_t = (med_n + log2_fc) if med_t is None else med_t
    n_tumor_total = n_tumor if n_tumor_total is None else n_tumor_total
    n_normal_total = n_normal if n_normal_total is None else n_normal_total
    return {
        "gene_symbol": gene,
        "uniprot_ac": uac,
        "cohort": cohort,
        "tissue": tissue,
        "normal_arm_source": normal_arm_source,
        "n_tumor": n_tumor,
        "n_normal": n_normal,
        "n_tumor_total": n_tumor_total,
        "n_normal_total": n_normal_total,
        "detection_rate_tumor": n_tumor / n_tumor_total,
        "detection_rate_normal": n_normal / n_normal_total,
        "detection_complete": bool(n_tumor == n_tumor_total and n_normal == n_normal_total),
        "median_log2_tumor": med_t,
        "median_log2_normal": med_n,
        "log2_fc": log2_fc,
        "p_value": q / 2.0,
        "q_value": q,
        "effect": effect,
    }


def _write_product(tmp_path, rows) -> Path:
    df = pd.DataFrame(rows, columns=_COLS)
    p = tmp_path / "tphp_tvn.parquet"
    df.to_parquet(p, index=False)
    return p


def _fixture(tmp_path):
    # CEACAM5 across three cohorts; strongest tumor-up in Colon carcinoma (log2fc=3.0). Plus a
    # background gene so the pushdown must actually filter on gene_symbol.
    rows = [
        _row("CEACAM5", "Colon carcinoma", "colon", 3.0, "strong_up", q=1e-6),
        _row("CEACAM5", "Rectum carcinoma", "rectum", 2.2, "strong_up", q=1e-4),
        _row("CEACAM5", "Gastric carcinoma", "stomach", 0.4, "unchanged", q=0.30),
        _row("BRAF", "Colon carcinoma", "colon", 0.1, "unchanged", q=0.8, uac="P15056"),
    ]
    return _write_product(tmp_path, rows)


def test_summary_shape_matches_card_and_cptac_aligned(tmp_path):
    prod = _fixture(tmp_path)
    out = read.read_target_summary("CEACAM5", indication="COADREAD", product_path=prod)

    missing = _CARD_SUMMARY_FIELDS - set(out)
    assert not missing, f"reader is missing card-declared summary_fields: {sorted(missing)}"
    # COADREAD → "Colon carcinoma" (mirrors the CPTAC COADREAD→COAD choice)
    assert out["cohort"] == "Colon carcinoma"
    assert out["tissue"] == "colon"
    assert out["protein_expression_class"] in _EFFECT_VOCAB
    assert out["protein_expression_class"] == "strong_up"
    # CPTAC-ALIGNED names carry the product's log2_fc / q_value (the projection consumes these).
    assert out["protein_effect_size"] == 3.0
    assert out["protein_bh_q_value"] == pytest.approx(1e-6)
    assert out["protein_median_log2_tumor"] == pytest.approx(8.0)
    assert out["protein_median_log2_normal"] == pytest.approx(5.0)
    assert out["n_tumor_samples"] == 40
    assert out["n_normal_samples"] == 6
    assert out["uniprot_ac"] == "P40199"
    assert out["stat_test_used"] == read.STAT_TEST
    assert out["method_version"] == read.METHOD_VERSION


def test_cptac_aligned_fields_feed_concordance_projection(tmp_path):
    """The two keys the tumor-selectivity `_rna_protein_tvn_concordance(rna_dir, effect, q)` projection
    reads — protein_effect_size + protein_bh_q_value — must be present + non-null on a real cohort so
    the SAME projection that runs over the CPTAC card summary consumes THIS card unchanged."""
    prod = _fixture(tmp_path)
    out = read.read_target_summary("CEACAM5", indication="READ", product_path=prod)
    assert out["cohort"] == "Rectum carcinoma"
    assert out["protein_effect_size"] is not None and out["protein_bh_q_value"] is not None
    # sign + significance the projection keys on: q<0.05, effect>0 → would read concordant with RNA-up.
    assert out["protein_effect_size"] > 0 and out["protein_bh_q_value"] < 0.05


def test_unmapped_indication_is_data_unavailable_no_leak(tmp_path):
    """A supplied-but-unmapped indication must NOT leak another cohort's contrast (the product is a
    PER-COHORT differential). BRCA has no unambiguous single TPHP cohort → data_unavailable."""
    prod = _fixture(tmp_path)
    out = read.read_target_summary("CEACAM5", indication="BRCA", product_path=prod)
    assert out["protein_expression_class"] == "data_unavailable"
    assert out["cohort"] is None
    assert out["protein_effect_size"] is None
    assert _CARD_SUMMARY_FIELDS <= set(out)


def test_no_indication_returns_best_effect_cohort(tmp_path):
    """Target-only / pan-cancer query (no indication) → the largest-|effect_size| cohort row."""
    prod = _fixture(tmp_path)
    out = read.read_target_summary("CEACAM5", product_path=prod)
    assert out["cohort"] == "Colon carcinoma"  # |3.0| is the max across the three cohorts
    assert out["protein_effect_size"] == 3.0


def test_gene_absent_is_data_unavailable(tmp_path):
    prod = _fixture(tmp_path)
    out = read.read_target_summary("GHOSTGENE", indication="COADREAD", product_path=prod)
    assert out["protein_expression_class"] == "data_unavailable"
    assert out["cohort"] is None
    assert _CARD_SUMMARY_FIELDS <= set(out)


def test_target_absent_from_mapped_cohort_is_data_unavailable(tmp_path):
    """Gene present in the product but NOT quantified in the mapped cohort → data_unavailable (honest;
    the gene's rows exist for other cohorts but not the queried one)."""
    prod = _fixture(tmp_path)
    out = read.read_target_summary("CEACAM5", indication="GBM", product_path=prod)  # no Glioblastoma row
    assert out["protein_expression_class"] == "data_unavailable"
    assert "cohort" in out


def test_read_all_cohorts_sorted_by_abs_effect(tmp_path):
    prod = _fixture(tmp_path)
    panel = read.read_all_cohorts("CEACAM5", product_path=prod)
    assert [r["cohort"] for r in panel] == ["Colon carcinoma", "Rectum carcinoma", "Gastric carcinoma"]
    assert panel[0]["protein_effect_size"] == 3.0


def test_indication_map_values_are_verbatim_cohorts():
    """Every mapped cohort string must be one of the product's real cohort names (guards a typo in the
    free-text map — enumerated from S3 2026-08-25)."""
    real_cohorts = {
        "Breast carcinoma (Luminal A)",
        "Breast carcinoma (Luminal B, HER2-)",
        "Breast carcinoma (TNBC)",
        "Cervical carcinoma",
        "Colon carcinoma",
        "Diffused large B-cell carcinoma",
        "Endometrial carcinoma",
        "Esophageal carcinoma",
        "Fallopian tube carcinoma",
        "Gallbladder carcinoma",
        "Gastric carcinoma",
        "Gastrointestinal stromal tumors",
        "Glioblastoma",
        "Hepatocellular carcinoma",
        "Laryngocarcinoma",
        "Lung carcinoma",
        "Pancreas carcinoma",
        "Rectum carcinoma",
        "Renal carcinoma",
        "Testis carcinoma",
        "Thymoma and thymic carcinoma",
        "Tongue carcinoma",
    }
    unknown = set(read.INDICATION_TO_TPHP_COHORT.values()) - real_cohorts
    assert not unknown, f"INDICATION_TO_TPHP_COHORT maps to non-existent cohort(s): {sorted(unknown)}"


# ── v2: detection censoring is DECLARED, and the pan-cancer pick gates on it ──────────────────────
# The product's n_tumor / n_normal are DETECTED counts. Incompleteness INFLATES |log2_fc| (median
# log2_fc -0.055 with a fully-detected tumour arm vs -0.860 below 50% detected), so a bare
# max-|log2_fc| pan-cancer pick selects the most CENSORED cohort by construction.


def test_v2_declaration_fields_present_in_both_paths(tmp_path):
    """The completeness/provenance fields appear on the populated AND the data_unavailable path, so a
    consumer gating on protein_detection_complete never hits a missing key."""
    prod = _fixture(tmp_path)
    populated = read.read_target_summary("CEACAM5", indication="COADREAD", product_path=prod)
    empty = read.read_target_summary("GHOSTGENE", indication="COADREAD", product_path=prod)
    for out, label in ((populated, "populated"), (empty, "data_unavailable")):
        missing = _V2_DECLARATION_FIELDS - set(out)
        assert not missing, f"{label} summary is missing v2 declaration fields: {sorted(missing)}"
    # None, NOT False, on the gap path: an unread row is not a censored row, and `if not complete`
    # must not read a coverage gap as a measured-but-censored contrast.
    assert empty["protein_detection_complete"] is None
    assert empty["cohort_pick_basis"] is None


def test_detection_totals_and_rates_pass_through(tmp_path):
    """v1 shipped detected counts with NO denominator, so completeness was unreconstructable downstream.
    The arm TOTALS and rates must reach the summary as the product's own values."""
    rows = [
        _row(
            "G",
            "Colon carcinoma",
            "large intestine",
            1.2,
            "strong_up",
            n_tumor=30,
            n_normal=6,
            n_tumor_total=45,
            n_normal_total=13,
        )
    ]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("G", indication="COADREAD", product_path=prod)
    assert out["n_tumor_samples"] == 30 and out["n_tumor_samples_total"] == 45
    assert out["n_normal_samples"] == 6 and out["n_normal_samples_total"] == 13
    assert out["protein_detection_rate_tumor"] == pytest.approx(30 / 45)
    assert out["protein_detection_rate_normal"] == pytest.approx(6 / 13)
    assert out["protein_detection_complete"] is False


def test_pan_cancer_pick_prefers_detection_complete(tmp_path):
    """★ The censored cohort has the LARGEST |log2_fc| (-4.0, one third of its arms detected) and must
    NOT be returned; the smaller but fully-detected +1.5 contrast wins, with the basis naming the
    population it came from.

    This is the artifact the old bare max() maximised: over the whole product, 4,431 genes have >=1
    complete row and this changes the returned cohort for 2,201 of them (49.7%), flipping the SIGN for
    470. Reverting to `max(rows, key=abs(log2_fc))` fails here."""
    rows = [
        _row(
            "G",
            "Esophageal carcinoma",
            "esophagus",
            -4.0,
            "strong_down",
            n_tumor=12,
            n_normal=3,
            n_tumor_total=38,
            n_normal_total=8,
        ),
        _row("G", "Gallbladder carcinoma", "gallbladder", 1.5, "strong_up", n_tumor=10, n_normal=5),
        _row(
            "G",
            "Gastric carcinoma",
            "stomach",
            -2.0,
            "strong_down",
            n_tumor=9,
            n_normal=4,
            n_tumor_total=62,
            n_normal_total=16,
        ),
    ]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("G", product_path=prod)
    assert out["cohort"] == "Gallbladder carcinoma"
    assert out["protein_effect_size"] == 1.5
    assert out["protein_detection_complete"] is True
    assert out["cohort_pick_basis"] == read.PICK_PAN_COMPLETE
    # and the direction is the OPPOSITE of what the censored extremum would have reported
    assert out["protein_expression_class"] == "strong_up"


def test_pan_cancer_falls_back_when_no_complete_row_exists(tmp_path):
    """58.1% of genes have NO detection-complete row in ANY cohort. Those must still get an answer —
    filtering here would blank most of the facet — but the basis has to SAY the pick came from the
    censored population so a directional consumer can discount it."""
    rows = [
        _row(
            "G",
            "Esophageal carcinoma",
            "esophagus",
            -4.0,
            "strong_down",
            n_tumor=12,
            n_normal=3,
            n_tumor_total=38,
            n_normal_total=8,
        ),
        _row(
            "G",
            "Gastric carcinoma",
            "stomach",
            -2.0,
            "strong_down",
            n_tumor=9,
            n_normal=4,
            n_tumor_total=62,
            n_normal_total=16,
        ),
    ]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("G", product_path=prod)
    assert out["protein_expression_class"] != "data_unavailable"
    assert out["cohort"] == "Esophageal carcinoma"
    assert out["cohort_pick_basis"] == read.PICK_PAN_ANY
    assert out["protein_detection_complete"] is False


def test_indication_path_never_drops_a_censored_cohort(tmp_path):
    """The indication-mapped cohort is returned even when its arms are censored — dropping it would
    turn a measured-but-noisy contrast into a coverage gap. Completeness is SURFACED, not enforced."""
    rows = [
        _row(
            "G",
            "Colon carcinoma",
            "large intestine",
            -0.6,
            "unchanged",
            n_tumor=32,
            n_normal=7,
            n_tumor_total=45,
            n_normal_total=13,
        ),
        _row("G", "Gallbladder carcinoma", "gallbladder", 2.5, "strong_up", n_tumor=10, n_normal=5),
    ]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("G", indication="COADREAD", product_path=prod)
    assert out["cohort"] == "Colon carcinoma"
    assert out["protein_detection_complete"] is False
    assert out["cohort_pick_basis"] == read.PICK_INDICATION


def test_normal_arm_source_is_read_from_the_product_not_hardcoded(tmp_path):
    """The normal arm is the BODY ATLAS of the tumour's organism part — the same samples the TPHP
    normal-tissue product summarises — so this facet is NOT independent of that atlas. The reader must
    pass the product's VALUE through, so a consumer testing platform independence keys on the value
    instead of maintaining a product-id allowlist. A different value must survive the read."""
    rows = [
        _row("G", "Colon carcinoma", "large intestine", 1.0, "strong_up", normal_arm_source="matched_adjacent_normal")
    ]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("G", indication="COADREAD", product_path=prod)
    assert out["normal_arm_source"] == "matched_adjacent_normal"

    rows2 = [_row("H", "Colon carcinoma", "large intestine", 1.0, "strong_up")]
    prod2 = _write_product(tmp_path, rows2)
    out2 = read.read_target_summary("H", indication="COADREAD", product_path=prod2)
    assert out2["normal_arm_source"] == "body_atlas_same_organism_part"


def test_stat_test_literal_names_the_body_atlas_not_an_adjacent_normal(tmp_path):
    """`stat_test_used` must NOT spell the normal arm "adjacent_normal" — TPHP collected no adjacent-
    normal series, so that name asserted a study design that does not exist (and it said so on every row
    of a 128,708-row product). This is STEP 2 of the forward-rename alias window: target-contracts #764
    declared BOTH tokens first, so this emitter flip cannot fail closed on the card vocabulary; the
    DEPRECATED alias is dropped only after the two skills fixtures re-pin (step 3).

    This test replaces test_stat_test_literal_is_deliberately_left_wrong, which pinned the false literal
    as a RECORDED decision and said in its own docstring that the rename belonged to the contracts leg.
    That leg has landed, so the recorded decision is discharged rather than deleted — the assertion now
    guards the rename in the other direction, against a revert to the false name."""
    assert read.STAT_TEST == "welch_unpaired_tumor_vs_body_atlas_normal_same_organism_part"
    prod = _fixture(tmp_path)
    out = read.read_target_summary("CEACAM5", indication="COADREAD", product_path=prod)
    assert out["stat_test_used"] == read.STAT_TEST
    assert out["normal_arm_source"] == "body_atlas_same_organism_part"
    # the FALSE design claim must not survive anywhere in the emitted summary — not just in the one key
    # this test pins. `adjacent` is the load-bearing substring: it is the study design that never existed.
    leaked = {k: v for k, v in out.items() if isinstance(v, str) and "adjacent" in v}
    assert not leaked, f"emitted values still claim an adjacent normal: {leaked}"


def test_non_finite_effect_never_wins_the_argmax(tmp_path):
    """±Inf is a NUMBER: abs(inf) wins every max() and NaN makes max() order-dependent, so one
    degenerate row would capture the pan-cancer pick and the top of the panel. The product should never
    contain one — which is exactly why the guard needs a test rather than a comment."""
    rows = [
        _row("G", "Colon carcinoma", "large intestine", float("inf"), "strong_up"),
        _row("G", "Gallbladder carcinoma", "gallbladder", 1.5, "strong_up"),
        _row("G", "Gastric carcinoma", "stomach", float("nan"), "unchanged"),
    ]
    prod = _write_product(tmp_path, rows)
    out = read.read_target_summary("G", product_path=prod)
    assert out["cohort"] == "Gallbladder carcinoma"
    assert read.read_all_cohorts("G", product_path=prod)[0]["cohort"] == "Gallbladder carcinoma"


def test_panel_rows_carry_no_pick_basis(tmp_path):
    """read_all_cohorts returns EVERY cohort, so nothing was 'picked' — cohort_pick_basis is None and
    per-row completeness rides on protein_detection_complete instead."""
    prod = _fixture(tmp_path)
    panel = read.read_all_cohorts("CEACAM5", product_path=prod)
    assert panel and all(r["cohort_pick_basis"] is None for r in panel)
    assert all(r["protein_detection_complete"] is not None for r in panel)


def test_definitive_absence_degrades_not_crashes(monkeypatch):
    """A genuine 404-class fault → data_unavailable + _live_read_error (honest degrade)."""

    def _boom(*a, **k):
        raise FileNotFoundError("no such key")

    monkeypatch.setattr(read, "_read_rows_from_derived", _boom)
    out = read.read_target_summary("CEACAM5", indication="COADREAD")
    assert out["_live_read_error"] == "tphp_tumor_vs_normal_protein_read_failed"
    assert out["protein_expression_class"] == "data_unavailable"
    assert out["method_version"] == read.METHOD_VERSION


def test_transient_fault_is_reraised(monkeypatch):
    """A transient / non-definitive error must NOT be masked as an empty protein footprint — re-raise
    so the live-read seam surfaces the infra failure (absence discipline)."""

    def _boom(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(read, "_read_rows_from_derived", _boom)
    with pytest.raises(RuntimeError):
        read.read_target_summary("CEACAM5", indication="COADREAD")
