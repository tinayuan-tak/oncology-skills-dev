"""tumor-presence's declared certainty-corroboration source must EQUAL the target-contracts manifest
(certainty_corroboration.yaml gate 'tumor_presence'). Mirrors the FR/selectivity/genomic/surface guards."""
from __future__ import annotations
from pathlib import Path

from _skills_common.certainty_corroboration import corroboration_cards
from _test_support import load_run_py

tp = load_run_py(Path(__file__).resolve().parent.parent, "tp_run_cc")


def test_presence_corroboration_source_matches_manifest():
    manifest = corroboration_cards("tumor_presence")
    if not manifest:
        import pytest
        pytest.skip("target-contracts not checked out / tumor_presence not registered")
    assert tp._CERTAINTY_CORROBORATION_CARDS == manifest, (
        f"tumor-presence reads corroboration from {set(tp._CERTAINTY_CORROBORATION_CARDS)} but the manifest "
        f"declares {set(manifest)} for gate 'tumor_presence' — manifest/Python drift.")
