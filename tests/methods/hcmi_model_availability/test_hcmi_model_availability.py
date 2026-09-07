"""Tests for hcmi_model_availability — the per-indication translational model-availability signal (#1)."""

from __future__ import annotations

import pytest

from methods.hcmi_model_availability import (
    read_genotype_matched_model,
    read_model_availability,
)
from methods.hcmi_model_availability.cli import (
    _FUNCTIONAL_CODING_CLASSES,
    _availability_class,
    _model_id_from_barcode,
    aggregate_genotype_matched,
    aggregate_model_availability,
    crosswalk_indication,
    genotype_matched_class,
)


# ── crosswalk unit tests (the (primary_site, disease_type) -> indication judgment) ──────────────────
@pytest.mark.parametrize(
    "ps,dt,expected",
    [
        # ── core set (pre-existing v1) ──────────────────────────────────────────────────────────────────
        ("Colon", "Adenomas and Adenocarcinomas", "COADREAD"),
        ("Rectum", "Adenomas and Adenocarcinomas", "COADREAD"),
        ("Rectosigmoid junction", "Adenomas and Adenocarcinomas", "COADREAD"),
        ("Pancreas", "Ductal and Lobular Neoplasms", "PAAD"),
        ("Pancreas", "Adenomas and Adenocarcinomas", "PAAD"),
        ("Bronchus and lung", "Adenomas and Adenocarcinomas", "NSCLC"),
        ("Bronchus and lung", "Squamous Cell Neoplasms", "NSCLC"),
        ("Stomach", "Adenomas and Adenocarcinomas", "GC"),
        # ── broadened set (2026-08-24): unambiguous single-histology categories now MAPPED ──────────────
        ("Esophagus", "Adenomas and Adenocarcinomas", "ESCA"),
        ("Breast", "Ductal and Lobular Neoplasms", "BRCA"),  # was None pre-broaden
        ("Breast", "Complex Epithelial Neoplasms", "BRCA"),
        ("Skin", "Nevi and Melanomas", "SKCM"),  # was None pre-broaden
        ("Ovary", "Cystic, Mucinous and Serous Neoplasms", "OV"),
        ("Ovary", "Adenomas and Adenocarcinomas", "OV"),
        ("Bladder", "Transitional Cell Papillomas and Carcinomas", "BLCA"),
        ("Corpus uteri", "Adenomas and Adenocarcinomas", "UCEC"),
        ("Corpus uteri", "Cystic, Mucinous and Serous Neoplasms", "UCEC"),
        ("Other and unspecified parts of mouth", "Squamous Cell Neoplasms", "HNSC"),
        ("Larynx", "Squamous Cell Neoplasms", "HNSC"),
        ("Thyroid gland", "Adenomas and Adenocarcinomas", "THCA"),
        # ── DELIBERATELY LEFT UNMAPPED -> None (conservative: never mis-assign) ──────────────────────────
        ("Brain", "Gliomas", None),  # grade-indeterminate: GBM vs LGG
        ("Liver and intrahepatic bile ducts", "Adenomas and Adenocarcinomas", None),  # cholangio, not LIHC
        ("Kidney", "Adenomas and Adenocarcinomas", None),  # RCC subtype KIRC/KIRP/KICH unresolvable
        ("Other and unspecified parts of biliary tract", "Adenomas and Adenocarcinomas", None),  # no CHOL code
        ("Small intestine", "Adenomas and Adenocarcinomas", None),  # no SBA code; not COADREAD
        ("Ovary", "Complex Mixed and Stromal Neoplasms", None),  # sex-cord stromal, non-epithelial
        ("Skin", "Squamous Cell Neoplasms", None),  # cutaneous SCC, not melanoma
        ("Eye and adnexa", "Nevi and Melanomas", None),  # uveal melanoma, not cutaneous SKCM
        ("Uterus, NOS", "Adenomas and Adenocarcinomas", None),  # corpus-vs-cervix ambiguous site
        ("Colon", "Cystic, Mucinous and Serous Neoplasms", None),  # non-adenocarcinoma colon histology
        ("Thyroid gland", "Squamous Cell Neoplasms", None),  # thyroid SCC, not adeno
        (None, None, None),
    ],
)
def test_crosswalk_maps_core_indications_and_rejects_unmapped(ps, dt, expected):
    assert crosswalk_indication(ps, dt) == expected


def test_availability_class_thresholds():
    assert _availability_class(209) == "deep_model_coverage"
    assert _availability_class(50) == "deep_model_coverage"
    assert _availability_class(49) == "moderate_model_coverage"
    assert _availability_class(15) == "moderate_model_coverage"
    assert _availability_class(14) == "sparse_model_coverage"
    assert _availability_class(0) == "sparse_model_coverage"


# ── hermetic reader tests (local product_path, no S3) ────────────────────────────────────────────────
@pytest.fixture
def product(tmp_path):
    import pandas as pd

    p = tmp_path / "hcmi_model_availability.parquet"
    pd.DataFrame(
        [
            {
                "indication": "COADREAD",
                "n_patient_derived_models": 209,
                "model_availability_class": "deep_model_coverage",
                "source": "HCMI-CMDC-DR45",
                "primary_site_breakdown": "Colon|Adenomas and Adenocarcinomas=153",
            },
            {
                "indication": "GC",
                "n_patient_derived_models": 25,
                "model_availability_class": "moderate_model_coverage",
                "source": "HCMI-CMDC-DR45",
                "primary_site_breakdown": "Stomach|Adenomas and Adenocarcinomas=25",
            },
        ]
    ).to_parquet(p)
    return str(p)


def test_read_hit_returns_summary(product):
    r = read_model_availability("COADREAD", product_path=product)
    assert r["model_availability_class"] == "deep_model_coverage"
    assert r["n_patient_derived_models"] == 209
    assert r["source"] == "HCMI-CMDC-DR45"


def test_read_unmapped_indication_is_graceful(product):
    r = read_model_availability("PRAD", product_path=product)  # not in the crosswalk / product
    assert r["model_availability_class"] == "data_unavailable"
    assert r["n_patient_derived_models"] == 0
    assert "not in the HCMI" in r["_missing_reason"]


def test_read_missing_product_is_graceful(tmp_path):
    r = read_model_availability("COADREAD", product_path=str(tmp_path / "nope.parquet"))
    assert r["model_availability_class"] == "data_unavailable"
    assert "no HCMI model-availability product" in r["_missing_reason"]


# ── live biology-gate (skips if HCMI source unreachable) ─────────────────────────────────────────────
def test_hcmi_gi_heavy_composition_biology_gate():
    """HCMI is documented GI/colorectal-heavy: COADREAD must be the deepest-covered core indication."""
    try:
        rows = aggregate_model_availability()
    except Exception as e:  # noqa: BLE001 — no S3 creds in CI → skip, not fail
        pytest.skip(f"HCMI source unreachable: {e}")
    if not rows:
        pytest.skip("HCMI source returned no rows (unreachable)")
    by = {r["indication"]: r for r in rows}
    assert "COADREAD" in by, "COADREAD should map from HCMI colon/rectum adenocarcinoma models"
    assert by["COADREAD"]["model_availability_class"] == "deep_model_coverage"
    # COADREAD is the deepest-covered (GI-heavy cohort)
    assert by["COADREAD"]["n_patient_derived_models"] == max(r["n_patient_derived_models"] for r in rows)
    # broadened crosswalk (2026-08-24): a newly-mapped indication (breast BRCA + skin melanoma SKCM) now
    # appears — the crosswalk is no longer the 4-core GI/lung set.
    assert "BRCA" in by and by["BRCA"]["n_patient_derived_models"] > 0
    assert "SKCM" in by and by["SKCM"]["n_patient_derived_models"] > 0
    assert len(by) >= 8, "broadened crosswalk should map well beyond the original 4 core indications"


# ── generic-dispatch contract (2026-08-14): compose-dashboard calls fn(target=, indication=) ──────────
def test_generic_dispatch_contract_accepts_target_kwarg(product):
    """_live_readers._generic_dispatch calls every reader as fn(target=, indication=). The reader must
    accept target (ignored — model availability is target-independent) or the card silently errors to
    data_unavailable in live compositions."""
    r = read_model_availability(target="KRAS", indication="COADREAD", product_path=product)
    assert r["model_availability_class"] == "deep_model_coverage"
    assert r["n_patient_derived_models"] == 209


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# GENOTYPE-MATCHED-MODEL (R2.10 v2): per-(gene, indication) — "do HCMI models carry an alteration in X?"
# ══════════════════════════════════════════════════════════════════════════════════════════════════


# ── unit: the coarse-match thresholds + the MAF-barcode -> model-id derivation (the join key) ────────
def test_genotype_matched_class_thresholds():
    assert genotype_matched_class(5) == "matched_deep"
    assert genotype_matched_class(71) == "matched_deep"
    assert genotype_matched_class(4) == "matched_sparse"
    assert genotype_matched_class(1) == "matched_sparse"
    assert genotype_matched_class(0) == "none"


@pytest.mark.parametrize(
    "barcode,expected",
    [
        # HCM-<TSS>-<Patient>-<Sample>-<portion...> -> first 4 fields == case-JSON SubjectData.submitter_id
        ("HCM-STAN-0846-C20-01D-04D-A937-36", "HCM-STAN-0846-C20"),
        ("HCM-CSHL-0257-C18-06A-11D-A78W-36", "HCM-CSHL-0257-C18"),
        ("HCM-BROD-1129-C56", "HCM-BROD-1129-C56"),  # already model-length
        ("HCM-STAN", None),  # too few fields -> unmappable
        (None, None),
        ("", None),
    ],
)
def test_model_id_from_barcode(barcode, expected):
    assert _model_id_from_barcode(barcode) == expected


def test_functional_coding_classes_are_the_coarse_set():
    # COARSE = any functional coding class; Silent / RNA / intronic / UTR / IGR are NOT a match.
    assert "Missense_Mutation" in _FUNCTIONAL_CODING_CLASSES
    assert "Splice_Site" in _FUNCTIONAL_CODING_CLASSES
    assert "Frame_Shift_Del" in _FUNCTIONAL_CODING_CLASSES
    assert "Silent" not in _FUNCTIONAL_CODING_CLASSES
    assert "3'UTR" not in _FUNCTIONAL_CODING_CLASSES
    assert "Intron" not in _FUNCTIONAL_CODING_CLASSES


# ── hermetic reader tests (local product_path, no S3) ────────────────────────────────────────────────
@pytest.fixture
def genotype_product(tmp_path):
    import pandas as pd

    p = tmp_path / "hcmi_genotype_matched_model.parquet"
    pd.DataFrame(
        [
            {
                "gene_symbol": "KRAS",
                "indication": "PAAD",
                "n_models_in_indication": 115,
                "n_models_with_alteration": 71,
                "n_models_with_recurrent_hotspot": 68,
                "variant_classes_present": "Missense_Mutation",
                "hgvsp_examples": "p.G12D; p.G12V",
                "genotype_matched_class": "matched_deep",
                "source": "HCMI-CMDC-DR45",
            },
            {
                "gene_symbol": "KRAS",
                "indication": "GC",
                "n_models_in_indication": 25,
                "n_models_with_alteration": 2,
                "n_models_with_recurrent_hotspot": 2,
                "variant_classes_present": "Missense_Mutation",
                "hgvsp_examples": "p.G12D; p.A146V",
                "genotype_matched_class": "matched_sparse",
                "source": "HCMI-CMDC-DR45",
            },
            {
                "gene_symbol": "KRAS",
                "indication": "ALL",
                "n_models_in_indication": 631,
                "n_models_with_alteration": 129,
                "n_models_with_recurrent_hotspot": 121,
                "variant_classes_present": "Missense_Mutation",
                "hgvsp_examples": "p.G12D",
                "genotype_matched_class": "matched_deep",
                "source": "HCMI-CMDC-DR45",
            },
            # COADREAD present as a COVERED indication (with a driver row) so a MISS on a different gene in
            # COADREAD is an honest 'none', distinguishable from an uncovered indication → data_unavailable.
            {
                "gene_symbol": "APC",
                "indication": "COADREAD",
                "n_models_in_indication": 209,
                "n_models_with_alteration": 140,
                "n_models_with_recurrent_hotspot": 40,
                "variant_classes_present": "Frame_Shift_Del",
                "hgvsp_examples": "p.R1450*",
                "genotype_matched_class": "matched_deep",
                "source": "HCMI-CMDC-DR45",
            },
        ]
    ).to_parquet(p)
    return str(p)


def test_genotype_read_deep_hit(genotype_product):
    r = read_genotype_matched_model(target="KRAS", indication="PAAD", product_path=genotype_product)
    assert r["genotype_matched_class"] == "matched_deep"
    assert r["n_models_with_alteration"] == 71
    assert r["n_models_with_recurrent_hotspot"] == 68  # cohort-recurrent-hotspot column (#2)
    assert r["n_models_in_indication"] == 115


def test_genotype_read_sparse_hit(genotype_product):
    r = read_genotype_matched_model(target="KRAS", indication="GC", product_path=genotype_product)
    assert r["genotype_matched_class"] == "matched_sparse"
    assert r["n_models_with_alteration"] == 2


def test_genotype_read_defaults_indication_to_ALL_rollup(genotype_product):
    r = read_genotype_matched_model(target="KRAS", product_path=genotype_product)
    assert r["n_models_in_indication"] == 631
    assert r["n_models_with_alteration"] == 129
    assert r["n_models_with_recurrent_hotspot"] == 121


def test_genotype_read_absent_gene_in_covered_indication_is_honest_none(genotype_product):
    # gene absent but the indication IS covered (COADREAD has an APC row) → honest NEGATIVE (none),
    # NOT data_unavailable: HCMI COADREAD models exist, none carry a functional alteration in this gene.
    r = read_genotype_matched_model(target="ZZZ3FAKE", indication="COADREAD", product_path=genotype_product)
    assert r["genotype_matched_class"] == "none"
    assert r["n_models_with_alteration"] == 0
    assert "no HCMI model" in r["_missing_reason"]


def test_genotype_read_uncovered_indication_is_data_unavailable(genotype_product):
    # PRAD is NOT in the HCMI genotype crosswalk → data_unavailable (a coverage GAP), NOT 'none'. A 'none'
    # here would falsely assert "no HCMI model carries the alteration" when we simply have no PRAD models.
    r = read_genotype_matched_model(target="KRAS", indication="PRAD", product_path=genotype_product)
    assert r["genotype_matched_class"] == "data_unavailable"
    assert "not in the HCMI indication crosswalk" in r["_missing_reason"]


def test_genotype_read_missing_product_is_data_unavailable(tmp_path):
    r = read_genotype_matched_model(target="KRAS", indication="PAAD", product_path=str(tmp_path / "nope.parquet"))
    assert r["genotype_matched_class"] == "data_unavailable"
    assert "no HCMI genotype-matched-model product" in r["_missing_reason"]


# ── live biology-gate (skips if HCMI source unreachable) ─────────────────────────────────────────────
def test_genotype_kras_is_matched_deep_in_pancreatic_and_colorectal():
    """KRAS is a canonical PDAC/CRC driver — HCMI PAAD + COADREAD models MUST carry it deeply."""
    try:
        rows, meta = aggregate_genotype_matched()
    except Exception as e:  # noqa: BLE001 — no S3 creds in CI → skip, not fail
        pytest.skip(f"HCMI source unreachable: {e}")
    if not rows:
        pytest.skip("HCMI source returned no rows (unreachable)")
    by = {(r["gene_symbol"], r["indication"]): r for r in rows}
    assert ("KRAS", "PAAD") in by and by[("KRAS", "PAAD")]["genotype_matched_class"] == "matched_deep"
    assert ("KRAS", "COADREAD") in by and by[("KRAS", "COADREAD")]["genotype_matched_class"] == "matched_deep"
    # denominators reuse v1's per-indication distinct-model counts verbatim
    assert by[("KRAS", "PAAD")]["n_models_in_indication"] == 115
    assert meta["n_maf_files"] == 923 and meta["n_cases_walked"] == 805
    # recurrent-hotspot column (#2): KRAS is dominated by canonical G12/G13/Q61 hotspots, so almost every
    # altered PAAD model carries a cohort-recurrent HGVSp -> the recurrent count is a large fraction of
    # (and never exceeds) the altered count.
    kp = by[("KRAS", "PAAD")]
    assert 0 < kp["n_models_with_recurrent_hotspot"] <= kp["n_models_with_alteration"]


def test_genotype_dispatch_contract_accepts_target_and_indication(genotype_product):
    r = read_genotype_matched_model(target="KRAS", indication="PAAD", product_path=genotype_product)
    assert r["genotype_matched_class"] == "matched_deep"


# ══════════════════════════════════════════════════════════════════════════════════════════════════
# INDICATION NORMALIZATION (2026-09-02): OncoTree LEAF codes → the products' COMPOSITE indication keys.
# Before this, an exact-match read MISSED common leaves (EGFR/LUAD reported 0 models though 27 NSCLC HCMI
# models exist; ERBB2/STAD reported 0 though GC=25) — a false "no models" the organoid leg never made.
# ══════════════════════════════════════════════════════════════════════════════════════════════════
from methods.hcmi_model_availability.read import normalize_indication


@pytest.mark.parametrize(
    "leaf,composite",
    [
        ("LUAD", "NSCLC"),
        ("LUSC", "NSCLC"),
        ("STAD", "GC"),
        ("ESCC", "ESCA"),
        ("COAD", "COADREAD"),
        ("READ", "COADREAD"),
        ("PDAC", "PAAD"),
        ("luad", "NSCLC"),  # case-insensitive
        ("NSCLC", "NSCLC"),
        ("COADREAD", "COADREAD"),
        ("GC", "GC"),  # already-composite: idempotent no-op
        ("PRAD", "PRAD"),
        ("GBM", "GBM"),  # not in the alias map → passthrough unchanged
        (None, None),
        ("", ""),
    ],
)
def test_normalize_indication_leaf_to_composite(leaf, composite):
    assert normalize_indication(leaf) == composite


def test_availability_leaf_code_resolves_via_normalization(product):
    # STAD → GC (the fixture's gastric row): a LEAF query now resolves to the composite bucket instead of
    # falsely reporting data_unavailable.
    r = read_model_availability("STAD", product_path=product)
    assert r["model_availability_class"] == "moderate_model_coverage"
    assert r["n_patient_derived_models"] == 25


def test_availability_leaf_normalizes_but_composite_absent_notes_the_mapping(product):
    # LUAD → NSCLC, but the fixture product has no NSCLC row → honest data_unavailable, and the reason
    # discloses the leaf→composite mapping that was attempted (so it reads as coverage, not a typo).
    r = read_model_availability("LUAD", product_path=product)
    assert r["model_availability_class"] == "data_unavailable"
    assert "LUAD→NSCLC" in r["_missing_reason"]


def test_genotype_leaf_code_resolves_via_normalization(genotype_product):
    # STAD → GC: KRAS is a matched_sparse hit in the fixture's GC row; a leaf query now resolves it.
    r = read_genotype_matched_model(target="KRAS", indication="STAD", product_path=genotype_product)
    assert r["genotype_matched_class"] == "matched_sparse"
    assert r["n_models_with_alteration"] == 2
