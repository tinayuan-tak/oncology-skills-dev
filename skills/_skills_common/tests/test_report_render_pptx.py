"""report_render — PPTX backend produces a valid .pptx (pandoc). Skipped where pandoc is unavailable."""

import io
import shutil
import sys
import zipfile
from pathlib import Path

import pytest

SKILLS = Path(__file__).resolve().parents[2]  # skills/
if str(SKILLS) not in sys.path:
    sys.path.insert(0, str(SKILLS))

from _skills_common.report_render import PRESETS, render_report
from _skills_common.report_render._fixtures import make_nomination

pytestmark = pytest.mark.skipif(shutil.which("pandoc") is None, reason="pandoc not on PATH")


def test_pptx_is_a_valid_zip_with_slides():
    data = render_report(make_nomination(), preset="deck", backend="pptx")
    assert isinstance(data, bytes) and data[:2] == b"PK", "not a pptx (zip) blob"
    slides = [n for n in zipfile.ZipFile(io.BytesIO(data)).namelist() if n.startswith("ppt/slides/slide")]
    assert slides, "no slide parts in the pptx"


def test_pptx_renders_for_every_preset():
    for preset in PRESETS:
        data = render_report(make_nomination(), preset=preset, backend="pptx")
        assert data[:2] == b"PK" and len(data) > 1000, f"pptx too small / invalid for {preset}"


def test_pptx_handles_all_block_kinds_transitively():
    from _skills_common.report_render import backends as be
    from _skills_common.report_render import vocab

    assert vocab.BLOCK_KINDS <= be.coverage()["pptx"]
