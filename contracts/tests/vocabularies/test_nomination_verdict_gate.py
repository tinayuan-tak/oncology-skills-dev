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
    """The veto set must be exactly the three cross-target killers (guards against scope creep
    that would over-veto).

    WIDENED 2026-09-18 (Stage 2b) from two arms to three: `not_dependent_in_indication` joins the
    pooled `non_dependent`. This pin was written to stop exactly this kind of addition, so the
    widening is deliberate and the reason is stated here rather than in a commit nobody re-reads:
    the new arm is the SAME claim as the pooled one measured at the grain the run actually asked
    about (dependency.resolver v1.5.0, priority 9 vs the pooled arm's 22), not a new KIND of veto.
    It forecloses EXACTLY the queried scope — which is why `subtype_specific_non_dependence`
    remains a HOLD, foreclosing a scope narrower than the question.

    An exact-set assert is KEPT rather than relaxed to a predicate, because the ratchet is the
    point: a fourth arm must again be a deliberate edit here. The PROPERTY the pin protects is
    asserted separately below, so that widening the set cannot quietly also widen the kind.
    """
    v = _load()
    veto = {(g["sub_skill"], g["verdict"]) for g in v["gates"] if g["action"] == "veto"}
    assert veto == {
        ("dependency", "pan_essential_killer"),
        ("dependency", "non_dependent"),
        ("dependency", "not_dependent_in_indication"),
    }


def test_veto_kind_is_never_widened_by_adding_an_arm():
    """The PROPERTY test_conservative_veto_set's exact set used to carry implicitly.

    Enumerating three tuples says nothing about what KIND of thing may veto, so adding an arm
    could silently widen the kind while the set assert still looked deliberate. Three structural
    invariants, none of which mentions a specific arm:

      1. Only `dependency` may veto. Every other axis is hold-or-nothing (safety escalates, it
         does not foreclose; surface/selectivity are modality calls).
      2. A veto is either a broad-tox SAFETY liability or a MEASURED NON-DEPENDENCE. Never an
         `insufficient*` verdict — "we could not look" is the one state that must never
         foreclose a target, and the resolver routes all three could-not-look states to their
         own rungs precisely so a coverage gap cannot reach the killer.
      3. Never `discordant`. That verdict means the axis's own arms disagree, i.e. an ABSENCE of
         resolution rather than a measurement against the target (vocab 1.20.0 moved it off
         `contradiction` for the same reason).
    """
    v = _load()
    vetoes = [g for g in v["gates"] if g["action"] == "veto"]
    assert vetoes, "an empty veto set would make every assertion below vacuous"

    off_axis = [(g["sub_skill"], g["verdict"]) for g in vetoes if g["sub_skill"] != "dependency"]
    assert not off_axis, f"only the dependency axis may veto; found {off_axis}"

    underpowered = [g["verdict"] for g in vetoes if g["verdict"].startswith("insufficient")]
    assert not underpowered, (
        f"'we could not look' must never veto: {underpowered}. A veto on an underpowered read "
        f"forecloses a target for a coverage gap, which is fail-CLOSED on absence."
    )

    assert "discordant" not in {g["verdict"] for g in vetoes}, (
        "discordant is an absence of resolution, not a measurement against the target"
    )

    # Anti-vacuity: the two arms below must genuinely DIFFER in kind, or invariant 2 is testing
    # nothing. One veto must be the safety liability and at least one a non-dependence claim.
    verdicts = {g["verdict"] for g in vetoes}
    assert "pan_essential_killer" in verdicts, "the safety-liability arm must be present"
    assert verdicts - {"pan_essential_killer"}, "at least one non-dependence arm must be present"
    assert all("non_dependent" in v_ or "not_dependent" in v_ for v_ in verdicts - {"pan_essential_killer"}), (
        f"every non-safety veto arm must be a non-dependence claim: {verdicts}"
    )


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
    """A verdict cannot be simultaneously a positive AND a kill AND/OR a contradiction AND/OR
    uncorroborated — the sets must be pairwise disjoint or the gate resolution is ambiguous."""
    v = _load()
    pos = {(p["sub_skill"], p["verdict"]) for p in v["positive_signals"]}
    kills = {(g["sub_skill"], g["verdict"]) for g in v["gates"]}
    contra = {(c["sub_skill"], c["verdict"]) for c in v["positive_contradictions"]}
    # positive_uncorroborated (v1.20.0): blocks `strong` like a contradiction, so a verdict that is
    # simultaneously a positive would both supply and withhold corroboration.
    uncorr = {(u["sub_skill"], u["verdict"]) for u in v["positive_uncorroborated"]}
    assert pos.isdisjoint(kills), f"positive∩kills: {pos & kills}"
    assert pos.isdisjoint(contra), f"positive∩contradiction: {pos & contra}"
    assert pos.isdisjoint(uncorr), f"positive∩uncorroborated: {pos & uncorr}"
    assert contra.isdisjoint(uncorr), f"contradiction∩uncorroborated: {contra & uncorr}"


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
    # selection signal. both_patterns_present ADDED as a positive #897 (2026-09-25): it is a SUPERSET of
    # the strong_mutually_exclusive predicate (cooccurrence_fisher_pancohort/read.py:225-230), so wiring
    # only the mutex-exclusive composite was non-monotone — the mutex HALF is a genuine positive regardless
    # of the co-occurring half. strong_cooccurring stays advisory (pure combination CONTEXT, no mutex arm).
    # GROUPED with genomic_alteration+cis_coherence (correlated_dimension_groups) so it corroborates
    # confidence but never independently mints `strong`.
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
    # cell-line dependency rung (subtype_restricted_dependency), its tumor-tissue analogue
    # (subtype_restricted_selectivity, 2026-09-11, added to reach indications whose DepMap subtype
    # channel is data-blocked, e.g. STAD/ESCA), and the POWERED cross-subtype expression differential
    # (subtype_powered_differential, 2026-09-26 v1.23.0, claude-oncology-skills#1624 — the DOMINANT
    # patient-selection rung minted on a `powered` axis). The negative subtype hold
    # (subtype_specific_non_dependence) must never leak into positives — same guard shape as expression.
    subtype_pos = {p["verdict"] for p in v["positive_signals"] if p["sub_skill"] == "subtype_fit"}
    assert subtype_pos <= {
        "subtype_restricted_dependency",
        "subtype_restricted_selectivity",
        "subtype_powered_differential",
    }, (
        "only subtype_restricted_dependency / subtype_restricted_selectivity / "
        f"subtype_powered_differential may be a subtype_fit positive; got {subtype_pos}"
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
    """Context-escape suppressors must (a) be well-formed, (b) only suppress a NON-DEPENDENCE
    verdict — NEVER pan_essential_killer, which is a distinct too-essential failure a stratified
    signal cannot rescue.

    WIDENED 2026-09-18 (Stage 2b): the suppressible set was the single token `non_dependent`; it is
    now the two non-dependence arms. The exclusion this pin exists for is UNCHANGED and is now
    asserted directly as a negative rather than implied by an equality — which is strictly stronger,
    because the old form would also have been satisfied by a typo'd token that happened not to be
    `pan_essential_killer`.
    """
    v = _load()
    supps = v["veto_suppressors"]
    assert isinstance(supps, list) and supps
    _SUPPRESSIBLE = {"non_dependent", "not_dependent_in_indication"}
    for s in supps:
        assert set(s["suppresses"]) == {"sub_skill", "verdict"}
        assert s["suppresses"]["verdict"] != "pan_essential_killer", (
            "context-escape must not suppress pan_essential_killer: a broad-tox liability is real "
            "regardless of which stratum the dependency lives in"
        )
        assert s["suppresses"]["verdict"] in _SUPPRESSIBLE, (
            f"only a non-dependence verdict is suppressible by a context escape, got {s['suppresses']['verdict']!r}"
        )
        assert s["suppresses"]["sub_skill"] == "dependency"
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
    # (2), second member (2026-09-18, A4i): strong paralog buffering is also rescue-to-insufficient.
    # It says which MODALITY could work (degrader-preferred), not that the target is required, so it
    # must never be a positive_signal — the same reason curated SL annotation is not one. This arm
    # exists only for the indication grain: at pooled grain the resolver's paralog rung relabels the
    # verdict to `non_dependent_paralog_buffered` before the gate sees it, so a pooled suppressor
    # would be unreachable. (An earlier version of this comment added "and no such rung outranks the
    # indication killer" — true of resolver v1.5.0, made FALSE by v1.6.0, which added the indication
    # twin. A4i is kept as pin-lag defence-in-depth; see
    # test_a4i_is_kept_as_defence_in_depth_not_as_redundancy.)
    assert ("paralog-buffering", "paralog_buffering_class", "strong") in cardfield_triggers, (
        "the paralog-buffering veto-suppressor trigger must be present as a card-field trigger"
    )
    assert not any("paralog" in p["verdict"] for p in v["positive_signals"]), (
        "paralog buffering must never be a positive_signal: it is a modality preference, not "
        "evidence that the target is required"
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
    # ALL dependency veto arms are suppressed for biologics. WIDENED 2026-09-18 to three: the
    # escape here is ORTHOGONALITY, not dilution — an ADC/TCE/mAb engages a surface antigen, so
    # genetic essentiality is the wrong question at EVERY grain (CD19/TROP2/DLL3 are approved and
    # none is a dependency in any indication). That makes the indication-conditioned arm's inclusion
    # forced rather than analogical: an argument that does not depend on panel size cannot become
    # invalid when the panel narrows. Note this block DOES suppress pan_essential_killer, unlike
    # veto_suppressors — a surface-directed modality need not spare the gene in normal tissue.
    assert suppressed_verdicts == {
        "non_dependent",
        "not_dependent_in_indication",
        "pan_essential_killer",
    }


# The two HISTORICAL per-version "inertness controls" that used to live here
# (`test_gates_still_unchanged_by_v1_2_0`, and the trailing veto-set clause of
# `test_contested_threshold_well_formed_and_inert`) were REMOVED 2026-09-29 (SK#2091). Neither
# asserted what the veto set contains — each asserted only that ITS OWN landed version bump
# (v1.2.0 suppression, v1.4.0 contested_threshold) had left the set alone. Verdict non-movement is
# not a proof obligation, so a per-version non-movement control is not a test. The RATCHET is
# unaffected: `test_conservative_veto_set` above still asserts the veto set exactly, by literal, so
# a fourth arm still requires a deliberate edit there.


# ---------------------------------------------------------------------------
# Contested threshold (v1.4.0, 2026-08-12) — fragility banner, off the kill/positive spine
# ---------------------------------------------------------------------------


def test_contested_threshold_well_formed_and_structurally_off_the_spine():
    """The contested_threshold stanza feeds the target-profile FRAGILITY facet ONLY. It must be a
    well-formed numeric knob in [0,1] and must not smuggle a verdict into the kill/positive spine —
    a STRUCTURAL claim: its keys are disjoint from the gate/positive/contradiction (sub_skill,
    verdict) space because it carries no sub_skill/verdict at all. That disjointness is the teeth
    here; the old trailing "and the veto set didn't move" clause was a non-movement control and is
    gone (SK#2091)."""
    v = _load()
    ct = v.get("contested_threshold")
    assert isinstance(ct, dict), "contested_threshold must be a mapping"
    fim = ct.get("fragility_index_min")
    assert isinstance(fim, (int, float)) and 0.0 <= fim <= 1.0, "fragility_index_min must be a fraction in [0,1]"
    # structurally off the spine: it declares no (sub_skill, verdict) — it cannot participate in
    # gate/positive resolution at all.
    assert "sub_skill" not in ct and "verdict" not in ct


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


# ── Thesis DECIDING axes (Step 3, v1.18.0) ─────────────────────────────────────────────────────────
# The first block in this vocabulary that can produce `nominate`. Every test below guards one of the
# four fail-closed paths that keep "routing must never invent a GO" a STRUCTURAL property rather than
# a policy note: (1) abstention-only, (2) measured-only, (3) registered-thesis-only, (4) an inverted
# (fail-EMPTY) loader on the skills side.


def _resolver_verdicts(name: str) -> set[str]:
    """Every verdict this axis can PUBLISH — the `resolve:` rungs PLUS anything a declared
    `post_resolver_clamp` stage can mint. Selectivity's `selective_with_normal_liability` (the
    selectivity-PRESERVING clamp arm that FOLR1/DLL3/MSLN all read) exists ONLY in the clamp's
    precedence table, so a rungs-only reader would wrongly call it a dead entry."""
    p = REPO / "resolvers" / f"{name}.resolver.yaml"
    doc = yaml.safe_load(p.read_text())
    out = {r["verdict"] for r in (doc.get("resolve") or []) if isinstance(r, dict) and r.get("verdict")}
    clamp = doc.get("post_resolver_clamp") or {}
    out |= {c["verdict"] for c in (clamp.get("precedence") or []) if isinstance(c, dict) and c.get("verdict")}
    if isinstance(clamp.get("upgrade"), dict) and clamp["upgrade"].get("verdict"):
        out.add(clamp["upgrade"]["verdict"])
    return out


def test_action_precedence_still_has_no_nominate():
    """SAFETY-CRITICAL, the load-bearing assertion of Step 3's design: the deterministic kill gate stays
    one-directional-up. `nominate` is minted by a SEPARATE stage that only runs in the else-branch of the
    kill gate (structurally unreachable while any veto/hold survives) — exactly the reachability argument
    the positive tier already relies on. Adding `nominate` here instead would demote 'kills resolve first'
    from a structural property to a precedence-ordering policy, and would perturb every fail-closed path."""
    v = _load()
    assert set(v["action_precedence"]) == {"veto", "hold"}
    assert not any(g.get("action") == "nominate" for g in v["gates"])


def test_thesis_deciding_axes_well_formed():
    tda = _load().get("thesis_deciding_axes")
    assert isinstance(tda, list) and tda, "thesis_deciding_axes must be a non-empty list"
    enum = _thesis_enum()
    for blk in tda:
        assert blk["thesis"], "each block names a thesis"
        if enum is not None:
            assert blk["thesis"] in enum, f"{blk['thesis']} not in target_thesis.yaml enum"
        assert blk["action"] == "nominate", "a deciding-axis block exists only to mint `nominate`"
        assert blk["rationale"].strip(), "a human-reviewable rationale is mandatory"
        dec = blk["deciding"]
        assert dec["sub_skill"], "the deciding axis names its sub_skill"
        assert dec["favorable_verdicts"], "a decider with no favorable verdict set can never fire"


def test_every_deciding_block_carries_corroboration_and_a_measured_conjunct():
    """NEVER-INVENT-A-GO, structural form. A favorable decider verdict alone must never be sufficient:
    every block must also require (a) >=1 corroborating measured verdict on an INDEPENDENT axis and
    (b) >=1 MEASURED card field. (b) is what stops a nomination whose own deciding axis is blind — the
    surface cohort's ground-truth deciding axis (E2 antigen density) is `blind` for all 7 surface
    reference targets, so without it the block would nominate on an unmeasured decider."""
    for blk in _load()["thesis_deciding_axes"]:
        reqs = blk.get("requires") or []
        assert len(reqs) >= 1, f"{blk['thesis']}: a deciding axis must be corroborated, never sufficient alone"
        for r in reqs:
            assert r["sub_skill"] != blk["deciding"]["sub_skill"], (
                f"{blk['thesis']}: corroboration must come from an axis OTHER than the decider"
            )
            assert r["verdict_in"], "an empty verdict_in would be vacuously satisfiable"
            assert r["rationale"].strip()
        measured = blk.get("requires_measured_card_field") or []
        assert len(measured) >= 1, f"{blk['thesis']}: needs >=1 measured-card-field conjunct (anti-blind bound)"
        for m in measured:
            assert m["card_id"] and m["field"] and m["value_in"]
            assert m["rationale"].strip()


def test_deciding_favorable_verdicts_are_emitted_by_their_resolver():
    """Dead-entry / casing guard (same failure mode test_modality_scoped_positive_verdicts_match_resolver_casing
    exists for): a favorable verdict the resolver never emits is a silently dead admissibility condition."""
    for blk in _load()["thesis_deciding_axes"]:
        sub = blk["deciding"]["sub_skill"]
        emitted = _resolver_verdicts(sub)
        assert emitted, f"could not parse {sub} resolver verdicts"
        for verdict in blk["deciding"]["favorable_verdicts"]:
            assert verdict in emitted, (
                f"{blk['thesis']} favorable verdict {verdict!r} is not emitted by the {sub} resolver "
                f"{sorted(emitted)} — name/casing drift makes the decider dead"
            )
            assert verdict == verdict.lower(), f"{verdict!r} is mis-cased"


def test_deciding_requires_verdicts_are_emitted_where_a_resolver_exists():
    """Same dead-entry guard for the corroboration conjuncts, for the axes that HAVE a contracts resolver
    (expression verdicts are emitted by the tumor-presence skill, not a resolver here — skipped)."""
    for blk in _load()["thesis_deciding_axes"]:
        for r in blk.get("requires") or []:
            path = REPO / "resolvers" / f"{r['sub_skill']}.resolver.yaml"
            if not path.exists():
                continue
            emitted = _resolver_verdicts(r["sub_skill"])
            for verdict in r["verdict_in"]:
                assert verdict in emitted, (
                    f"{blk['thesis']} requires {r['sub_skill']}={verdict!r} which that resolver never "
                    f"emits {sorted(emitted)} — the conjunction could never be satisfied"
                )


def test_deciding_verdicts_never_overlap_a_kill_or_a_contradiction():
    """A verdict that elsewhere in this vocabulary KILLS or CONTRADICTS a target must never also be
    admissible as a positive decider or as corroboration. Guards the incoherence that would let one
    measured verdict simultaneously veto and nominate."""
    v = _load()
    kills = {(g["sub_skill"], g["verdict"]) for g in v["gates"]}
    contras = {(c["sub_skill"], c["verdict"]) for c in (v.get("positive_contradictions") or [])}
    forbidden = kills | contras
    for blk in v["thesis_deciding_axes"]:
        sub = blk["deciding"]["sub_skill"]
        for verdict in blk["deciding"]["favorable_verdicts"]:
            assert (sub, verdict) not in forbidden, f"{sub}={verdict} both decides positively and kills/contradicts"
        for r in blk.get("requires") or []:
            for verdict in r["verdict_in"]:
                assert (r["sub_skill"], verdict) not in forbidden, (
                    f"{r['sub_skill']}={verdict} is required as corroboration yet also kills/contradicts"
                )


def test_measured_conjunct_never_admits_the_abstention_token():
    """The anti-blind conjunct must exclude the card's own 'no calibrated measurement' token — admitting
    it would reinstate exactly the blindness it exists to block (absence of measurement is never evidence:
    the honest-negative discipline). Also pins the field name against the card's summary_fields so a
    rename cannot silently make the conjunct unreadable (a missing field must fail closed, not pass)."""
    _ABSTENTION_TOKENS = {"unmeasured", "unknown", "not_assessed", "data_unavailable", "not_informative"}
    for blk in _load()["thesis_deciding_axes"]:
        for m in blk.get("requires_measured_card_field") or []:
            assert not (_ABSTENTION_TOKENS & set(m["value_in"])), (
                f"{m['card_id']}.{m['field']} value_in admits an abstention token: {sorted(m['value_in'])}"
            )
            card = REPO / "cards" / f"{m['card_id']}.card.yaml"
            assert card.exists(), f"deciding block references a non-existent card {m['card_id']}"
            fields = (yaml.safe_load(card.read_text()).get("outputs") or {}).get("summary_fields") or []
            assert m["field"] in fields, (
                f"{m['field']!r} is not in {m['card_id']}'s outputs.summary_fields {fields} — "
                f"the conjunct would read a missing key on every run"
            )


def test_only_the_graduated_theses_can_mint_a_nominate():
    """Blast-radius pin. Step 3 graduates the SURFACE axis under `antigen_driven` only; every other
    thesis — including `unresolved` (which must reproduce today's gate byte-for-byte) and
    `oncogene_addiction` (the KRAS golden) — keeps a deterministic gate that can only veto/hold, so their
    behaviour is unchanged. Widening this set is a reviewed decision, not a drive-by edit."""
    routed = {blk["thesis"] for blk in _load()["thesis_deciding_axes"]}
    assert routed == {"antigen_driven"}, f"unreviewed widening of the nominate-capable thesis set: {sorted(routed)}"


def test_surface_verdicts_with_no_viable_arm_are_not_favorable():
    """The favorable set is the ADMISSIBILITY half of the 2d bound ('admissibility of surface-as-decider is
    co-conditioned on a FAVORABLE measured verdict'). Verdicts that foreclose every delivery arm, or that
    assert only an unconfirmed annotation, must never be favorable — that is where a routing change would
    invent a GO. Pinned by name so a resolver that later renames them fails this test loudly."""
    never_favorable = {
        "neither_viable",  # no viable arm at all
        "shed_dominant_opposed",  # shedding opposes every arm
        "tce_unsafe_normal_liability",  # TCE foreclosed, no ADC arm asserted
        "tce_escape_risk",  # ditto
        "surface_annotation_only_unconfirmed",  # ANNOTATION, not a measurement — the decoys' shape
        "pmhc_tce_supported",  # single-axis IEDB support; only ever `supportive`
    }
    emitted = _resolver_verdicts("surface_modality")
    for blk in _load()["thesis_deciding_axes"]:
        if blk["deciding"]["sub_skill"] != "surface_modality":
            continue
        favorable = set(blk["deciding"]["favorable_verdicts"])
        assert not (favorable & never_favorable), (
            f"{blk['thesis']} admits a no-viable-arm surface verdict: {sorted(favorable & never_favorable)}"
        )
        # the exclusion list must stay LIVE: every name still has to be a verdict the resolver emits
        assert never_favorable <= emitted, (
            f"exclusion list has drifted from the surface_modality resolver: {sorted(never_favorable - emitted)}"
        )


def test_irrelevant_contradiction_axes_is_a_narrow_whitelist_of_irrelevance():
    """`irrelevant_contradiction_axes` stops a positive_contradiction on a named axis from blocking a
    nomination. Three bounds keep it from becoming a permission list:
      (a) it may NEVER name a KILL-capable axis — a kill resolves in the gate, and naming it here would
          read as "this thesis ignores that axis" even though the code cannot honour that;
      (b) it may NEVER name an axis the thesis's OWN deciding/requires conjunction depends on (that
          would let a verdict be simultaneously required-favorable and ignored-when-opposing);
      (c) every entry needs a rationale, and the named axis must actually HAVE a contradiction to be
          irrelevant about — otherwise the entry is decoration that hides its own deadness."""
    v = _load()
    kill_axes = {g["sub_skill"] for g in v["gates"]}
    contra_axes = {c["sub_skill"] for c in (v.get("positive_contradictions") or [])}
    for blk in v["thesis_deciding_axes"]:
        own = {blk["deciding"]["sub_skill"]} | {r["sub_skill"] for r in (blk.get("requires") or [])}
        for e in blk.get("irrelevant_contradiction_axes") or []:
            ax = e["sub_skill"]
            assert e.get("rationale", "").strip(), f"{ax}: a human-reviewable rationale is mandatory"
            assert ax not in kill_axes, f"{blk['thesis']}: {ax} is kill-capable — not declarable irrelevant here"
            assert ax not in own, f"{blk['thesis']}: {ax} is part of its own conjunction — cannot also be ignored"
            assert ax in contra_axes, f"{blk['thesis']}: {ax} carries no positive_contradiction — dead entry"


# Pre-clamp verdicts a `downgrade_only` clamp can re-label INTO an arm this conjunction admits, without
# the loader being able to see where they came from. Keyed by axis, pinned BY NAME (not by count) so the
# guard below fires in BOTH directions: if the hole WIDENS, and if it is CLOSED. Closing it is a reviewed
# edit that updates this table — never a silent green. The default for an unlisted axis is the empty set,
# i.e. "a newly clamped axis showing this shape is an unreviewed fail-open hole".
_ACCEPTED_PRE_CLAMP_LEAKS = {
    "selectivity": {"field_effect_tumor_selective"},
}


def test_admitted_clamp_arms_cannot_launder_an_excluded_pre_clamp_verdict():
    """FAIL-OPEN NON-MONOTONICITY GUARD, and the pin the `⚠ THAT LAST EXCLUSION IS NOT ENFORCEABLE
    THROUGH THE CLAMP` comment in the vocabulary points at.

    A `post_resolver_clamp` publishes ONE token. When a corroboration conjunct admits a clamp OUTPUT
    while excluding one of that clamp's declared `applies_to_input_verdicts`, the excluded input becomes
    reachable through the admitted output — and the loader cannot tell the two apart, because it reads
    only the post-clamp verdict and the clamp exports no pre-clamp provenance field. The direction is
    fail-OPEN, which is the part that makes it a safety bug rather than an inelegance:

        clean normal profile           -> <excluded pre-clamp verdict>  -> conjunction UNSATISFIED
        critical-organ liability FIRED -> <admitted clamp arm>          -> conjunction SATISFIED

    i.e. DETECTING a liability flips a block into a GO. This test does not pretend the hole is closed. It
    bounds the hole to a named set, keeps that set LIVE against resolver renames, and refuses to go
    vacuous if the shape that makes it reachable ever disappears (a guard that silently stops applying is
    worse than no guard).

    ⚠ WHAT WOULD ACTUALLY CLOSE IT — corrected 2026-09-15 (session d50d3d59), immediately after the
    guard itself landed as 232f4ca8 / #778, because this docstring as merged says "publishes the
    pre-clamp verdict" and that is INSUFFICIENT for the selectivity
    clamp, the only clamp this guard currently has anything to compare. That clamp's `upgrade:` arm runs
    BEFORE its downgrade precedence and MINTS the excluded token out of {not_informative,
    discordant_across_comparators}, so the chain is THREE tokens and the excluded one is an INTERMEDIATE
    that exists only inside the clamp. A field named for what ENTERS the clamp publishes
    `not_informative`, the exclusion compares against a token that is not it, and the leak survives.
    Publish the immediate input to the PRECEDENCE WALK (post-upgrade) instead.
    THIS MATTERS TO THIS TEST SPECIFICALLY: arm 2 fires when the hole is CLOSED, by design — so it
    CANNOT distinguish a real fix from one that covers only the direct-rung arm. A partial fix would red
    this guard, get reviewed as a closure, and take the ⚠ vocabulary comment with it. The full
    three-token derivation is in `nomination_verdict_gate.yaml` under THE PRESCRIPTION IS NARROWER THAN
    IT LOOKS."""
    axes_checked: set[str] = set()
    for blk in _load()["thesis_deciding_axes"]:
        for r in blk.get("requires") or []:
            axis = r["sub_skill"]
            path = REPO / "resolvers" / f"{axis}.resolver.yaml"
            if not path.exists():
                continue  # advisory axis, resolved skills-side — no contracts clamp to reason about
            doc = yaml.safe_load(path.read_text())
            clamp = doc.get("post_resolver_clamp") or {}
            if clamp.get("direction") != "downgrade_only":
                continue
            admitted = set(r["verdict_in"])
            outputs = set(doc.get("clamp_verdicts") or [])
            outputs |= {
                c["verdict"] for c in (clamp.get("precedence") or []) if isinstance(c, dict) and c.get("verdict")
            }
            if not (admitted & outputs):
                continue  # no clamp arm admitted => nothing can be laundered through this conjunct
            axes_checked.add(axis)
            leak = set(clamp.get("applies_to_input_verdicts") or []) - admitted
            expected = _ACCEPTED_PRE_CLAMP_LEAKS.get(axis, set())
            assert leak == expected, (
                f"{blk['thesis']} requires {axis} in {sorted(admitted)}, which admits the clamp arm(s) "
                f"{sorted(admitted & outputs)} while excluding the pre-clamp verdict(s) {sorted(leak)}. "
                f"Recorded/accepted leak for {axis} is {sorted(expected)}. Every name in the difference is a "
                f"target that CANNOT satisfy this conjunction while its normal profile is clean, but CAN once "
                f"a normal-organ liability fires — a fail-open flip from block to nominate. If this change is "
                f"intended, update _ACCEPTED_PRE_CLAMP_LEAKS and say why in the vocabulary comment."
            )
            if leak:
                emitted = _resolver_verdicts(axis)
                assert leak <= emitted, (
                    f"accepted-leak entry for {axis} names {sorted(leak - emitted)}, which the resolver no "
                    f"longer emits — the pin has gone stale and would no longer detect a widening"
                )
                # Reachability, pinned: the leaked token is not a corner case reached by some other skill —
                # this clamp's OWN `upgrade` arm mints it (from not_informative / discordant_across_comparators),
                # so a target can be promoted INTO the excluded state and then re-labelled out of it by a veto
                # fire. If that arm goes away the hazard narrows, which is worth noticing rather than assuming.
                assert (clamp.get("upgrade") or {}).get("verdict") in leak, (
                    f"the reachability argument recorded in nomination_verdict_gate.yaml no longer holds for "
                    f"{axis}: its clamp upgrade arm now mints "
                    f"{(clamp.get('upgrade') or {}).get('verdict')!r}, not one of {sorted(leak)} — re-derive the "
                    f"hazard before relaxing anything that cites it"
                )

    assert axes_checked, (
        "no requires conjunct admits a post-clamp arm any longer, so this guard exercised nothing — it has "
        f"gone vacuous. Re-derive the hazard and update _ACCEPTED_PRE_CLAMP_LEAKS "
        f"({sorted(_ACCEPTED_PRE_CLAMP_LEAKS)})"
    )
    assert set(_ACCEPTED_PRE_CLAMP_LEAKS) <= axes_checked, (
        f"stale accepted-leak entries: {sorted(set(_ACCEPTED_PRE_CLAMP_LEAKS) - axes_checked)} — the hole they "
        f"record is no longer reachable, so the entry is now a false record of a live risk"
    )
