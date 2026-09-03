"""PPTX slide-deck backend — the markdown rendering converted to a native .pptx via pandoc.

Dependency-free by design: it shells out to `pandoc` (already on the env PATH) rather than adding a
python-pptx dependency to the shared skills env (a team-level env change, out of this workstream's
scope). One slide per skill (``--slide-level=2`` splits on the per-skill ``##`` headings).

It composes the markdown backend (single source — deck content == the markdown report), so it inherits
every block kind's rendering; `handled_kinds()` is the full vocabulary transitively. Returns BYTES (a
.pptx zip), so it is a BINARY backend (see backends.BINARY_BACKENDS): stdout printing is unsupported —
callers must write to a file.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

from .. import vocab
from ..ir import ReportIR
from .text import TextBackend


class PptxBackend:
    def handled_kinds(self) -> set:
        # renders via the markdown backend, which covers the whole vocabulary.
        return set(vocab.BLOCK_KINDS)

    def render(self, ir: ReportIR) -> bytes:
        md = TextBackend(markdown=True).render(ir)
        pandoc = shutil.which("pandoc")
        if not pandoc:
            raise RuntimeError(
                "the pptx backend needs `pandoc` on PATH (markdown→pptx conversion); "
                "install pandoc, or use the 'html' backend for a slide-style deck.")
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as tf:
                tmp = tf.name
            subprocess.run(
                [pandoc, "-f", "markdown", "-t", "pptx", "--slide-level=2", "-o", tmp],
                input=md.encode("utf-8"), check=True, capture_output=True,
            )
            with open(tmp, "rb") as fh:
                return fh.read()
        except subprocess.CalledProcessError as e:  # surface pandoc's own message, not a bare exit code
            raise RuntimeError(f"pandoc failed to build the pptx: {e.stderr.decode('utf-8', 'replace')}")
        finally:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)


__all__ = ["PptxBackend"]
