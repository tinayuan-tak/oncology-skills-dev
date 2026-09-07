"""surface-modality-fit's declared certainty-corroboration source must EQUAL the target-contracts
manifest (certainty_corroboration.yaml gate 'surface_modality'). Mirrors the FR/selectivity/genomic guards."""

from __future__ import annotations
from pathlib import Path

from _skills_common.certainty_corroboration import corroboration_cards
from _test_support import load_run_py

sm = load_run_py(Path(__file__).resolve().parent.parent, "smf_run_cc")


def test_surface_corroboration_source_matches_manifest():
    manifest = corroboration_cards("surface_modality")
    if not manifest:
        import pytest

        pytest.skip("target-contracts not checked out / surface_modality not registered")
    assert sm._CERTAINTY_CORROBORATION_CARDS == manifest, (
        f"surface-modality-fit reads corroboration from {set(sm._CERTAINTY_CORROBORATION_CARDS)} but the "
        f"manifest declares {set(manifest)} for gate 'surface_modality' — manifest/Python drift."
    )
