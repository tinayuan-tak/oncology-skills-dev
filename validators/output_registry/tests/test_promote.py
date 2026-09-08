"""Tests for the exploratory→governed promotion helper. CI-safe (no siblings, no compose run)."""

from __future__ import annotations

import sys
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

import promote as P  # noqa: E402

_CAT = {
    "summary": {"n_cells": 3, "n_cells_governed": 1},
    "coverage": {
        "grid": {
            "BRAF/SKCM": {
                "governed": {"verdict": "x", "tier": "governed"},
                "tumor-presence": {"verdict": "p", "tier": "exploratory"},
            },
            "MET/COADREAD": {
                "tumor-presence": {"verdict": "broadly_high_expression", "tier": "exploratory"},
                "tumor-selectivity": {"verdict": "selective_but_broadly_normal", "tier": "exploratory"},
            },
            "APC/COADREAD": {"tumor-presence": {"verdict": "tumor_broadly_expressed", "tier": "exploratory"}},
        }
    },
}


def test_candidates_excludes_governed_cells():
    cands = P.promotion_candidates(_CAT)
    cells = {c["cell"] for c in cands}
    assert cells == {"MET/COADREAD", "APC/COADREAD"}  # BRAF/SKCM is governed → excluded
    met = next(c for c in cands if c["cell"] == "MET/COADREAD")
    assert met["target"] == "MET" and met["indication"] == "COADREAD"
    assert met["exploratory"]["tumor-presence"] == "broadly_high_expression"


def test_candidates_sorted():
    assert [c["cell"] for c in P.promotion_candidates(_CAT)] == ["APC/COADREAD", "MET/COADREAD"]


def test_compose_cmd_shape(tmp_path):
    script = tmp_path / "skills" / "compose-dashboard" / "scripts" / "compose_dashboard.py"
    script.parent.mkdir(parents=True)
    script.write_text("# stub")
    cmd = P.compose_cmd(tmp_path, "MET", "COADREAD", "latest_approved", None, None, "pixi run python")
    assert cmd[:3] == ["pixi", "run", "python"]
    assert "--target" in cmd and "MET" in cmd and "COADREAD" in cmd
    assert "--data-mode" in cmd and "latest_approved" in cmd


def test_compose_cmd_missing_script(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError):
        P.compose_cmd(tmp_path, "MET", "COADREAD", "latest_approved", None, None, "pixi run python")
