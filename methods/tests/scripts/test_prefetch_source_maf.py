"""Tests for scripts/prefetch_source_maf.py — the Phase-2b/c mutation-source
prefetch driver.

Validates the source-config table + dry-run planning without requiring
network access. Real S3 pulls are exercised in operational runs, not CI.
"""

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def _load_ops_script(name: str):
    """Load ``methods/scripts/<name>.py`` by file location.

    ``methods/scripts/`` holds operational drivers, NOT package modules: pyproject's
    ``packages.find.include`` is ``onc_methods*``, so the scripts dir is not installed and
    there is no import path to it. These tests used to reach it as a bare top-level
    ``scripts`` namespace package, which resolved ONLY because a ``sys.path.insert`` had put
    the distribution root on ``sys.path`` (deleted in skills#2237). Load by location instead
    — the same idiom the ``steps/*.py`` tests use. The script's OWN
    ``from onc_methods... import`` lines still resolve through the editable install, so
    identity assertions against reader-module objects hold.
    """
    import importlib.util

    path = _OPS_SCRIPTS / f"{name}.py"
    assert path.is_file(), f"ops script not found: {path}"
    spec = importlib.util.spec_from_file_location(f"_ops_script_{name}", path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


_OPS_SCRIPTS = REPO_ROOT / "scripts"
_OPS_PREFETCH_CN_GISTIC = _load_ops_script("prefetch_cn_gistic")
_OPS_PREFETCH_MARKER_PAPER = _load_ops_script("prefetch_marker_paper")
_OPS_PREFETCH_SOURCE_MAF = _load_ops_script("prefetch_source_maf")


def test_source_configs_complete():
    """All 4 sources have complete SourceConfig entries."""
    SOURCE_CONFIGS = _OPS_PREFETCH_SOURCE_MAF.SOURCE_CONFIGS

    expected = {"tcga_mc3", "genie_public_v19", "genie_bpc_crc", "depmap_somatic"}
    assert set(SOURCE_CONFIGS) == expected
    for name, cfg in SOURCE_CONFIGS.items():
        assert cfg.gene_col and cfg.protein_col and cfg.effect_col and cfg.sample_col
        assert cfg.filter_strategy in {"tcga_patient_list", "genie_cancer_type", "depmap_lineage", "none"}


def test_depmap_uses_protein_change_column():
    """DepMap MAF uses Protein_Change (not HGVSp_Short like MC3/GENIE)."""
    SOURCE_CONFIGS = _OPS_PREFETCH_SOURCE_MAF.SOURCE_CONFIGS

    assert SOURCE_CONFIGS["depmap_somatic"].protein_col == "Protein_Change"
    assert SOURCE_CONFIGS["tcga_mc3"].protein_col == "HGVSp_Short"
    assert SOURCE_CONFIGS["genie_public_v19"].protein_col == "HGVSp_Short"


def test_genie_bpc_no_filter():
    """GENIE-BPC CRC is already CRC-only → filter_strategy=none."""
    SOURCE_CONFIGS = _OPS_PREFETCH_SOURCE_MAF.SOURCE_CONFIGS

    assert SOURCE_CONFIGS["genie_bpc_crc"].filter_strategy == "none"


def test_dry_run_depmap(tmp_path):
    """Dry-run prints the plan without pulling the MAF."""
    result = subprocess.run(
        [sys.executable, "-m", "scripts.prefetch_source_maf", "--source", "depmap_somatic", "--indication", "COADREAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={"PATH": "/opt/conda/bin:/usr/bin:/bin", "HOME": str(Path.home()), "DRY_RUN": "1", "AWS_PROFILE": "cbg"},
    )
    assert result.returncode == 0, f"failed: {result.stderr}"
    assert "prefetch depmap_somatic × COADREAD" in result.stderr
    assert "depmap_lineage" in result.stderr
    assert "DRY_RUN" in result.stderr


def test_genie_bpc_lot_prefix_present():
    """LOT derivation is a distinct non-MAF mode with its own S3 prefix map."""
    GENIE_BPC_S3_PREFIX = _OPS_PREFETCH_SOURCE_MAF.GENIE_BPC_S3_PREFIX

    assert "COADREAD" in GENIE_BPC_S3_PREFIX
    assert "CRC_2.0-public_clinical_data" in GENIE_BPC_S3_PREFIX["COADREAD"]


# ---------- effect/exon normalization (Tier-B: enables effect/exon rules) ----


def test_tcga_mc3_opts_into_effect_exon_normalization():
    """MC3 config carries Exon_Number + PolyPhen + normalize_effect so the
    catalogs' effect/exon rules can evaluate."""
    SOURCE_CONFIGS = _OPS_PREFETCH_SOURCE_MAF.SOURCE_CONFIGS

    mc3 = SOURCE_CONFIGS["tcga_mc3"]
    assert mc3.exon_col == "Exon_Number"
    assert mc3.polyphen_col == "PolyPhen"
    assert mc3.normalize_effect is True


def test_depmap_normalizes_effect_but_declares_exon_polyphen_absent():
    """DepMap must normalize `effect` even though it has no Exon_Number/PolyPhen.

    ★ This test previously asserted the OPPOSITE — it pinned `normalize_effect is
    False` for depmap_somatic as intended behaviour, under the reading that DepMap
    "stays opt-out" because it lacks the exon/PolyPhen columns. But the three knobs are
    independent: DepMap DOES carry Variant_Classification, and opting out of
    normalization left its `effect` column holding raw `Nonsense_Mutation` while every
    catalog rule tested `nonsense`. Nothing matched, and all 13 effect-referencing
    strata reported a confident zero on the DepMap cohort (HNSC TP53_mut 0/95 against
    181/277 for the same rule on MC3, with 86 of those 95 models carrying a TP53 hit).

    So: normalize_effect is about the VOCABULARY of a column the source has; exon_col /
    polyphen_col are about columns it does not. Conflating them is what made the defect
    look like a deliberate choice for long enough to ship.
    """
    SOURCE_CONFIGS = _OPS_PREFETCH_SOURCE_MAF.SOURCE_CONFIGS

    depmap = SOURCE_CONFIGS["depmap_somatic"]
    assert depmap.effect_col == "Variant_Classification"
    assert depmap.normalize_effect is True, "raw Variant_Classification matches no catalog rule"
    # DepMap's MAF genuinely has neither column — these stay empty, and the resulting
    # capability gap is DECLARED in the sidecar rather than answered False.
    assert depmap.exon_col == ""
    assert depmap.polyphen_col == ""


def test_genie_sources_stay_raw_and_declare_the_whole_vocabulary_unavailable():
    """GENIE stays raw-passthrough (no effect rule targets it today), but that must be
    DECLARED, not assumed: every normalized token is unproducible from a raw column, so
    a future GENIE effect-rule abstains instead of silently answering False."""
    SOURCE_CONFIGS = _OPS_PREFETCH_SOURCE_MAF.SOURCE_CONFIGS
    _unavailable_effect_tokens = _OPS_PREFETCH_SOURCE_MAF._unavailable_effect_tokens

    for other in ("genie_public_v19", "genie_bpc_crc"):
        cfg = SOURCE_CONFIGS[other]
        assert cfg.normalize_effect is False
        assert cfg.exon_col == "" and cfg.polyphen_col == ""
        unavailable = _unavailable_effect_tokens(cfg)
        assert "nonsense" in unavailable and "frameshift" in unavailable
        assert "missense_damaging" in unavailable


def test_depmap_declares_missense_damaging_unproducible_but_not_the_rest():
    """The declaration has to be NARROW to be useful.

    DepMap can produce `nonsense`/`frameshift`/`splice_site` once normalized, so those
    legs of the TP53 rule must stay evaluable — declaring the whole vocabulary
    unavailable would swap a false-negative defect for a false-abstention one and lose
    every real call."""
    SOURCE_CONFIGS = _OPS_PREFETCH_SOURCE_MAF.SOURCE_CONFIGS
    _unavailable_effect_tokens = _OPS_PREFETCH_SOURCE_MAF._unavailable_effect_tokens

    unavailable = _unavailable_effect_tokens(SOURCE_CONFIGS["depmap_somatic"])
    assert unavailable == {"missense_damaging"}, unavailable

    # MC3 has PolyPhen, so it declares nothing unavailable at all.
    assert _unavailable_effect_tokens(SOURCE_CONFIGS["tcga_mc3"]) == set()


def test_variant_classification_effect_map_covers_catalog_vocab():
    """The MAF v2.4 → catalog effect map must cover every token the catalogs
    author rules against (the effect/exon rules across NSCLC/HNSC/ESCA/PAAD/AML)."""
    M = _OPS_PREFETCH_SOURCE_MAF.VARIANT_CLASSIFICATION_TO_EFFECT

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
    _HNSC_SITE_GROUPING = _OPS_PREFETCH_MARKER_PAPER._HNSC_SITE_GROUPING
    INDICATION_CLINICAL_ENRICH = _OPS_PREFETCH_MARKER_PAPER.INDICATION_CLINICAL_ENRICH
    INDICATION_COHORTS = _OPS_PREFETCH_MARKER_PAPER.INDICATION_COHORTS
    INDICATION_SUBTYPE_ENRICH = _OPS_PREFETCH_MARKER_PAPER.INDICATION_SUBTYPE_ENRICH

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
    AMP_THRESHOLD = _OPS_PREFETCH_CN_GISTIC.AMP_THRESHOLD

    assert AMP_THRESHOLD == 2


def test_marker_paper_stad_esca_paad_subtype_sources():
    """STAD subtype from pancan-curated (GI. strip); PAAD Moffitt from a per-cohort
    numeric column; ESCA is pancan-only with histology-from-subtype."""
    INDICATION_PANCAN_ONLY = _OPS_PREFETCH_MARKER_PAPER.INDICATION_PANCAN_ONLY
    INDICATION_PERCOHORT_SUBTYPE = _OPS_PREFETCH_MARKER_PAPER.INDICATION_PERCOHORT_SUBTYPE
    INDICATION_SUBTYPE_ENRICH = _OPS_PREFETCH_MARKER_PAPER.INDICATION_SUBTYPE_ENRICH

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
        [sys.executable, "-m", "scripts.prefetch_source_maf", "--source", "genie_bpc_lot", "--indication", "COADREAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        env={"PATH": "/opt/conda/bin:/usr/bin:/bin", "HOME": str(Path.home()), "DRY_RUN": "1", "AWS_PROFILE": "cbg"},
    )
    assert result.returncode == 0, f"failed: {result.stderr}"
    assert "prefetch genie_bpc_lot × COADREAD" in result.stderr
    assert "regimen_cancer_level_dataset.csv" in result.stderr
    assert "DRY_RUN: skipping LOT derivation" in result.stderr


# ---------- DepMap lineage resolution (2026-09-13) --------------------------
# This script used to hold its own ONE-entry lineage map ({"COADREAD": "Bowel"}),
# so `--source depmap_somatic` exited 1 with "No DepMap lineage mapping" for SIX
# indications (AML, BRCA, ESCA, HNSC, NSCLC, PAAD) — blocking their DepMap MAF
# measurements outright. test_dry_run_depmap above could never catch it: it asks
# for COADREAD, the one entry that resolved, and its `--dry-run` bails out of
# _filter_samples before the lineage lookup whenever Model.csv is not already
# cached. So the tests below (a) name a NON-COADREAD indication and (b) reach the
# lookup without touching S3.


_PREVIOUSLY_BLOCKED = {
    "AML": "Myeloid",
    "BRCA": "Breast",
    "ESCA": "Esophagus/Stomach",
    "HNSC": "Head and Neck",
    "NSCLC": "Lung",
    "PAAD": "Pancreas",
}


def test_all_previously_blocked_indications_resolve_a_lineage():
    """Every indication the one-entry map rejected now resolves, with the value
    DepMap's own Model.csv uses (verified against a live 26Q1 load: each of the
    six prefetches emits a non-empty parquet, 95-264 distinct models)."""
    _depmap_lineage = _OPS_PREFETCH_SOURCE_MAF._depmap_lineage

    for ind, expected in _PREVIOUSLY_BLOCKED.items():
        assert _depmap_lineage(ind) == expected, ind

    # COADREAD, the one the old map did carry, must not have regressed
    assert _depmap_lineage("COADREAD") == "Bowel"


def test_unmapped_indication_raises_rather_than_scoping_pan_cancer():
    """A missing mapping must be an error, not a silent pan-lineage read."""
    import pytest

    _depmap_lineage = _OPS_PREFETCH_SOURCE_MAF._depmap_lineage

    with pytest.raises(KeyError, match="No DepMap lineage mapping"):
        _depmap_lineage("THYM")


def test_lineage_import_resolves_when_the_script_is_run_by_path():
    """`python scripts/prefetch_source_maf.py` must work, not just `-m scripts...`.

    In the PATH form sys.path[0] is scripts/, so the lazy
    `methods.subgroup_common.lineage` import raises ModuleNotFoundError for every
    DepMap indication unless the module puts the repo root on sys.path. The
    existing dry-run test uses the `-m` form from REPO_ROOT, which masks this.

    Driven through runpy from a foreign cwd with PYTHONPATH stripped so the check
    depends on the script's own bootstrap and nothing else — and offline, so it
    cannot degrade to a skip.
    """
    import os

    script = REPO_ROOT / "scripts" / "prefetch_source_maf.py"
    probe = "import runpy, sys; m = runpy.run_path(sys.argv[1], run_name='_probe'); print(m['_depmap_lineage']('HNSC'))"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}

    result = subprocess.run(
        [sys.executable, "-c", probe, str(script)],
        cwd="/tmp",
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
    )
    assert result.returncode == 0, f"PATH-form invocation broke: {result.stderr}"
    assert result.stdout.strip() == "Head and Neck"
