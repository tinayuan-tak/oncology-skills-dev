"""Per-SCOPE decomposition (genomic_alteration_by_scope + scope_of_driving_verdict).

The genomic_alteration verdict is a SCOPE HYBRID: the ladder-leading KO-dependency / variant-shape /
drug-response signals are pan-cancer DepMap/PRISM cell-line calls (localised to the queried lineage only
when powered, via each stratified card's evidence_scope), while patient recurrence, patient-focal CN,
TCGA fusion recurrence, and the IntOGen role are indication-native. This reducer classifies the SCOPE of
the driving verdict and rolls up which evidence exists at each scope. ADDITIVE / verdict-inert — it reads
fields already emitted by the cards and touches no resolver rung."""

from __future__ import annotations

from pathlib import Path

from _test_support import load_run_py

gap = load_run_py(Path(__file__).resolve().parent.parent, "gap_run_byscope")


def _card(cid, **fields):
    return {"card_id": cid, "summary": dict(fields)}


def _by_id(cards):
    return {c["card_id"]: c for c in cards}


# ── scope_of_driving_verdict ───────────────────────────────────────────────────────────────────────


def test_within_indication_dependency_is_indication_anchored():
    """KRAS/COADREAD-like: the strong mutation dependency leads the ladder and its evidence_scope is
    within_indication → the verdict is indication_anchored."""
    cards = _by_id(
        [
            _card(
                "mutation-stratified-dependency",
                mutation_stratification_class="mutant_strongly_dependent",
                evidence_scope="within_indication",
            ),
            _card("alteration-role", alteration_role="direct_driver_gof", intogen_scope="indication"),
        ]
    )
    assert gap._scope_of_driving_verdict(cards, "mutant-strongly-dependent-supportive") == "indication_anchored"


def test_pan_lineage_dependency_without_indication_support_is_extrapolation():
    """A dependency computed from pan-lineage evidence only, with no indication-native corroboration,
    is honestly a pan_cancer_extrapolation — the scope leak the verdict otherwise hides."""
    cards = _by_id(
        [
            _card(
                "copy-number-stratified-dependency",
                cn_stratification_class="amplified_strongly_dependent",
                evidence_scope="pan_lineage_evidence_only",
            ),
            _card("alteration-role", alteration_role="passenger", intogen_scope="pan_cancer"),
            _card("mutation-hotspot-frequency", driver_recurrence_class="bottom_decile"),
            _card("copy-number-distribution", patient_focal_cn_class="focal_neutral"),
            _card("fusion-rearrangement-landscape", fusion_class="no_recurrent_fusion"),
        ]
    )
    assert (
        gap._scope_of_driving_verdict(cards, "cn-amplified-strongly-dependent-supportive") == "pan_cancer_extrapolation"
    )


def test_pan_lineage_dependency_with_indication_role_is_mixed():
    """Same pan-lineage dependency, but an IntOGen indication-scoped driver role corroborates it in the
    queried indication → mixed (not a bare extrapolation)."""
    cards = _by_id(
        [
            _card(
                "copy-number-stratified-dependency",
                cn_stratification_class="amplified_strongly_dependent",
                evidence_scope="pan_lineage_evidence_only",
            ),
            _card("alteration-role", alteration_role="direct_driver_gof", intogen_scope="indication"),
        ]
    )
    assert gap._scope_of_driving_verdict(cards, "cn-amplified-strongly-dependent-supportive") == "mixed"


def test_patient_focal_cn_rung_is_indication_anchored():
    """A patient-focal CN landscape driver is inherently indication-native (TCGA GISTIC in-tissue)."""
    assert gap._scope_of_driving_verdict({}, "cn-patient-focal-amplified-supportive") == "indication_anchored"


def test_pan_cancer_variant_shape_rung_without_support_is_extrapolation():
    """A bare missense-dominant SHAPE call (cell-line MAF, pan-cancer) with no indication anchor."""
    cards = _by_id([_card("alteration-role", intogen_scope="pan_cancer")])
    assert gap._scope_of_driving_verdict(cards, "mut-missense-dominant-supportive") == "pan_cancer_extrapolation"


def test_no_driving_rule_is_not_applicable():
    assert gap._scope_of_driving_verdict({}, None) == "not_applicable"


# ── completeness of the map against the resolver (the reachability guard) ─────────────────────────
# The four tests below exist because `unclassified` was reachable for FOUR of the resolver's 22 distinct
# driving rules while the docstring called that value "defensive". Every scope test above asserts one
# hand-picked rule resolves correctly — which is exactly the shape that stays green while a rule the map
# has never heard of leads a real verdict. `test_every_resolver_driving_rule_is_scoped` inverts that: it
# reads the driving rules from the RESOLVER, so it fails for the next rule anyone adds there.


def _resolver_driving_rules() -> set:
    """Every distinct `driving_rule` the genomic resolver can name, read from the resolver itself."""
    import yaml
    from _skills_common.paths import target_contracts_root

    p = target_contracts_root() / "resolvers" / "genomic_alteration.resolver.yaml"
    doc = yaml.safe_load(p.read_text()) or {}
    out = set()
    for e in doc.get("resolve") or []:
        d = e.get("driving_rule") or e.get("when_fired")
        if isinstance(d, str):
            out.add(d)
    return out


def test_every_resolver_driving_rule_is_scoped():
    """No driving rule the resolver can name may fall through to `unclassified`.

    Each dependency card is given a READABLE `evidence_scope`, because a dependency rung whose card is
    absent also returns `unclassified` — the two must not be conflated here or the guard would report map
    drift for a rule the map handles fine. This asserts the map KNOWS every rule; the absent-card path is
    a payload condition pinned separately below."""
    cards = _by_id([_card(cid, evidence_scope="within_indication") for cid in gap._DEP_RULE_SCOPE_CARD.values()])
    rules = _resolver_driving_rules()
    assert len(rules) >= 20, f"resolver read looks wrong — only {len(rules)} driving rules found"
    unscoped = sorted(r for r in rules if gap._scope_of_driving_verdict(cards, r) == "unclassified")
    assert not unscoped, (
        f"{len(unscoped)} resolver driving rule(s) are not in the scope map, so a real verdict would "
        f"publish scope_of_driving_verdict='unclassified': {unscoped}. Add each to _INDICATION_ANCHORED_RULES "
        f"/ _PAN_CANCER_RULES / _NO_EVIDENCE_RULES / _DEP_RULE_SCOPE_CARD per its SOURCE CARD's scope."
    )


def test_the_four_previously_unscoped_rules_resolve_by_their_source_card():
    """Pins each of the four the guard above caught, with the card that decides its scope.

    `mutation-type-counts` asks "Across DepMap cell lines ..." → pan-cancer for ALL FOUR of its tiers, so
    the neutral tiers scope like the supportive ones already did. `target-clonality` is `tier: indication`
    → indication-anchored even though its rung is OPPOSING. `cn-data-unavailable-insufficient` fires on
    `copy_number_class == data_unavailable`, i.e. on the ABSENCE of the measurement, so no scope exists."""
    no_support = _by_id([_card("alteration-role", intogen_scope="pan_cancer")])
    assert gap._scope_of_driving_verdict(no_support, "mut-mixed-neutral") == "pan_cancer_extrapolation"
    assert gap._scope_of_driving_verdict(no_support, "mut-no-mutations-neutral") == "pan_cancer_extrapolation"
    assert gap._scope_of_driving_verdict({}, "snv-clonality-subclonal-opposing") == "indication_anchored"
    assert gap._scope_of_driving_verdict({}, "cn-data-unavailable-insufficient") == "not_applicable"


def test_a_neutral_shape_call_with_indication_support_reads_mixed():
    """`mixed` must stay meaningful for a NEUTRAL rung: a pan-cancer shape call that says "no dominant
    pattern" while patient recurrence in the indication says top-1% driver is a genuine scope tension, and
    reporting it as bare `pan_cancer_extrapolation` would hide the indication-native evidence."""
    cards = _by_id([_card("mutation-hotspot-frequency", driver_recurrence_class="top_1pct")])
    assert gap._scope_of_driving_verdict(cards, "mut-mixed-neutral") == "mixed"


def test_data_unavailable_is_distinguishable_from_map_drift():
    """`not_applicable` (honest absence) and `unclassified` (map drift) must not collapse into each other —
    conflating them would make the drift guard above unable to see drift."""
    assert gap._scope_of_driving_verdict({}, "cn-data-unavailable-insufficient") == "not_applicable"
    assert gap._scope_of_driving_verdict({}, "some-rule-nobody-mapped-yet") == "unclassified"


def test_a_mapped_dependency_rung_with_no_readable_card_scope_is_unclassified():
    """The OTHER route to `unclassified`, pinned so the drift guard's card fixture is not load-bearing by
    accident: the rule IS mapped, but its stratified card is absent (or carries an `evidence_scope` this
    map does not recognise), so the rung cannot be localised. Documented in the docstring as the second
    meaning of the value; the resolver guard deliberately supplies a readable scope to avoid it."""
    assert gap._scope_of_driving_verdict({}, "mutant-strongly-dependent-supportive") == "unclassified"
    odd = _by_id([_card("mutation-stratified-dependency", evidence_scope="something_new")])
    assert gap._scope_of_driving_verdict(odd, "mutant-strongly-dependent-supportive") == "unclassified"


# ── genomic_alteration_by_scope structure ────────────────────────────────────────────────────────


def test_by_scope_has_three_scopes_and_flags_presence():
    cards = [
        _card(
            "mutation-stratified-dependency",
            mutation_stratification_class="mutant_strongly_dependent",
            evidence_scope="within_indication",
        ),
        _card(
            "mutation-hotspot-frequency", driver_recurrence_class="top_1pct", genie_driver_recurrence_class="top_1pct"
        ),
        _card("alteration-role", alteration_role="direct_driver_gof", intogen_scope="indication"),
    ]
    bs = gap._genomic_alteration_by_scope(cards, "mutant-strongly-dependent-supportive")
    assert set(bs) == {"scope_of_driving_verdict", "pan_cancer", "indication", "subtype"}
    assert bs["scope_of_driving_verdict"] == "indication_anchored"
    assert bs["pan_cancer"]["evidence_present"] is True  # mutation dependency present
    assert bs["indication"]["evidence_present"] is True  # top_1pct recurrence + role present
    assert bs["pan_cancer"]["mutation_dependency_scope"] == "within_indication"
    assert bs["indication"]["driver_recurrence_class"] == "top_1pct"
    # subtype is a placeholder until --subtypes is passed (patched by main()), so it must not fabricate.
    assert bs["subtype"]["evidence_present"] is False


def test_by_scope_indication_absent_when_no_patient_evidence():
    """Only pan-cancer cell-line evidence present → indication.evidence_present is False (an honest gap,
    not a fabricated indication anchor)."""
    cards = [
        _card(
            "mutation-stratified-dependency",
            mutation_stratification_class="mutant_strongly_dependent",
            evidence_scope="pan_lineage_evidence_only",
        ),
    ]
    bs = gap._genomic_alteration_by_scope(cards, "mutant-strongly-dependent-supportive")
    assert bs["pan_cancer"]["evidence_present"] is True
    assert bs["indication"]["evidence_present"] is False
    assert bs["scope_of_driving_verdict"] == "pan_cancer_extrapolation"
