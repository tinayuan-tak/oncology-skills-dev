"""G11 (tumor-presence expert review): structured malignant-annotation provenance.

The single-cell malignant call's reliability varies by product — an explicit curated 'Cancer cell' label
(CRC/LuCA) and an inferCNV/CNA-validated call (3CA) are stronger than a phenotype heuristic (STAD:
Epithelial∩GC, no inferCNV), and a pan-entity-pooled cube (3CA kidney/ovarian; LUAD via the NSCLC
umbrella) is not purified to the queried disease. Previously only the free-text product_id hinted at
this. Now `malignant_annotation_method` + `entity_purity` are emitted as structured fields so downstream
(claim-vector confidence) can read a weaker provenance down. Verdict-inert. Values are derived strictly
from the atlas provenance documented in INDICATION_TO_PRODUCT — not guessed (LUSC's undocumented method
is honestly `unspecified`).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]   # the repo root of THIS checkout (worktree-safe)
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from methods.sc_tumor_expression_celltype import read as R  # noqa: E402


def _prov(ind):
    return R._malignant_annotation_provenance(ind)


def test_curated_entity_specific_crc():
    assert _prov("COADREAD") == {"malignant_annotation_method": "curated", "entity_purity": "entity_specific"}


def test_infercnv_entity_specific_pdac_hnsc():
    for ind in ("PAAD", "HNSC"):
        assert _prov(ind)["malignant_annotation_method"] == "infercnv"
        assert _prov(ind)["entity_purity"] == "entity_specific"


def test_infercnv_multi_entity_pooled_kirc_ov():
    for ind in ("KIRC", "OV"):
        assert _prov(ind) == {"malignant_annotation_method": "infercnv", "entity_purity": "multi_entity_pooled"}


def test_curated_entity_specific_brca():
    # Wu/Swarbrick breast atlas (GSE176078): malignant = 'Cancer Epithelial' author annotation (verbatim),
    # a native breast primary-tumour cube → curated + entity_specific (not pooled, not inferCNV/phenotype).
    assert R.INDICATION_TO_PRODUCT["BRCA"] == "sc-pseudobulk-tumor-brca-wu-v1"
    assert _prov("BRCA") == {"malignant_annotation_method": "curated", "entity_purity": "entity_specific"}


def test_phenotype_proxy_stad():
    # the flagged case: gastric malignant = Epithelial∩GC phenotype, NO inferCNV → weaker provenance
    assert _prov("STAD")["malignant_annotation_method"] == "phenotype_proxy"
    assert _prov("STAD")["entity_purity"] == "entity_specific"


def test_luad_is_multi_entity_via_nsclc_umbrella():
    # LUAD is served by the NSCLC-umbrella LuCA product → curated but NOT LUAD-purified
    assert _prov("LUAD") == {"malignant_annotation_method": "curated", "entity_purity": "multi_entity_pooled"}
    # NSCLC itself is the native entity of that atlas → entity_specific
    assert _prov("NSCLC")["entity_purity"] == "entity_specific"


def test_undocumented_lusc_method_is_unspecified_not_guessed():
    # LUSC has a dedicated cube but its malignant-call method is not documented → honest 'unspecified'
    assert _prov("LUSC")["malignant_annotation_method"] == "unspecified"
    assert _prov("LUSC")["entity_purity"] == "entity_specific"


def test_unwired_indication_is_unspecified():
    assert _prov("SKCM") == {"malignant_annotation_method": "unspecified", "entity_purity": "unspecified"}


def test_every_wired_product_has_a_documented_method():
    """Guard: every product in INDICATION_TO_PRODUCT except the known-undocumented LUSC cube has an
    explicit annotation method (so a NEW product addition can't silently default to 'unspecified')."""
    known_undocumented = {"sc-pseudobulk-donor-celltype-lusc-v1"}
    for product in set(R.INDICATION_TO_PRODUCT.values()):
        if product in known_undocumented:
            continue
        assert product in R._PRODUCT_ANNOTATION_METHOD, f"{product} missing a documented annotation method"
