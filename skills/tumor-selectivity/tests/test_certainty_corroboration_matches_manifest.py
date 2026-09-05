"""tumor-selectivity's declared certainty-corroboration source card(s) must EQUAL the target-contracts
manifest (vocabularies/certainty_corroboration.yaml gate 'selectivity'). Mirrors the FR guard — the
disjointness validator checks manifest-vs-resolvers, but only THIS catches drift between the manifest
and the card the Python certainty extractor actually reads."""
from __future__ import annotations

from pathlib import Path

from _skills_common.certainty_corroboration import corroboration_cards
from _test_support import load_run_py

sel = load_run_py(Path(__file__).resolve().parent.parent, "sel_run_cc")


def test_selectivity_corroboration_source_matches_manifest():
    manifest = corroboration_cards("selectivity")
    if not manifest:
        import pytest
        pytest.skip("target-contracts not checked out / selectivity not registered")
    assert sel._CERTAINTY_CORROBORATION_CARDS == manifest, (
        f"tumor-selectivity reads corroboration from {set(sel._CERTAINTY_CORROBORATION_CARDS)} but the "
        f"manifest declares {set(manifest)} for gate 'selectivity' — manifest/Python drift. Reconcile "
        f"certainty_corroboration.yaml with _sel_corroboration's input card.")
