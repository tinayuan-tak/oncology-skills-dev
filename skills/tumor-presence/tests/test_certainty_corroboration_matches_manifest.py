"""tumor-presence's declared certainty-corroboration source must EQUAL the target-contracts manifest
(certainty_corroboration.yaml gate 'tumor_presence'). Mirrors the FR/selectivity/genomic/surface guards."""
from __future__ import annotations
import sys
from pathlib import Path
SKILLS = Path(__file__).resolve().parent.parent.parent
TP_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SKILLS)); sys.path.insert(0, str(TP_SCRIPTS))
from _skills_common.certainty_corroboration import corroboration_cards  # noqa: E402
import run as tp  # noqa: E402


def test_presence_corroboration_source_matches_manifest():
    manifest = corroboration_cards("tumor_presence")
    if not manifest:
        import pytest
        pytest.skip("target-contracts not checked out / tumor_presence not registered")
    assert tp._CERTAINTY_CORROBORATION_CARDS == manifest, (
        f"tumor-presence reads corroboration from {set(tp._CERTAINTY_CORROBORATION_CARDS)} but the manifest "
        f"declares {set(manifest)} for gate 'tumor_presence' — manifest/Python drift.")
