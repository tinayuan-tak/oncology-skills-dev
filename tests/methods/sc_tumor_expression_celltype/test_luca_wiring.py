"""Wiring regression: NSCLC/LUAD point at the LuCA tumor pseudobulk (upgrade from the Census cube)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from methods.sc_tumor_expression_celltype import read as R  # noqa: E402


def test_nsclc_luad_wired_to_luca():
    assert R.INDICATION_TO_PRODUCT["NSCLC"] == "sc-pseudobulk-tumor-luca-nsclc-v1"
    assert R.INDICATION_TO_PRODUCT["LUAD"] == "sc-pseudobulk-tumor-luca-nsclc-v1"
    assert R.INDICATION_TO_PRODUCT["LUSC"] == "sc-pseudobulk-donor-celltype-lusc-v1"
