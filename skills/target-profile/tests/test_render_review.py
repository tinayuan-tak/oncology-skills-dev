"""render_review.py is RETIRED (dashboard consolidation, 2026-09-09).

Its bespoke review layout (cross-evidence synthesis + 6-dim deterministic-vs-literature risk +
modality-fit) is now the canonical report_render composed dashboard. This test locks the retirement:
the module no longer builds its own HTML (no `build_html`) — it is a thin shim that points callers at
report_render.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import render_review as rr  # noqa: E402


def test_render_review_is_retired_shim():
    # the bespoke HTML builder is gone (retired onto the canonical report_render dashboard)
    assert not hasattr(rr, "build_html")
    # the shim exits non-zero with a deprecation pointer (never silently renders a divergent design)
    assert rr.main() == 2
