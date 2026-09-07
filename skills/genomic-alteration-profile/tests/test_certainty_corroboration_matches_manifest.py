"""genomic-alteration-profile's declared certainty-corroboration source card(s) must EQUAL the
target-contracts manifest (certainty_corroboration.yaml gate 'genomic_alteration'). Mirrors the FR /
selectivity guards — catches drift between the manifest and the card the Python extractor reads."""

from __future__ import annotations

from pathlib import Path

from _skills_common.certainty_corroboration import corroboration_cards
from _test_support import load_run_py

ga = load_run_py(Path(__file__).resolve().parent.parent, "ga_run_cc")


def test_genomic_corroboration_source_matches_manifest():
    manifest = corroboration_cards("genomic_alteration")
    if not manifest:
        import pytest

        pytest.skip("target-contracts not checked out / genomic_alteration not registered")
    assert ga._CERTAINTY_CORROBORATION_CARDS == manifest, (
        f"genomic-alteration-profile reads corroboration from {set(ga._CERTAINTY_CORROBORATION_CARDS)} but "
        f"the manifest declares {set(manifest)} for gate 'genomic_alteration' — manifest/Python drift."
    )
