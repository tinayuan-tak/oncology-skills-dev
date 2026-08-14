"""Wiring + classifier regression for spatial_colocalization.

Value invariants + product resolution need no S3 (dict lookups + local catalog YAML). The classifier
tests are pure. Mirrors tests/methods/pair_selectivity_gate/test_lusc_wiring.py.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.spatial_colocalization import read as SC   # noqa: E402
from methods.spatial_colocalization import stats as ST   # noqa: E402


# ── wiring invariants (no S3) ────────────────────────────────────────────────

def test_coadread_wired_to_crc_cosmx():
    for code in ("COADREAD", "COAD", "READ"):
        assert SC.INDICATION_TO_SPATIAL_COLOC[code] == "spatial-coloc-tumor-crc-coadread-v1"


def test_stad_wired_to_gastric_cosmx():
    assert SC.INDICATION_TO_SPATIAL_COLOC["STAD"] == "spatial-coloc-tumor-stad-v1"


def test_paad_wired_to_pdac_xenium():
    assert SC.INDICATION_TO_SPATIAL_COLOC["PAAD"] == "spatial-coloc-tumor-paad-v1"


def test_paad_caf_variants_map_to_stromal():
    # GSE280634 CAF-variant labels tokenize to a single glued token; must resolve to stromal (explicit dict)
    assert ST.compartment_of_neighbor("myCAF") == "stromal"
    assert ST.compartment_of_neighbor("iCAF") == "stromal"
    assert ST.compartment_of_neighbor("Smooth muscle") == "stromal"
    assert ST.compartment_of_neighbor("B, Plasma cell") == "immune"
    assert ST.compartment_of_neighbor("Epithelial (ADM-like)") == "epithelial_normal"


def test_products_resolve_to_catalog_s3_uris():
    from methods.catalog_query.read import s3_uri_for
    assert s3_uri_for("spatial-coloc-tumor-crc-coadread-v1").endswith(
        "spatial-coloc-tumor-crc-coadread-v1/spatial_coloc.parquet")
    assert s3_uri_for("spatial-coloc-tumor-stad-v1").endswith(
        "spatial-coloc-tumor-stad-v1/spatial_coloc.parquet")


def test_unmapped_indication_is_data_unavailable():
    # NSCLC has no spatial product yet → _product_key None → data_unavailable (no network hit).
    out = SC.read_spatial_colocalization("EPCAM", "NSCLC")
    assert out["spatial_coloc_class"] == "data_unavailable"
    assert out["product_id"] is None


# ── neighbour-compartment mapping ────────────────────────────────────────────

def test_neighbor_compartment_mapping():
    # GSE303070 CosMx labels
    assert ST.compartment_of_neighbor("TCD8") == "immune"
    assert ST.compartment_of_neighbor("Macro") == "immune"
    assert ST.compartment_of_neighbor("Fibro") == "stromal"
    assert ST.compartment_of_neighbor("Endo") == "endothelial"
    assert ST.compartment_of_neighbor("Epi") == "epithelial_normal"
    # GSE308624 gastric labels (incl. the source's 'Mocrophage' misspelling + SMC)
    assert ST.compartment_of_neighbor("Mocrophage") == "immune"
    assert ST.compartment_of_neighbor("SMC") == "stromal"
    assert ST.compartment_of_neighbor("Fibroblast") == "stromal"
    assert ST.compartment_of_neighbor("T_cell") == "immune"
    assert ST.compartment_of_neighbor("B_cell") == "immune"
    assert ST.compartment_of_neighbor("Endothelial") == "endothelial"


def test_token_fallback_does_not_misroute_epithelial_to_immune():
    # REGRESSION: the old substring fallback read 'Basal'/'Tuft'/'Tumor' as immune via a bare 'T'/'B'.
    # Token matching must route these to epithelial_normal / other, NOT immune.
    assert ST.compartment_of_neighbor("Basal") == "epithelial_normal"
    assert ST.compartment_of_neighbor("Tuft") == "epithelial_normal"
    assert ST.compartment_of_neighbor("Goblet") == "epithelial_normal"
    assert ST.compartment_of_neighbor("Enterocyte") == "epithelial_normal"
    assert ST.compartment_of_neighbor("Tumor") != "immune"          # not misrouted


def test_token_fallback_catches_unmapped_immune_and_stromal():
    assert ST.compartment_of_neighbor("Neutrophil") == "immune"     # was 'other' under substring fallback
    assert ST.compartment_of_neighbor("Basophil") == "immune"
    assert ST.compartment_of_neighbor("CAF") == "stromal"
    assert ST.compartment_of_neighbor("Pericyte") == "stromal"
    assert ST.compartment_of_neighbor("Lymphatic endothelial") == "endothelial"
    assert ST.compartment_of_neighbor("Neuron") == "other"          # genuinely unknown -> other, not guessed


# ── classifier (pure) ────────────────────────────────────────────────────────

def _rows(spec):
    """spec: list of (donor, dataset, neighbor_cell_type, enrichment, adjacency)."""
    return [{"donor_id": d, "dataset_id": s, "neighbor_cell_type": ct,
             "enrichment_vs_random": e, "adjacency_fraction": a, "target_pos_fraction": 0.1}
            for (d, s, ct, e, a) in spec]


def test_classify_immune_niche_colocalized():
    rows = _rows([("d1", "s1", "Macro", 1.4, 0.20), ("d1", "s1", "TCD8", 1.3, 0.10),
                  ("d1", "s1", "Fibro", 0.9, 0.10)])
    c = ST.classify_spatial_coloc(ST.neighbor_summary(rows), rows)
    assert c["spatial_coloc_class"] == "immune_niche_colocalized"
    assert c["top_enriched_compartment"] == "immune"
    assert c["n_donors"] == 1 and c["n_datasets"] == 1


def test_classify_normal_epithelium_adjacent_is_safety_margin_flag():
    # target-positive malignant cells enriched next to NORMAL epithelium = bystander-risk geometry
    rows = _rows([("d1", "s1", "Epi", 1.5, 0.30), ("d1", "s1", "Macro", 1.0, 0.05)])
    c = ST.classify_spatial_coloc(ST.neighbor_summary(rows), rows)
    assert c["spatial_coloc_class"] == "normal_epithelium_adjacent"


def test_classify_no_spatial_preference():
    rows = _rows([("d1", "s1", "Macro", 1.02, 0.1), ("d1", "s1", "Fibro", 0.98, 0.1)])
    assert ST.classify_spatial_coloc(ST.neighbor_summary(rows), rows)["spatial_coloc_class"] == "no_spatial_preference"


def test_classify_immune_excluded():
    # immune neighbours DEPLETED (enrichment <= 0.85), no compartment enriched → immune-cold tumour region
    rows = _rows([("d1", "s1", "Macro", 0.7, 0.03), ("d1", "s1", "TCD8", 0.8, 0.02),
                  ("d1", "s1", "Epi", 1.05, 0.4)])
    assert ST.classify_spatial_coloc(ST.neighbor_summary(rows), rows)["spatial_coloc_class"] == "immune_excluded"


def test_classify_empty_is_data_unavailable():
    assert ST.classify_spatial_coloc({}, [])["spatial_coloc_class"] == "data_unavailable"


def test_cross_donor_median_not_dominated_by_one_donor():
    # two donors: enrichment 1.0 and 2.0 for Macro → median 1.5 (not mean-skewed by an outlier)
    rows = _rows([("d1", "s1", "Macro", 1.0, 0.1), ("d2", "s1", "Macro", 2.0, 0.1)])
    ns = ST.neighbor_summary(rows)
    assert ns["Macro"]["median_enrichment"] == 1.5
