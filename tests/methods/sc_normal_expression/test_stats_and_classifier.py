"""Tests for sc_normal_expression — pure stats + monkeypatched assembler.

Mirrors tests/methods/sc_tumor_expression_celltype/test_stats_and_assembler.py structure:
  - stats primitives tested purely (synthetic Tier-1 DataFrame, no S3);
  - S3 boundary (read_gene_celltype_rows) monkeypatched, never hit;
  - data_unavailable safety branches (no product, gene absent, low donors) asserted;
  - safety-essential cell type flagging asserted.
"""

from __future__ import annotations

import itertools

import pandas as pd
import pytest

pytest.importorskip("numpy")
pytest.importorskip("pandas")

from methods.sc_normal_expression import cli as C
from methods.sc_normal_expression import read as R
from methods.sc_normal_expression import stats as S

# --- fixtures ----------------------------------------------------------------


def _tier1_rows(spec, tissue: str = "colon") -> pd.DataFrame:
    """Build a Tier-1-shaped DataFrame.
    spec: list of (cell_type, n_donors_reliable, median_det, expressing_donor_fraction)
    tissue: the origin tissue label for all rows (default 'colon'; override for organ-aware tests).
    New schema columns (n_datasets_reliable, q25_abund, q25_det) filled with sensible defaults.
    """
    return pd.DataFrame(
        [
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
        ]
    )


# --- classify_sc_normal_expression: liability ladder -------------------------


def test_classify_high_liability():
    """Any cell type exceeding BOTH thresholds → HIGH_LIABILITY."""
    rows = _tier1_rows(
        [
            ("colonocyte", 20, 0.85, 0.90),  # well above HIGH thresholds
            ("fibroblast", 15, 0.10, 0.20),
        ]
    )
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "HIGH_LIABILITY"
    assert r["max_detection_cell_type"] == "colonocyte"
    assert r["max_detection_fraction"] == pytest.approx(0.85)


def test_classify_high_liability_reports_triggering_cell_not_global_argmax():
    """The cell type with highest raw detection may not be the one that fired HIGH_LIABILITY.
    When Cell A has det=0.85 (fails AND: frac=0.40 < 0.70) and Cell B has det=0.55 (passes AND:
    frac=0.80 > 0.70), HIGH fires and max_detection_cell_type must be Cell B, not Cell A."""
    rows = _tier1_rows(
        [
            ("fibroblast", 20, 0.85, 0.40),  # highest det but fails AND (frac below threshold)
            ("colonocyte", 20, 0.55, 0.80),  # lower det but BOTH thresholds met → fires HIGH
        ]
    )
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "HIGH_LIABILITY"
    assert r["max_detection_cell_type"] == "colonocyte"  # the triggering cell, not the argmax
    assert r["max_detection_fraction"] == pytest.approx(0.55)


def test_safety_essential_flags_excludes_near_zero_values():
    """Entries with median_det <= 0.05 (census annotation noise) must NOT appear in safety flags."""
    rows = _tier1_rows(
        [
            ("hepatocyte", 10, 0.03, 0.10),  # essential but below noise floor — must be excluded
            ("fibroblast", 10, 0.50, 0.60),
        ]
    )
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


def test_islet_beta_cell_is_safety_essential():
    """W3b: the pancreas shard was promoted always-on 'for islet safety' but no islet prefix
    existed. The raw Census β-cell label is 'type B pancreatic cell' (NOT 'beta'/'islet'); it and
    the other endocrine islet cells must now flag."""
    for ct in (
        "type B pancreatic cell",
        "pancreatic A cell",
        "pancreatic D cell",
        "pancreatic PP cell",
        "pancreatic epsilon cell",
    ):
        assert S._is_safety_essential(ct), ct
    # exocrine ductal/stellate are NOT in the islet-endocrine set (a bare 'pancreatic' prefix
    # would have over-matched them) and must stay unflagged
    assert not S._is_safety_essential("pancreatic ductal cell")
    assert not S._is_safety_essential("pancreatic stellate cell")
    # podocyte + Schwann added the same wave
    assert S._is_safety_essential("podocyte")
    assert S._is_safety_essential("Schwann cell")
    # exocrine acinar (pancreatic only — bare 'acinar cell' deliberately NOT used, to avoid the
    # single-atlas lung airway-gland 'acinar cell' hit), cholangiocyte, endothelium
    assert S._is_safety_essential("pancreatic acinar cell")
    assert not S._is_safety_essential("acinar cell")  # bare label intentionally unmatched
    assert S._is_safety_essential("cholangiocyte")
    assert S._is_safety_essential("intrahepatic cholangiocyte")
    # endothelium is broad by design — every subtype matches the whole-token "endothelial cell"
    for ct in (
        "endothelial cell",
        "glomerular endothelial cell",
        "vein endothelial cell",
        "endothelial cell of sinusoid",
    ):
        assert S._is_safety_essential(ct), ct


def test_beta_cell_target_off_origin_vs_origin():
    """A β-restricted target flips to critical_organ_liability when the pancreas is OFF-origin
    (islet is a critical off-target endocrine organ) but stays origin_tissue_liability when the
    tumour IS pancreatic (islet on-tissue, therapeutic-window-arbitrated)."""
    rows = _tier1_rows([("type B pancreatic cell", 40, 0.84, 0.98)], tissue="pancreas")
    r_off = S.classify_sc_normal_expression(rows, origin_tissues=["colon"])
    assert r_off["sc_normal_safety_essential_class"] == "critical_organ_liability"
    assert r_off["sc_normal_essential_max_cell_type"] == "type B pancreatic cell"
    r_on = S.classify_sc_normal_expression(rows, origin_tissues=["pancreas"])
    assert r_on["sc_normal_safety_essential_class"] == "origin_tissue_liability"


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
    # off_origin dominates: a gene hitting BOTH lung(origin) AND heart(critical) → critical.
    # pd.concat, NOT `+`: DataFrame addition is ELEMENT-WISE, so the two 1-row frames used to collapse
    # into a SINGLE mangled row (cell_type "pulmonary alveolar type 1 cellcardiac muscle cell", tissue
    # "lungheart", median_det 0.60+0.90 = 1.5 — an impossible detection FRACTION). That row is trivially
    # off-origin because "lungheart" is in no origin set, so this assertion passed without ever building
    # the two-organ case it names and could not fail if off-origin-dominates regressed.
    rows_both = pd.concat(
        [
            _tier1_rows([("pulmonary alveolar type 1 cell", 10, 0.60, 0.70)], tissue="lung"),
            _tier1_rows([("cardiac muscle cell", 10, 0.90, 0.90)], tissue="heart"),
        ],
        ignore_index=True,
    )
    assert len(rows_both) == 2, "the both-organs frame must actually carry two rows"
    assert set(rows_both["tissue"]) == {"lung", "heart"}
    r3 = S.classify_sc_normal_expression(rows_both, origin_tissues=["lung"])
    assert r3["sc_normal_safety_essential_class"] == "critical_organ_liability"
    assert r3["sc_normal_essential_max_tissue"] == "heart", (
        "the named driver must be the OFF-ORIGIN heart hit, not the origin lung one"
    )


def test_norm_tissue_folds_shard_key_and_census_separators():
    """The shard-key vocabulary (UNDERSCORED, needed to build the S3 product id) and the CELLxGENE
    Census `tissue` column (SPACED) must compare equal after normalization."""
    for key, census in (
        ("prostate_gland", "prostate gland"),
        ("bladder_organ", "bladder organ"),
        ("bone_marrow", "bone marrow"),
        ("adrenal_gland", "adrenal gland"),
        ("small_intestine", "small intestine"),
        ("large_intestine", "Large  Intestine"),
    ):
        assert S._norm_tissue(key) == S._norm_tissue(census)
    # single-word tissues are unaffected (which is why the defect went unnoticed — every existing
    # organ-aware test used colon/lung/liver/heart/kidney/pancreas)
    assert S._norm_tissue("colon") == S._norm_tissue("Colon ")
    # hyphens fold too, so a future hyphenated label cannot silently reintroduce the mismatch
    assert S._norm_tissue("bone-marrow") == "bone marrow"


def test_multiword_origin_tissue_is_not_read_as_off_origin_critical_organ():
    """REGRESSION: `origin_tissues` arrives as UNDERSCORED shard keys (read.py INDICATION_TO_TISSUES:
    PRAD -> prostate_gland, BLCA -> bladder_organ) while the per-row `tissue` column carries the SPACED
    Census value, so the raw `row_tissue in origin` test never matched for ANY multi-word origin and the
    tumor's OWN organ was scored as an off-origin critical-organ liability — the hard-veto class both
    consumers key on (tvn-sc-normal-critical-organ-veto and the surface-modality-fit BiTE killer both
    `equals: critical_organ_liability`). Measured on the panel: KLK3/PRAD and KLK2/PRAD fired on
    `prostate gland` cells."""
    rows = _tier1_rows([("endothelial cell", 10, 0.56, 0.60)], tissue="prostate gland")
    r = S.classify_sc_normal_expression(rows, origin_tissues=["prostate_gland"])
    assert r["sc_normal_safety_essential_class"] == "origin_tissue_liability"
    assert r["sc_normal_essential_max_tissue"] == "prostate gland"
    # same for bladder (BLCA), and the off-origin case still hard-vetoes
    rows_bl = _tier1_rows([("endothelial cell", 10, 0.56, 0.60)], tissue="bladder organ")
    assert (
        S.classify_sc_normal_expression(rows_bl, origin_tissues=["bladder_organ"])["sc_normal_safety_essential_class"]
        == "origin_tissue_liability"
    )
    assert (
        S.classify_sc_normal_expression(rows_bl, origin_tissues=["colon"])["sc_normal_safety_essential_class"]
        == "critical_organ_liability"
    )


def test_origin_only_driver_is_never_an_off_origin_cell():
    """The NAMED driver of an origin_tissue_liability must be an ON-ORIGIN cell. The origin-only branch
    used to pool ALL essential records, so an argmax over the sub-floor (0.05-0.20) OFF-ORIGIN hits that
    deliberately did NOT flip the class could out-rank the origin hit that DID — naming a cell in the
    wrong organ. Measured live on CD274/LUAD ('brain L5 ... cortical neuron' for a lung-origin
    liability) and UPK1B/BLCA."""
    rows = pd.concat(
        [
            _tier1_rows([("pulmonary alveolar type 1 cell", 10, 0.11, 0.30)], tissue="lung"),  # origin, fired
            _tier1_rows([("neuron", 110, 0.14, 0.30)], tissue="brain"),  # off-origin, SUB-FLOOR, inert
        ],
        ignore_index=True,
    )
    r = S.classify_sc_normal_expression(rows, origin_tissues=["lung"])
    assert r["sc_normal_safety_essential_class"] == "origin_tissue_liability"
    assert r["sc_normal_essential_max_tissue"] == "lung"
    assert r["sc_normal_essential_max_cell_type"] == "pulmonary alveolar type 1 cell"
    # the off-origin sub-floor hit is still RECORDED for transparency, it just cannot be the driver
    assert "neuron" in r["safety_essential_flags"]


def test_origin_normalization_never_creates_a_critical_organ_liability():
    """Monotonicity in the HARD-VETO direction: reclassifying a hit as origin can only REMOVE an
    off-origin contribution, so no spelling of `origin_tissues` may turn a non-critical class critical.
    (It is NOT globally monotonic — origin hits keep the lower 0.05 floor, so a 0.05-0.20 own-organ hit
    can move `none` -> origin_tissue_liability. That is the honest, window-arbitrated class.)"""
    rows = _tier1_rows([("endothelial cell", 10, 0.30, 0.60)], tissue="prostate gland")
    for origin in (["prostate_gland"], ["prostate gland"], ["PROSTATE_GLAND"], ["prostate-gland"]):
        assert (
            S.classify_sc_normal_expression(rows, origin_tissues=origin)["sc_normal_safety_essential_class"]
            == "origin_tissue_liability"
        ), origin
    # sub-floor own-organ hit: `none` -> origin_tissue_liability once the origin match works
    sub = _tier1_rows([("endothelial cell", 10, 0.07, 0.20)], tissue="bladder organ")
    assert S.classify_sc_normal_expression(sub, origin_tissues=[])["sc_normal_safety_essential_class"] == "none"
    assert (
        S.classify_sc_normal_expression(sub, origin_tissues=["bladder_organ"])["sc_normal_safety_essential_class"]
        == "origin_tissue_liability"
    )


def test_safety_essential_flags_includes_above_floor():
    """Entries above the 0.05 flag floor appear in safety_essential_flags for transparency — but a
    marginal off-origin hit (0.08, below the 0.20 off-origin critical floor) does NOT flip to
    critical_organ_liability (the 2026-09-04 ambient-noise floor). A det=0.30 hit DOES."""
    rows = _tier1_rows(
        [
            ("hepatocyte", 10, 0.08, 0.20),  # above 0.05 flag floor, below 0.20 off-origin critical floor
            ("fibroblast", 10, 0.05, 0.10),
        ]
    )
    r = S.classify_sc_normal_expression(rows)
    assert "hepatocyte" in r["safety_essential_flags"]  # recorded for transparency
    assert r["safety_essential_flags"]["hepatocyte"] == pytest.approx(0.08)
    assert r["sc_normal_safety_essential_class"] == "none"  # sub-floor off-origin does NOT flip
    # a hepatocyte hit ABOVE the 0.20 floor with no origin passed → off-origin critical (conservative)
    r2 = S.classify_sc_normal_expression(_tier1_rows([("hepatocyte", 10, 0.30, 0.45)]))
    assert r2["sc_normal_safety_essential_class"] == "critical_organ_liability"


def test_classify_moderate_liability_by_det():
    """A cell type above MODERATE_LIABILITY_DET (0.20) but below HIGH threshold → MODERATE."""
    rows = _tier1_rows(
        [
            ("enterocyte", 10, 0.35, 0.25),  # med_det > 0.20, frac < 0.30
            ("fibroblast", 10, 0.05, 0.10),
        ]
    )
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "MODERATE_LIABILITY"


def test_classify_moderate_liability_by_donor_fraction():
    """A cell type with frac > 0.30 but med_det < 0.20 → MODERATE (OR logic)."""
    rows = _tier1_rows(
        [
            ("plasma cell", 8, 0.15, 0.55),  # frac > 0.30 triggers moderate
            ("fibroblast", 10, 0.04, 0.10),
        ]
    )
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "MODERATE_LIABILITY"


def test_classify_low_liability():
    rows = _tier1_rows(
        [
            ("colonocyte", 12, 0.08, 0.15),  # above NOT_EXPRESSED but below MODERATE
            ("fibroblast", 12, 0.03, 0.05),
        ]
    )
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "LOW_LIABILITY"


def test_classify_not_expressed():
    """All cell types below NOT_EXPRESSED_CEILING → NOT_EXPRESSED."""
    rows = _tier1_rows(
        [
            ("colonocyte", 20, 0.005, 0.02),
            ("fibroblast", 20, 0.003, 0.01),
        ]
    )
    r = S.classify_sc_normal_expression(rows)
    assert r["sc_normal_expression_class"] == "NOT_EXPRESSED"


def test_classify_data_unavailable_low_donors():
    """All n_donors_reliable < MIN_RELIABLE_DONORS → data_unavailable."""
    rows = _tier1_rows(
        [
            ("colonocyte", 3, 0.90, 0.95),  # very high detection but n_donors < 5
            ("fibroblast", 2, 0.05, 0.10),
        ]
    )
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
    rows = _tier1_rows(
        [
            ("cardiomyocyte", 15, 0.40, 0.55),  # above LOW, essential cell type
            ("fibroblast", 15, 0.05, 0.10),
        ]
    )
    r = S.classify_sc_normal_expression(rows)
    assert "cardiomyocyte" in r["safety_essential_flags"]
    assert r["safety_essential_flags"]["cardiomyocyte"] == pytest.approx(0.40)


def test_safety_essential_flags_hepatocyte():
    rows = _tier1_rows(
        [
            ("hepatocyte", 20, 0.30, 0.45),
            ("colonocyte", 20, 0.02, 0.05),
        ]
    )
    r = S.classify_sc_normal_expression(rows)
    assert "hepatocyte" in r["safety_essential_flags"]


def test_safety_essential_flags_empty_when_no_essential():
    rows = _tier1_rows(
        [
            ("fibroblast", 15, 0.05, 0.10),
            ("B cell", 15, 0.03, 0.08),
        ]
    )
    r = S.classify_sc_normal_expression(rows)
    assert r["safety_essential_flags"] == {}


# --- n_cell_types_above_20pct from classify ----------------------------------


def test_n_cell_types_above_20pct_count():
    rows = _tier1_rows(
        [
            ("colonocyte", 10, 0.55, 0.70),  # > 0.20
            ("enterocyte", 10, 0.35, 0.40),  # > 0.20
            ("fibroblast", 10, 0.08, 0.15),  # <= 0.20
        ]
    )
    r = S.classify_sc_normal_expression(rows)
    assert r["n_cell_types_above_20pct"] == 2


# --- read.py with monkeypatched S3 -------------------------------------------


def test_read_target_summary_full_path(monkeypatch):
    rows = _tier1_rows(
        [
            ("colonocyte", 20, 0.85, 0.90),
            ("fibroblast", 15, 0.10, 0.20),
        ]
    )
    monkeypatch.setattr(R, "read_gene_celltype_rows", lambda t, ts: rows)
    out = R.read_target_summary("EPCAM", "COADREAD")
    assert out["sc_normal_expression_class"] == "HIGH_LIABILITY"
    assert out["indication"] == "COADREAD"
    # COADREAD now queries the matched tissue (colon) UNION the always-on safety-essential tissues
    assert out["tissues_queried"] == [
        "colon",
        "heart",
        "liver",
        "kidney",
        "bone_marrow",
        "brain",
        "adrenal_gland",
        "lung",
        "pancreas",
    ]


def test_read_target_summary_unknown_indication_still_reads_safety_essential(monkeypatch):
    """Unknown indication no longer abstains-by-mapping: it queries the safety-essential tissues
    (cross-tissue on-target-tox check). With a real product it would classify; here the reader is
    monkeypatched to None (no product) → data_unavailable, but tissues_queried is non-empty."""
    monkeypatch.setattr(R, "read_gene_celltype_rows", lambda t, ts: None)
    out = R.read_target_summary("EPCAM", "UNKNOWN_IND")
    assert out["sc_normal_expression_class"] == "data_unavailable"
    assert out["tissues_queried"] == [
        "heart",
        "liver",
        "kidney",
        "bone_marrow",
        "brain",
        "adrenal_gland",
        "lung",
        "pancreas",
    ]
    assert "_data_note" in out


def test_read_target_summary_no_product(monkeypatch):
    """read_gene_celltype_rows returns None → data_unavailable."""
    monkeypatch.setattr(R, "read_gene_celltype_rows", lambda t, ts: None)
    out = R.read_target_summary("EPCAM", "COADREAD")
    assert out["sc_normal_expression_class"] == "data_unavailable"
    assert "_data_note" in out


def test_read_target_summary_gene_absent(monkeypatch):
    """Empty DataFrame (gene not in product) → data_unavailable, 'absent' note."""
    monkeypatch.setattr(R, "read_gene_celltype_rows", lambda t, ts: pd.DataFrame())
    out = R.read_target_summary("MADEUPGENE99", "COADREAD")
    assert out["sc_normal_expression_class"] == "data_unavailable"
    assert "absent" in out.get("_data_note", "")


def test_tissues_for_indication_unions_matched_and_safety_essential():
    """tumor-matched tissue(s) UNION the always-on safety-essential tissues, de-duplicated."""
    # Census-backed indications. Always-on safety-essential set now includes lung + pancreas
    # (promoted 2026-08-19: pneumocyte / islet safety), de-duped against the matched tissue.
    assert R.tissues_for_indication("COADREAD") == [
        "colon",
        "heart",
        "liver",
        "kidney",
        "bone_marrow",
        "brain",
        "adrenal_gland",
        "lung",
        "pancreas",
    ]
    assert R.tissues_for_indication("NSCLC") == [
        "lung",
        "heart",
        "liver",
        "kidney",
        "bone_marrow",
        "brain",
        "adrenal_gland",
        "pancreas",
    ]
    # 3CA-backed indications added 2026-08-12
    assert R.tissues_for_indication("PAAD") == [
        "pancreas",
        "heart",
        "liver",
        "kidney",
        "bone_marrow",
        "brain",
        "adrenal_gland",
        "lung",
    ]
    assert R.tissues_for_indication("HNSC") == [
        "esophagus",
        "heart",
        "liver",
        "kidney",
        "bone_marrow",
        "brain",
        "adrenal_gland",
        "lung",
        "pancreas",
    ]
    assert R.tissues_for_indication("STAD") == [
        "stomach",
        "heart",
        "liver",
        "kidney",
        "bone_marrow",
        "brain",
        "adrenal_gland",
        "lung",
        "pancreas",
    ]
    # Unknown indication → safety-essential only (never empty)
    assert R.tissues_for_indication("UNKNOWN") == [
        "heart",
        "liver",
        "kidney",
        "bone_marrow",
        "brain",
        "adrenal_gland",
        "lung",
        "pancreas",
    ]


def test_indication_coverage_wires_orphaned_shards_and_origin_correctness():
    """2026-09-04 coverage: 3 previously-orphaned shards (bladder/skin/uterus) are now queried via an
    indication map, and origin-organ tumors (KIRC/LIHC/GBM) de-dup their origin out of the always-on set
    (front position) so it is treated as origin, not off-target."""
    # orphaned shards now reachable via an indication → prepended to the always-on set
    assert R.tissues_for_indication("BLCA")[0] == "bladder_organ"
    assert R.tissues_for_indication("SKCM")[0] == "skin"
    assert R.tissues_for_indication("UCEC")[0] == "uterus"
    # origin organ already in the always-on set → de-duped to the front, queried ONCE
    assert R.tissues_for_indication("KIRC") == [
        "kidney",
        "heart",
        "liver",
        "bone_marrow",
        "brain",
        "adrenal_gland",
        "lung",
        "pancreas",
    ]
    assert R.tissues_for_indication("GBM") == [
        "brain",
        "heart",
        "liver",
        "kidney",
        "bone_marrow",
        "adrenal_gland",
        "lung",
        "pancreas",
    ]


def test_kidney_origin_softens_own_organ_liability_for_renal_cancer(monkeypatch):
    """A renal target expressed in kidney tubule reads critical_organ_liability for a NON-renal tumor,
    but origin_tissue_liability for KIRC (kidney IS the tissue-of-origin) — the coverage correctness fix."""
    rows = _tier1_rows([("kidney proximal tubule epithelial cell", 12, 0.60, 0.75)], tissue="kidney")
    monkeypatch.setattr(R, "read_gene_celltype_rows", lambda t, ts: rows)
    # non-renal tumor: kidney is off-origin → hard-veto class
    assert (
        R.read_target_summary("SOMEGENE", "COADREAD")["sc_normal_safety_essential_class"] == "critical_organ_liability"
    )
    # renal tumor: kidney is origin → softened
    assert R.read_target_summary("SOMEGENE", "KIRC")["sc_normal_safety_essential_class"] == "origin_tissue_liability"


def test_all_tissue_products_resolve():
    """All wired tissues route to a Tier-1 product key (hyphenated slugs for multi-word tissues)."""
    for t in [
        "colon",
        "lung",
        "heart",
        "liver",
        "kidney",
        "stomach",
        "bone_marrow",
        "skin",
        "small_intestine",
        "brain",
        "esophagus",
        "pancreas",
        "ovary",
        "prostate_gland",
        # 2026-08-15: the map now covers all 19 landed normal-tissue shards
        "adrenal_gland",
        "bladder_organ",
        "large_intestine",
        "spleen",
        "uterus",
    ]:
        assert t in R.TISSUE_TO_PRODUCT, f"{t} missing from TISSUE_TO_PRODUCT"
    assert len(R.TISSUE_TO_PRODUCT) == 19  # all landed normal-tissue shards are reachable
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
    rows = _tier1_rows(
        [
            ("colonocyte", 20, 0.85, 0.90),  # safety-essential (enterocyte/colonocyte lineage)
            ("cardiomyocyte", 18, 0.60, 0.75),  # safety-essential (critical organ)
            ("fibroblast", 15, 0.10, 0.20),  # not essential
        ],
        tissue="colon",
    )
    top = S.classify_sc_normal_expression(rows)["per_cell_type_top"]
    assert [r["cell_type"] for r in top] == ["colonocyte", "cardiomyocyte", "fibroblast"]
    assert top[0]["median_detection_fraction"] >= top[-1]["median_detection_fraction"]
    flags = {r["cell_type"]: r["is_safety_essential"] for r in top}
    assert flags["cardiomyocyte"] is True and flags["fibroblast"] is False
    assert top[0]["tissue"] == "colon" and top[0]["n_donors_reliable"] == 20


def test_per_cell_type_top_empty_when_data_unavailable():
    assert S._data_unavailable_class()["per_cell_type_top"] == []


def test_emit_normal_celltype_liability_writes_svg(tmp_path):
    summary = S.classify_sc_normal_expression(
        _tier1_rows(
            [("colonocyte", 20, 0.85, 0.90), ("cardiomyocyte", 18, 0.60, 0.75), ("fibroblast", 15, 0.10, 0.20)],
            tissue="colon",
        )
    )
    C.emit_normal_celltype_liability(summary, "EPCAM", tmp_path)
    svg = tmp_path / "figure_sc_normal_celltype_liability.svg"
    assert svg.exists() and svg.stat().st_size > 0
    assert svg.read_text().lstrip().startswith("<?xml") or "<svg" in svg.read_text()


def test_emit_normal_celltype_liability_noop_when_empty(tmp_path):
    C.emit_normal_celltype_liability(S._data_unavailable_class(), "EPCAM", tmp_path)
    assert not (tmp_path / "figure_sc_normal_celltype_liability.svg").exists()


# --- #984 Tier-2: normal-tissue ABUNDANCE class (at the liability-anchor cell type) ---------------


def _row(ct, n, med, frac, abund, tissue="colon"):
    return {
        "gene_symbol": "EPCAM",
        "ensembl_gene_id": "E",
        "tissue": tissue,
        "cell_type": ct,
        "n_donors_total": n,
        "n_donors_reliable": n,
        "n_datasets_reliable": max(1, n // 5),
        "n_donors_expressing": max(0, n - 2),
        "median_det": med,
        "q25_det": med * 0.7,
        "q75_det": med * 1.3,
        "expressing_donor_fraction": frac,
        "median_abund": abund,
        "q25_abund": abund * 0.8,
        "q75_abund": abund * 1.2,
        "detection_pct_rank": 0.5,
        "n_cell_types_above_20pct": 0,
    }


def test_abundance_class_bands_high_moderate_low():
    """Bands (0.24 / 0.64) at the anchor cell type: EPCAM-like high, ERBB2-like moderate, FOLR1-like low."""
    for abund, expect in [(3.36, "high_abundance"), (0.36, "moderate_abundance"), (0.21, "low_abundance")]:
        r = S.classify_sc_normal_expression(pd.DataFrame([_row("colonocyte", 20, 0.85, 0.90, abund)]))
        assert r["sc_normal_abundance_class"] == expect, (abund, r["sc_normal_abundance_class"])
        assert r["sc_normal_peak_median_abund"] == pytest.approx(abund)


def test_abundance_classified_at_liability_anchor_not_global_argmax():
    """Abundance is read at the cell type that DRIVES the liability (HIGH AND-gate passer), not the
    globally most-abundant cell — a MODERATE-only high-abundance cell must not shadow it."""
    rows = pd.DataFrame(
        [
            _row("colonocyte", 20, 0.55, 0.80, 0.20),  # fires HIGH (det>0.5 AND frac>0.7); LOW abundance
            _row("goblet cell", 20, 0.85, 0.40, 3.00),  # MODERATE only (frac<0.7); high abundance — NOT anchor
        ]
    )
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
    rows = pd.concat(
        [
            _tier1_rows([("colonocyte", 20, 0.85, 0.90)], tissue="colon"),
            _tier1_rows([("cardiac muscle cell", 18, 0.60, 0.75)], tissue="heart"),
        ],
        ignore_index=True,
    )
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
    rows = _tier1_rows(
        [
            ("colonocyte", 20, 0.55, 0.80),  # fires HIGH (anchor); det 0.55
            ("goblet cell", 20, 0.88, 0.40),  # MODERATE only, but the GLOBAL detection ceiling
        ]
    )
    r = S.classify_sc_normal_expression(rows)
    assert r["max_detection_fraction"] == pytest.approx(0.55)  # anchor
    assert r["sc_normal_ceiling_detection_fraction"] == pytest.approx(0.88)  # global ceiling


def test_per_cell_type_top_carries_abundance_and_atlas_count():
    """W1a enrichment: each footprint element now carries median_abund + n_datasets_reliable."""
    rows = _tier1_rows([("colonocyte", 20, 0.85, 0.90)], tissue="colon")
    top = S.classify_sc_normal_expression(rows)["per_cell_type_top"]
    assert top[0]["median_abund"] == pytest.approx(0.85 * 3.0)  # _tier1_rows sets median_abund = med*3
    assert top[0]["n_datasets_reliable"] == max(1, 20 // 5)


def test_off_origin_subfloor_hit_does_not_flip_to_critical():
    """CDH17 archetype: a GI target with strong ORIGIN (colon) essential hits + a MARGINAL (det=0.156,
    single-atlas) off-origin cortical-neuron hit must read origin_tissue_liability, NOT critical_organ_
    liability — the sub-0.20 off-origin hit is ambient/annotation noise and must not flip the verdict."""
    rows = pd.concat(
        [
            _tier1_rows([("colonocyte", 20, 0.70, 0.85), ("BEST4+ colonocyte", 20, 0.92, 0.90)], tissue="colon"),
            _tier1_rows([("L4/5 intratelencephalic projecting glutamatergic neuron", 6, 0.156, 0.30)], tissue="brain"),
        ],
        ignore_index=True,
    )
    r = S.classify_sc_normal_expression(rows, origin_tissues=["colon"])
    assert r["sc_normal_safety_essential_class"] == "origin_tissue_liability"  # was critical_organ_liability
    # the marginal off-origin hit is still RECORDED for transparency
    assert any("neuron" in ct for ct in r["safety_essential_flags"])
    # named driver is the ORIGIN colon cell, not the sub-floor brain neuron
    assert r["sc_normal_essential_max_tissue"] == "colon"


def test_off_origin_above_floor_still_fires_critical():
    """FOLR1/DLL3 archetype: an off-origin essential hit ABOVE the 0.20 floor still fires the hard veto."""
    rows = pd.concat(
        [
            _tier1_rows([("colonocyte", 20, 0.70, 0.85)], tissue="colon"),
            _tier1_rows([("kidney loop of Henle epithelial cell", 8, 0.61, 0.70)], tissue="kidney"),
        ],
        ignore_index=True,
    )
    r = S.classify_sc_normal_expression(rows, origin_tissues=["colon"])
    assert r["sc_normal_safety_essential_class"] == "critical_organ_liability"
    assert r["sc_normal_essential_max_tissue"] == "kidney"  # named driver is the above-floor off-origin cell
    assert r["sc_normal_essential_max_detection_fraction"] == pytest.approx(0.61)


def test_only_subfloor_off_origin_hit_reads_none():
    """A lone marginal off-origin essential hit (no origin hit) → class 'none', no named driver."""
    rows = _tier1_rows([("cardiac muscle cell", 6, 0.12, 0.20)], tissue="heart")
    r = S.classify_sc_normal_expression(rows, origin_tissues=["colon"])
    assert r["sc_normal_safety_essential_class"] == "none"
    assert r["sc_normal_essential_max_cell_type"] is None
    assert "cardiac muscle cell" in r["safety_essential_flags"]  # still recorded for transparency


def test_new_fields_present_in_data_unavailable_branch():
    r = S._data_unavailable_class()
    for k in (
        "sc_normal_essential_max_cell_type",
        "sc_normal_essential_max_tissue",
        "sc_normal_essential_max_detection_fraction",
        "sc_normal_essential_donor_fraction",
        "sc_normal_essential_n_datasets_reliable",
        "sc_normal_essential_median_abund",
        "sc_normal_ceiling_detection_fraction",
    ):
        assert k in r and r[k] is None


# --- sc_normal_essential_veto_grade: compartment x severity ------------------
#
# The graded veto instrument. sc_normal_safety_essential_class is a 92.9%-base-rate boolean on
# corpus-20260914 whose single largest driver is the brain shard (55.3%), and it feeds a `dominant: true`
# BiTE/TCE killer — the modality least able to reach brain parenchyma. These tests pin the two properties
# that make the grade safe to key a killer on: it never relieves the veto on THIN data, and it never lets
# the argmax organ hide an accessible-organ liability.


def _grade(rows, origin):
    return S.classify_sc_normal_expression(rows, origin_tissues=origin)["sc_normal_essential_veto_grade"]


def test_veto_grade_accessible_high_severity_when_well_replicated():
    """A well-replicated, high-detection hit in an ACCESSIBLE critical organ is the maximal rung —
    the one a dominant killer may key on."""
    # NB: label chosen because it VERIFIABLY matches SAFETY_ESSENTIAL_CELL_TYPE_PREFIXES. The obvious
    # pick, "kidney proximal convoluted tubule epithelial cell", does NOT match — see
    # test_kidney_proximal_tubule_prefix_misses_the_real_census_labels below.
    rows = _tier1_rows([("kidney loop of Henle thick ascending limb epithelial cell", 40, 0.90, 0.95)], tissue="kidney")
    r = S.classify_sc_normal_expression(rows, origin_tissues=["colon"])
    assert r["sc_normal_safety_essential_class"] == "critical_organ_liability"
    assert r["sc_normal_essential_veto_grade"] == "accessible_high_severity"


def test_veto_grade_single_atlas_is_low_confidence_not_high():
    """n_datasets_reliable <= 1 caps the grade at low_confidence however high the detection.
    This is the EPCAM/FOLR1 shape: det ~0.99/0.71 on ONE atlas."""
    rows = _tier1_rows([("cardiac muscle cell", 40, 0.99, 1.0)], tissue="heart")
    rows["n_datasets_reliable"] = 1
    assert _grade(rows, ["colon"]) == "accessible_low_confidence"


def test_veto_grade_bbb_protected_only_when_every_hit_is_brain():
    """A brain-parenchyma-only liability grades bbb_protected — still a liability (the class is
    unchanged), but not the rung a systemically dosed TCE killer keys on."""
    rows = _tier1_rows(
        [("L5 extratelencephalic projecting glutamatergic cortical neuron", 40, 0.97, 1.0)], tissue="brain"
    )
    r = S.classify_sc_normal_expression(rows, origin_tissues=["lung"])
    assert r["sc_normal_safety_essential_class"] == "critical_organ_liability", (
        "the CLASS must be untouched — this grades the veto, it does not drop it"
    )
    assert r["sc_normal_essential_veto_grade"] == "bbb_protected"


def test_veto_grade_brain_argmax_must_not_mask_an_accessible_organ_hit():
    """THE FAIL-OPEN THIS DESIGN EXISTS TO DEFEAT. Grading the compartment on the ARGMAX organ would
    call this bbb_protected, because the brain hit (0.97) outranks the lung hit (0.62) on detection.
    Measured on corpus-20260914, at least 96 of 259 brain-argmax critical calls (37.1%) carry exactly
    this shape — AKT1 is the clean case (brain argmax, cycling pulmonary AT2 at det 0.615). The
    partition is over the WHOLE above-floor off-origin pool, so ANY accessible hit governs, and severity
    comes from the worst ACCESSIBLE hit rather than the global argmax."""
    rows = pd.concat(
        [
            _tier1_rows(
                [("L5 extratelencephalic projecting glutamatergic cortical neuron", 40, 0.97, 1.0)], tissue="brain"
            ),
            _tier1_rows([("cycling pulmonary alveolar type 2 cell", 40, 0.62, 0.90)], tissue="lung"),
        ],
        ignore_index=True,
    )
    r = S.classify_sc_normal_expression(rows, origin_tissues=["colon"])
    assert r["sc_normal_essential_max_tissue"] == "brain", "the named driver is still the global argmax"
    assert r["sc_normal_essential_veto_grade"] == "accessible_high_severity", (
        "the LUNG hit must govern the grade even though BRAIN wins the argmax"
    )


def test_veto_grade_ignores_a_sub_floor_accessible_hit():
    """Only ABOVE-floor off-origin hits are in the pool. A sub-0.20 accessible hit did not fire the
    class and must not upgrade the grade off bbb_protected either — otherwise the grade would disagree
    with the very class it describes."""
    rows = pd.concat(
        [
            _tier1_rows([("neuron of the forebrain", 40, 0.97, 1.0)], tissue="brain"),
            _tier1_rows([("cardiac muscle cell", 40, 0.12, 0.30)], tissue="heart"),
        ],
        ignore_index=True,
    )
    assert _grade(rows, ["colon"]) == "bbb_protected"


def test_veto_grade_unknown_tissue_is_accessible_not_protected():
    """A missing `tissue` column must not earn the modality-relieving compartment: a coverage gap is
    not a safety argument. Mirrors the origin split, which treats unknown tissue as off-origin."""
    rows = _tier1_rows([("cardiac muscle cell", 40, 0.90, 0.95)], tissue="heart").drop(columns=["tissue"])
    assert _grade(rows, ["colon"]) == "accessible_high_severity"


def test_veto_grade_ungraded_when_replication_is_absent_and_it_is_not_a_low_rung():
    """DIRECTION TEST ON THE FIX ITSELF. If the fields needed to grade are ABSENT, the grade must stay
    veto-eligible (`accessible_ungraded`), never `accessible_low_confidence` — otherwise removing a
    column would RELAX a killer, i.e. thinner data would buy a better safety verdict."""
    rows = _tier1_rows([("cardiac muscle cell", 40, 0.90, 0.95)], tissue="heart").drop(columns=["n_datasets_reliable"])
    g = _grade(rows, ["colon"])
    assert g == "accessible_ungraded", g
    assert g != "accessible_low_confidence"


def test_veto_grade_origin_only_and_not_applicable_are_distinct():
    """origin_tissue (window-arbitrated by design) must not be spelled the same as not_applicable
    (no essential hit at all), and neither may be spelled data_unavailable (a coverage gap)."""
    origin_only = _tier1_rows([("cardiac muscle cell", 40, 0.90, 0.95)], tissue="heart")
    assert _grade(origin_only, ["heart"]) == "origin_tissue"
    # `fibroblast`, not an enterocyte: GI enterocytes/colonocytes ARE in the essential vocabulary, so a
    # colon epithelial hit grades origin_tissue, not not_applicable. not_applicable means NO essential
    # hit exists anywhere — the pool is empty, not merely exempted.
    none_at_all = _tier1_rows([("fibroblast", 40, 0.90, 0.95)], tissue="colon")
    assert _grade(none_at_all, ["colon"]) == "not_applicable"
    assert S._data_unavailable_class()["sc_normal_essential_veto_grade"] == "data_unavailable"


def test_veto_grade_takes_the_worst_GRADE_not_the_detection_argmax():
    """THE SECOND-LAYER FAIL-OPEN. The compartment was already partitioned over the whole pool, but
    SEVERITY was still read off the DETECTION ARGMAX — so the pool's worst-graded hit could be
    shadowed by a higher-detection hit that grades lower. Detection is not a monotone proxy for the
    grade, because `_essential_severity` is a CONJUNCTION over det x donor x atlas count.

    POSITIVE CONTROL, constructed to FAIL on the argmax implementation:
      A  det 0.80, donor 0.50, 5 atlases  -> moderate_severity  (wins the detection argmax)
      B  det 0.75, donor 0.95, 10 atlases -> high_severity      (the hit that should govern)
    The argmax picks A and grades the target `accessible_moderate_severity`, relieving the dominant
    killer; taking the worst GRADE picks B. Live blast radius over all 504 corpus-20260914 pairs:
    110 of the 439 pairs with an accessible hit (25.1%) were under-graded, 59 of them out of the
    killer entirely."""
    hit_a = {"median_detection_fraction": 0.80, "expressing_donor_fraction": 0.50, "n_datasets_reliable": 5}
    hit_b = {"median_detection_fraction": 0.75, "expressing_donor_fraction": 0.95, "n_datasets_reliable": 10}
    # ANTI-VACUITY: the construction only tests anything if A really is the detection argmax AND the
    # two hits really grade differently. Assert both, so a fixture edit cannot quietly neuter it.
    assert hit_a["median_detection_fraction"] > hit_b["median_detection_fraction"], "A must win the argmax"
    assert S._essential_severity(hit_a) == "moderate_severity"
    assert S._essential_severity(hit_b) == "high_severity"

    rows = pd.concat(
        [
            _tier1_rows([("cardiac muscle cell", 40, 0.80, 0.50)], tissue="heart"),
            _tier1_rows([("hepatocyte", 40, 0.75, 0.95)], tissue="liver"),
        ],
        ignore_index=True,
    )
    rows["n_datasets_reliable"] = [5, 10]
    r = S.classify_sc_normal_expression(rows, origin_tissues=["colon"])
    assert r["sc_normal_essential_veto_grade"] == "accessible_high_severity", (
        "the LIVER hit must govern the grade even though HEART wins the detection argmax"
    )
    assert r["sc_normal_safety_essential_class"] == "critical_organ_liability", "LABEL, not DROP"


def test_veto_grade_single_atlas_argmax_must_not_shadow_a_replicated_hit():
    """THE MECHANISM, not just the symptom. The under-grading is systematic rather than incidental:
    a single-dataset detection fraction is unshrunk and noisy, so it WINS a maximum over detection —
    while `_essential_severity` sends `n_ds <= 1` straight to `low_confidence`. So the selection
    criterion is ANTI-CORRELATED with the grading criterion. Measured live: the argmax hit was
    measured in exactly ONE atlas in 104 of the 110 under-graded pairs (94.5%), against 8.2% of the
    pairs the argmax grades correctly.

    This is FOLR1-OV's real shape, read live from S3: a 1-atlas kidney hit at det 0.708 shadowed
    pulmonary alveolar type 2 at det 0.626 / donor 0.884 across 30 atlases, so a heavily replicated
    lung AND kidney liability graded `accessible_low_confidence` and fired nothing at all."""
    rows = pd.concat(
        [
            _tier1_rows([("kidney collecting duct principal cell", 40, 0.708, 1.0)], tissue="kidney"),
            _tier1_rows([("pulmonary alveolar type 2 cell", 40, 0.626, 0.884)], tissue="lung"),
        ],
        ignore_index=True,
    )
    rows["n_datasets_reliable"] = [1, 30]
    assert _grade(rows, ["ovary"]) == "accessible_high_severity"
    # ANTI-VACUITY: strip the replicated hit and the SAME pool must fall back to low_confidence, which
    # proves the assertion above is carried by the lung hit and not by the kidney hit's detection.
    kidney_only = rows.iloc[[0]].copy()
    assert _grade(kidney_only, ["ovary"]) == "accessible_low_confidence"


def test_essential_severity_rank_is_ordered_by_veto_consequence_then_measurement():
    """The rank map that picks the worst grade must order by VETO CONSEQUENCE first. `ungraded` is
    killer-eligible and `moderate_severity` is not, so ranking ungraded lower would mean that
    DROPPING a column relaxes the killer — thinner data buying a better safety verdict, which is the
    fail-open direction this whole instrument exists to close. Between `high_severity` and `ungraded`
    the veto consequence is identical, so the MEASURED label wins as the more informative one."""
    rank = S._ESSENTIAL_SEVERITY_RANK
    assert rank["ungraded"] > rank["moderate_severity"] > rank["low_confidence"]
    assert rank["high_severity"] > rank["ungraded"]
    # EXHAUSTIVE over what _essential_severity can actually return, so a new rung cannot sort
    # silently as "lowest" — the map is keyed, so an unmapped rung raises KeyError instead.
    returnable = {
        S._essential_severity(rec)
        for rec in [
            {"median_detection_fraction": 0.9, "expressing_donor_fraction": 0.9, "n_datasets_reliable": 4},
            {"median_detection_fraction": 0.4, "expressing_donor_fraction": 0.9, "n_datasets_reliable": 4},
            {"median_detection_fraction": 0.1, "expressing_donor_fraction": 0.9, "n_datasets_reliable": 4},
            {"median_detection_fraction": 0.9, "expressing_donor_fraction": 0.9},
        ]
    }
    assert returnable == {"high_severity", "moderate_severity", "low_confidence", "ungraded"}
    assert returnable <= set(rank), f"unranked severity rung(s): {returnable - set(rank)}"


def test_veto_grade_worst_hit_selection_is_MONOTONE_fail_closed():
    """THE DIRECTION INVARIANT, and the property that makes this change safe to land: adding a hit to
    an accessible pool may only hold the grade or RAISE it, never lower it. Verified live across all
    504 corpus-20260914 pairs — 0 pairs graded lower than before, and none crossed out of
    bbb_protected / not_applicable / origin_tissue — so this is a contract, not a measurement.

    Scoped to ACCESSIBLE hits: adding the first accessible hit to a brain-only pool legitimately
    moves the grade off `bbb_protected`, which is a different axis (the compartment partition)."""
    shapes = [
        ("cardiac muscle cell", "heart", 0.80, 0.50, 5),  # moderate
        ("hepatocyte", "liver", 0.75, 0.95, 10),  # high
        ("pulmonary alveolar type 2 cell", "lung", 0.62, 1.00, 1),  # low_confidence (single atlas)
        ("kidney collecting duct principal cell", "kidney", 0.35, 0.90, 20),  # high via replication
    ]

    def grade_of(subset):
        rows = pd.concat(
            [_tier1_rows([(ct, 40, det, frac)], tissue=tis) for ct, tis, det, frac, _n in subset],
            ignore_index=True,
        )
        rows["n_datasets_reliable"] = [n for *_rest, n in subset]
        g = _grade(rows, ["colon"])
        return S._ESSENTIAL_SEVERITY_RANK[g.removeprefix("accessible_")]

    seen = set()
    for i, extra in enumerate(shapes):
        for r in range(1, len(shapes) + 1):
            for combo in itertools.combinations(shapes, r):
                if extra in combo:
                    continue
                before, after = grade_of(list(combo)), grade_of([*combo, extra])
                assert after >= before, f"adding {extra[0]} LOWERED the grade of {[c[0] for c in combo]}"
                seen.add((before, after))
    # ANTI-VACUITY: the loop must actually observe a STRICT increase somewhere, otherwise `after >= before`
    # would hold trivially on a set of shapes that all grade the same.
    assert any(a > b for b, a in seen), "no strict increase observed — the shapes cannot detect a regression"


def test_veto_grade_severity_matches_the_skills_w3c_grader_thresholds():
    """The rungs are ported from tumor-selectivity's `_sc_normal_essential_severity`
    (det >= 0.50 AND donor >= 0.70 AND >= 2 atlases → high; det < 0.30 OR <= 1 atlas → low). Pinned
    here so the method and that skill cannot drift into disagreeing about the same hit.

    ⚠️ ONE DELIBERATE DIVERGENCE NOW EXISTS — see the companion test below. The replication-dominant
    path is NOT yet in the skill's copy, so for det in [0.40, 0.50) with donor >= 0.70 and >= 15
    atlases the two graders DISAGREE, method = high vs skill = moderate. That divergence is pinned
    explicitly rather than left to be discovered, and the skills-side port is tracked as follow-up.
    This test previously claimed to prevent exactly that drift while its fixture used
    n_datasets_reliable = 4 — below the replication floor — so it would have stayed green through the
    divergence. The bound is now exercised on BOTH sides."""
    base = {"median_detection_fraction": 0.60, "expressing_donor_fraction": 0.80, "n_datasets_reliable": 4}
    assert S._essential_severity(base) == "high_severity"
    assert S._essential_severity({**base, "n_datasets_reliable": 1}) == "low_confidence"
    assert S._essential_severity({**base, "median_detection_fraction": 0.25}) == "low_confidence"
    # det >= 0.50 but donor consistency below the HIGH bar, still replicated → moderate
    assert S._essential_severity({**base, "expressing_donor_fraction": 0.50}) == "moderate_severity"
    # det in [0.30, 0.50) with ORDINARY replication → moderate, not low. Still shared with the skill:
    # n_datasets_reliable = 4 is far below REPLICATION_DOMINANT_N_DATASETS, so the new path is not
    # reachable here and this rung means the same thing on both sides.
    assert S._essential_severity({**base, "median_detection_fraction": 0.40}) == "moderate_severity"
    assert S._essential_severity({**base, "median_detection_fraction": 0.40, "n_datasets_reliable": 14}) == (
        "moderate_severity"
    ), "one atlas below the floor must still be the SHARED verdict — the divergence starts at the floor"


def test_replication_dominant_path_is_the_only_divergence_from_the_skills_grader():
    """DIRECTION + BOUNDS on the replication-dominant rung, and an explicit map of where the method
    now disagrees with tumor-selectivity's ported copy.

    THE DEFECT IT REPAIRS, measured live over all 504 corpus-20260914 pairs: MSLN-PAAD carries a
    pulmonary alveolar type 1 hit at det 0.413 / donor 0.881 across 26 INDEPENDENT ATLASES — the
    strongest replication anywhere in the corpus — and graded `moderate_severity`, relieving the
    dominant BiTE/TCE killer, while a 2-atlas hit at det 0.51 fires it. Overwhelming independent
    replication cannot lose to a single-threshold detection miss.

    Only the DETECTION line is tradeable. Donor consistency is not (replication says a signal is
    REAL, not that it is CONSISTENT ACROSS DONORS), and the low band is not rescuable (replication
    makes a weak signal credible, not large)."""
    msln = {"median_detection_fraction": 0.413, "expressing_donor_fraction": 0.881, "n_datasets_reliable": 26}
    assert S._essential_severity(msln) == "high_severity", "the named live defect must now grade high"

    # --- the three bounds, each probed from BOTH sides so none of them is vacuous ---
    at_det_floor = {**msln, "median_detection_fraction": S.REPLICATION_DOMINANT_DET_FLOOR}
    below_det_floor = {**msln, "median_detection_fraction": S.REPLICATION_DOMINANT_DET_FLOOR - 0.01}
    assert S._essential_severity(at_det_floor) == "high_severity"
    assert S._essential_severity(below_det_floor) == "moderate_severity", (
        "the relaxation is BOUNDED — an open-ended path gated at the moderate floor promotes 350/504"
    )
    at_nds_floor = {**msln, "n_datasets_reliable": S.REPLICATION_DOMINANT_N_DATASETS}
    below_nds_floor = {**msln, "n_datasets_reliable": S.REPLICATION_DOMINANT_N_DATASETS - 1}
    assert S._essential_severity(at_nds_floor) == "high_severity"
    assert S._essential_severity(below_nds_floor) == "moderate_severity", (
        "the atlas floor is the corpus p90, not the median — a floor of 5 would promote 364/504"
    )
    # donor consistency is NOT tradeable, however extreme the replication
    assert S._essential_severity({**msln, "expressing_donor_fraction": 0.69, "n_datasets_reliable": 30}) == (
        "moderate_severity"
    ), "replication must not buy its way past HIGH_LIABILITY_DONOR_FRACTION"
    # the low band is NOT rescuable, however extreme the replication
    assert S._essential_severity({**msln, "median_detection_fraction": 0.29, "n_datasets_reliable": 30}) == (
        "low_confidence"
    ), "replication makes a weak signal credible, not large"


def test_veto_grade_never_reclassifies_the_class_itself():
    """LABEL, NOT DROP: for every shape below the grade changes while
    sc_normal_safety_essential_class stays exactly what it was before this field existed."""
    cases = [
        (_tier1_rows([("cardiac muscle cell", 40, 0.90, 0.95)], tissue="heart"), ["colon"], "critical_organ_liability"),
        (
            _tier1_rows([("neuron of the forebrain", 40, 0.97, 1.0)], tissue="brain"),
            ["colon"],
            "critical_organ_liability",
        ),
        (_tier1_rows([("cardiac muscle cell", 40, 0.90, 0.95)], tissue="heart"), ["heart"], "origin_tissue_liability"),
    ]
    for rows, origin, expected_class in cases:
        r = S.classify_sc_normal_expression(rows, origin_tissues=origin)
        assert r["sc_normal_safety_essential_class"] == expected_class
        assert r["sc_normal_essential_veto_grade"] != "none", "the grade is a separate vocabulary"


@pytest.mark.xfail(
    strict=True,
    reason="KNOWN GAP, deliberately not fixed in the veto-grade change: the "
    "`kidney proximal tubule` prefix matches no real Census label. Tightening the essential "
    "vocabulary moves the CLASS on an unmeasured set of targets and needs its own backtest.",
)
def test_kidney_proximal_tubule_prefix_misses_the_real_census_labels():
    """FAIL-OPEN IN THE ESSENTIAL VOCABULARY — found while picking a fixture label for the veto-grade
    tests, and pinned here so it cannot be forgotten.

    `SAFETY_ESSENTIAL_CELL_TYPE_PREFIXES` contains the CONTIGUOUS multi-word prefix
    `"kidney proximal tubule"`. The Cell Ontology labels Census actually uses are
    `epithelial cell of proximal tubule[ segment N]` (reversed word order, no "kidney") and
    `kidney proximal convoluted tubule epithelial cell` ("convoluted" interposed). Neither matches,
    so the prefix as written appears to cover a label that does not occur in the data while missing
    the two that do — and the proximal tubule is THE canonical kidney-toxicity compartment.

    MEASURED on corpus-20260914, DPEP1-COADREAD (a kidney brush-border dipeptidase):
      - `epithelial cell of proximal tubule`  det 0.479, **22 independent atlases** → NOT flagged
      - `epithelial cell of proximal tubule segment 1`  det 0.710 → NOT flagged
      - the only kidney label that DID flag: `kidney loop of Henle descending limb epithelial cell`
        at det 0.115, i.e. below even the 0.20 off-origin floor
    Its `critical_organ_liability` therefore names **pancreas / pancreatic acinar cell**, and the
    most heavily replicated kidney signal in the package is invisible to the safety-essential class.
    Only 10 of 513 corpus packages mention a proximal-tubule label at all, and the stored
    `per_cell_type_top` is truncated to 15 rows, so 10 is a FLOOR on the blast radius, not a count.

    Direction note: unlike the veto-grade change this test sits beside, closing this gap makes the
    veto fire MORE, so it cannot be justified by the same "92.9% is too blunt" argument and must be
    argued on its own evidence.
    """
    assert S._is_safety_essential("epithelial cell of proximal tubule")
    assert S._is_safety_essential("epithelial cell of proximal tubule segment 1")
    assert S._is_safety_essential("kidney proximal convoluted tubule epithelial cell")


def test_veto_grade_is_a_STRICT_REFINEMENT_of_the_safety_essential_class():
    """THE CONTRACT BETWEEN THE TWO FIELDS, pinned. The grade must partition the class, never cross it:

        accessible_* / bbb_protected  <=>  critical_organ_liability
        origin_tissue                 <=>  origin_tissue_liability
        not_applicable                <=>  none

    Verified on live data before being pinned here: a run of this method against S3 over all 504
    corpus-20260914 (target, indication) pairs produced ZERO crossings — the cross-tab of class x grade
    has exactly 6 populated cells, one per arm, with the 468 critical calls splitting
    223 accessible_high_severity / 145 accessible_low_confidence / 71 accessible_moderate_severity /
    29 bbb_protected. A crossing would mean the veto and its own grade disagree about whether there IS a
    liability, which is the one thing a graded companion may never do."""
    ARMS = {
        "critical_organ_liability": {
            "accessible_high_severity",
            "accessible_moderate_severity",
            "accessible_low_confidence",
            "accessible_ungraded",
            "bbb_protected",
        },
        "origin_tissue_liability": {"origin_tissue"},
        "none": {"not_applicable"},
    }
    cases = [
        # (rows, origin_tissues) spanning every arm, incl. the mixed and sub-floor shapes
        (_tier1_rows([("cardiac muscle cell", 40, 0.90, 0.95)], tissue="heart"), ["colon"]),
        (_tier1_rows([("neuron of the forebrain", 40, 0.97, 1.0)], tissue="brain"), ["colon"]),
        (_tier1_rows([("cardiac muscle cell", 40, 0.90, 0.95)], tissue="heart"), ["heart"]),
        (_tier1_rows([("fibroblast", 40, 0.90, 0.95)], tissue="colon"), ["colon"]),
        (_tier1_rows([("hepatocyte", 40, 0.03, 0.10)], tissue="liver"), ["colon"]),  # below the flag floor
        (
            pd.concat(
                [
                    _tier1_rows([("neuron of the forebrain", 40, 0.97, 1.0)], tissue="brain"),
                    _tier1_rows([("hepatocyte", 40, 0.55, 0.80)], tissue="liver"),
                ],
                ignore_index=True,
            ),
            ["colon"],
        ),
        (
            pd.concat(
                [
                    _tier1_rows([("cardiac muscle cell", 40, 0.90, 0.95)], tissue="heart"),
                    _tier1_rows([("enterocyte", 40, 0.80, 0.90)], tissue="colon"),
                ],
                ignore_index=True,
            ),
            ["colon"],  # origin hit AND off-origin hit → off_origin dominates on BOTH fields
        ),
    ]
    for rows, origin in cases:
        r = S.classify_sc_normal_expression(rows, origin_tissues=origin)
        cls, grade = r["sc_normal_safety_essential_class"], r["sc_normal_essential_veto_grade"]
        assert grade in ARMS[cls], f"grade {grade!r} crosses class arm {cls!r} (origin={origin})"
    # and the coverage-gap branch keeps its own spelling on BOTH fields
    du = S._data_unavailable_class()
    assert du["sc_normal_safety_essential_class"] == "data_unavailable"
    assert du["sc_normal_essential_veto_grade"] == "data_unavailable"
