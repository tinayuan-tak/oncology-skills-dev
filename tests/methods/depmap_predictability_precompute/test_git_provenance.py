"""git-provenance capture for the depmap_predictability_precompute run_manifest.

`_git_provenance()` stamps the producing repo's git HEAD + working-tree dirty
flag into run_manifest.json, so the downstream data-catalog derived manifest
can copy an AUTHORITATIVE `git_commit` instead of inferring it from whatever
the checkout happens to point at when someone later reads it. Provenance
capture must never fail the precompute — it degrades to None on any git error.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def cli():
    # The module uses a package-relative import (`from . import features`), so
    # load it as a package rather than via spec_from_file_location.
    sys.path.insert(0, str(REPO))
    from methods.depmap_predictability_precompute import cli as _cli

    return _cli


def test_git_provenance_returns_current_head(cli):
    """Inside the analysis-methods checkout, capture the real HEAD SHA."""
    prov = cli._git_provenance()
    expected = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert prov["commit"] == expected
    assert prov["commit"] is not None and len(prov["commit"]) == 40
    assert isinstance(prov["dirty"], bool)
    assert Path(prov["repo_dir"]) == REPO


def test_git_provenance_degrades_when_git_unavailable(cli, monkeypatch):
    """A git failure (e.g. git not installed / not a checkout) must yield
    None fields, not an exception."""

    def _boom(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(cli.subprocess, "run", _boom)
    prov = cli._git_provenance()
    assert prov["commit"] is None
    assert prov["dirty"] is None
    assert "repo_dir" in prov
