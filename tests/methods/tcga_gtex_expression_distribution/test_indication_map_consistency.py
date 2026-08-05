"""Regression: the tumor reader's indication maps must be MUTUALLY CONSISTENT (no S3).

The NSCLC bug (2026-08-05): the subtype-assignment map accepted the canonical code NSCLC,
but the base study/tissue maps only had LUAD/LUSC — so an NSCLC query fetched a subtype shard
for a target that had NO pooled tumor data (tumor axis silently data_unavailable). This locks
the invariant: any indication that resolves a subtype shard MUST also resolve base tumor
studies AND a normal tissue, so all three axes are available together.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.tcga_gtex_expression_distribution import read as R  # noqa: E402


def test_nsclc_resolves_both_lung_studies_and_tissue():
    assert R.INDICATION_TO_TCGA_STUDIES.get("NSCLC") == ["LUAD", "LUSC"]
    assert R.INDICATION_TO_GTEX_TISSUE.get("NSCLC") == "LUNG"


def test_luad_lusc_unchanged_single_study():
    # byte-stability: the histology codes still map to their own single study.
    assert R.INDICATION_TO_TCGA_STUDIES.get("LUAD") == ["LUAD"]
    assert R.INDICATION_TO_TCGA_STUDIES.get("LUSC") == ["LUSC"]


def test_every_subtype_shard_indication_resolves_base_maps():
    """The consistency invariant. Any code in the subtype-assignment map must also be in
    BOTH base maps — otherwise a subtype query has no pooled tumor data to stratify."""
    missing_studies, missing_tissue = [], []
    for code in R.INDICATION_TO_TUMOR_ASSIGNMENT_MANIFEST:
        if code not in R.INDICATION_TO_TCGA_STUDIES:
            missing_studies.append(code)
        if code not in R.INDICATION_TO_GTEX_TISSUE:
            missing_tissue.append(code)
    assert not missing_studies, f"subtype-shard codes absent from INDICATION_TO_TCGA_STUDIES: {missing_studies}"
    assert not missing_tissue, f"subtype-shard codes absent from INDICATION_TO_GTEX_TISSUE: {missing_tissue}"
