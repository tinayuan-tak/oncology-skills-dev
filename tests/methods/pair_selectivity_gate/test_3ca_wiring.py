"""Regression: PAAD and HNSC must resolve their 3CA single-cell products in all sc maps.

data-catalog #334–#340 landed 3CA tumor products for PAAD (Pancreas) and HNSC (Head-and-Neck).
Census has 0 HNSC malignant-annotated cells; 3CA fills the gap via inferCNV/CNA-validated
malignant call. This module pins the map entries + the cross-map consistency invariant
(all sc maps must cover identical indication codes — drift causes a silent data_unavailable
on one axis; the same guard catches the 2026-08-05 NSCLC drift class).

Pattern mirrors test_lusc_wiring.py. Map tests need no catalog/S3 (pure dict lookups).
Resolution tests read local manifest YAML (no network).
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.pair_selectivity_gate import samecell as SC  # noqa: E402
from methods.sc_tumor_expression_celltype import read as TSC  # noqa: E402


# ── value invariants (no catalog / no S3) ────────────────────────────────────

def test_paad_pseudobulk_map_points_to_3ca_pancreas():
    assert TSC.INDICATION_TO_PRODUCT["PAAD"] == "sc-pseudobulk-tumor-3ca-pancreas-v1"


def test_hnsc_pseudobulk_map_points_to_3ca_hnsc():
    assert TSC.INDICATION_TO_PRODUCT["HNSC"] == "sc-pseudobulk-tumor-3ca-hnsc-v1"


def test_paad_samecell_map_points_to_3ca_pancreas():
    assert SC.INDICATION_TO_SAMECELL_MANIFEST["PAAD"] == "sc-samecell-coexpr-3ca-pancreas-v1"


def test_hnsc_samecell_map_points_to_3ca_hnsc():
    assert SC.INDICATION_TO_SAMECELL_MANIFEST["HNSC"] == "sc-samecell-coexpr-3ca-hnsc-v1"


def test_stad_has_no_product_no_3ca_bucket():
    # STAD is explicitly absent — Census gastric atlases label tumor cells 'unknown' (no malignant
    # compartment); 3CA has no gastric bucket. Must stay data_unavailable, never silently fall back.
    assert "STAD" not in TSC.INDICATION_TO_PRODUCT
    assert "STAD" not in SC.INDICATION_TO_SAMECELL_MANIFEST


def test_sc_maps_agree_on_all_indications():
    # Both maps must cover the SAME set of indication codes — a code in one but not the other
    # causes a silent data_unavailable on one axis (avidity unconfirmed / presence unknown).
    assert set(TSC.INDICATION_TO_PRODUCT) == set(SC.INDICATION_TO_SAMECELL_MANIFEST)


# ── resolution smoke (reads local catalog YAML, no network) ──────────────────

def test_3ca_products_resolve_to_catalog_s3_uris():
    from methods.catalog_query.read import s3_uri_for
    assert s3_uri_for("sc-pseudobulk-tumor-3ca-pancreas-v1").endswith(
        "sc-pseudobulk-tumor-3ca-pancreas-v1/sc_pseudobulk.parquet")
    assert s3_uri_for("sc-pseudobulk-tumor-3ca-hnsc-v1").endswith(
        "sc-pseudobulk-tumor-3ca-hnsc-v1/sc_pseudobulk.parquet")
    assert s3_uri_for("sc-samecell-coexpr-3ca-pancreas-v1").endswith(
        "sc-samecell-coexpr-3ca-pancreas-v1/sc_samecell_coexpr.parquet")
    assert s3_uri_for("sc-samecell-coexpr-3ca-hnsc-v1").endswith(
        "sc-samecell-coexpr-3ca-hnsc-v1/sc_samecell_coexpr.parquet")
