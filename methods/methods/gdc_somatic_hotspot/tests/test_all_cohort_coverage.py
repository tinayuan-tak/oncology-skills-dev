"""CASE-029 SNV-recurrence coverage: the all-cohort MC3 aggregate must route every TCGA cohort to a
framework indication, else that cohort is blind on the SNV-recurrence axis (the product is PRODUCT-ONLY —
no live-MAF fallback — so an unbuilt indication reads data_unavailable, a silent false-negative for
IDH1/GBM, IDH2/AML, FLT3/AML etc.)."""

from __future__ import annotations

from methods.gdc_somatic_hotspot.cli import CANCER_TYPE_TO_INDICATION

# The 33 TCGA cohorts in the GDC PanCanAtlas MC3 / merged_sample_quality_annotations crosswalk.
_TCGA_COHORTS = {
    "ACC",
    "BLCA",
    "BRCA",
    "CESC",
    "CHOL",
    "COAD",
    "DLBC",
    "ESCA",
    "GBM",
    "HNSC",
    "KICH",
    "KIRC",
    "KIRP",
    "LAML",
    "LGG",
    "LIHC",
    "LUAD",
    "LUSC",
    "MESO",
    "OV",
    "PAAD",
    "PCPG",
    "PRAD",
    "READ",
    "SARC",
    "SKCM",
    "STAD",
    "TGCT",
    "THCA",
    "THYM",
    "UCEC",
    "UCS",
    "UVM",
}


def test_every_tcga_cohort_maps_to_a_framework_indication():
    missing = _TCGA_COHORTS - set(CANCER_TYPE_TO_INDICATION)
    assert not missing, f"TCGA cohorts unrouted in the all-cohort MC3 build (blind SNV-recurrence): {sorted(missing)}"


def test_pooled_canonicals_are_correct():
    """The three pooled framework canonicals mirror indication_aliases.to_cohort_canonical, and LAML→AML
    is the one heme remap. A wrong pooling would stamp the product's `indication` column with a value the
    read side never queries → a silent data_unavailable."""
    m = CANCER_TYPE_TO_INDICATION
    assert m["COAD"] == m["READ"] == "COADREAD"
    assert m["LUAD"] == m["LUSC"] == "NSCLC"
    assert m["STAD"] == "GC"
    assert m["LAML"] == "AML"
    # every other cohort is identity (its own canonical partition)
    for ct in _TCGA_COHORTS - {"COAD", "READ", "LUAD", "LUSC", "STAD", "LAML"}:
        assert m[ct] == ct, f"{ct} should map to itself, got {m[ct]!r}"
