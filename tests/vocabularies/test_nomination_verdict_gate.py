"""Tests for vocabularies/nomination_verdict_gate.yaml.

Pins the structure the target-profile gate loader depends on + the
safety-critical curation invariants (no modality-scoped killer smuggled into
the veto set; excluded set stays disjoint from gates).
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
VOCAB = REPO / "vocabularies" / "nomination_verdict_gate.yaml"


def _load():
    return yaml.safe_load(VOCAB.read_text())


def test_loads_and_has_required_top_level():
    v = _load()
    assert v["enum_id"] == "nomination_verdict_gate"
    assert set(v["action_precedence"]) == {"veto", "hold"}
    assert v["action_precedence"]["veto"] > v["action_precedence"]["hold"]
    assert isinstance(v["gates"], list) and v["gates"]


def test_every_gate_well_formed():
    for g in _load()["gates"]:
        assert g["sub_skill"] and g["verdict"]
        assert g["action"] in {"veto", "hold"}
        assert g["rationale"].strip()  # a human-reviewable reason is mandatory


def test_conservative_veto_set():
    """The veto set must be exactly the two cross-target killers (guards against
    scope creep that would over-veto)."""
    v = _load()
    veto = {(g["sub_skill"], g["verdict"]) for g in v["gates"] if g["action"] == "veto"}
    assert veto == {("dependency", "pan_essential_killer"),
                    ("dependency", "non_dependent")}


def test_safety_is_hold_not_veto():
    v = _load()
    safety = [g for g in v["gates"] if g["sub_skill"] == "safety"]
    assert len(safety) == 1
    assert safety[0]["action"] == "hold"


def test_excluded_modality_scoped_not_in_gates():
    """SAFETY-CRITICAL: modality-scoped killers must NEVER appear in gates — they
    foreclose a modality, not the target (KRAS golden). The excluded list and the
    gate list must be disjoint."""
    v = _load()
    gated = {(g["sub_skill"], g["verdict"]) for g in v["gates"]}
    excluded = {(e["sub_skill"], e["verdict"]) for e in v["excluded_modality_scoped"]}
    assert gated.isdisjoint(excluded)
    # the specific KRAS-relevant killers are on the excluded list
    assert ("surface_modality", "neither_viable") in excluded
    assert ("expression", "broadly_low_expression") in excluded
