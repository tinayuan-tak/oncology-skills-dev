"""Wiring + classifier regression for spatial_region_rna (GeoMx WTA region-RNA)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.spatial_region_rna import read as RR  # noqa: E402
from methods.spatial_region_rna import stats as ST  # noqa: E402


def test_hnsc_wired_to_geomx_wta():
    assert RR.INDICATION_TO_REGION_RNA["HNSC"] == "spatial-region-rna-hnsc-v1"


def test_nsclc_histologies_wired_to_geomx_rna():
    # all three lung histologies share the one NSCLC GeoMx Cancer Transcriptome Atlas product (GSE174743)
    for code in ("NSCLC", "LUAD", "LUSC"):
        assert RR.INDICATION_TO_REGION_RNA[code] == "spatial-region-rna-nsclc-v1"


def test_product_resolves_to_catalog_s3_uri():
    from methods.catalog_query.read import s3_uri_for

    assert s3_uri_for("spatial-region-rna-hnsc-v1").endswith("spatial-region-rna-hnsc-v1/spatial_region_rna.parquet")
    assert s3_uri_for("spatial-region-rna-nsclc-v1").endswith("spatial-region-rna-nsclc-v1/spatial_region_rna.parquet")


def test_coadread_wired_to_geomx_wta():
    assert RR.INDICATION_TO_REGION_RNA["COADREAD"] == "spatial-region-rna-coadread-v1"


def test_paad_wired_to_geomx_wta():
    assert RR.INDICATION_TO_REGION_RNA["PAAD"] == "spatial-region-rna-paad-v1"


def test_brca_wired_to_geomx_wta():
    # breast — GeoMx WTA (GSE327983 HER2+ metastatic; PanCK/CD45 segments, Q3-normalized)
    # (catalog-S3-resolution parity is covered once spatial-region-rna-brca-v1 lands in data-catalog)
    assert RR.INDICATION_TO_REGION_RNA["BRCA"] == "spatial-region-rna-brca-v1"


def test_unmapped_indication_is_data_unavailable():
    out = RR.read_spatial_region_rna("EGFR", "STAD")  # no region-RNA product for STAD
    assert out["spatial_rna_class"] == "data_unavailable"
    assert out["product_id"] is None


def _rows(spec):
    """spec: list of (donor, compartment, abundance_lcpm)."""
    return [{"donor_id": d, "compartment": c, "abundance_lcpm": a, "detected": True} for (d, c, a) in spec]


def test_classify_tumour_enriched():
    # KRT-like: strongly tumour-enriched squamous epithelium
    rows = _rows([("d1", "TUMOUR", 11.8), ("d1", "TME", 8.2), ("d2", "TUMOUR", 11.0), ("d2", "TME", 7.5)])
    c = ST.classify_region_rna(ST.summarize_rna(rows), rows)
    assert c["spatial_rna_class"] == "tumour_enriched_rna"
    assert c["tumour_vs_tme_delta"] and c["tumour_vs_tme_delta"] > 0


def test_classify_tme_enriched():
    # COL1A1/PECAM1-like: TME-enriched (stromal/endothelial)
    rows = _rows([("d1", "TUMOUR", 7.8), ("d1", "TME", 11.6), ("d2", "TUMOUR", 5.4), ("d2", "TME", 7.4)])
    assert ST.classify_region_rna(ST.summarize_rna(rows), rows)["spatial_rna_class"] == "tme_enriched_rna"


def test_classify_no_compartment_preference():
    # EPCAM-like small delta in HNSC; two donors so it clears the _MIN_DONORS power floor and grades
    # the measured class rather than `underpowered`.
    rows = _rows([("d1", "TUMOUR", 5.16), ("d1", "TME", 4.93), ("d2", "TUMOUR", 5.16), ("d2", "TME", 4.93)])
    assert (
        ST.classify_region_rna(ST.summarize_rna(rows), rows)["spatial_rna_class"]
        == "tumour_present_no_compartment_preference"
    )


def test_underpowered_single_donor_is_not_minted_as_measured():
    # SAME strongly tumour-enriched values, one donor vs two. The power floor (_MIN_DONORS = 2) must
    # grade the single-donor case `underpowered` — the "we could barely look" band — while two donors
    # grade the real tumour_enriched_rna. Anti-vacuity: the two arms MUST differ, so the floor (not
    # the values) is what drives the underpowered verdict; a data_unavailable case (no rows) is a
    # THIRD, distinct outcome ("we could not look").
    one = _rows([("d1", "TUMOUR", 11.8), ("d1", "TME", 8.2)])
    two = _rows([("d1", "TUMOUR", 11.8), ("d1", "TME", 8.2), ("d2", "TUMOUR", 11.0), ("d2", "TME", 7.5)])
    c1 = ST.classify_region_rna(ST.summarize_rna(one), one)
    c2 = ST.classify_region_rna(ST.summarize_rna(two), two)
    assert c1["spatial_rna_class"] == "underpowered" and c1["n_donors"] == 1
    assert c2["spatial_rna_class"] == "tumour_enriched_rna" and c2["n_donors"] == 2
    assert ST.classify_region_rna({}, [])["spatial_rna_class"] == "data_unavailable"


def test_empty_is_data_unavailable():
    assert ST.classify_region_rna({}, [])["spatial_rna_class"] == "data_unavailable"


def test_cross_donor_median():
    rows = _rows([("d1", "TUMOUR", 9.0), ("d2", "TUMOUR", 11.0)])  # median 10.0
    assert ST.summarize_rna(rows)["compartment_abundance"]["TUMOUR"] == 10.0
