"""Regression: LUSC must resolve its DEDICATED single-cell products, not the NSCLC umbrella.

data-catalog #332 landed LUSC-specific cubes (sc-pseudobulk-donor-celltype-lusc-v1 +
sc-samecell-coexpr-lusc-v1) — squamous-only malignant denominators, distinct from the
LUAD+LUSC-mixed NSCLC umbrella. Before that, both sc maps fell back to the umbrella. This is
the same "indication map drift" failure class as the 2026-08-05 NSCLC bug (see
tcga_gtex_expression_distribution/test_indication_map_consistency.py) — except the *single-cell*
maps had no consistency guard. This module locks the two sc maps to the dedicated LUSC products
and pins the invariant that LUAD/NSCLC stay on the umbrella (no LUAD-specific cube exists).

The value assertions need no catalog/S3 (pure dict lookups). The resolution assertions read the
local data-catalog manifest YAML (no network — mirrors depmap_common/test_release_pin_guard.py).
"""

from __future__ import annotations

from onc_methods.pair_selectivity_gate import samecell as SC
from onc_methods.sc_tumor_expression_celltype import read as TSC

# ── value invariants (no catalog / no S3) ───────────────────────────────────


def test_lusc_pseudobulk_map_points_to_dedicated_cube():
    assert TSC.INDICATION_TO_PRODUCT["LUSC"] == "sc-pseudobulk-donor-celltype-lusc-v1"


def test_lusc_samecell_map_points_to_dedicated_cube():
    assert SC.INDICATION_TO_SAMECELL_MANIFEST["LUSC"] == "sc-samecell-coexpr-lusc-v1"


def test_luad_and_nsclc_stay_on_the_umbrella():
    # LUAD has no dedicated cube → umbrella; NSCLC *is* the umbrella. Guard against an over-eager
    # split that would orphan LUAD queries.
    # 2026-08-13: NSCLC/LUAD repointed from the Census umbrella to the richer LuCA atlas (both maps).
    assert TSC.INDICATION_TO_PRODUCT["LUAD"] == "sc-pseudobulk-tumor-luca-nsclc-v1"
    assert TSC.INDICATION_TO_PRODUCT["NSCLC"] == "sc-pseudobulk-tumor-luca-nsclc-v1"
    assert SC.INDICATION_TO_SAMECELL_MANIFEST["LUAD"] == "sc-samecell-coexpr-luca-nsclc-v1"
    assert SC.INDICATION_TO_SAMECELL_MANIFEST["NSCLC"] == "sc-samecell-coexpr-luca-nsclc-v1"


def test_coadread_wired_to_crc_atlas():
    # 2026-08-13: COADREAD/COAD/READ repointed from the Census coadread cubes to the CRC core atlas
    # (Marteau 2025), which carries an EXPLICIT 'Cancer cell' malignant call (the Census cube inferred
    # the malignant compartment via compartment_of, conflating malignant with normal colonic epithelium).
    # Both maps must move together (same pattern as the NSCLC→LuCA repoint).
    for code in ("COADREAD", "COAD", "READ"):
        assert TSC.INDICATION_TO_PRODUCT[code] == "sc-pseudobulk-tumor-crc-coadread-v1"
        assert SC.INDICATION_TO_SAMECELL_MANIFEST[code] == "sc-samecell-coexpr-crc-coadread-v1"


def test_sc_maps_agree_on_every_indication():
    # The pseudobulk map and the same-cell map must cover the same indication codes — a code present
    # in one but not the other means an axis silently data_unavailable for that indication.
    assert set(TSC.INDICATION_TO_PRODUCT) == set(SC.INDICATION_TO_SAMECELL_MANIFEST)


def test_crc_coadread_products_resolve_to_catalog_s3_uris():
    from onc_methods.catalog_query.read import s3_uri_for

    assert s3_uri_for("sc-pseudobulk-tumor-crc-coadread-v1").endswith(
        "sc-pseudobulk-tumor-crc-coadread-v1/sc_pseudobulk.parquet"
    )
    assert s3_uri_for("sc-samecell-coexpr-crc-coadread-v1").endswith(
        "sc-samecell-coexpr-crc-coadread-v1/sc_samecell_coexpr.parquet"
    )


# ── resolution smoke (reads local catalog YAML, no network) ──────────────────


def test_lusc_products_resolve_to_catalog_s3_uris():
    from onc_methods.catalog_query.read import s3_uri_for

    assert s3_uri_for("sc-pseudobulk-donor-celltype-lusc-v1").endswith(
        "sc-pseudobulk-donor-celltype-lusc-v1/sc_pseudobulk.parquet"
    )
    assert s3_uri_for("sc-samecell-coexpr-lusc-v1").endswith("sc-samecell-coexpr-lusc-v1/sc_samecell_coexpr.parquet")
