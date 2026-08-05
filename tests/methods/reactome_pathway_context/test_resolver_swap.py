"""Guard: the HGNC→UniProt crosswalk comes from the Reactome resolver SIDECAR, not a hardcoded map.

Regression for the v0.1 shortcut (a ~30-target inline dict) that failed the standing resolver-sidecar
rule for any target outside the inline set. This pins that the crosswalk is sidecar-backed and resolves
targets that were NEVER in the old inline map (CDH17/GPC3/MSLN). Needs S3 (live sidecar read); skips if
unreachable."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.reactome_pathway_context import read as _r  # noqa: E402


def test_crosswalk_is_sidecar_backed_not_hardcoded():
    # The source must reference the resolver sidecar, and the inline 30-target dict must be gone.
    src = (REPO / "methods" / "reactome_pathway_context" / "read.py").read_text()
    assert "target_resolution.parquet" in src, "crosswalk must read the resolver sidecar"
    assert '"KRAS": "P01116"' not in src, "the hardcoded inline crosswalk must be removed"


@pytest.mark.parametrize("target", ["CDH17", "GPC3", "MSLN"])
def test_non_inline_targets_now_resolve(target):
    # These were NOT in the former inline crosswalk — they resolve only via the sidecar.
    try:
        xwalk = _r._load_hgnc_uniprot_crosswalk()
    except Exception:  # noqa: BLE001
        pytest.skip("resolver sidecar unreachable (no S3)")
    if not xwalk:
        pytest.skip("resolver sidecar unreachable (no S3)")
    assert target in xwalk, f"{target} should resolve to a UniProt AC via the sidecar"
