"""Wiring regression: NSCLC/LUAD point at the LuCA tumor pseudobulk (upgrade from the Census cube)."""

from __future__ import annotations

from onc_methods.sc_tumor_expression_celltype import read as R


def test_nsclc_luad_wired_to_luca():
    assert R.INDICATION_TO_PRODUCT["NSCLC"] == "sc-pseudobulk-tumor-luca-nsclc-v1"
    assert R.INDICATION_TO_PRODUCT["LUAD"] == "sc-pseudobulk-tumor-luca-nsclc-v1"
    assert R.INDICATION_TO_PRODUCT["LUSC"] == "sc-pseudobulk-donor-celltype-lusc-v1"
