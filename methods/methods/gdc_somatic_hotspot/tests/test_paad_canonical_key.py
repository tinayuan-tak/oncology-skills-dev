"""Regression: PAAD (framework-canonical pancreatic OncoTree code) must resolve to
TCGA-PAAD in the indication→projects maps.

The maps originally keyed ONLY on `PDAC` (the CPTAC-cohort spelling), so a skill invoked
with the canonical `PAAD` (indication_crosswalk.yaml) hit `.get('PAAD') -> None` and the
aggregate/per-sample producers short-circuited to an EMPTY product — a silent
indication-vocabulary-fragmentation failure. Both codes are now dual-keyed (mirrors
dge_deseq2). These pin that both resolve to the same projects, so neither spelling n/a's.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from methods.gdc_somatic_hotspot import cli  # noqa: E402
from methods.gdc_somatic_hotspot import read as R  # noqa: E402


def test_paad_and_pdac_both_resolve_in_cli_map():
    m = cli.INDICATION_TO_TCGA_PROJECTS
    assert m.get("PAAD") == ["TCGA-PAAD"], "canonical PAAD must resolve (was the empty-product bug)"
    assert m.get("PDAC") == ["TCGA-PAAD"], "PDAC (CPTAC spelling) must still resolve"
    assert m["PAAD"] == m["PDAC"], "dual-key must point at the same projects"


def test_paad_and_pdac_both_resolve_in_read_map():
    m = R.INDICATION_TO_GDC_PROJECTS
    assert m.get("PAAD") == ["TCGA-PAAD"]
    assert m.get("PDAC") == ["TCGA-PAAD"]
    assert m["PAAD"] == m["PDAC"]


def test_cli_and_read_maps_agree():
    """The two maps are duplicated across cli.py and read.py (to keep read.py click-free);
    they must not drift — a canonical code present in one but not the other reintroduces the bug."""
    assert set(cli.INDICATION_TO_TCGA_PROJECTS) == set(R.INDICATION_TO_GDC_PROJECTS)
    for k in cli.INDICATION_TO_TCGA_PROJECTS:
        assert cli.INDICATION_TO_TCGA_PROJECTS[k] == R.INDICATION_TO_GDC_PROJECTS[k], f"{k} drifted"
