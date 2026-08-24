"""genomic-alteration-profile's declared certainty-corroboration source card(s) must EQUAL the
target-contracts manifest (certainty_corroboration.yaml gate 'genomic_alteration'). Mirrors the FR /
selectivity guards — catches drift between the manifest and the card the Python extractor reads."""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent.parent
GA_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SKILLS))
sys.path.insert(0, str(GA_SCRIPTS))

from _skills_common.certainty_corroboration import corroboration_cards  # noqa: E402
import run as ga  # noqa: E402


def test_genomic_corroboration_source_matches_manifest():
    manifest = corroboration_cards("genomic_alteration")
    if not manifest:
        import pytest
        pytest.skip("target-contracts not checked out / genomic_alteration not registered")
    assert ga._CERTAINTY_CORROBORATION_CARDS == manifest, (
        f"genomic-alteration-profile reads corroboration from {set(ga._CERTAINTY_CORROBORATION_CARDS)} but "
        f"the manifest declares {set(manifest)} for gate 'genomic_alteration' — manifest/Python drift.")
