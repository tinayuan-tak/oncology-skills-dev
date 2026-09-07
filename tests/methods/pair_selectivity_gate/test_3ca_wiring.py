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


def test_kirc_pseudobulk_map_points_to_3ca_kidney():
    assert TSC.INDICATION_TO_PRODUCT["KIRC"] == "sc-pseudobulk-tumor-3ca-kidney-v1"


def test_kirc_samecell_map_points_to_3ca_kidney():
    assert SC.INDICATION_TO_SAMECELL_MANIFEST["KIRC"] == "sc-samecell-coexpr-3ca-kidney-v1"


def test_ov_pseudobulk_map_points_to_3ca_ovarian():
    assert TSC.INDICATION_TO_PRODUCT["OV"] == "sc-pseudobulk-tumor-3ca-ovarian-v1"


def test_ov_samecell_map_points_to_3ca_ovarian():
    assert SC.INDICATION_TO_SAMECELL_MANIFEST["OV"] == "sc-samecell-coexpr-3ca-ovarian-v1"


def test_kidney_cube_is_pan_renal_only_kirc_mapped():
    # The 3CA kidney bucket is MULTI-ENTITY POOLED (ccRCC + papillary + chromophobe + Wilms + normal,
    # no cancer_type filter). Only KIRC is wired — the pooled cube cannot serve entity-specific
    # denominators for the other renal codes, so they must stay data_unavailable (never silently
    # fall back to a pan-renal cube presented as papillary/chromophobe-specific).
    assert "KIRP" not in TSC.INDICATION_TO_PRODUCT
    assert "KICH" not in TSC.INDICATION_TO_PRODUCT
    assert "KIRP" not in SC.INDICATION_TO_SAMECELL_MANIFEST
    assert "KICH" not in SC.INDICATION_TO_SAMECELL_MANIFEST


def test_stad_wired_to_golim_gastric_atlas():
    # STAD was previously data_unavailable (Census gastric atlases label tumor cells 'unknown'; no 3CA
    # gastric bucket). RESOLVED 2026-08-17: the Go/Lim integrated gastric atlas (data-catalog #425)
    # provides an explicit malignant compartment (Epithelial ∩ Phenotype==GC), yielding the
    # sc-pseudobulk-tumor-stad-golim-v1 (#433) and sc-samecell-coexpr-stad-golim-v1 (#434) products.
    # CLDN18 (CLDN18.2/zolbetuximab) is malignant-specific (1.23 vs 0.06), validating the malignant call.
    assert TSC.INDICATION_TO_PRODUCT["STAD"] == "sc-pseudobulk-tumor-stad-golim-v1"
    assert SC.INDICATION_TO_SAMECELL_MANIFEST["STAD"] == "sc-samecell-coexpr-stad-golim-v1"


def test_npc_3ca_registered_but_intentionally_not_wired():
    # NPC (nasopharyngeal) 3CA products ARE registered (#340, alongside HNSC) but NPC is deliberately
    # NOT wired into the indication maps. Reasons, pinned so the non-wiring reads as INTENT not
    # oversight (mirrors the STAD / KIRP / KICH deliberate-absence guards): NPC is a biologically
    # DISTINCT entity from HNSCC (EBV-driven) — the manifest emits it as its OWN reference product,
    # explicitly "not an HNSCC substitute"; its malignant signal is THIN (Chen2020: 14 donors, 1
    # study); and NPC is not a first-class indication code elsewhere in the framework, so nothing
    # would request it. Promoting NPC to a wired indication is a separate full indication-vertical, not
    # a map edit — until then it stays a registered-but-unwired distinct-entity reference.
    assert "NPC" not in TSC.INDICATION_TO_PRODUCT
    assert "NPC" not in SC.INDICATION_TO_SAMECELL_MANIFEST
    # Registration IS complete: both NPC products resolve in the catalog (wiring is withheld, not the
    # products). If someone wires NPC, the two asserts above flip and this guard fails — the prompt to
    # do the full indication vertical (or update this rationale) rather than a silent one-line map add.
    from methods.catalog_query.read import s3_uri_for

    assert s3_uri_for("sc-pseudobulk-tumor-3ca-npc-v1").endswith("sc-pseudobulk-tumor-3ca-npc-v1/sc_pseudobulk.parquet")
    assert s3_uri_for("sc-samecell-coexpr-3ca-npc-v1").endswith(
        "sc-samecell-coexpr-3ca-npc-v1/sc_samecell_coexpr.parquet"
    )


def test_sc_maps_agree_on_all_indications():
    # Both maps must cover the SAME set of indication codes — a code in one but not the other
    # causes a silent data_unavailable on one axis (avidity unconfirmed / presence unknown).
    assert set(TSC.INDICATION_TO_PRODUCT) == set(SC.INDICATION_TO_SAMECELL_MANIFEST)


# ── resolution smoke (reads local catalog YAML, no network) ──────────────────


def test_3ca_products_resolve_to_catalog_s3_uris():
    from methods.catalog_query.read import s3_uri_for

    assert s3_uri_for("sc-pseudobulk-tumor-3ca-pancreas-v1").endswith(
        "sc-pseudobulk-tumor-3ca-pancreas-v1/sc_pseudobulk.parquet"
    )
    assert s3_uri_for("sc-pseudobulk-tumor-3ca-hnsc-v1").endswith(
        "sc-pseudobulk-tumor-3ca-hnsc-v1/sc_pseudobulk.parquet"
    )
    assert s3_uri_for("sc-samecell-coexpr-3ca-pancreas-v1").endswith(
        "sc-samecell-coexpr-3ca-pancreas-v1/sc_samecell_coexpr.parquet"
    )
    assert s3_uri_for("sc-samecell-coexpr-3ca-hnsc-v1").endswith(
        "sc-samecell-coexpr-3ca-hnsc-v1/sc_samecell_coexpr.parquet"
    )
    assert s3_uri_for("sc-pseudobulk-tumor-3ca-kidney-v1").endswith(
        "sc-pseudobulk-tumor-3ca-kidney-v1/sc_pseudobulk.parquet"
    )
    assert s3_uri_for("sc-samecell-coexpr-3ca-kidney-v1").endswith(
        "sc-samecell-coexpr-3ca-kidney-v1/sc_samecell_coexpr.parquet"
    )
    assert s3_uri_for("sc-pseudobulk-tumor-3ca-ovarian-v1").endswith(
        "sc-pseudobulk-tumor-3ca-ovarian-v1/sc_pseudobulk.parquet"
    )
    assert s3_uri_for("sc-samecell-coexpr-3ca-ovarian-v1").endswith(
        "sc-samecell-coexpr-3ca-ovarian-v1/sc_samecell_coexpr.parquet"
    )
