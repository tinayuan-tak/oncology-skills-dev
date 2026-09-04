"""Tests for sc_normal_expression — pure stats + monkeypatched assembler.

Mirrors tests/methods/sc_tumor_expression_celltype/test_stats_and_assembler.py structure:
  - stats primitives tested purely (synthetic Tier-1 DataFrame, no S3);
  - S3 boundary (read_gene_celltype_rows) monkeypatched, never hit;
  - data_unavailable safety branches (no product, gene absent, low donors) asserted;
  - safety-essential cell type flagging asserted.
"""
from __future__ import annotations

import pytest
import pandas as pd

pytest.importorskip("numpy")
pytest.importorskip("pandas")

from methods.sc_normal_expression import stats as S
from methods.sc_normal_expression import read as R
from methods.sc_normal_expression import cli as C


# --- fixtures ----------------------------------------------------------------

def _tier1_rows(spec, tissue: str = "colon") -> pd.DataFrame:
    """Build a Tier-1-shaped DataFrame.
    spec: list of (cell_type, n_donors_reliable, median_det, expressing_donor_fraction)
    tissue: the origin tissue label for all rows (default 'colon'; override for organ-aware tests).
    New schema columns (n_datasets_reliable, q25_abund, q25_det) filled with sensible defaults.
    """
    return pd.DataFrame([
        {
            "gene_symbol": "EPCAM",
            "ensembl_gene_id": "ENSG00000119888",
            "tissue": tissue,
            "cell_type": ct,
            "n_donors_total": n,
            "n_donors_reliable": n,
            "n_datasets_reliable": max(1, n // 5),  # reasonable default: ~1 dataset per 5 donors
            "n_donors_expressing": max(0, n - 2),
            "median_det": med,
            "q25_det": med * 0.7,
            "q75_det": med * 1.3,
            "expressing_donor_fraction": frac,
            "median_abund": med * 3.0,
            "q25_abund": med * 2.0,
            "q75_abund": med * 4.0,
            "detection_pct_rank": 0.5,
            "n_cell_types_above_20pct": 0,
        }
        for (ct, n, med, frac) in spec
    ])


# --- classify_sc_normal_expression: liability ladder -------------------------

def test_classify_high_liability():
    """Any cell type exceeding BOTH thresholds → HIGH_LIABILITY."""
    rows = _tier1_rows([
        ("colonocyte",   20, 0.85, 0.90),   # well above HIGH thresholds
        ("fibroblast",   15, 0.10, 0.20),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "HIGH_LIABILITY"
    assert r["max_detection_cell_type"] == "colonocyte"
    assert r["max_detection_fraction"] == pytest.approx(0.85)


def test_classify_high_liability_reports_triggering_cell_not_global_argmax():
    """The cell type with highest raw detection may not be the one that fired HIGH_LIABILITY.
    When Cell A has det=0.85 (fails AND: frac=0.40 < 0.70) and Cell B has det=0.55 (passes AND:
    frac=0.80 > 0.70), HIGH fires and max_detection_cell_type must be Cell B, not Cell A."""
    rows = _tier1_rows([
        ("fibroblast",   20, 0.85, 0.40),   # highest det but fails AND (frac below threshold)
        ("colonocyte",   20, 0.55, 0.80),   # lower det but BOTH thresholds met → fires HIGH
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "HIGH_LIABILITY"
    assert r["max_detection_cell_type"] == "colonocyte"   # the triggering cell, not the argmax
    assert r["max_detection_fraction"] == pytest.approx(0.55)


def test_safety_essential_flags_excludes_near_zero_values():
    """Entries with median_det <= 0.05 (census annotation noise) must NOT appear in safety flags."""
    rows = _tier1_rows([
        ("hepatocyte",   10, 0.03, 0.10),   # essential but below noise floor — must be excluded
        ("fibroblast",   10, 0.50, 0.60),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert "hepatocyte" not in r["safety_essential_flags"]
    # no safety-essential cell above floor → categorical companion is 'none' (not vetoing)
    assert r["sc_normal_safety_essential_class"] == "none"


def test_is_safety_essential_whole_token_not_substring():
    """W3a: `_is_safety_essential` matches a lineage token wherever it stands as a whole word, but
    must NOT match a longer word that merely embeds the token. 'neuron' → real neurons, NOT the
    'neuronal'-prefixed non-neuron labels that the old `pfx in ct` substring test wrongly flagged."""
    # TRUE positives (token appears as a standalone word):
    assert S._is_safety_essential("neuron")
    assert S._is_safety_essential("dopaminergic neuron")
    assert S._is_safety_essential("central nervous system neuron")
    assert S._is_safety_essential("cardiac muscle cell")
    assert S._is_safety_essential("kidney loop of Henle thick ascending limb epithelial cell")
    # FALSE positives the substring test produced — must now be rejected:
    assert not S._is_safety_essential("non-neuronal cell")
    assert not S._is_safety_essential("neuronal-restricted precursor")  # real Census label
    # a cell type sharing no essential token stays unflagged
    assert not S._is_safety_essential("fibroblast")


def test_safety_essential_class_ignores_neuronal_substring_false_match():
    """End-to-end: a gene detected ONLY in 'neuronal-restricted precursor' (off-origin brain) must
    NOT be flagged essential — the substring 'neuron' no longer flips the safety-essential class."""
    rows = _tier1_rows([("neuronal-restricted precursor", 10, 0.60, 0.80)], tissue="brain")
    r = S.classify_sc_normal_expression(rows, origin_tissues=["colon"])
    assert "neuronal-restricted precursor" not in r["safety_essential_flags"]
    assert r["sc_normal_safety_essential_class"] == "none"


def test_safety_essential_class_critical_organ_vs_origin_tissue():
    """ORGAN-AWARE veto instrument: an essential-cell hit in a NON-origin critical organ →
    critical_organ_liability (hard veto); essential hits ONLY in the tissue-of-origin →
    origin_tissue_liability (soft, therapeutic-window-arbitrated). The FOLR1/TNNT2 discriminator."""
    # hepatocyte (liver) is a critical off-target organ for a LUNG tumor → hard-veto class
    rows_liver = _tier1_rows([("hepatocyte", 10, 0.30, 0.60)], tissue="liver")
    r = S.classify_sc_normal_expression(rows_liver, origin_tissues=["lung"])
    assert r["sc_normal_safety_essential_class"] == "critical_organ_liability"
    # pneumocyte (lung) essential expression when the tumor IS lung → origin-tissue only (soft)
    rows_lung = _tier1_rows([("pulmonary alveolar type 1 cell", 10, 0.60, 0.70)], tissue="lung")
    r2 = S.classify_sc_normal_expression(rows_lung, origin_tissues=["lung"])
    assert r2["sc_normal_safety_essential_class"] == "origin_tissue_liability"
    # off_origin dominates: a gene hitting BOTH lung(origin) AND heart(critical) → critical
    rows_both = _tier1_rows([("pulmonary alveolar type 1 cell", 10, 0.60, 0.70)], tissue="lung") \
              + _tier1_rows([("cardiac muscle cell", 10, 0.90, 0.90)], tissue="heart")
    r3 = S.classify_sc_normal_expression(rows_both, origin_tissues=["lung"])
    assert r3["sc_normal_safety_essential_class"] == "critical_organ_liability"


def test_safety_essential_flags_includes_above_floor():
    """Entries above the 0.05 flag floor appear in safety_essential_flags for transparency — but a
    marginal off-origin hit (0.08, below the 0.20 off-origin critical floor) does NOT flip to
    critical_organ_liability (the 2026-09-04 ambient-noise floor). A det=0.30 hit DOES."""
    rows = _tier1_rows([
        ("hepatocyte",   10, 0.08, 0.20),   # above 0.05 flag floor, below 0.20 off-origin critical floor
        ("fibroblast",   10, 0.05, 0.10),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert "hepatocyte" in r["safety_essential_flags"]                 # recorded for transparency
    assert r["safety_essential_flags"]["hepatocyte"] == pytest.approx(0.08)
    assert r["sc_normal_safety_essential_class"] == "none"             # sub-floor off-origin does NOT flip
    # a hepatocyte hit ABOVE the 0.20 floor with no origin passed → off-origin critical (conservative)
    r2 = S.classify_sc_normal_expression(_tier1_rows([("hepatocyte", 10, 0.30, 0.45)]))
    assert r2["sc_normal_safety_essential_class"] == "critical_organ_liability"


def test_classify_moderate_liability_by_det():
    """A cell type above MODERATE_LIABILITY_DET (0.20) but below HIGH threshold → MODERATE."""
    rows = _tier1_rows([
        ("enterocyte",   10, 0.35, 0.25),   # med_det > 0.20, frac < 0.30
        ("fibroblast",   10, 0.05, 0.10),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "MODERATE_LIABILITY"


def test_classify_moderate_liability_by_donor_fraction():
    """A cell type with frac > 0.30 but med_det < 0.20 → MODERATE (OR logic)."""
    rows = _tier1_rows([
        ("plasma cell",  8, 0.15, 0.55),    # frac > 0.30 triggers moderate
        ("fibroblast",  10, 0.04, 0.10),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "MODERATE_LIABILITY"


def test_classify_low_liability():
    rows = _tier1_rows([
        ("colonocyte",   12, 0.08, 0.15),   # above NOT_EXPRESSED but below MODERATE
        ("fibroblast",   12, 0.03, 0.05),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "LOW_LIABILITY"


def test_classify_not_expressed():
    """All cell types below NOT_EXPRESSED_CEILING → NOT_EXPRESSED."""
    rows = _tier1_rows([
        ("colonocyte",   20, 0.005, 0.02),
        ("fibroblast",   20, 0.003, 0.01),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "NOT_EXPRESSED"


def test_classify_data_unavailable_low_donors():
    """All n_donors_reliable < MIN_RELIABLE_DONORS → data_unavailable."""
    rows = _tier1_rows([
        ("colonocyte",  3, 0.90, 0.95),   # very high detection but n_donors < 5
        ("fibroblast",  2, 0.05, 0.10),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "data_unavailable"
    assert "_data_note" in r


def test_classify_empty_dataframe_is_data_unavailable():
    r = S.classify_sc_normal_expression(pd.DataFrame())
    assert r["sc_normal_expression_class"] == "data_unavailable"


def test_classify_none_is_data_unavailable():
    r = S.classify_sc_normal_expression(None)
    assert r["sc_normal_expression_class"] == "data_unavailable"


# --- safety-essential cell type flagging -------------------------------------

def test_safety_essential_flags_cardiomyocyte():
    rows = _tier1_rows([
        ("cardiomyocyte", 15, 0.40, 0.55),  # above LOW, essential cell type
        ("fibroblast",    15, 0.05, 0.10),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert "cardiomyocyte" in r["safety_essential_flags"]
    assert r["safety_essential_flags"]["cardiomyocyte"] == pytest.approx(0.40)


def test_safety_essential_flags_hepatocyte():
    rows = _tier1_rows([
        ("hepatocyte",   20, 0.30, 0.45),
        ("colonocyte",   20, 0.02, 0.05),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert "hepatocyte" in r["safety_essential_flags"]


def test_safety_essential_flags_empty_when_no_essential():
    rows = _tier1_rows([
        ("fibroblast",   15, 0.05, 0.10),
        ("B cell",       15, 0.03, 0.08),
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["safety_essential_flags"] == {}


# --- n_cell_types_above_20pct from classify ----------------------------------

def test_n_cell_types_above_20pct_count():
    rows = _tier1_rows([
        ("colonocyte",   10, 0.55, 0.70),   # > 0.20
        ("enterocyte",   10, 0.35, 0.40),   # > 0.20
        ("fibroblast",   10, 0.08, 0.15),   # <= 0.20
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["n_cell_types_above_20pct"] == 2


# --- read.py with monkeypatched S3 -------------------------------------------

def test_read_target_summary_full_path(monkeypatch):
    rows = _tier1_rows([
        ("colonocyte",   20, 0.85, 0.90),
        ("fibroblast",   15, 0.10, 0.20),
    ])
    monkeypatch.setattr(R, "read_gene_celltype_rows", lambda t, ts: rows)
    out = R.read_target_summary("EPCAM", "COADREAD")
    assert out["sc_normal_expression_class"] == "HIGH_LIABILITY"
    assert out["indication"] == "COADREAD"
    # COADREAD now queries the matched tissue (colon) UNION the always-on safety-essential tissues
    assert out["tissues_queried"] == ["colon", "heart", "liver", "kidney", "bone_marrow", "brain", "adrenal_gland", "lung", "pancreas"]


def test_read_target_summary_unknown_indication_still_reads_safety_essential(monkeypatch):
    """Unknown indication no longer abstains-by-mapping: it queries the safety-essential tissues
    (cross-tissue on-target-tox check). With a real product it would classify; here the reader is
    monkeypatched to None (no product) → data_unavailable, but tissues_queried is non-empty."""
    monkeypatch.setattr(R, "read_gene_celltype_rows", lambda t, ts: None)
    out = R.read_target_summary("EPCAM", "UNKNOWN_IND")
    assert out["sc_normal_expression_class"] == "data_unavailable"
    assert out["tissues_queried"] == ["heart", "liver", "kidney", "bone_marrow", "brain", "adrenal_gland", "lung", "pancreas"]
    assert "_data_note" in out


def test_read_target_summary_no_product(monkeypatch):
    """read_gene_celltype_rows returns None → data_unavailable."""
    monkeypatch.setattr(R, "read_gene_celltype_rows", lambda t, ts: None)
    out = R.read_target_summary("EPCAM", "COADREAD")
    assert out["sc_normal_expression_class"] == "data_unavailable"
    assert "_data_note" in out


def test_read_target_summary_gene_absent(monkeypatch):
    """Empty DataFrame (gene not in product) → data_unavailable, 'absent' note."""
    monkeypatch.setattr(R, "read_gene_celltype_rows",
                        lambda t, ts: pd.DataFrame())
    out = R.read_target_summary("MADEUPGENE99", "COADREAD")
    assert out["sc_normal_expression_class"] == "data_unavailable"
    assert "absent" in out.get("_data_note", "")


def test_tissues_for_indication_unions_matched_and_safety_essential():
    """tumor-matched tissue(s) UNION the always-on safety-essential tissues, de-duplicated."""
    # Census-backed indications. Always-on safety-essential set now includes lung + pancreas
    # (promoted 2026-08-19: pneumocyte / islet safety), de-duped against the matched tissue.
    assert R.tissues_for_indication("COADREAD") == ["colon", "heart", "liver", "kidney", "bone_marrow", "brain", "adrenal_gland", "lung", "pancreas"]
    assert R.tissues_for_indication("NSCLC") == ["lung", "heart", "liver", "kidney", "bone_marrow", "brain", "adrenal_gland", "pancreas"]
    # 3CA-backed indications added 2026-08-12
    assert R.tissues_for_indication("PAAD") == ["pancreas", "heart", "liver", "kidney", "bone_marrow", "brain", "adrenal_gland", "lung"]
    assert R.tissues_for_indication("HNSC") == ["esophagus", "heart", "liver", "kidney", "bone_marrow", "brain", "adrenal_gland", "lung", "pancreas"]
    assert R.tissues_for_indication("STAD") == ["stomach", "heart", "liver", "kidney", "bone_marrow", "brain", "adrenal_gland", "lung", "pancreas"]
    # Unknown indication → safety-essential only (never empty)
    assert R.tissues_for_indication("UNKNOWN") == ["heart", "liver", "kidney", "bone_marrow", "brain", "adrenal_gland", "lung", "pancreas"]


def test_indication_coverage_wires_orphaned_shards_and_origin_correctness():
    """2026-09-04 coverage: 3 previously-orphaned shards (bladder/skin/uterus) are now queried via an
    indication map, and origin-organ tumors (KIRC/LIHC/GBM) de-dup their origin out of the always-on set
    (front position) so it is treated as origin, not off-target."""
    # orphaned shards now reachable via an indication → prepended to the always-on set
    assert R.tissues_for_indication("BLCA")[0] == "bladder_organ"
    assert R.tissues_for_indication("SKCM")[0] == "skin"
    assert R.tissues_for_indication("UCEC")[0] == "uterus"
    # origin organ already in the always-on set → de-duped to the front, queried ONCE
    assert R.tissues_for_indication("KIRC") == ["kidney", "heart", "liver", "bone_marrow", "brain", "adrenal_gland", "lung", "pancreas"]
    assert R.tissues_for_indication("GBM") == ["brain", "heart", "liver", "kidney", "bone_marrow", "adrenal_gland", "lung", "pancreas"]


def test_kidney_origin_softens_own_organ_liability_for_renal_cancer(monkeypatch):
    """A renal target expressed in kidney tubule reads critical_organ_liability for a NON-renal tumor,
    but origin_tissue_liability for KIRC (kidney IS the tissue-of-origin) — the coverage correctness fix."""
    rows = _tier1_rows([("kidney proximal tubule epithelial cell", 12, 0.60, 0.75)], tissue="kidney")
    monkeypatch.setattr(R, "read_gene_celltype_rows", lambda t, ts: rows)
    # non-renal tumor: kidney is off-origin → hard-veto class
    assert R.read_target_summary("SOMEGENE", "COADREAD")["sc_normal_safety_essential_class"] == "critical_organ_liability"
    # renal tumor: kidney is origin → softened
    assert R.read_target_summary("SOMEGENE", "KIRC")["sc_normal_safety_essential_class"] == "origin_tissue_liability"


def test_all_tissue_products_resolve():
    """All wired tissues route to a Tier-1 product key (hyphenated slugs for multi-word tissues)."""
    for t in ["colon", "lung", "heart", "liver", "kidney", "stomach",
              "bone_marrow", "skin", "small_intestine",
              "brain", "esophagus", "pancreas", "ovary", "prostate_gland",
              # 2026-08-15: the map now covers all 19 landed normal-tissue shards
              "adrenal_gland", "bladder_organ", "large_intestine", "spleen", "uterus"]:
        assert t in R.TISSUE_TO_PRODUCT, f"{t} missing from TISSUE_TO_PRODUCT"
    assert len(R.TISSUE_TO_PRODUCT) == 19   # all landed normal-tissue shards are reachable
    assert R.TISSUE_TO_PRODUCT["bone_marrow"] == "sc-normal-celltype-expression-bone-marrow-v1"
    assert R.TISSUE_TO_PRODUCT["small_intestine"] == "sc-normal-celltype-expression-small-intestine-v1"
    assert R.TISSUE_TO_PRODUCT["brain"] == "sc-normal-celltype-expression-brain-v1"
    assert R.TISSUE_TO_PRODUCT["prostate_gland"] == "sc-normal-celltype-expression-prostate-gland-v1"
    assert R.TISSUE_TO_PRODUCT["large_intestine"] == "sc-normal-celltype-expression-large-intestine-v1"


# --- cli build_summary -------------------------------------------------------

def test_cli_build_summary_adds_method_version(monkeypatch):
    monkeypatch.setattr(R, "read_gene_celltype_rows", lambda t, ts: None)
    out = C.build_summary("EPCAM", "PAAD")
    assert out["method_version"] == C.METHOD_VERSION
    assert out["sc_normal_expression_class"] == "data_unavailable"


# --- per_cell_type_top (ranked footprint) + liability figure -----------------
def test_per_cell_type_top_ranks_and_flags_safety_essential():
    """The ranked per-cell-type footprint carries the full liability landscape (not just the argmax),
    ordered by detection descending, with safety-essential cell types flagged."""
    rows = _tier1_rows([
        ("colonocyte",     20, 0.85, 0.90),   # safety-essential (enterocyte/colonocyte lineage)
        ("cardiomyocyte",  18, 0.60, 0.75),   # safety-essential (critical organ)
        ("fibroblast",     15, 0.10, 0.20),   # not essential
    ], tissue="colon")
    top = S.classify_sc_normal_expression(rows)["per_cell_type_top"]
    assert [r["cell_type"] for r in top] == ["colonocyte", "cardiomyocyte", "fibroblast"]
    assert top[0]["median_detection_fraction"] >= top[-1]["median_detection_fraction"]
    flags = {r["cell_type"]: r["is_safety_essential"] for r in top}
    assert flags["cardiomyocyte"] is True and flags["fibroblast"] is False
    assert top[0]["tissue"] == "colon" and top[0]["n_donors_reliable"] == 20


def test_per_cell_type_top_empty_when_data_unavailable():
    assert S._data_unavailable_class()["per_cell_type_top"] == []


def test_emit_normal_celltype_liability_writes_svg(tmp_path):
    summary = S.classify_sc_normal_expression(_tier1_rows([
        ("colonocyte", 20, 0.85, 0.90), ("cardiomyocyte", 18, 0.60, 0.75),
        ("fibroblast", 15, 0.10, 0.20)], tissue="colon"))
    C.emit_normal_celltype_liability(summary, "EPCAM", tmp_path)
    svg = tmp_path / "figure_sc_normal_celltype_liability.svg"
    assert svg.exists() and svg.stat().st_size > 0
    assert svg.read_text().lstrip().startswith("<?xml") or "<svg" in svg.read_text()


def test_emit_normal_celltype_liability_noop_when_empty(tmp_path):
    C.emit_normal_celltype_liability(S._data_unavailable_class(), "EPCAM", tmp_path)
    assert not (tmp_path / "figure_sc_normal_celltype_liability.svg").exists()


# --- #984 Tier-2: normal-tissue ABUNDANCE class (at the liability-anchor cell type) ---------------

def _row(ct, n, med, frac, abund, tissue="colon"):
    return {"gene_symbol": "EPCAM", "ensembl_gene_id": "E", "tissue": tissue, "cell_type": ct,
            "n_donors_total": n, "n_donors_reliable": n, "n_datasets_reliable": max(1, n // 5),
            "n_donors_expressing": max(0, n - 2), "median_det": med, "q25_det": med * 0.7,
            "q75_det": med * 1.3, "expressing_donor_fraction": frac, "median_abund": abund,
            "q25_abund": abund * 0.8, "q75_abund": abund * 1.2, "detection_pct_rank": 0.5,
            "n_cell_types_above_20pct": 0}


def test_abundance_class_bands_high_moderate_low():
    """Bands (0.24 / 0.64) at the anchor cell type: EPCAM-like high, ERBB2-like moderate, FOLR1-like low."""
    for abund, expect in [(3.36, "high_abundance"), (0.36, "moderate_abundance"), (0.21, "low_abundance")]:
        r = S.classify_sc_normal_expression(pd.DataFrame([_row("colonocyte", 20, 0.85, 0.90, abund)]))
        assert r["sc_normal_abundance_class"] == expect, (abund, r["sc_normal_abundance_class"])
        assert r["sc_normal_peak_median_abund"] == pytest.approx(abund)


def test_abundance_classified_at_liability_anchor_not_global_argmax():
    """Abundance is read at the cell type that DRIVES the liability (HIGH AND-gate passer), not the
    globally most-abundant cell — a MODERATE-only high-abundance cell must not shadow it."""
    rows = pd.DataFrame([
        _row("colonocyte", 20, 0.55, 0.80, 0.20),   # fires HIGH (det>0.5 AND frac>0.7); LOW abundance
        _row("goblet cell", 20, 0.85, 0.40, 3.00),  # MODERATE only (frac<0.7); high abundance — NOT anchor
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "HIGH_LIABILITY"
    assert r["max_detection_cell_type"] == "colonocyte"
    assert r["sc_normal_abundance_class"] == "low_abundance"


def test_abundance_class_data_unavailable_when_column_absent():
    df = pd.DataFrame([_row("colonocyte", 20, 0.85, 0.90, 3.0)]).drop(columns=["median_abund"])
    r = S.classify_sc_normal_expression(df)
    assert r["sc_normal_abundance_class"] == "data_unavailable"
    assert r["sc_normal_peak_median_abund"] is None


def test_abundance_class_present_in_data_unavailable_branch():
    r = S.classify_sc_normal_expression(pd.DataFrame([]))
    assert r["sc_normal_abundance_class"] == "data_unavailable" and r["sc_normal_peak_median_abund"] is None


# --- W1a: NAMED essential-cell driver + ceiling + enriched footprint -----------------------------

def test_named_essential_driver_is_off_origin_cell_not_pooled_argmax():
    """The named essential driver must be the OFF-ORIGIN critical-organ cell that fired the veto —
    NOT the pooled max_detection_cell_type (which can be an origin-tissue epithelial cell with higher
    detection). This is the de-anonymization: name the organ the clamp actually keyed on."""
    rows = pd.concat([
        _tier1_rows([("colonocyte", 20, 0.85, 0.90)], tissue="colon"),
        _tier1_rows([("cardiac muscle cell", 18, 0.60, 0.75)], tissue="heart"),
    ], ignore_index=True)
    r = S.classify_sc_normal_expression(rows, origin_tissues=["colon"])
    assert r["sc_normal_safety_essential_class"] == "critical_organ_liability"
    # pooled anchor is the higher-detection ORIGIN cell; the veto driver is the off-origin heart cell
    assert r["max_detection_cell_type"] == "colonocyte"
    assert r["sc_normal_essential_max_cell_type"] == "cardiac muscle cell"
    assert r["sc_normal_essential_max_tissue"] == "heart"
    assert r["sc_normal_essential_max_detection_fraction"] == pytest.approx(0.60)
    assert r["sc_normal_essential_donor_fraction"] == pytest.approx(0.75)
    assert r["sc_normal_essential_n_datasets_reliable"] == max(1, 18 // 5)


def test_named_essential_driver_origin_only():
    """When essential hits are ONLY in the tissue-of-origin, the named driver is that origin cell."""
    rows = _tier1_rows([("pulmonary alveolar type 1 cell", 12, 0.60, 0.70)], tissue="lung")
    r = S.classify_sc_normal_expression(rows, origin_tissues=["lung"])
    assert r["sc_normal_safety_essential_class"] == "origin_tissue_liability"
    assert r["sc_normal_essential_max_cell_type"] == "pulmonary alveolar type 1 cell"
    assert r["sc_normal_essential_max_tissue"] == "lung"


def test_named_essential_driver_none_when_no_essential_hit():
    rows = _tier1_rows([("fibroblast", 15, 0.50, 0.60), ("B cell", 15, 0.10, 0.20)])
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_safety_essential_class"] == "none"
    assert r["sc_normal_essential_max_cell_type"] is None
    assert r["sc_normal_essential_max_detection_fraction"] is None


def test_ceiling_detection_fraction_is_global_max():
    """The single-cell WINDOW denominator is the global max detection across reliable cell types —
    distinct from max_detection_fraction (the liability-anchor cell, which for HIGH is the AND-gate
    argmax and may be lower than a MODERATE-only high-detection cell)."""
    rows = _tier1_rows([
        ("colonocyte",  20, 0.55, 0.80),   # fires HIGH (anchor); det 0.55
        ("goblet cell", 20, 0.88, 0.40),   # MODERATE only, but the GLOBAL detection ceiling
    ])
    r = S.classify_sc_normal_expression(rows)
    assert r["max_detection_fraction"] == pytest.approx(0.55)          # anchor
    assert r["sc_normal_ceiling_detection_fraction"] == pytest.approx(0.88)  # global ceiling


def test_per_cell_type_top_carries_abundance_and_atlas_count():
    """W1a enrichment: each footprint element now carries median_abund + n_datasets_reliable."""
    rows = _tier1_rows([("colonocyte", 20, 0.85, 0.90)], tissue="colon")
    top = S.classify_sc_normal_expression(rows)["per_cell_type_top"]
    assert top[0]["median_abund"] == pytest.approx(0.85 * 3.0)   # _tier1_rows sets median_abund = med*3
    assert top[0]["n_datasets_reliable"] == max(1, 20 // 5)


def test_off_origin_subfloor_hit_does_not_flip_to_critical():
    """CDH17 archetype: a GI target with strong ORIGIN (colon) essential hits + a MARGINAL (det=0.156,
    single-atlas) off-origin cortical-neuron hit must read origin_tissue_liability, NOT critical_organ_
    liability — the sub-0.20 off-origin hit is ambient/annotation noise and must not flip the verdict."""
    rows = pd.concat([
        _tier1_rows([("colonocyte", 20, 0.70, 0.85), ("BEST4+ colonocyte", 20, 0.92, 0.90)], tissue="colon"),
        _tier1_rows([("L4/5 intratelencephalic projecting glutamatergic neuron", 6, 0.156, 0.30)], tissue="brain"),
    ], ignore_index=True)
    r = S.classify_sc_normal_expression(rows, origin_tissues=["colon"])
    assert r["sc_normal_safety_essential_class"] == "origin_tissue_liability"   # was critical_organ_liability
    # the marginal off-origin hit is still RECORDED for transparency
    assert any("neuron" in ct for ct in r["safety_essential_flags"])
    # named driver is the ORIGIN colon cell, not the sub-floor brain neuron
    assert r["sc_normal_essential_max_tissue"] == "colon"


def test_off_origin_above_floor_still_fires_critical():
    """FOLR1/DLL3 archetype: an off-origin essential hit ABOVE the 0.20 floor still fires the hard veto."""
    rows = pd.concat([
        _tier1_rows([("colonocyte", 20, 0.70, 0.85)], tissue="colon"),
        _tier1_rows([("kidney loop of Henle epithelial cell", 8, 0.61, 0.70)], tissue="kidney"),
    ], ignore_index=True)
    r = S.classify_sc_normal_expression(rows, origin_tissues=["colon"])
    assert r["sc_normal_safety_essential_class"] == "critical_organ_liability"
    assert r["sc_normal_essential_max_tissue"] == "kidney"   # named driver is the above-floor off-origin cell
    assert r["sc_normal_essential_max_detection_fraction"] == pytest.approx(0.61)


def test_only_subfloor_off_origin_hit_reads_none():
    """A lone marginal off-origin essential hit (no origin hit) → class 'none', no named driver."""
    rows = _tier1_rows([("cardiac muscle cell", 6, 0.12, 0.20)], tissue="heart")
    r = S.classify_sc_normal_expression(rows, origin_tissues=["colon"])
    assert r["sc_normal_safety_essential_class"] == "none"
    assert r["sc_normal_essential_max_cell_type"] is None
    assert "cardiac muscle cell" in r["safety_essential_flags"]   # still recorded for transparency


def test_new_fields_present_in_data_unavailable_branch():
    r = S._data_unavailable_class()
    for k in ("sc_normal_essential_max_cell_type", "sc_normal_essential_max_tissue",
              "sc_normal_essential_max_detection_fraction", "sc_normal_essential_donor_fraction",
              "sc_normal_essential_n_datasets_reliable", "sc_normal_essential_median_abund",
              "sc_normal_ceiling_detection_fraction"):
        assert k in r and r[k] is None
