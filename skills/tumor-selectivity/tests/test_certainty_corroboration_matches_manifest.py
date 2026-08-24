"""tumor-selectivity's declared certainty-corroboration source card(s) must EQUAL the target-contracts
manifest (vocabularies/certainty_corroboration.yaml gate 'selectivity'). Mirrors the FR guard — the
disjointness validator checks manifest-vs-resolvers, but only THIS catches drift between the manifest
and the card the Python certainty extractor actually reads."""
from __future__ import annotations

import sys
from pathlib import Path

SKILLS = Path(__file__).resolve().parent.parent.parent            # for _skills_common
SEL_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SKILLS))
sys.path.insert(0, str(SEL_SCRIPTS))

from _skills_common.certainty_corroboration import corroboration_cards  # noqa: E402
import run as sel  # noqa: E402


def test_selectivity_corroboration_source_matches_manifest():
    manifest = corroboration_cards("selectivity")
    if not manifest:
        import pytest
        pytest.skip("target-contracts not checked out / selectivity not registered")
    assert sel._CERTAINTY_CORROBORATION_CARDS == manifest, (
        f"tumor-selectivity reads corroboration from {set(sel._CERTAINTY_CORROBORATION_CARDS)} but the "
        f"manifest declares {set(manifest)} for gate 'selectivity' — manifest/Python drift. Reconcile "
        f"certainty_corroboration.yaml with _sel_corroboration's input card.")
