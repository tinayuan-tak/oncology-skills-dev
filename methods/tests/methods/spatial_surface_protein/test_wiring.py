"""Wiring + classifier regression for spatial_surface_protein (GeoMx region-protein)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.spatial_surface_protein import read as SP  # noqa: E402
from methods.spatial_surface_protein import stats as ST  # noqa: E402


def test_hnsc_fallback_chain_order():
    # HNSC is a within-indication FALLBACK CHAIN: primary 580-plex first, then the IO panel that rescues
    # the surface/IO targets the un-crosswalked 580-plex drops.
    assert SP.INDICATION_TO_SURFACE_PROTEIN["HNSC"] == [
        "spatial-surface-protein-hnsc-v1",
        "spatial-surface-protein-hnsc-gse200601-v1",
    ]
    assert SP._products("HNSC")[0] == "spatial-surface-protein-hnsc-v1"  # primary wins


def test_nsclc_histologies_wired_to_geomx_protein():
    # all three lung histologies share the one NSCLC GeoMx IO-panel product (GSE221322), single-element chain
    for code in ("NSCLC", "LUAD", "LUSC"):
        assert SP.INDICATION_TO_SURFACE_PROTEIN[code] == ["spatial-surface-protein-nsclc-v1"]


def test_product_resolves_to_catalog_s3_uri():
    from methods.catalog_query.read import s3_uri_for

    for pid in (
        "spatial-surface-protein-hnsc-v1",
        "spatial-surface-protein-hnsc-gse200601-v1",
        "spatial-surface-protein-nsclc-v1",
    ):
        assert s3_uri_for(pid).endswith(f"{pid}/spatial_surface_protein.parquet")


def test_unmapped_indication_is_data_unavailable():
    out = SP.read_spatial_surface_protein("EGFR", "COADREAD")  # no region-protein product for COADREAD
    assert out["spatial_protein_class"] == "data_unavailable"
    assert out["product_id"] is None


def _rows(spec):
    """spec: list of (donor, compartment, abundance_lcpm)."""
    return [{"donor_id": d, "compartment": c, "abundance_lcpm": a, "detected": True} for (d, c, a) in spec]


def test_classify_tumour_enriched():
    rows = _rows([("d1", "TUMOUR", 10.5), ("d1", "TME", 9.6), ("d2", "TUMOUR", 10.2), ("d2", "TME", 9.5)])
    c = ST.classify_surface_protein(ST.summarize_protein(rows), rows)
    assert c["spatial_protein_class"] == "tumour_enriched_protein"
    assert c["tumour_vs_tme_delta"] and c["tumour_vs_tme_delta"] > 0


def test_classify_tme_enriched():
    # CD34/CD68-like: TME-enriched (endothelial/macrophage protein)
    rows = _rows([("d1", "TUMOUR", 6.4), ("d1", "TME", 7.2), ("d2", "TUMOUR", 6.5), ("d2", "TME", 7.3)])
    assert (
        ST.classify_surface_protein(ST.summarize_protein(rows), rows)["spatial_protein_class"] == "tme_enriched_protein"
    )


def test_classify_no_compartment_preference():
    # EGFR-like small delta; two donors so it clears the _MIN_DONORS power floor and grades the
    # measured class rather than `underpowered`.
    rows = _rows([("d1", "TUMOUR", 10.27), ("d1", "TME", 10.10), ("d2", "TUMOUR", 10.27), ("d2", "TME", 10.10)])
    assert (
        ST.classify_surface_protein(ST.summarize_protein(rows), rows)["spatial_protein_class"]
        == "tumour_present_no_compartment_preference"
    )


def test_underpowered_single_donor_is_not_minted_as_measured():
    # SAME tumour-enriched values, one donor vs two. The power floor (_MIN_DONORS = 2) grades the
    # single-donor case `underpowered` ("we could barely look") while two donors grade the real
    # tumour_enriched_protein. Anti-vacuity: the two arms MUST differ, so the floor (not the values)
    # drives the verdict; a no-rows case is the THIRD, distinct data_unavailable ("could not look").
    one = _rows([("d1", "TUMOUR", 10.5), ("d1", "TME", 9.6)])
    two = _rows([("d1", "TUMOUR", 10.5), ("d1", "TME", 9.6), ("d2", "TUMOUR", 10.2), ("d2", "TME", 9.5)])
    c1 = ST.classify_surface_protein(ST.summarize_protein(one), one)
    c2 = ST.classify_surface_protein(ST.summarize_protein(two), two)
    assert c1["spatial_protein_class"] == "underpowered" and c1["n_donors"] == 1
    assert c2["spatial_protein_class"] == "tumour_enriched_protein" and c2["n_donors"] == 2
    assert ST.classify_surface_protein({}, [])["spatial_protein_class"] == "data_unavailable"


def test_empty_is_data_unavailable():
    assert ST.classify_surface_protein({}, [])["spatial_protein_class"] == "data_unavailable"


def test_cross_donor_median():
    rows = _rows([("d1", "TUMOUR", 9.0), ("d2", "TUMOUR", 11.0)])  # median 10.0
    assert ST.summarize_protein(rows)["compartment_abundance"]["TUMOUR"] == 10.0
