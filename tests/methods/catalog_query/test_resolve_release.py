"""T4 (2026-08-11 engineering review): catalog_query.resolve_release — data_mode/release_pin
actually select a manifest.

Before this, compose-dashboard's data_mode (latest_approved|pinned|exploratory) + release_pin
flowed only into ID strings — 'pinned' and 'exploratory' resolved the SAME data. resolve_release
turns (family, data_mode, release_pin) into a concrete manifest_id via the existing catalog +
supersedes graph. These tests run against the REAL catalog (families with coexisting siblings).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_METHODS = Path(__file__).resolve().parents[3] / "methods"
sys.path.insert(0, str(_METHODS))

from catalog_query.read import (  # noqa: E402
    resolve_release, _family_of, load_catalog, ReleaseResolutionError,
)

# A family known to carry multiple coexisting siblings in the catalog.
_MULTI_FAMILY = "depmap-consortium"


def _members(family: str) -> list[str]:
    idx = load_catalog()
    return sorted(m for m in idx.manifests if _family_of(m) == family)


@pytest.fixture(scope="module")
def multi_members():
    ms = _members(_MULTI_FAMILY)
    if len(ms) < 2:
        pytest.skip(f"family {_MULTI_FAMILY!r} no longer has >=2 coexisting members ({ms})")
    return ms


def test_family_strip():
    assert _family_of("depmap-predictability-26q1-v2") == "depmap-predictability"
    assert _family_of("prism-oncref-dmc-25q4") == "prism-oncref-dmc"
    assert _family_of("sc-pseudobulk-donor-celltype-coadread-v2") == "sc-pseudobulk-donor-celltype-coadread"


def test_latest_approved_picks_head(multi_members):
    """latest_approved resolves to a real member and is >= every other member by id sort
    (newest release wins when there are no supersedes edges)."""
    resolved = resolve_release(_MULTI_FAMILY, "latest_approved")
    assert resolved in multi_members
    assert resolved == multi_members[-1], f"expected head {multi_members[-1]}, got {resolved}"


def test_pinned_selects_specific_sibling(multi_members):
    """pinned resolves to the sibling matching the pin — including an OLDER one (real selection)."""
    oldest = multi_members[0]
    # derive the pin token from the oldest member id (its release suffix)
    pin = oldest[len(_MULTI_FAMILY) + 1:]
    assert resolve_release(_MULTI_FAMILY, "pinned", pin) == oldest


def test_pinned_requires_pin():
    with pytest.raises(ReleaseResolutionError):
        resolve_release(_MULTI_FAMILY, "pinned")


def test_pinned_unknown_pin_fails_loud(multi_members):
    with pytest.raises(ReleaseResolutionError):
        resolve_release(_MULTI_FAMILY, "pinned", "99q9-nonexistent")


def test_exploratory_pin_takes_precedence_else_head(multi_members):
    oldest = multi_members[0]
    pin = oldest[len(_MULTI_FAMILY) + 1:]
    # with a resolvable pin, exploratory honors it
    assert resolve_release(_MULTI_FAMILY, "exploratory", pin) == oldest
    # with no pin, exploratory falls to head (same as latest_approved)
    assert resolve_release(_MULTI_FAMILY, "exploratory") == multi_members[-1]


def test_unknown_family_fails_loud():
    with pytest.raises(ReleaseResolutionError):
        resolve_release("no-such-family-xyz", "latest_approved")


def test_concrete_id_as_family_is_accepted():
    """A single-release product often IS its own family id; passing the concrete id resolves to it."""
    idx = load_catalog()
    # pick any manifest whose id == its own family (no version siblings)
    concrete = next(m for m in idx.manifests if _family_of(m) == m)
    assert resolve_release(concrete, "latest_approved") == concrete
