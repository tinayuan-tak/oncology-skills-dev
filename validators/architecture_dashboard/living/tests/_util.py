"""Shared test helpers: locate + load the committed framework_atlas.json and import the builder."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_LIVING = Path(__file__).resolve().parent.parent           # .../living
_ARCH = _LIVING.parent                                     # .../architecture_dashboard
_REPO = _ARCH.parent.parent                                # target-contracts repo root
COMMITTED_JSON = _REPO / "health" / "framework_atlas.json"

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
