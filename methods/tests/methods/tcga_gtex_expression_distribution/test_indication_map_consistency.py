"""Regression: the tumor reader's indication maps must be MUTUALLY CONSISTENT (no S3).

The NSCLC bug (2026-08-05): the subtype-assignment map accepted the canonical code NSCLC,
but the base study/tissue maps only had LUAD/LUSC — so an NSCLC query fetched a subtype shard
for a target that had NO pooled tumor data (tumor axis silently data_unavailable). This locks
the invariant: any indication that resolves a subtype shard MUST also resolve base tumor
studies AND a normal tissue, so all three axes are available together.
"""

from __future__ import annotations

from onc_methods.tcga_gtex_expression_distribution import read as R


def test_nsclc_resolves_both_lung_studies_and_tissue():
    assert R.INDICATION_TO_TCGA_STUDIES.get("NSCLC") == ["LUAD", "LUSC"]
    assert R.INDICATION_TO_GTEX_TISSUE.get("NSCLC") == "LUNG"


def test_luad_lusc_unchanged_single_study():
    # byte-stability: the histology codes still map to their own single study.
    assert R.INDICATION_TO_TCGA_STUDIES.get("LUAD") == ["LUAD"]
    assert R.INDICATION_TO_TCGA_STUDIES.get("LUSC") == ["LUSC"]


def test_every_subtype_shard_indication_resolves_a_tumor_source():
    """The consistency invariant (generalized 2026-08-05 for non-TCGA cohorts). Any code in the
    subtype-assignment map must resolve a TUMOR PER-SAMPLE SOURCE — either the TCGA studies map OR
    the non-TCGA source map (SCLC→George) — otherwise a subtype query has no pooled tumor data to
    stratify. (Tissue is TCGA-only; non-TCGA cohorts have no matched GTEx normal, which is fine.)"""
    missing = []
    for code in R.INDICATION_TO_TUMOR_ASSIGNMENT_MANIFEST:
        in_tcga = code in R.INDICATION_TO_TCGA_STUDIES
        in_nontcga = code in R.INDICATION_TO_NONTCGA_SOURCE
        if not (in_tcga or in_nontcga):
            missing.append(code)
    assert not missing, f"subtype-shard codes with NO tumor source (TCGA or non-TCGA): {missing}"


def test_sclc_routes_nontcga_not_tcga():
    # SCLC is deliberately NOT in the TCGA maps — it routes via the non-TCGA source (George).
    assert "SCLC" in R.INDICATION_TO_NONTCGA_SOURCE
    assert R.INDICATION_TO_NONTCGA_SOURCE["SCLC"] == ("sclc", "SCLC")
    assert "SCLC" not in R.INDICATION_TO_TCGA_STUDIES  # not a TCGA study
    assert R._tumor_source("SCLC") == ("sclc", ["SCLC"])


def test_rare_cohort_coverage_resolves_studies_and_tissue():
    """A3 (2026-08-19): the 8 rare cohorts added for per-sample percentile-crossing coverage each
    resolve BOTH a TCGA study and a matched GTEx tissue (recount3 substrate verified live). Kept in
    lockstep — a study without a tissue would compute a fraction-above with no normal reference."""
    rare = {
        "ACC": "ADRENAL_GLAND",
        "PCPG": "ADRENAL_GLAND",
        "KICH": "KIDNEY",
        "KIRP": "KIDNEY",
        "TGCT": "TESTIS",
        "THCA": "THYROID",
        "UCS": "UTERUS",
        "UCEC": "UTERUS",
    }
    for code, tissue in rare.items():
        assert R.INDICATION_TO_TCGA_STUDIES.get(code) == [code], f"{code}: no TCGA study"
        assert R.INDICATION_TO_GTEX_TISSUE.get(code) == tissue, f"{code}: wrong/absent GTEx tissue"
