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
    # >= 1: the gnomAD highly_constrained concern + (2026-07-24) the P5 human-genetics concern.
    # The invariant under test is that EVERY safety verdict is HOLD, never veto (a safety liability
    # is a product decision to escalate, never a default target-foreclosing veto) — assert the
    # PROPERTY across all safety entries, not a brittle count.
    assert len(safety) >= 1
    assert all(g["action"] == "hold" for g in safety), \
        f"every safety gate must be hold, not veto: {[(g['verdict'], g['action']) for g in safety]}"


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
    """Curation discipline: positives come ONLY from cross-target / target-INTRINSIC axes
    (dependency, selectivity, tractability_sm, genomic_alteration, + expression's target-intrinsic
    tumor-vs-adjacent verdict). MODALITY-scoped/advisory signals (surface, mechanism, and expression's
    modality-adjacent broadly_high_expression) must NOT be positive-eligible.

    genomic_alteration added v1.2.0 (biomarker-stratified dependency = a genuine cross-target
    requirement). expression added v1.3.0 (2026-07-21) for the TARGET-INTRINSIC
    strongly_upregulated_in_tumor ONLY — the target's own tumor-vs-normal biology, distinct from the
    modality-scoped broadly_high_expression which stays excluded (the KRAS-guard symmetry)."""
    v = _load()
    allowed = {"dependency", "selectivity", "tractability_sm", "genomic_alteration", "expression"}
    used = {p["sub_skill"] for p in v["positive_signals"]}
    assert used <= allowed, f"positive from disallowed axis: {used - allowed}"
    # expression is positive-eligible ONLY for the target-intrinsic verdict, never the modality-scoped one.
    expr_pos = {p["verdict"] for p in v["positive_signals"] if p["sub_skill"] == "expression"}
    assert expr_pos <= {"strongly_upregulated_in_tumor"}, \
        f"only the target-intrinsic expression verdict may be a positive; got {expr_pos}"
    excl = {(e["sub_skill"], e["verdict"]) for e in v["excluded_positive_modality_scoped"]}
    # the modality-scoped/advisory positives are explicitly documented as excluded
    assert ("surface_modality", "adc_favorable") in excl
    assert ("mechanism", "well_characterized") in excl
    assert ("expression", "broadly_high_expression") in excl   # modality-scoped expression stays OUT
    # and the excluded modality-scoped verdict must NOT also appear as a positive (no contradiction)
    pos = {(p["sub_skill"], p["verdict"]) for p in v["positive_signals"]}
    assert ("expression", "broadly_high_expression") not in pos


# ---------------------------------------------------------------------------
# Veto suppression (v1.2.0, 2026-07-17) — backtest-driven gate-C correction
# ---------------------------------------------------------------------------

def test_veto_suppressors_well_formed_and_conservative():
    """Context-escape suppressors must (a) be well-formed, (b) only suppress
    `non_dependent` (the dilution artifact) — NEVER pan_essential_killer, which is
    a distinct too-essential failure a stratified signal cannot rescue."""
    v = _load()
    supps = v["veto_suppressors"]
    assert isinstance(supps, list) and supps
    for s in supps:
        assert set(s["suppresses"]) == {"sub_skill", "verdict"}
        assert s["suppresses"]["verdict"] == "non_dependent", (
            "context-escape must not suppress pan_essential_killer")
        assert s["when_present"] and s["rationale"].strip()
    # Two suppressor CLASSES (by design), distinguished by whether the trigger also
    # nominates:
    #  (1) rescue-and-nominate — the biomarker-stratified trigger both suppresses the
    #      veto AND is a positive_signal (carries the target through the positive tier).
    #  (2) rescue-to-insufficient — the SynLethDB curated-SL trigger suppresses the veto
    #      to `insufficient` but is ANNOTATION, not measurement, so it must NEVER be a
    #      positive_signal (a curated SL relationship does not nominate a target).
    triggers = {(w["sub_skill"], w["verdict"])
                for s in supps for w in s["when_present"]}
    pos = {(p["sub_skill"], p["verdict"]) for p in v["positive_signals"]}
    # (1) the biomarker trigger IS a positive
    assert ("genomic_alteration", "biomarker_stratified_dependency") in triggers
    assert ("genomic_alteration", "biomarker_stratified_dependency") in pos
    # (2) the SL-annotation trigger is a suppressor but MUST NOT be a positive (never nominates)
    assert ("synthetic_lethal_partners", "has_experimental_sl_partner") in triggers
    assert ("synthetic_lethal_partners", "has_experimental_sl_partner") not in pos, (
        "curated SL is annotation, not measurement — it suppresses a veto but must "
        "never nominate (no positive_signal entry)")


def test_modality_scoped_veto_suppression_biologics_only():
    """Biologics-modality veto suppression must (a) target only the dependency veto
    arms, (b) fire only for surface-directed modalities (adc/bite_tce/antibody) —
    never for SM/degrader (where dependency IS a necessary condition)."""
    v = _load()
    msvs = v["modality_scoped_veto_suppression"]
    assert isinstance(msvs, list) and msvs
    biologics = {"adc", "bite_tce", "antibody"}
    suppressed_verdicts = set()
    for m in msvs:
        assert m["suppresses"]["sub_skill"] == "dependency"
        suppressed_verdicts.add(m["suppresses"]["verdict"])
        assert set(m["when_modality_in"]) <= biologics, (
            "dependency veto must NOT be suppressed for SM/degrader modalities")
    # both dependency veto arms are suppressed for biologics
    assert suppressed_verdicts == {"non_dependent", "pan_essential_killer"}


def test_gates_still_unchanged_by_v1_2_0():
    """v1.2.0 adds suppression + a positive; the `gates` veto set itself is byte-
    stable (suppression is applied by the loader, not by removing a gate)."""
    v = _load()
    veto = {(g["sub_skill"], g["verdict"]) for g in v["gates"] if g["action"] == "veto"}
    assert veto == {("dependency", "pan_essential_killer"),
                    ("dependency", "non_dependent")}


# ---------------------------------------------------------------------------
# Contested threshold (v1.4.0, 2026-08-12) — verdict-INERT fragility banner
# ---------------------------------------------------------------------------

def test_contested_threshold_well_formed_and_inert():
    """The contested_threshold stanza feeds the target-profile FRAGILITY facet ONLY. It must be a
    well-formed numeric knob in [0,1] and must NOT smuggle a verdict into the kill/positive spine —
    it is a verdict-inert banner, so its keys must be disjoint from the gate/positive/contradiction
    (sub_skill, verdict) space (it carries no sub_skill/verdict at all)."""
    v = _load()
    ct = v.get("contested_threshold")
    assert isinstance(ct, dict), "contested_threshold must be a mapping"
    fim = ct.get("fragility_index_min")
    assert isinstance(fim, (int, float)) and 0.0 <= fim <= 1.0, \
        "fragility_index_min must be a fraction in [0,1]"
    # inert: it declares no (sub_skill, verdict) — it cannot participate in gate/positive resolution.
    assert "sub_skill" not in ct and "verdict" not in ct

    # v1.4.0 adds ONLY this stanza; the kill veto set stays byte-stable (regression guard).
    veto = {(g["sub_skill"], g["verdict"]) for g in v["gates"] if g["action"] == "veto"}
    assert veto == {("dependency", "pan_essential_killer"),
                    ("dependency", "non_dependent")}
