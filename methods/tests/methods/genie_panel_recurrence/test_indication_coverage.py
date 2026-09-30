"""CASE-029 GENIE SNV coverage: the indication maps + shared selector.

GENIE (271k samples, 112 cancer types) was wired for only 4 framework indications (COADREAD/NSCLC/GC/PAAD)
— the same blind spot as the MC3 hotspot product. This pins the extension: the coarse CANCER_TYPE map for
the solid tumours, the ONCOTREE_CODE leaf map for AML/GBM (which "Leukemia"/"Glioma" CANCER_TYPE would pool
away), and the selector precedence the MAF builder + recurrence reader share as one source of truth.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from onc_methods.genie_panel_recurrence.read import (
    GENIE_CANCER_TYPE,
    GENIE_ONCOTREE_CODE,
    select_indication_sample_ids,
)


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


_OPS_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
_OPS_PREFETCH_SOURCE_MAF = _load_ops_script("prefetch_source_maf")


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
    b = _OPS_PREFETCH_SOURCE_MAF
    from onc_methods.genie_panel_recurrence import read as r

    assert b.GENIE_CANCER_TYPE is r.GENIE_CANCER_TYPE
    assert b.GENIE_ONCOTREE_CODE is r.GENIE_ONCOTREE_CODE
    assert b.select_indication_sample_ids is r.select_indication_sample_ids
