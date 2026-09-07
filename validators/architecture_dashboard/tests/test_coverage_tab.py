"""Tests for the dashboard Coverage tab (output-registry layer).

CI-safe: no sibling repos. Uses a fixture catalog.json. Inserts the package dir on sys.path
because this package uses bare (non-relative) imports (build_architecture_explorer, render_arch).

Run: pytest validators/architecture_dashboard/tests/ -q
"""

from __future__ import annotations

import json
import sys
from html.parser import HTMLParser
from pathlib import Path

_PKG = Path(__file__).resolve().parents[1]
if str(_PKG) not in sys.path:
    sys.path.insert(0, str(_PKG))

import build_unified_dashboard as B  # noqa: E402
import render_unified as R  # noqa: E402


_FIXTURE = {
    "generated_at": "2026-08-20T00:00:00Z",
    "summary": {
        "n_entries": 3,
        "n_governed": 1,
        "n_exploratory": 2,
        "n_cells": 2,
        "n_cells_governed": 1,
        "n_cells_exploratory_only": 1,
        "n_cells_both": 0,
        "n_cards_fired_governed": 1,
        "n_cards_fired_exploratory_only": 1,
    },
    "coverage": {
        "lanes": ["governed", "tumor-presence"],
        "cells": ["BRAF/SKCM", "MET/COADREAD"],
        "grid": {
            "BRAF/SKCM": {
                "governed": {
                    "verdict": "no viable modality",
                    "date": "2026-07-02",
                    "location": "BRAF/SKCM/ep-x",
                    "tier": "governed",
                }
            },
            "MET/COADREAD": {
                "tumor-presence": {
                    "verdict": "broadly_high_expression",
                    "date": "2026-08-17",
                    "location": "s3://x",
                    "tier": "exploratory",
                }
            },
        },
    },
    "card_firings": {
        "fired_card_ids_governed": ["a"],
        "fired_card_ids_any": ["a", "z"],
        "by_card": {"z": {"governed": [], "exploratory": ["r1", "r2"]}},
    },
}


def test_load_coverage_present(tmp_path):
    (tmp_path / "catalog.json").write_text(json.dumps(_FIXTURE))
    cov = B.load_coverage(tmp_path)
    assert cov is not None
    assert cov["summary"]["n_cells"] == 2
    assert cov["grid"]["lanes"] == ["governed", "tumor-presence"]
    assert cov["firings"]["fired_card_ids_any"] == ["a", "z"]


def test_load_coverage_absent(tmp_path):
    assert B.load_coverage(tmp_path) is None  # no catalog.json
    (tmp_path / "catalog.json").write_text("{ bad json")
    assert B.load_coverage(tmp_path) is None  # malformed → None, not a crash


def test_coverage_renders_grid_and_signal():
    g = {
        "summary": {},
        "datasets": {},
        "coverage": {
            "generated_at": _FIXTURE["generated_at"],
            "summary": _FIXTURE["summary"],
            "grid": _FIXTURE["coverage"],
            "firings": _FIXTURE["card_firings"],
        },
    }
    frag = R._coverage(g)
    HTMLParser().feed(frag)  # well-formed
    assert "Coverage grid" in frag
    assert "BRAF/SKCM" in frag and "MET/COADREAD" in frag
    # exploratory-lit card 'z' surfaces in the signal-merge callout with its run count
    assert "◐" in frag and "z" in frag
    assert "feeds framework_health" in frag


def test_coverage_empty_state():
    assert "no output registry" in R._coverage({})  # graceful when no coverage attached
