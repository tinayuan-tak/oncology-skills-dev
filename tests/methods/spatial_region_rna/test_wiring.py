"""Wiring + classifier regression for spatial_region_rna (GeoMx WTA region-RNA)."""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.spatial_region_rna import read as RR   # noqa: E402
from methods.spatial_region_rna import stats as ST   # noqa: E402


def test_hnsc_wired_to_geomx_wta():
    assert RR.INDICATION_TO_REGION_RNA["HNSC"] == "spatial-region-rna-hnsc-v1"


def test_product_resolves_to_catalog_s3_uri():
    from methods.catalog_query.read import s3_uri_for
    assert s3_uri_for("spatial-region-rna-hnsc-v1").endswith(
        "spatial-region-rna-hnsc-v1/spatial_region_rna.parquet")


def test_unmapped_indication_is_data_unavailable():
    out = RR.read_spatial_region_rna("EGFR", "COADREAD")   # no region-RNA product for COADREAD yet
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
    rows = _rows([("d1", "TUMOUR", 5.16), ("d1", "TME", 4.93)])   # EPCAM-like small delta in HNSC
    assert ST.classify_region_rna(ST.summarize_rna(rows), rows)["spatial_rna_class"] == "tumour_present_no_compartment_preference"


def test_empty_is_data_unavailable():
    assert ST.classify_region_rna({}, [])["spatial_rna_class"] == "data_unavailable"


def test_cross_donor_median():
    rows = _rows([("d1", "TUMOUR", 9.0), ("d2", "TUMOUR", 11.0)])   # median 10.0
    assert ST.summarize_rna(rows)["compartment_abundance"]["TUMOUR"] == 10.0
