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


# ---------------------------------------------------------------------------
# Positive tier (v1.1.0, 2026-07-17)
# ---------------------------------------------------------------------------

def test_positive_tier_blocks_present_and_well_formed():
    v = _load()
    assert isinstance(v["positive_signals"], list) and v["positive_signals"]
    for p in v["positive_signals"]:
        assert p["sub_skill"] and p["verdict"]
        assert p["weight"] in {"dominant", "supportive"}
    assert v["positive_tier_config"]["min_dimensions_for_strong"] >= 2
    assert v["positive_tier_config"]["require_dominant_for_strong"] is True
    assert any(p["weight"] == "dominant" for p in v["positive_signals"])


def test_positive_set_disjoint_from_kills_and_contradictions():
    """A verdict cannot be simultaneously a positive AND a kill AND/OR a contradiction
    — the three sets must be pairwise disjoint or the gate resolution is ambiguous."""
    v = _load()
    pos = {(p["sub_skill"], p["verdict"]) for p in v["positive_signals"]}
    kills = {(g["sub_skill"], g["verdict"]) for g in v["gates"]}
    contra = {(c["sub_skill"], c["verdict"]) for c in v["positive_contradictions"]}
    assert pos.isdisjoint(kills), f"positive∩kills: {pos & kills}"
    assert pos.isdisjoint(contra), f"positive∩contradiction: {pos & contra}"


def test_positives_only_from_cross_target_axes():
    """Curation discipline: positives come ONLY from the cross-target axes
    (dependency, selectivity, tractability_sm) — surface/expression/mechanism are
    modality-scoped/advisory and must NOT be positive-eligible."""
    v = _load()
    allowed = {"dependency", "selectivity", "tractability_sm"}
    used = {p["sub_skill"] for p in v["positive_signals"]}
    assert used <= allowed, f"positive from non-cross-target axis: {used - allowed}"
    excl = {(e["sub_skill"], e["verdict"]) for e in v["excluded_positive_modality_scoped"]}
    # the modality-scoped/advisory positives are explicitly documented as excluded
    assert ("surface_modality", "adc_favorable") in excl
    assert ("mechanism", "well_characterized") in excl
