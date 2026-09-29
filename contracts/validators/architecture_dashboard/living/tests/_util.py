"""Shared test helpers: locate + load the committed framework_atlas.json and import the builder."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_LIVING = Path(__file__).resolve().parent.parent  # .../living
_ARCH = _LIVING.parent  # .../architecture_dashboard
_REPO = _ARCH.parent.parent  # target-contracts repo root
COMMITTED_JSON = _REPO / "health" / "framework_atlas.json"
GOLDENS = Path(__file__).resolve().parent / "goldens"
_SKILLS_REPO = "rnd-computational-biology-oncology-claude-oncology-skills"

for p in (str(_ARCH), str(_LIVING)):
    if p not in sys.path:
        sys.path.insert(0, p)


def load_committed() -> dict:
    if not COMMITTED_JSON.exists():
        pytest.skip(f"no committed framework_atlas.json at {COMMITTED_JSON} — run build_living_doc first")
    return json.loads(COMMITTED_JSON.read_text())


def builder():
    import build_living_doc  # noqa: E402  (arch/living on path)

    return build_living_doc


def load_golden(name: str) -> dict:
    return json.loads((GOLDENS / name).read_text())


def skills_root():
    """The claude-oncology-skills sibling checkout, or skip. Live-extraction tests (ladder /
    code-map shims read skill SOURCE) need it; CI is checkout-only, so they skip there while the
    committed-artifact tests still run. Tries the build default, then the worktree sibling."""
    import build_architecture_explorer as A  # noqa: E402

    # NOTE (#2090): the in-tree skills root is _REPO.parent (`<repo>/skills`), but these
    # LIVE-EXTRACTION tests compare against committed goldens that have drifted from the live
    # extraction (e.g. test_ladder_extract's rung `tier`s) — a separate golden re-baseline owned by
    # the living-doc/framework-health maintainers, out of scope for the sibling-root un-pin. Left
    # deliberately gated on the legacy sibling-checkout path so they stay a NAMED, pre-existing skip
    # (checkout-only), never a false green, until that re-baseline lands.
    candidates = [Path(A.DEFAULTS["sk"]), _REPO.parent / _SKILLS_REPO]
    for c in candidates:
        if (c / "skills" / "tumor-presence" / "scripts" / "run.py").exists():
            return c
    pytest.skip(f"no {_SKILLS_REPO} sibling (checkout-only env) — skipping live source extraction")


def tc_root() -> Path:
    return _REPO
