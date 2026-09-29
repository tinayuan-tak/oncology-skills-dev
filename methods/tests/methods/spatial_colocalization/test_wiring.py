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

from methods.spatial_colocalization import read as SC  # noqa: E402
from methods.spatial_colocalization import stats as ST  # noqa: E402

# ── wiring invariants (no S3) ────────────────────────────────────────────────


def test_coadread_wired_to_crc_cosmx():
    # COADREAD carries the CosMx lead + depth cohorts (Visium HD measured + Xenium inferred).
    for code in ("COADREAD", "COAD", "READ"):
        prods = SC._product_ids(code)
        assert "spatial-coloc-tumor-crc-coadread-v1" in prods
        assert "spatial-coloc-tumor-crc-gse280318-v1" in prods  # Visium HD depth (MEASURED)
        assert "spatial-coloc-tumor-crc-gse335552-v1" in prods  # Xenium liver-mets depth (inferred)
    # the Visium HD cohort is author-labelled -> measured tier (NOT in _INFERRED_PRODUCTS)
    assert SC._tier_of("spatial-coloc-tumor-crc-gse280318-v1") == "measured"


def test_visiumhd_fine_labels_map_to_compartments():
    # GSE280318 DeconvolutionLabel1 labels the token fallback misses/misroutes -> explicit dict
    assert ST.compartment_of_neighbor("vSM") == "stromal"
    assert ST.compartment_of_neighbor("Proliferating Macrophages") == "immune"
    assert ST.compartment_of_neighbor("mRegDC") == "immune"
    assert ST.compartment_of_neighbor("Neuroendocrine") == "epithelial_normal"
    assert ST.compartment_of_neighbor("Goblet") == "epithelial_normal"  # via fallback, safety-margin signal


def test_stad_wired_to_gastric_cosmx():
    assert SC.INDICATION_TO_SPATIAL_COLOC["STAD"] == "spatial-coloc-tumor-stad-v1"


def test_paad_wired_to_pdac_xenium():
    prods = SC._product_ids("PAAD")
    assert "spatial-coloc-tumor-paad-v1" in prods  # measured lead
    assert "spatial-coloc-tumor-paad-gse313662-v1" in prods  # inferred depth cohort (Xenium)
    assert "spatial-coloc-tumor-paad-gse310352-v1" in prods  # inferred depth cohort (CosMx GSE310352)
    assert SC._tier_of("spatial-coloc-tumor-paad-gse310352-v1") == "inferred"


def test_hnsc_wired_to_xenium_inferred():
    assert SC.INDICATION_TO_SPATIAL_COLOC["HNSC"] == "spatial-coloc-tumor-hnsc-v1"


def test_nsclc_histologies_wired_to_lung_product():
    # all three histologies share the same lung product list (lead + depth cohort)
    for code in ("NSCLC", "LUAD", "LUSC"):
        prods = SC._product_ids(code)
        assert "spatial-coloc-tumor-nsclc-v1" in prods
        assert "spatial-coloc-tumor-nsclc-gse319755-v1" in prods


def test_tier_dominant_partition_measured_vs_inferred():
    # tier_dominant: the author-curated leads are measured; the mode-C depth cohorts are inferred. The
    # reader reads measured first and only falls back to inferred — it never pools the two (Rule 5).
    assert SC._tier_of("spatial-coloc-tumor-crc-coadread-v1") == "measured"  # CosMx CRC atlas lead
    assert SC._tier_of("spatial-coloc-tumor-paad-v1") == "measured"  # Xenium PDAC atlas lead
    assert SC._tier_of("spatial-coloc-tumor-crc-gse335552-v1") == "inferred"  # mode-C depth
    assert SC._tier_of("spatial-coloc-tumor-paad-gse313662-v1") == "inferred"
    # a mixed indication resolves BOTH tiers; a pure-inferred indication resolves only inferred
    assert {SC._tier_of(p) for p in SC._product_ids("PAAD")} == {"measured", "inferred"}
    assert {SC._tier_of(p) for p in SC._product_ids("NSCLC")} == {"inferred"}
    assert {SC._tier_of(p) for p in SC._product_ids("COADREAD")} == {"measured", "inferred"}


def test_inferred_compartment_labels_self_map():
    # mode-C products emit compartment labels directly; they must map to themselves.
    for c in ("immune", "stromal", "endothelial"):
        assert ST.compartment_of_neighbor(c) == c
    assert ST.compartment_of_neighbor("other") == "other"


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
        "spatial-coloc-tumor-crc-coadread-v1/spatial_coloc.parquet"
    )
    assert s3_uri_for("spatial-coloc-tumor-stad-v1").endswith("spatial-coloc-tumor-stad-v1/spatial_coloc.parquet")


def test_product_ids_normalizes_str_and_list():
    # a map value may be a single product id (str) or a list (multiple datasets per indication)
    assert SC._product_ids("STAD") == ["spatial-coloc-tumor-stad-v1"]  # str value -> [str]
    assert SC._product_ids("KIRC") == []  # unmapped -> []
    # list values are returned as-is (simulate a multi-dataset indication)
    orig = SC.INDICATION_TO_SPATIAL_COLOC.get("PAAD")
    try:
        SC.INDICATION_TO_SPATIAL_COLOC["PAAD"] = ["a-v1", "b-v1"]
        assert SC._product_ids("PAAD") == ["a-v1", "b-v1"]
    finally:
        SC.INDICATION_TO_SPATIAL_COLOC["PAAD"] = orig


def test_unmapped_indication_is_data_unavailable():
    # KIRC is out of iDAS and has no spatial product → _product_key None → data_unavailable (no network).
    out = SC.read_spatial_colocalization("EPCAM", "KIRC")
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
    assert ST.compartment_of_neighbor("Tumor") != "immune"  # not misrouted


def test_token_fallback_catches_unmapped_immune_and_stromal():
    assert ST.compartment_of_neighbor("Neutrophil") == "immune"  # was 'other' under substring fallback
    assert ST.compartment_of_neighbor("Basophil") == "immune"
    assert ST.compartment_of_neighbor("CAF") == "stromal"
    assert ST.compartment_of_neighbor("Pericyte") == "stromal"
    assert ST.compartment_of_neighbor("Lymphatic endothelial") == "endothelial"
    assert ST.compartment_of_neighbor("Neuron") == "other"  # genuinely unknown -> other, not guessed


# ── classifier (pure) ────────────────────────────────────────────────────────


def _rows(spec):
    """spec: list of (donor, dataset, neighbor_cell_type, enrichment, adjacency)."""
    return [
        {
            "donor_id": d,
            "dataset_id": s,
            "neighbor_cell_type": ct,
            "enrichment_vs_random": e,
            "adjacency_fraction": a,
            "target_pos_fraction": 0.1,
        }
        for (d, s, ct, e, a) in spec
    ]


def test_classify_immune_niche_colocalized():
    # two donors (mirrored) so it clears the _MIN_DONORS power floor and grades the measured class
    rows = _rows(
        [
            ("d1", "s1", "Macro", 1.4, 0.20),
            ("d1", "s1", "TCD8", 1.3, 0.10),
            ("d1", "s1", "Fibro", 0.9, 0.10),
            ("d2", "s1", "Macro", 1.4, 0.20),
            ("d2", "s1", "TCD8", 1.3, 0.10),
            ("d2", "s1", "Fibro", 0.9, 0.10),
        ]
    )
    c = ST.classify_spatial_coloc(ST.neighbor_summary(rows), rows)
    assert c["spatial_coloc_class"] == "immune_niche_colocalized"
    assert c["top_enriched_compartment"] == "immune"
    assert c["n_donors"] == 2 and c["n_datasets"] == 1


def test_classify_normal_epithelium_adjacent_is_safety_margin_flag():
    # target-positive malignant cells enriched next to NORMAL epithelium = bystander-risk geometry
    # (two donors so it clears the _MIN_DONORS power floor)
    rows = _rows(
        [
            ("d1", "s1", "Epi", 1.5, 0.30),
            ("d1", "s1", "Macro", 1.0, 0.05),
            ("d2", "s1", "Epi", 1.5, 0.30),
            ("d2", "s1", "Macro", 1.0, 0.05),
        ]
    )
    c = ST.classify_spatial_coloc(ST.neighbor_summary(rows), rows)
    assert c["spatial_coloc_class"] == "normal_epithelium_adjacent"


def test_classify_no_spatial_preference():
    rows = _rows(
        [
            ("d1", "s1", "Macro", 1.02, 0.1),
            ("d1", "s1", "Fibro", 0.98, 0.1),
            ("d2", "s1", "Macro", 1.02, 0.1),
            ("d2", "s1", "Fibro", 0.98, 0.1),
        ]
    )
    assert ST.classify_spatial_coloc(ST.neighbor_summary(rows), rows)["spatial_coloc_class"] == "no_spatial_preference"


def test_classify_immune_excluded():
    # immune neighbours DEPLETED (enrichment <= 0.85), no compartment enriched → immune-cold tumour region
    # (two donors so it clears the _MIN_DONORS power floor)
    rows = _rows(
        [
            ("d1", "s1", "Macro", 0.7, 0.03),
            ("d1", "s1", "TCD8", 0.8, 0.02),
            ("d1", "s1", "Epi", 1.05, 0.4),
            ("d2", "s1", "Macro", 0.7, 0.03),
            ("d2", "s1", "TCD8", 0.8, 0.02),
            ("d2", "s1", "Epi", 1.05, 0.4),
        ]
    )
    assert ST.classify_spatial_coloc(ST.neighbor_summary(rows), rows)["spatial_coloc_class"] == "immune_excluded"


def test_classify_empty_is_data_unavailable():
    assert ST.classify_spatial_coloc({}, [])["spatial_coloc_class"] == "data_unavailable"


def test_underpowered_single_donor_is_not_minted_as_measured():
    # SAME immune-niche enrichment, one donor vs two. The power floor (_MIN_DONORS = 2) grades the
    # single-donor case `underpowered` ("we could barely look") while two donors grade the real
    # immune_niche_colocalized. Anti-vacuity: the two arms MUST differ, so the floor (not the values)
    # drives the verdict; the empty case above is the THIRD, distinct data_unavailable.
    one = _rows([("d1", "s1", "Macro", 1.4, 0.20), ("d1", "s1", "TCD8", 1.3, 0.10)])
    two = _rows(
        [
            ("d1", "s1", "Macro", 1.4, 0.20),
            ("d1", "s1", "TCD8", 1.3, 0.10),
            ("d2", "s1", "Macro", 1.4, 0.20),
            ("d2", "s1", "TCD8", 1.3, 0.10),
        ]
    )
    c1 = ST.classify_spatial_coloc(ST.neighbor_summary(one), one)
    c2 = ST.classify_spatial_coloc(ST.neighbor_summary(two), two)
    assert c1["spatial_coloc_class"] == "underpowered" and c1["n_donors"] == 1
    assert c2["spatial_coloc_class"] == "immune_niche_colocalized" and c2["n_donors"] == 2


def test_other_compartment_excluded_from_headline():
    # 'other' (marker-inference catch-all) must NOT be the headline even when top-enriched; an immune
    # depletion underneath must surface as immune_excluded (regression: NSCLC EPCAM was masked to
    # other_niche_colocalized by an enriched 'other' compartment).
    rows = _rows(
        [
            ("d1", "s1", "other", 1.4, 0.3),
            ("d1", "s1", "Macro", 0.7, 0.05),
            ("d2", "s1", "other", 1.5, 0.3),
            ("d2", "s1", "TCD8", 0.75, 0.04),
        ]
    )
    c = ST.classify_spatial_coloc(ST.neighbor_summary(rows), rows)
    assert c["spatial_coloc_class"] == "immune_excluded"
    assert c["top_enriched_compartment"] != "other"


def test_cross_donor_median_not_dominated_by_one_donor():
    # two donors: enrichment 1.0 and 2.0 for Macro → median 1.5 (not mean-skewed by an outlier)
    rows = _rows([("d1", "s1", "Macro", 1.0, 0.1), ("d2", "s1", "Macro", 2.0, 0.1)])
    ns = ST.neighbor_summary(rows)
    assert ns["Macro"]["median_enrichment"] == 1.5


# ── PRODUCT absence vs TARGET absence (2026-09-12) ───────────────────────────
def _fake_pq(monkeypatch, obj):
    """Substitute the reader's `import pyarrow.parquet as pq`. Patching sys.modules ALONE is not enough:
    `import a.b as c` resolves `getattr(a, "b")` first and only falls back to sys.modules, so once any
    earlier test in the session has imported the real pyarrow.parquet (which sets the attribute on the
    pyarrow package), a sys.modules-only patch is silently bypassed and the read goes LIVE to S3. That
    made these two tests pass alone and fail on ACCESS_DENIED in the full suite. Patch both."""
    import pyarrow

    monkeypatch.setitem(sys.modules, "pyarrow.parquet", obj)
    monkeypatch.setattr(pyarrow, "parquet", obj, raising=False)


def test_every_product_404_reads_as_a_product_gap_not_as_target_absence(monkeypatch):
    """The per-product `except FileNotFoundError: continue` is right, but when EVERY listed product 404s
    the loop fell through to the empty-frame return and the caller reported "<target> absent from the
    spatial panel" — a claim about the TARGET's biology manufactured from an infrastructure gap. Both
    paths still yield spatial_coloc_class=data_unavailable (verdict-inert); what changes is whether the
    note blames the gene or the product."""

    class _Boom:
        def read_table(self, *a, **k):
            raise FileNotFoundError("no such key")

    monkeypatch.setattr(SC, "bucket_key_for", lambda prod: ("onc-compbio", f"k/{prod}.parquet"))
    _fake_pq(monkeypatch, _Boom())
    rows, tier = SC.read_target_neighbor_rows("EPCAM", "COADREAD")
    assert rows is None and tier is None  # "no readable product", NOT an empty frame
    out = SC.read_spatial_colocalization("EPCAM", "COADREAD")
    assert out["spatial_coloc_class"] == "data_unavailable"
    assert "PRODUCT gap" in out["_data_note"]
    assert "absent from the spatial panel" not in out["_data_note"]


def test_a_readable_product_that_lacks_the_gene_still_reads_as_target_absence(monkeypatch):
    """The other side of the same distinction — the check above must not have collapsed both cases into
    'product gap', or it would be a vacuous pass."""
    import pandas as pd
    import pyarrow as pa

    class _Empty:
        def read_table(self, *a, **k):
            return pa.Table.from_pandas(pd.DataFrame(columns=SC._PARQUET_COLS))

    monkeypatch.setattr(SC, "bucket_key_for", lambda prod: ("onc-compbio", f"k/{prod}.parquet"))
    _fake_pq(monkeypatch, _Empty())
    rows, tier = SC.read_target_neighbor_rows("ZZZ9", "COADREAD")
    assert rows is not None and rows.empty and tier is None
    out = SC.read_spatial_colocalization("ZZZ9", "COADREAD")
    assert out["spatial_coloc_class"] == "data_unavailable"
    assert "absent from the spatial panel" in out["_data_note"]


# ── indication ALIAS parity with the immune lane (2026-09-13, found by the panel) ──
def test_the_pdac_alias_resolves_to_the_same_spatial_products_as_paad():
    """MSLN/PDAC and CSF1R/PAAD read the identical 183-sample TCGA-PAAD cohort in the immune lane, but
    PDAC used to resolve NO spatial product — and the spatial lane is what caps bite_tce and drives
    immune-context confidence, so the same tumour asked by its other name came back a confidence rung
    lower. An indication ALIAS must never change the evidence base."""
    assert SC.INDICATION_TO_SPATIAL_COLOC["PDAC"] == SC.INDICATION_TO_SPATIAL_COLOC["PAAD"]


def test_no_immune_lane_alias_silently_loses_its_spatial_lane():
    """The durable form of the check above, so the next alias added to the immune lane cannot reopen the
    gap. For every set of TCGA studies the immune lane resolves, if ANY of the codes mapping to that
    study set is spatially covered, they ALL must be — otherwise two spellings of one cohort disagree
    about what evidence exists. (Codes with no spatial product at all are fine; the asymmetry is what
    is forbidden.)"""
    from methods.immune_context.read import INDICATION_TO_TCGA_STUDIES as IC

    by_studies = {}
    for code, studies in IC.items():
        by_studies.setdefault(tuple(sorted(studies)), []).append(code)
    gaps = {}
    for studies, codes in by_studies.items():
        covered = [c for c in codes if c in SC.INDICATION_TO_SPATIAL_COLOC]
        missing = [c for c in codes if c not in SC.INDICATION_TO_SPATIAL_COLOC]
        if covered and missing:
            gaps[studies] = {"covered": covered, "missing": missing}
    assert not gaps, f"indication aliases that lose the spatial lane: {gaps}"


def test_the_alias_parity_check_is_not_vacuous():
    """It must be comparing something: the immune lane has to contain at least one study set reached by
    two different codes AND at least one code the spatial map covers."""
    from methods.immune_context.read import INDICATION_TO_TCGA_STUDIES as IC

    by_studies = {}
    for code, studies in IC.items():
        by_studies.setdefault(tuple(sorted(studies)), []).append(code)
    assert any(len(codes) > 1 for codes in by_studies.values())
    assert set(IC) & set(SC.INDICATION_TO_SPATIAL_COLOC)
