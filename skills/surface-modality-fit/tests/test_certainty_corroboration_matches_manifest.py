"""surface-modality-fit's declared certainty-corroboration source must EQUAL the target-contracts
manifest (certainty_corroboration.yaml gate 'surface_modality'). Mirrors the FR/selectivity/genomic guards."""
from __future__ import annotations
import sys
from pathlib import Path
SKILLS = Path(__file__).resolve().parent.parent.parent
SM_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SKILLS)); sys.path.insert(0, str(SM_SCRIPTS))
from _skills_common.certainty_corroboration import corroboration_cards  # noqa: E402
import run as sm  # noqa: E402


def test_surface_corroboration_source_matches_manifest():
    manifest = corroboration_cards("surface_modality")
    if not manifest:
        import pytest
        pytest.skip("target-contracts not checked out / surface_modality not registered")
    assert sm._CERTAINTY_CORROBORATION_CARDS == manifest, (
        f"surface-modality-fit reads corroboration from {set(sm._CERTAINTY_CORROBORATION_CARDS)} but the "
        f"manifest declares {set(manifest)} for gate 'surface_modality' — manifest/Python drift.")
