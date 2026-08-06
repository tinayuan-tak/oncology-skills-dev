"""Axis-2 (dependency): control_position_dependency classification (fixture vocab +
mocked Chronos, no S3).

Writes a tiny dependency_controls vocab into a tmp contracts dir and monkeypatches the
per-gene median-Chronos read, so the INVERTED classification (pan-essential ceiling vs
non-essential floor) + the data-driven bands + the assembly logic are tested
deterministically offline. Live Chronos reads are exercised end-to-end elsewhere.
"""
from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from methods.dependency_controls import read as DC  # noqa: E402


@pytest.fixture
def contracts(tmp_path):
    """A minimal target-contracts dir with the dependency_controls vocab."""
    voc = tmp_path / "vocabularies"
    voc.mkdir()
    (voc / "dependency_controls.yaml").write_text(textwrap.dedent("""
        version: 9.9.9
        chronos_source: {release_pin: 26q1, metric: pan_panel_median_chronos}
        positive_controls:
          PANESS_DEEP:    {role: pan_essential, applies: universal, empirical_median_chronos_26q1: -2.8}
          PANESS_SHALLOW: {role: pan_essential, applies: universal, empirical_median_chronos_26q1: -1.5}
        negative_controls:
          NONESS_A: {role: non_essential, applies: universal, empirical_median_chronos_26q1: 0.02}
          NONESS_B: {role: non_essential, applies: universal, empirical_median_chronos_26q1: -0.05}
    """))
    DC._load_controls.cache_clear()
    return str(tmp_path)


# Median Chronos each control gene should return under the mock (matches the fixture).
_CONTROL_MEDIANS = {
    "PANESS_DEEP": -2.8, "PANESS_SHALLOW": -1.5,
    "NONESS_A": 0.02, "NONESS_B": -0.05,
}


def _mock_median(target_value):
    """Return a _median_chronos replacement: controls resolve to their fixture value,
    the target resolves to `target_value` (None to simulate an absent target)."""
    def _inner(symbol, release_pin):
        if symbol in _CONTROL_MEDIANS:
            return _CONTROL_MEDIANS[symbol]
        return target_value
    return _inner


# ---- the INVERSION: three anchor classes ----
def test_pan_essential_target_flagged_as_tox_liability(contracts, monkeypatch):
    """A target as essential as the pan-essential controls → as_essential_as_pan_essential
    (the ceiling is the LEAST-negative positive = -1.5; a target <= -1.5 hits it)."""
    monkeypatch.setattr(DC, "_median_chronos", _mock_median(-2.0))
    r = DC.control_position_dependency("PANESS_TARGET", contracts_dir=contracts)
    assert r["dep_control_position_class"] == "as_essential_as_pan_essential"
    assert r["dep_control_pan_essential_ceiling"] == -1.5   # least-negative positive
    assert r["dep_control_non_essential_floor"] == -0.05    # most-negative negative


def test_selective_dependency_between_controls(contracts, monkeypatch):
    """KRAS-like: below the non-essential floor, above the pan-essential ceiling → the
    therapeutic sweet spot."""
    monkeypatch.setattr(DC, "_median_chronos", _mock_median(-0.46))
    r = DC.control_position_dependency("KRAS_LIKE", contracts_dir=contracts)
    assert r["dep_control_position_class"] == "between_controls"


def test_non_dependent_near_negatives(contracts, monkeypatch):
    """A gene at/above the non-essential floor → non_dependent_near_negatives."""
    monkeypatch.setattr(DC, "_median_chronos", _mock_median(0.03))
    r = DC.control_position_dependency("NONDEP", contracts_dir=contracts)
    assert r["dep_control_position_class"] == "non_dependent_near_negatives"


def test_boundary_target_exactly_at_ceiling_is_tox(contracts, monkeypatch):
    """A target EXACTLY at the ceiling counts as pan-essential (<=, conservative on tox)."""
    monkeypatch.setattr(DC, "_median_chronos", _mock_median(-1.5))
    r = DC.control_position_dependency("EDGE", contracts_dir=contracts)
    assert r["dep_control_position_class"] == "as_essential_as_pan_essential"


# ---- data_unavailable safety ----
def test_absent_target_is_data_unavailable(contracts, monkeypatch):
    monkeypatch.setattr(DC, "_median_chronos", _mock_median(None))
    r = DC.control_position_dependency("GHOST", contracts_dir=contracts)
    assert r["dep_control_position_class"] == "data_unavailable"


def test_missing_vocab_degrades_not_raises(tmp_path, monkeypatch):
    """No vocab file → data_unavailable, never a raise (method can land before vocab)."""
    DC._load_controls.cache_clear()
    r = DC.control_position_dependency("KRAS", contracts_dir=str(tmp_path))
    assert r["dep_control_position_class"] == "data_unavailable"
    assert "_dep_control_note" in r


# ---- assembly + provenance ----
def test_emits_provenance_and_control_medians(contracts, monkeypatch):
    monkeypatch.setattr(DC, "_median_chronos", _mock_median(-0.46))
    r = DC.control_position_dependency("KRAS_LIKE", contracts_dir=contracts)
    assert r["dep_control_method_version"] == DC.METHOD_VERSION
    assert set(r["dep_control_positives"]) == {"PANESS_DEEP", "PANESS_SHALLOW"}
    assert set(r["dep_control_negatives"]) == {"NONESS_A", "NONESS_B"}
    assert "INVERTED" in r["dep_control_position_context"]
    # human-readable position mentions both bands
    assert "pan-essential control" in r["dep_control_position"]
    assert "non-essential control" in r["dep_control_position"]
