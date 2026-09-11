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
    assert veto == {("dependency", "pan_essential_killer"), ("dependency", "non_dependent")}


def test_safety_is_hold_not_veto():
    v = _load()
    safety = [g for g in v["gates"] if g["sub_skill"] == "safety"]
    # >= 1: the gnomAD highly_constrained concern + (2026-07-24) the P5 human-genetics concern.
    # The invariant under test is that EVERY safety verdict is HOLD, never veto (a safety liability
    # is a product decision to escalate, never a default target-foreclosing veto) — assert the
    # PROPERTY across all safety entries, not a brittle count.
    assert len(safety) >= 1
    assert all(g["action"] == "hold" for g in safety), (
        f"every safety gate must be hold, not veto: {[(g['verdict'], g['action']) for g in safety]}"
    )


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


def test_forces_nominate_only_at_strong():
    """The positive path may force `nominate` (1.18.0) — but ONLY from the `strong` tier.

    `strong` is the only threshold that already encodes the conjunction a nomination should
    require (>= min_dimensions_for_strong independent lines after correlated-group collapse, a
    `dominant` hit, and no unreconciled measured contradiction). `moderate` is reachable on a
    SINGLE supportive hit — pointing this key at it would nominate on one weak signal.
    Absent/null is legal and means "never nominate" (pre-1.18.0 behaviour).
    """
    cfg = _load()["positive_tier_config"]
    tier = cfg.get("forces_nominate_at_tier")
    assert tier in {"strong", None}, f"forces_nominate_at_tier must be 'strong' or absent, got {tier!r}"


def test_nominate_is_not_a_gate_action():
    """`nominate` must NEVER become a gate action — the restraint/positive split is structural.

    `action_precedence` is the key function of a `max()` over the FIRED KILL hits in
    tp_gates._gate_recommendation. A positive token in that ranking would be compared against, and
    tie-break with, a veto/hold — i.e. a nomination could outrank (or be silently outranked by) a
    restraint. The positive path forces `nominate` from its own else-branch instead, reachable only
    when no kill fired. This test is the tripwire on that invariant; the companion assertions live in
    claude-oncology-skills/skills/target-profile/tests/test_gate_vocab_skills_coupling.py.
    """
    v = _load()
    assert "nominate" not in v["action_precedence"], (
        "`nominate` was added to action_precedence — it must stay a positive-tier-only action; "
        "see positive_tier_config.forces_nominate_at_tier"
    )
    for g in v["gates"]:
        assert g["action"] != "nominate", f"gate {g['sub_skill']}:{g['verdict']} declares action: nominate"


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
    # subtype_fit added v1.4.0 (2026-08-19, subtype-verdict-shifting review §5): a MEASURED,
    # floor-cleared STRONG subtype-restricted dependency is a genuine CROSS-TARGET requirement (a
    # stratified dependency signal), positive-eligible ONLY for subtype_restricted_dependency — the
    # negative subtype verdict (subtype_specific_non_dependence) stays a hold, never a positive.
    # cis_coherence added v1.5.0 (2026-08-20, cis-feature-coherence graduation): a coherent
    # cis-driver (the target's own CN dosage predicts its own expression AND it is dependency-
    # coupled) is a genuine TARGET-INTRINSIC cross-target requirement, positive-eligible ONLY for
    # coherent_cis_driver — the inert/uncoupled cis verdicts never nominate.
    # differentiation added v1.11.0 (2026-09-07, differentiation deep-dive): strong_mutually_exclusive
    # is a genuine CROSS-TARGET requirement — the target's mutations are strongly mutually-exclusive with
    # established driver partner(s) across the pan-cohort Fisher scan, a driver-inference + patient-
    # selection signal. Positive-eligible ONLY for strong_mutually_exclusive; both_patterns_present /
    # strong_cooccurring stay advisory (combination CONTEXT, not target-quality). GROUPED with
    # genomic_alteration+cis_coherence (correlated_dimension_groups) so it corroborates confidence but
    # never independently mints `strong`.
    allowed = {
        "dependency",
        "selectivity",
        "tractability_sm",
        "genomic_alteration",
        "expression",
        "subtype_fit",
        "cis_coherence",
        "differentiation",
    }
    used = {p["sub_skill"] for p in v["positive_signals"]}
    assert used <= allowed, f"positive from disallowed axis: {used - allowed}"
    # cis_coherence is positive-eligible ONLY for the coherent-cis-driver verdict (same guard shape
    # as expression/subtype_fit — the inert/uncoupled cis verdicts must never leak into positives).
    cis_pos = {p["verdict"] for p in v["positive_signals"] if p["sub_skill"] == "cis_coherence"}
    assert cis_pos <= {"coherent_cis_driver"}, (
        f"only coherent_cis_driver may be a cis_coherence positive; got {cis_pos}"
    )
    # expression is positive-eligible ONLY for the target-intrinsic verdict, never the modality-scoped one.
    expr_pos = {p["verdict"] for p in v["positive_signals"] if p["sub_skill"] == "expression"}
    assert expr_pos <= {"strongly_upregulated_in_tumor"}, (
        f"only the target-intrinsic expression verdict may be a positive; got {expr_pos}"
    )
    # subtype_fit is positive-eligible ONLY for the measured subtype-restricted POSITIVES — the
    # cell-line dependency rung (subtype_restricted_dependency) and its tumor-tissue analogue
    # (subtype_restricted_selectivity, 2026-09-11, added to reach indications whose DepMap subtype
    # channel is data-blocked, e.g. STAD/ESCA). The negative subtype hold (subtype_specific_non_dependence)
    # must never leak into positives — same guard shape as expression.
    subtype_pos = {p["verdict"] for p in v["positive_signals"] if p["sub_skill"] == "subtype_fit"}
    assert subtype_pos <= {"subtype_restricted_dependency", "subtype_restricted_selectivity"}, (
        f"only subtype_restricted_dependency / subtype_restricted_selectivity may be a subtype_fit positive; got {subtype_pos}"
    )
    excl = {(e["sub_skill"], e["verdict"]) for e in v["excluded_positive_modality_scoped"]}
    # the modality-scoped/advisory positives are explicitly documented as excluded.
    # 2026-08-15: the surface_modality tokens must be the ones the resolver ACTUALLY
    # emits (adc_preferred/tce_preferred) — the former adc_favorable/tce_favorable were
    # never emitted, so the guard was inert. Assert the real tokens AND that the stale
    # spellings are gone (prevents this assertion silently going vacuous again).
    assert ("surface_modality", "adc_preferred") in excl
    assert ("surface_modality", "tce_preferred") in excl
    assert ("surface_modality", "adc_favorable") not in excl
    assert ("surface_modality", "tce_favorable") not in excl
    assert ("mechanism", "well_characterized") in excl
    assert ("expression", "broadly_high_expression") in excl  # modality-scoped expression stays OUT
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
        assert s["suppresses"]["verdict"] == "non_dependent", "context-escape must not suppress pan_essential_killer"
        assert s["when_present"] and s["rationale"].strip()
        # Each when_present trigger is EITHER a verdict-tuple form ({sub_skill, verdict}) OR a
        # CARD-FIELD form ({card_id, field, value} — 2026-08-21, for a signal on a card under a
        # GATELESS sub-skill). No other shape is valid.
        for w in s["when_present"]:
            assert set(w) == {"sub_skill", "verdict"} or set(w) == {"card_id", "field", "value"}, (
                f"veto-suppressor trigger must be a verdict-tuple or card-field trigger, got {set(w)}"
            )
    # Two suppressor CLASSES (by design), distinguished by whether the trigger also
    # nominates:
    #  (1) rescue-and-nominate — the biomarker-stratified trigger both suppresses the
    #      veto AND is a positive_signal (carries the target through the positive tier).
    #  (2) rescue-to-insufficient — the SynLethDB curated-SL trigger suppresses the veto
    #      to `insufficient` but is ANNOTATION, not measurement, so it must NEVER be a
    #      positive_signal (a curated SL relationship does not nominate a target).
    verdict_triggers = {(w["sub_skill"], w["verdict"]) for s in supps for w in s["when_present"] if "verdict" in w}
    cardfield_triggers = {
        (w["card_id"], w["field"], w["value"]) for s in supps for w in s["when_present"] if "card_id" in w
    }
    pos = {(p["sub_skill"], p["verdict"]) for p in v["positive_signals"]}
    # (1) the biomarker trigger IS a positive
    assert ("genomic_alteration", "biomarker_stratified_dependency") in verdict_triggers
    assert ("genomic_alteration", "biomarker_stratified_dependency") in pos
    # (2) the SynLethDB curated-SL trigger is now a CARD-FIELD trigger (the synthetic_lethal_partners
    #     short was consolidated 2026-08-20 into the GATELESS combination_vulnerability sub-skill, so
    #     the old verdict-tuple form could never match; the signal lives on the card field). It remains
    #     annotation-not-measurement, so it is (trivially) not a positive_signal.
    assert ("synthetic-lethal-partners", "sl_partner_class", "has_experimental_sl_partner") in cardfield_triggers, (
        "the SynLethDB curated-SL veto-suppressor trigger must be present as a card-field trigger"
    )
    assert ("synthetic_lethal_partners", "has_experimental_sl_partner") not in verdict_triggers, (
        "the retired synthetic_lethal_partners verdict-tuple trigger must be gone (it can never match "
        "a gateless sub-skill's verdict)"
    )


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
            "dependency veto must NOT be suppressed for SM/degrader modalities"
        )
    # both dependency veto arms are suppressed for biologics
    assert suppressed_verdicts == {"non_dependent", "pan_essential_killer"}


def test_gates_still_unchanged_by_v1_2_0():
    """v1.2.0 adds suppression + a positive; the `gates` veto set itself is byte-
    stable (suppression is applied by the loader, not by removing a gate)."""
    v = _load()
    veto = {(g["sub_skill"], g["verdict"]) for g in v["gates"] if g["action"] == "veto"}
    assert veto == {("dependency", "pan_essential_killer"), ("dependency", "non_dependent")}


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
    assert isinstance(fim, (int, float)) and 0.0 <= fim <= 1.0, "fragility_index_min must be a fraction in [0,1]"
    # inert: it declares no (sub_skill, verdict) — it cannot participate in gate/positive resolution.
    assert "sub_skill" not in ct and "verdict" not in ct

    # v1.4.0 adds ONLY this stanza; the kill veto set stays byte-stable (regression guard).
    veto = {(g["sub_skill"], g["verdict"]) for g in v["gates"] if g["action"] == "veto"}
    assert veto == {("dependency", "pan_essential_killer"), ("dependency", "non_dependent")}


# ---------------------------------------------------------------------------
# R1-casing (2026-08-15) — modality-scoped surface positives must match the
# surface_modality resolver's EMITTED (lowercase) verdicts, else the case-
# sensitive gate loader never matches them (the entries would be dead).
# ---------------------------------------------------------------------------


def _resolver_surface_verdicts() -> set[str]:
    rp = REPO / "resolvers" / "surface_modality.resolver.yaml"
    doc = yaml.safe_load(rp.read_text())
    out = set()
    for rung in doc.get("resolve", []) or []:
        if isinstance(rung, dict) and rung.get("verdict"):
            out.add(rung["verdict"])
    return out


def test_modality_scoped_positive_verdicts_match_resolver_casing():
    v = _load()
    block = v.get("positive_signals_modality_scoped")
    assert isinstance(block, list) and block
    resolver_verdicts = _resolver_surface_verdicts()
    assert resolver_verdicts, "could not parse surface_modality resolver verdicts"
    for p in block:
        assert p["sub_skill"] == "surface_modality"
        # every referenced verdict must be one the resolver actually emits (case-sensitive) — a
        # TitleCase drift (TCE_preferred/ADC_preferred) would be a DEAD entry the loader never matches.
        assert p["verdict"] in resolver_verdicts, (
            f"modality-scoped positive verdict {p['verdict']!r} is not emitted by the "
            f"surface_modality resolver {sorted(resolver_verdicts)} — casing/name drift makes it dead"
        )
        assert p["verdict"] == p["verdict"].lower(), (
            f"surface verdicts are emitted lowercase; {p['verdict']!r} is mis-cased"
        )


# ---------------------------------------------------------------------------
# R2 (2026-08-15) — human_genetics_safety_concern driving_rule_ids provenance
# completeness: must cite EVERY rule the safety resolver lists in the verdict's
# when_any_fired set (ClinVar was missing).
# ---------------------------------------------------------------------------


def test_human_genetics_driving_rules_match_resolver_when_any():
    v = _load()
    gate = next(g for g in v["gates"] if g["sub_skill"] == "safety" and g["verdict"] == "human_genetics_safety_concern")
    gate_rules = set(gate["driving_rule_ids"])
    assert "clinvar-germline-pathogenic-safety-warning" in gate_rules
    # cross-check against the resolver's when_any_fired for the same verdict
    resolver = yaml.safe_load((REPO / "resolvers" / "safety.resolver.yaml").read_text())
    rungs = resolver.get("resolve", [])
    # v1.4.0 (2026-08-09) hoisted several when_all_fired mutant-selective CONTEXT rungs with the
    # SAME verdict ABOVE the raw provenance rung, so a bare `verdict ==` next() now grabs a
    # when_all_fired rung first. Select the rung that actually carries when_any_fired — that is
    # the raw provenance rung whose fired-set this test cross-checks against the gate.
    hg = next(r for r in rungs if r.get("verdict") == "human_genetics_safety_concern" and "when_any_fired" in r)
    assert set(hg["when_any_fired"]) == gate_rules, (
        f"gate driving_rule_ids {sorted(gate_rules)} must equal the resolver's when_any_fired "
        f"{sorted(hg['when_any_fired'])} for full provenance"
    )


# ── Thesis routing (Step 2b, v1.17.0) ──────────────────────────────────────────────────────────────
def _thesis_enum():
    import yaml as _y

    p = REPO / "vocabularies" / "target_thesis.yaml"
    return set(_y.safe_load(p.read_text())["theses"]) if p.exists() else None


def test_thesis_axis_relevance_well_formed():
    tar = _load().get("thesis_axis_relevance")
    assert isinstance(tar, list) and tar, "thesis_axis_relevance must be a non-empty list"
    enum = _thesis_enum()
    for blk in tar:
        assert blk["thesis"], "each block names a thesis"
        if enum is not None:
            assert blk["thesis"] in enum, f"{blk['thesis']} not in target_thesis.yaml enum"
        assert blk["rationale"].strip(), "a human-reviewable rationale is mandatory"
        assert blk["irrelevant"], "each block lists >=1 irrelevant (sub_skill, verdict)"
        for ir in blk["irrelevant"]:
            assert ir["sub_skill"] and ir["verdict"]


def test_thesis_routing_never_drops_pan_essential_or_safety():
    """SAFETY-CRITICAL guardrail: thesis routing may make a pooled `non_dependent` irrelevant, but it
    must NEVER make pan_essential_killer (broad-tox) or any SAFETY hold irrelevant — those are real
    regardless of thesis. Mirrors biology_axis_scoped_veto_downgrade's 'does NOT touch
    pan_essential_killer' bound."""
    for blk in _load()["thesis_axis_relevance"]:
        for ir in blk["irrelevant"]:
            assert not (ir["sub_skill"] == "dependency" and ir["verdict"] == "pan_essential_killer"), (
                f"{blk['thesis']} must not drop pan_essential_killer (broad-tox liability)"
            )
            assert ir["sub_skill"] != "safety", f"{blk['thesis']} must not make a safety hold irrelevant"


def test_oncogene_addiction_and_unresolved_have_no_thesis_entry():
    """oncogene_addiction is where the dependency axis legitimately decides, and `unresolved` must
    reproduce today's gate byte-for-byte — neither may appear in thesis_axis_relevance."""
    routed = {blk["thesis"] for blk in _load()["thesis_axis_relevance"]}
    assert "unresolved" not in routed, "unresolved must be today's gate — no thesis routing"
    assert "oncogene_addiction" not in routed, "oncogene_addiction decides on dependency — not irrelevant"
