"""Wiring regression: NSCLC/LUAD avidity reads the LuCA same-cell coexpr cube (upgrade from Census)."""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))
from methods.pair_selectivity_gate import samecell as S  # noqa: E402


def test_nsclc_luad_avidity_wired_to_luca():
    assert S.INDICATION_TO_SAMECELL_MANIFEST["NSCLC"] == "sc-samecell-coexpr-luca-nsclc-v1"
    assert S.INDICATION_TO_SAMECELL_MANIFEST["LUAD"] == "sc-samecell-coexpr-luca-nsclc-v1"


def test_lusc_stays_dedicated():
    assert S.INDICATION_TO_SAMECELL_MANIFEST["LUSC"] == "sc-samecell-coexpr-lusc-v1"
