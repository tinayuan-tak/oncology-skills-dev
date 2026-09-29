"""CASE-029 GENIE SNV coverage: the indication maps + shared selector.

GENIE (271k samples, 112 cancer types) was wired for only 4 framework indications (COADREAD/NSCLC/GC/PAAD)
— the same blind spot as the MC3 hotspot product. This pins the extension: the coarse CANCER_TYPE map for
the solid tumours, the ONCOTREE_CODE leaf map for AML/GBM (which "Leukemia"/"Glioma" CANCER_TYPE would pool
away), and the selector precedence the MAF builder + recurrence reader share as one source of truth.
"""

from __future__ import annotations

import pandas as pd

from methods.genie_panel_recurrence.read import (
    GENIE_CANCER_TYPE,
    GENIE_ONCOTREE_CODE,
    select_indication_sample_ids,
)


def test_high_value_indications_are_mapped():
    """The cohorts TCGA is thinnest on (AML/GBM via ONCOTREE_CODE) plus the high-N solid tumours must be
    reachable, else GENIE recurrence reads data_unavailable for them (CASE-029)."""
    assert GENIE_ONCOTREE_CODE.get("AML") == "AML"
    assert GENIE_ONCOTREE_CODE.get("GBM") == "GBM"
    for ind in ("BRCA", "BLCA", "KIRC", "SKCM", "OV", "PRAD", "UCEC", "LIHC", "THCA", "SARC", "MESO", "HNSC"):
        assert ind in GENIE_CANCER_TYPE, f"{ind} unmapped — GENIE recurrence would read data_unavailable"
    # the original 4 are preserved
    for ind in ("COADREAD", "NSCLC", "GC", "PAAD"):
        assert ind in GENIE_CANCER_TYPE


def test_oncotree_code_takes_precedence_over_cancer_type():
    """AML/GBM must select by the leaf ONCOTREE_CODE, NOT the pooled CANCER_TYPE ("Leukemia" would sweep in
    CLL/CML/ALL; "Glioma" would sweep in LGG). This is the whole reason the ONCOTREE map exists."""
    clin = pd.DataFrame(
        {
            "SAMPLE_ID": ["aml1", "cll1", "gbm1", "lgg1", "brca1"],
            "CANCER_TYPE": ["Leukemia", "Leukemia", "Glioma", "Glioma", "Breast Cancer"],
            "ONCOTREE_CODE": ["AML", "CLL", "GBM", "AASTR", "IDC"],
        }
    )
    assert select_indication_sample_ids(clin, "AML") == {"aml1"}  # NOT cll1
    assert select_indication_sample_ids(clin, "GBM") == {"gbm1"}  # NOT lgg1
    assert select_indication_sample_ids(clin, "BRCA") == {"brca1"}
    assert select_indication_sample_ids(clin, "NOT_MAPPED") == set()


def test_builder_imports_the_reader_maps_not_a_copy():
    """Producer/reader must share ONE map so the product's `indication` stamp and the denominator cohort
    select identical samples. The builder imports from the reader module rather than duplicating."""
    import scripts.prefetch_source_maf as b
    from methods.genie_panel_recurrence import read as r

    assert b.GENIE_CANCER_TYPE is r.GENIE_CANCER_TYPE
    assert b.GENIE_ONCOTREE_CODE is r.GENIE_ONCOTREE_CODE
    assert b.select_indication_sample_ids is r.select_indication_sample_ids
