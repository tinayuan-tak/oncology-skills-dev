"""Tests for scripts/prefetch_source_maf.py — the Phase-2b/c mutation-source
prefetch driver.

Validates the source-config table + dry-run planning without requiring
network access. Real S3 pulls are exercised in operational runs, not CI.
"""

from pathlib import Path
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_source_configs_complete():
    """All 4 sources have complete SourceConfig entries."""
    from scripts.prefetch_source_maf import SOURCE_CONFIGS
    expected = {"tcga_mc3", "genie_public_v19", "genie_bpc_crc", "depmap_somatic"}
    assert set(SOURCE_CONFIGS) == expected
    for name, cfg in SOURCE_CONFIGS.items():
        assert cfg.gene_col and cfg.protein_col and cfg.effect_col and cfg.sample_col
        assert cfg.filter_strategy in {"tcga_patient_list", "genie_cancer_type",
                                        "depmap_lineage", "none"}


def test_depmap_uses_protein_change_column():
    """DepMap MAF uses Protein_Change (not HGVSp_Short like MC3/GENIE)."""
    from scripts.prefetch_source_maf import SOURCE_CONFIGS
    assert SOURCE_CONFIGS["depmap_somatic"].protein_col == "Protein_Change"
    assert SOURCE_CONFIGS["tcga_mc3"].protein_col == "HGVSp_Short"
    assert SOURCE_CONFIGS["genie_public_v19"].protein_col == "HGVSp_Short"


def test_genie_bpc_no_filter():
    """GENIE-BPC CRC is already CRC-only → filter_strategy=none."""
    from scripts.prefetch_source_maf import SOURCE_CONFIGS
    assert SOURCE_CONFIGS["genie_bpc_crc"].filter_strategy == "none"


def test_dry_run_depmap(tmp_path):
    """Dry-run prints the plan without pulling the MAF."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.prefetch_source_maf",
         "--source", "depmap_somatic", "--indication", "COADREAD"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        env={"PATH": "/opt/conda/bin:/usr/bin:/bin", "HOME": str(Path.home()),
             "DRY_RUN": "1", "AWS_PROFILE": "cbg"},
    )
    assert result.returncode == 0, f"failed: {result.stderr}"
    assert "prefetch depmap_somatic × COADREAD" in result.stderr
    assert "depmap_lineage" in result.stderr
    assert "DRY_RUN" in result.stderr


def test_genie_bpc_lot_prefix_present():
    """LOT derivation is a distinct non-MAF mode with its own S3 prefix map."""
    from scripts.prefetch_source_maf import GENIE_BPC_S3_PREFIX
    assert "COADREAD" in GENIE_BPC_S3_PREFIX
    assert "CRC_2.0-public_clinical_data" in GENIE_BPC_S3_PREFIX["COADREAD"]


# ---------- effect/exon normalization (Tier-B: enables effect/exon rules) ----

def test_tcga_mc3_opts_into_effect_exon_normalization():
    """MC3 config carries Exon_Number + PolyPhen + normalize_effect so the
    catalogs' effect/exon rules can evaluate; GENIE/DepMap stay opt-out."""
    from scripts.prefetch_source_maf import SOURCE_CONFIGS
    mc3 = SOURCE_CONFIGS["tcga_mc3"]
    assert mc3.exon_col == "Exon_Number"
    assert mc3.polyphen_col == "PolyPhen"
    assert mc3.normalize_effect is True
    # Other sources leave the new knobs at their backward-compatible defaults.
    for other in ("genie_public_v19", "genie_bpc_crc", "depmap_somatic"):
        cfg = SOURCE_CONFIGS[other]
        assert cfg.normalize_effect is False
        assert cfg.exon_col == "" and cfg.polyphen_col == ""


def test_variant_classification_effect_map_covers_catalog_vocab():
    """The MAF v2.4 → catalog effect map must cover every token the catalogs
    author rules against (the effect/exon rules across NSCLC/HNSC/ESCA/PAAD/AML)."""
    from scripts.prefetch_source_maf import VARIANT_CLASSIFICATION_TO_EFFECT as M
    # Catalog effect tokens that come from a raw Variant_Classification value.
    assert M["In_Frame_Del"] == "in_frame_deletion"
    assert M["In_Frame_Ins"] == "in_frame_insertion"
    assert M["Splice_Site"] == "splice_site"
    assert M["Missense_Mutation"] == "missense"
    assert M["Nonsense_Mutation"] == "nonsense"
    # Both frameshift directions collapse (catalogs don't distinguish del/ins).
    assert M["Frame_Shift_Del"] == "frameshift"
    assert M["Frame_Shift_Ins"] == "frameshift"


# ---------- marker-paper + CN prefetch configs (HNSC enrichment) -----------

def test_marker_paper_hnsc_subtype_and_clinical_enrich():
    """HNSC marker-paper prefetch enriches Bass subtype (from pancan-curated) +
    HPV/site (from clinical). NSCLC composes histology from two cohort files."""
    from scripts.prefetch_marker_paper import (
        INDICATION_COHORTS, INDICATION_SUBTYPE_ENRICH, INDICATION_CLINICAL_ENRICH,
        _HNSC_SITE_GROUPING,
    )
    # NSCLC = two cohort files with histology labels (multi-histology composition).
    assert [c[1] for c in INDICATION_COHORTS["NSCLC"]] == ["adenocarcinoma", "squamous_cell_carcinoma"]
    # HNSC Bass subtype comes from pancan-curated, prefix-stripped to bare labels.
    assert INDICATION_SUBTYPE_ENRICH["HNSC"] == ("hnsc_bass_subtype", "HNSC", "HNSC.")
    # HNSC clinical enrichment supplies hpv + site with a site-grouping map.
    ce = INDICATION_CLINICAL_ENRICH["HNSC"]
    assert ce["hpv_col"] == "hpv_status_by_p16_testing"
    assert ce["site_grouping"] is _HNSC_SITE_GROUPING
    # Oropharyngeal bucket = HPV-enriched sites; larynx separate.
    assert _HNSC_SITE_GROUPING["Tonsil"] == "oropharyngeal"
    assert _HNSC_SITE_GROUPING["Base of tongue"] == "oropharyngeal"
    assert _HNSC_SITE_GROUPING["Larynx"] == "larynx"
    assert _HNSC_SITE_GROUPING["Oral Tongue"] == "oral_cavity"


def test_cn_gistic_amp_threshold():
    """CN GISTIC prefetch calls amp at GISTIC +2 (high-level); +1 gain is NOT amp."""
    from scripts.prefetch_cn_gistic import AMP_THRESHOLD
    assert AMP_THRESHOLD == 2


def test_marker_paper_stad_esca_paad_subtype_sources():
    """STAD subtype from pancan-curated (GI. strip); PAAD Moffitt from a per-cohort
    numeric column; ESCA is pancan-only with histology-from-subtype."""
    from scripts.prefetch_marker_paper import (
        INDICATION_SUBTYPE_ENRICH, INDICATION_PERCOHORT_SUBTYPE, INDICATION_PANCAN_ONLY,
    )
    # STAD: 'GI.CIN' -> 'CIN' via prefix strip.
    assert INDICATION_SUBTYPE_ENRICH["STAD"] == ("stad_subtype", "STAD", "GI.")
    # PAAD Moffitt: numeric-coded per-cohort column → basal-like/classical.
    paad = INDICATION_PERCOHORT_SUBTYPE["PAAD"]
    assert paad["out_col"] == "paad_moffitt_subtype"
    assert paad["value_map"][1] == "basal-like" and paad["value_map"][2] == "classical"
    # ESCA: pancan-only base frame; ESCC = squamous, adeno subtypes = adenocarcinoma.
    esca = INDICATION_PANCAN_ONLY["ESCA"]
    assert esca["histology_from_subtype"]["GI.ESCC"] == "squamous_cell_carcinoma"
    assert esca["histology_from_subtype"]["GI.CIN"] == "adenocarcinoma"


def test_dry_run_genie_bpc_lot():
    """LOT dry-run prints the regimen + cancer-panel-test plan without deriving.

    genie_bpc_lot is NOT in SOURCE_CONFIGS — it's a distinct derivation path
    (regimen max-line per index-cancer → sample). The dry-run must still route
    through prefetch_genie_bpc_lot() and stop before pandas work.
    """
    result = subprocess.run(
        [sys.executable, "-m", "scripts.prefetch_source_maf",
         "--source", "genie_bpc_lot", "--indication", "COADREAD"],
        cwd=REPO_ROOT, capture_output=True, text=True, timeout=60,
        env={"PATH": "/opt/conda/bin:/usr/bin:/bin", "HOME": str(Path.home()),
             "DRY_RUN": "1", "AWS_PROFILE": "cbg"},
    )
    assert result.returncode == 0, f"failed: {result.stderr}"
    assert "prefetch genie_bpc_lot × COADREAD" in result.stderr
    assert "regimen_cancer_level_dataset.csv" in result.stderr
    assert "DRY_RUN: skipping LOT derivation" in result.stderr
