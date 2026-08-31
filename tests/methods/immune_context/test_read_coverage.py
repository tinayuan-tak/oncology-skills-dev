"""immune_context.read — indication→TCGA-study coverage map (no S3).

Pins that first-class TCGA studies the immune-context card advertises resolve to study code(s)
rather than silently returning data_unavailable. The CIBERSORT product covers all 33 TCGA studies,
so UCEC + SARC (absent from the dge_deseq2 map) are supplemented in the reader. (IM-1 fix)
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.immune_context.read import INDICATION_TO_TCGA_STUDIES  # noqa: E402


def test_ucec_sarc_resolve_to_studies():
    assert INDICATION_TO_TCGA_STUDIES.get("UCEC") == ["UCEC"]
    assert INDICATION_TO_TCGA_STUDIES.get("SARC") == ["SARC"]


def test_nsclc_umbrella_still_resolves():
    # regression guard: the pre-existing umbrella supplement is preserved.
    assert INDICATION_TO_TCGA_STUDIES.get("NSCLC") == ["LUAD", "LUSC"]
