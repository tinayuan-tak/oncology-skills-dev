"""R3 follow-on: FR's declared certainty-corroboration source cards must EQUAL the target-contracts
manifest (vocabularies/certainty_corroboration.yaml). This makes the manifest authoritative, not merely
parallel — the disjointness validator checks the manifest vs the resolvers, but only THIS check catches
drift between the manifest and the card(s) the Python certainty extractor actually reads.
"""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent.parent            # for _skills_common
FR_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SKILLS))
sys.path.insert(0, str(FR_SCRIPTS))

from _skills_common.certainty_corroboration import corroboration_cards  # noqa: E402
import run as fr  # noqa: E402


def test_fr_corroboration_source_matches_manifest():
    manifest = corroboration_cards("dependency")
    if not manifest:
        import pytest
        pytest.skip("target-contracts not checked out / dependency not registered")
    assert fr._CERTAINTY_CORROBORATION_CARDS == manifest, (
        f"FR reads corroboration from {set(fr._CERTAINTY_CORROBORATION_CARDS)} but the manifest declares "
        f"{set(manifest)} for gate 'dependency' — the manifest and the Python source drifted. Reconcile "
        f"certainty_corroboration.yaml with _corroboration_from_cross_consortium's inputs.")
