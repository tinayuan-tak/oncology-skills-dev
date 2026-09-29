"""`indication_dependency_class` — the indication-conditioned dependency verdict spine (2026-09-18).

Guards the three-layer chain card field -> interpretation rule -> resolver rung for the class that
answers the question a run actually asks ("is the target required in THE indication I queried?"),
as distinct from `enrichment_class`, which answers only "does dependency stratify by lineage at all?".

WHY EACH ASSERT EXISTS — every one of these is a hole that no existing gate covers:

  * `validate_interpretation_rules` walks RULE -> CARD (a rule may not name a value the card cannot
    produce) and NOT the reverse, so a card token that NO rule consumes is invisible to it. That is
    exactly the state `indication_not_supplied` is supposed to be in, which means the only thing
    standing between "deliberate" and "someone quietly wired it up" is an assert. The whole
    target-grain escape hatch depends on that token having no rule and no rung: wire it up and the
    indication block starts firing on runs that supplied no indication, and `lineage_selective`
    becomes unreachable.

  * The dependency verdict enum is declared at TWO sites -- the READ side
    (schemas/skills/functional-requirement.decision.schema.json) and the WRITE side
    (schemas/_skill_output/pins/functional-requirement.pins.json). Measured 2026-09-18: NOTHING in
    tests/ or validators/ referenced `dependency_verdict_enum`, so a token added to the resolver and
    to only one of the two sites would ship silently, and a golden-fixture conformance test cannot
    catch it because no fixture uses a brand-new token. `validate_verdict_tokens` does not close this
    either: it walks nomination-gate -> resolver, a different pair of files entirely.

  * The negative token's RANK is a deliberate, argued choice, not an accident of insertion order.
    v1.4.0 raised partner_conditional_dependent and chemical_genetic_confirmed_dependent above the
    pooled `non_dependent` veto because a pooled scalar is the wrong estimator for a
    context-conditional dependency; an indication-pooled median is the same kind of estimator. The
    compound rescue rungs encode that, and a future "tidy the ladder" renumber could silently undo
    it, so the ordering is asserted rather than left to the resolver's comments.

ANTI-VACUITY: every assert that iterates a derived collection first asserts the collection is
non-empty and, where the point is an ORDERING, that the two sides are DISTINCT. A renamed rule id or
a moved field would otherwise turn these into green loops over nothing.

VERIFIED BY MUTATION 2026-09-18 -- all 16 pass on the clean tree, and each of the 8 mutants below was
confirmed APPLIED (non-empty textual diff, checked inside the loop so an unapplied mutant cannot be
misread as coverage) and drove this file RED:
  1. add `indication_not_supplied` to the gap rule's `in:` list              -> 3 failed
  2. drop `dependent_in_indication` from the WRITE pin enum                  -> 3 failed
  3. drop `insufficient_underpowered_in_indication` from the READ schema     -> 3 failed
  4. swap the indication veto ABOVE its compound rescue (priority 6 <-> 9)   -> 1 failed
  5. delete a measured token from the card vocabulary                       -> 1 failed
  6. rename the gap rule's `rule_id`                                        -> 3 failed
  7. swap `lineage_selective` ABOVE `dependent_in_indication` (11 <-> 5)     -> 1 failed
  8. point a rescue's `driving_rule` at the killer instead of the positive  -> 1 failed
The precedence mutants are deliberately priority SWAPS, not reassignments, so they leave the dense-
unique-integer invariant intact and prove the ordering assert fires on its own rather than riding on
test_priorities_stay_dense_unique_integers.
  [priorities in the list above are AS OF resolver v1.5.0, when the mutants were run. v1.6.0 inserted
   a rung at 9 and shifted 9-24 to 10-25, so mutant 4 is now 6 <-> 10 and mutant 7 is 12 <-> 5. The
   mutants are recorded as they were EXECUTED rather than silently re-numbered, because a mutation
   record that is edited without being re-run is a claim about a test that never ran.]

RE-VERIFIED BY MUTATION 2026-09-18 for resolver v1.6.0 -- 18 pass on the clean tree, and 6 further
mutants (same applied-proof discipline, harness covering this file plus
test_indication_verdict_gate_parity.py; 9/9 killed across both files, 0 survivors) drove it RED:
  1. delete the indication paralog twin rung entirely       -> 5 failed  (the v1.5.0 regression itself)
  2. swap the veto ABOVE the paralog twin (9 <-> 10)         -> 3 failed  (rung present but dead code)
  3. twin emits `not_dependent_in_indication`                -> 2 failed  (escape emits what it escapes)
  4. twin emits `partner_conditional_dependent`              -> 2 failed  (gate-INERT becomes gate-POSITIVE)
  5. twin's `driving_rule` points at the killer              -> 2 failed
  6. POOLED paralog rung loses its compound form             -> 1 failed  (the subset invariant's far side)
Mutant 6 is the one worth keeping: it does not touch the indication grain at all, and it proves
test_the_indication_only_escapes_are_ones_the_pooled_ladder_gets_for_free is a real anti-vacuity
check on the subset direction rather than decoration.
"""

import json
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]

CARD = yaml.safe_load((REPO / "cards" / "dependency-lineage-selectivity.card.yaml").read_text())
RULES = yaml.safe_load((REPO / "interpretation-rules" / "intracellular-intrinsic.rules.yaml").read_text())
RESOLVER = yaml.safe_load((REPO / "resolvers" / "dependency.resolver.yaml").read_text())

FIELD = "indication_dependency_class"
CARD_ID = "dependency-lineage-selectivity"

#: The 6 MEASURED tokens, each of which must be consumed by exactly one rule.
MEASURED = {
    "selective_in_indication",
    "dependent_not_enriched",
    "not_dependent_in_indication",
    "underpowered",
    "not_in_panel",
    "data_unavailable",
}
#: The 7th token: a target-grain run asked no indication. NOT a measurement and NOT a coverage gap.
NOT_ASKED = "indication_not_supplied"

INDICATION_RULE_IDS = {
    "dependency-in-indication-selective-supportive",
    "dependency-in-indication-supportive",
    "not-dependent-in-indication-killer",
    "dependency-in-indication-underpowered-insufficient",
}


def _all_rules():
    """Every rule dict in the file, whatever the block nesting (the file groups rules by card)."""

    def walk(o):
        out = []
        if isinstance(o, dict):
            if "rule_id" in o:
                out.append(o)
            for v in o.values():
                out += walk(v)
        elif isinstance(o, list):
            for v in o:
                out += walk(v)
        return out

    rules = walk(RULES)
    assert len(rules) > 200, f"anti-vacuity: expected the full rule corpus, walked {len(rules)}"
    return rules


def _rules_on_field():
    """The rules whose `when` reads CARD_ID.FIELD, as {rule_id: set(values it fires on)}.

    Keyed on (card_id, field) deliberately: `data_unavailable` is ALSO a legal `enrichment_class`
    value with its own rule on the same card, so a value-only match would conflate the two families.
    """
    out = {}
    for r in _all_rules():
        w = r.get("when") or {}
        if w.get("card_id") != CARD_ID or w.get("field") != FIELD:
            continue
        vals = set(w["in"]) if "in" in w else {w["equals"]}
        out[r["rule_id"]] = vals
    return out


def _rungs_by_rule():
    """{rule_id: [priority, ...]} over every rung of the dependency resolver that names it."""
    out = {}
    for rung in RESOLVER["resolve"]:
        ids = []
        for key in ("when_fired", "when_any_fired", "when_all_fired"):
            v = rung.get(key)
            if isinstance(v, str):
                ids.append(v)
            elif isinstance(v, list):
                ids += v
        for rid in ids:
            out.setdefault(rid, []).append(rung["priority"])
    assert out, "anti-vacuity: no rung -> rule_id edges found"
    return out


def _priority_of(verdict):
    ps = [r["priority"] for r in RESOLVER["resolve"] if r["verdict"] == verdict]
    assert ps, f"anti-vacuity: no rung emits {verdict!r}"
    return min(ps)


# --------------------------------------------------------------------------------------------
# 1. the card's declared vocabulary
# --------------------------------------------------------------------------------------------


def test_card_declares_the_field_and_its_seven_token_vocabulary():
    out = CARD["outputs"]
    assert FIELD in out["summary_fields"], f"{FIELD} must be a declared summary field, not an ad-hoc key"
    assert set(out["summary_fields_vocabulary"][FIELD]) == MEASURED | {NOT_ASKED}


def test_card_declares_the_indication_grain():
    """The field's VALUE varies with the queried indication, so the claim is target_indication-grain.

    Admitted by the crispr_lof_dependency entity_grains ceiling; validate_cards enforces
    card.entity_grains subset-of measurement_type.entity_grains (Rule 5), so this would red there
    too -- asserted here because the grain is the whole point of the field.
    """
    assert "target_indication" in CARD["entity_grains"]
    mts = yaml.safe_load((REPO / "vocabularies" / "measurement_types.yaml").read_text())
    ceiling = mts["measurement_types"][CARD["measurement_type"]]["entity_grains"]
    assert "target_indication" in ceiling, "the type ceiling must admit the grain the card advertises"


# --------------------------------------------------------------------------------------------
# 2. the 6-measured-token -> 4-rule partition
# --------------------------------------------------------------------------------------------


def test_every_measured_token_is_consumed_by_exactly_one_rule():
    on_field = _rules_on_field()
    assert set(on_field) == INDICATION_RULE_IDS, f"unexpected rule set on {FIELD}: {sorted(on_field)}"
    owners = {t: [rid for rid, vals in on_field.items() if t in vals] for t in MEASURED}
    for token, rids in owners.items():
        assert len(rids) == 1, f"{token!r} is consumed by {len(rids)} rules ({rids}); must be exactly 1"


def test_the_three_could_not_look_tokens_share_one_rule_and_it_is_not_the_negative():
    """A coverage gap must never route to the veto (measured-vs-null discipline)."""
    on_field = _rules_on_field()
    gap = on_field["dependency-in-indication-underpowered-insufficient"]
    assert gap == {"underpowered", "not_in_panel", "data_unavailable"}
    killer = on_field["not-dependent-in-indication-killer"]
    assert killer == {"not_dependent_in_indication"}
    assert not (gap & killer), "a could-not-look token must not also reach the veto rule"


def test_the_negative_is_a_killer_and_the_gap_rule_is_not():
    """The two arms must DIFFER -- otherwise this file would pass on a corpus where the distinction
    between a measured negative and a coverage gap had been flattened away."""
    by_id = {r["rule_id"]: r for r in _all_rules()}
    neg = by_id["not-dependent-in-indication-killer"]["signals"]
    gap = by_id["dependency-in-indication-underpowered-insufficient"]["signals"]
    assert set(neg.values()) == {"killer"}, neg
    assert set(gap.values()) == {"insufficient"}, gap
    assert neg != gap, "anti-vacuity: the measured negative and the coverage gap must not agree"


# --------------------------------------------------------------------------------------------
# 3. the deliberate absence
# --------------------------------------------------------------------------------------------


def test_indication_not_supplied_has_no_rule():
    consumed = set().union(*_rules_on_field().values())
    assert NOT_ASKED not in consumed, (
        f"{NOT_ASKED!r} must be consumed by NO rule. It means 'a target-grain run asked no "
        "indication', which is neither a measurement nor a coverage gap. Giving it a rule makes the "
        "indication block fire on runs that supplied no indication and makes `lineage_selective` "
        "unreachable -- i.e. it silently inverts the grain fix this family exists to make."
    )


def test_indication_not_supplied_has_no_rung():
    """Belt and braces: even if some future rule fired on it, no rung may reference such a rule."""
    rung_rule_ids = set(_rungs_by_rule())
    for rid, vals in _rules_on_field().items():
        if NOT_ASKED in vals:
            assert rid not in rung_rule_ids, f"{rid} fires on {NOT_ASKED} and is wired to a rung"


def test_lineage_selective_stays_reachable_on_a_target_grain_run():
    """The target-grain shape verdict must survive: scope decision #3 keeps the token and makes it
    reachable exactly when no indication was supplied."""
    lineage = [r for r in RESOLVER["resolve"] if r["verdict"] == "lineage_selective"]
    assert len(lineage) == 1 and lineage[0]["when_fired"] == "lineage-selective-supportive"
    # its driving rule reads enrichment_class, NOT the indication field -> the two are independent
    by_id = {r["rule_id"]: r for r in _all_rules()}
    assert by_id["lineage-selective-supportive"]["when"]["field"] == "enrichment_class"


# --------------------------------------------------------------------------------------------
# 4. rung wiring and the two load-bearing precedence boundaries
# --------------------------------------------------------------------------------------------


def test_every_indication_rule_is_wired_to_at_least_one_rung():
    wired = _rungs_by_rule()
    for rid in sorted(INDICATION_RULE_IDS):
        assert rid in wired, f"{rid} fires but no rung consumes it -- the verdict could never move"


def test_indication_rungs_outrank_every_pooled_shape_rung():
    """BOUNDARY 1 (below): on an indication-scoped run the indication's own read is the verdict, so
    it must beat the panel-shape rungs. Asserted as a strict inequality between two NON-EMPTY,
    DISJOINT priority sets, so it cannot pass by both sides being the same rung."""
    ind = {_priority_of(v) for v in ("lineage_selective_in_indication", "dependent_in_indication")}
    shape = {_priority_of("lineage_selective"), _priority_of("selective_dependent")}
    assert ind and shape and not (ind & shape)
    assert max(ind) < min(shape), f"indication rungs {sorted(ind)} must outrank shape rungs {sorted(shape)}"


def test_indication_rungs_yield_to_pan_essential_and_concordant():
    """BOUNDARY 2 (above): a pan-essential is a SAFETY call no indication positive may rescue, and
    concordant_dependent is two-assay orthogonal corroboration. Out of scope to change."""
    ind = [
        _priority_of(v)
        for v in (
            "lineage_selective_in_indication",
            "dependent_in_indication",
            "not_dependent_in_indication",
            "insufficient_underpowered_in_indication",
        )
    ]
    for above in ("insufficient_underpowered_pan_essential", "pan_essential_killer", "concordant_dependent"):
        assert _priority_of(above) < min(ind), f"{above} must outrank the indication block"


def _compound_escapes(killer):
    """Rungs implementing the compound veto-suppressor idiom for `killer`: the veto's own rule fired
    AND something else did, so the rung re-labels the verdict. Returns (rungs, rescuing_rule_ids)."""
    rungs = [
        rung
        for rung in RESOLVER["resolve"]
        if isinstance(rung.get("when_all_fired"), list) and killer in rung["when_all_fired"]
    ]
    return rungs, {rid for r in rungs for rid in r["when_all_fired"] if rid != killer}


def test_every_escape_from_the_indication_veto_outranks_it():
    """The v1.4.0 precedence principle, machine-enforced at indication grain: a reason the
    indication-pooled negative is not a verdict about the target must outrank that negative, via the
    framework's compound veto-suppressor idiom. Without this, a bare negative above these rungs
    re-creates the exact defect v1.4.0 fixed (PRMT5 in MTAP-deleted MESO).

    TWO MECHANISMS, asserted as a non-empty partition so neither class can silently empty out:
      * CONTRADICTION — a measured stratified / chemical-genetic positive says the target IS required
        in a subset the indication median averaged away, so the rung emits a POSITIVE verdict.
      * DISQUALIFICATION (v1.6.0) — a redundant paralog means the knockout the negative rests on is
        the wrong INSTRUMENT. Nothing measured the target as required, so the rung emits neither a
        positive nor a kill; `non_dependent_paralog_buffered` is declared gate-inert.
    The earlier name for this test said "measured positives", which was true of the three rungs that
    existed then and is NOT true of the paralog rung — the escape hatch is wider than a positive."""
    neg = _priority_of("not_dependent_in_indication")
    rescues, _ = _compound_escapes("not-dependent-in-indication-killer")
    assert len(rescues) == 4, f"expected 4 compound rescue rungs, found {len(rescues)}"

    contradiction = {"partner_conditional_dependent", "chemical_genetic_confirmed_dependent"}
    disqualification = {"non_dependent_paralog_buffered"}
    by_verdict = {r["verdict"] for r in rescues}
    assert by_verdict & contradiction, "anti-vacuity: no CONTRADICTION-mechanism escape survives"
    assert by_verdict & disqualification, "anti-vacuity: no DISQUALIFICATION-mechanism escape survives"
    assert not (by_verdict - contradiction - disqualification), (
        f"escape rungs with an unclassified mechanism: {sorted(by_verdict - contradiction - disqualification)}. "
        f"Every escape must be either a measurement that CONTRADICTS the negative or an argument that "
        f"DISQUALIFIES it — a third kind needs its own gate-role argument, because the two differ in "
        f"whether the resulting verdict is gate-positive or gate-inert."
    )

    for rung in rescues:
        assert rung["priority"] < neg, f"rescue {rung['verdict']}@{rung['priority']} must outrank the veto @{neg}"
        assert rung["verdict"] != "not_dependent_in_indication"
        # each rescue must name the RESCUING rule as its provenance anchor, matching rungs 16-17
        assert rung["driving_rule"] != "not-dependent-in-indication-killer"
        assert rung["driving_rule"] in rung["when_all_fired"]

    # The DISQUALIFICATION escape must be the LAST of the four: a measurement that contradicts the
    # negative beats an argument that the negative was never admissible. Mirrors the pooled ladder,
    # where partner-conditional (16-19) outranks non_dependent_paralog_buffered (20).
    disq = [r["priority"] for r in rescues if r["verdict"] in disqualification]
    contra = [r["priority"] for r in rescues if r["verdict"] in contradiction]
    assert max(contra) < min(disq), (
        f"contradiction escapes {sorted(contra)} must outrank disqualification escapes {sorted(disq)}"
    )


def test_every_pooled_veto_escape_has_an_indication_twin():
    """THE INVARIANT #812 LACKED, and the reason its regression was shippable.

    v1.5.0 mirrored `non_dependent`'s ladder into indication grain by mirroring the VETO and three of
    its escapes, missing the fourth (`strong-paralog-buffering-degrader-preferred`). Nothing was blind
    to the new token — #814 gave it full gate parity — but nothing compared the two ESCAPE SETS, so
    the indication killer outranked a rescue the pooled killer loses to, and 3 of the 8 live
    `must_not_veto` calibration controls (WWTR1/MESO, MARK2/PAAD, MARK3/PAAD) were headed for a false
    veto the moment the token became reachable.

    Generalized so the next grain-conditioned veto cannot repeat it: MIRRORING A VETO MEANS MIRRORING
    EVERY RUNG THAT ESCAPES IT. A rule that disqualifies or contradicts the POOLED negative also does
    so for the indication negative — an indication still pools genotypes and subtypes, so every
    argument available to the wider cohort is available to the narrower one."""
    pooled_rungs, pooled = _compound_escapes("non-dependent-killer")
    ind_rungs, ind = _compound_escapes("not-dependent-in-indication-killer")
    assert pooled and ind, "anti-vacuity: both killers must have compound escapes"
    assert pooled_rungs and ind_rungs

    missing = pooled - ind
    assert not missing, (
        f"these rules rescue the POOLED veto but not the indication veto: {sorted(missing)}. The "
        f"indication killer therefore outranks a rescue its pooled twin loses to, so an indication-"
        f"scoped run vetoes a target a pan-cancer run does not. Add a compound rung pairing "
        f"`not-dependent-in-indication-killer` with each, ABOVE the indication veto."
    )


def test_the_indication_only_escapes_are_ones_the_pooled_ladder_gets_for_free():
    """Anti-vacuity for the subset direction above: a SUPERSET would also satisfy it, so prove each
    extra indication escape is a grain artefact rather than an unexplained asymmetry.

    `e7-triangulated-target-engaged-supportive` rescues the indication veto (rung 8) but has no
    pooled compound rung — because it does not need one: its BARE rung already outranks the pooled
    veto. At indication grain that same bare rung sits BELOW the indication veto (the indication block
    is hoisted above the whole pooled block), so the escape has to be made explicit. If a future
    renumber moves a bare rung above the indication veto, this test says so instead of leaving a
    redundant compound rung to rot."""
    _, pooled = _compound_escapes("non-dependent-killer")
    _, ind = _compound_escapes("not-dependent-in-indication-killer")
    extra = ind - pooled
    assert extra, "anti-vacuity: expected at least one indication-only escape (e7 triangulation)"

    pooled_veto = _priority_of("non_dependent")
    ind_veto = _priority_of("not_dependent_in_indication")
    assert pooled_veto > ind_veto, "the indication block must sit above the pooled block"

    for rid in sorted(extra):
        bare = [r["priority"] for r in RESOLVER["resolve"] if r.get("when_fired") == rid]
        assert bare, f"{rid} rescues only the indication veto and has NO bare rung — unexplained asymmetry"
        assert min(bare) < pooled_veto, (
            f"{rid}'s bare rung @{min(bare)} does not outrank the pooled veto @{pooled_veto}, so the "
            f"pooled ladder does NOT get this escape for free and owes a compound rung too"
        )
        assert min(bare) > ind_veto, (
            f"{rid}'s bare rung @{min(bare)} already outranks the indication veto @{ind_veto}, so its "
            f"compound rung is redundant — delete the compound rung rather than keeping both"
        )


def test_priorities_stay_dense_unique_integers():
    """The renumber mechanism's own invariant: resolver.schema.json requires integer >= 0 and
    validate_fold_migration requires uniqueness, so an insertion must renumber rather than fractionate."""
    ps = [r["priority"] for r in RESOLVER["resolve"]]
    assert all(isinstance(p, int) and p >= 0 for p in ps)
    assert sorted(ps) == list(range(len(ps))), f"priorities must be dense 0..{len(ps) - 1}: {sorted(ps)}"


# --------------------------------------------------------------------------------------------
# 5. the two-site verdict enum (previously unguarded in BOTH directions)
# --------------------------------------------------------------------------------------------


def _enum(rel):
    return json.loads((REPO / rel).read_text())["$defs"]["dependency_verdict_enum"]["enum"]


def test_read_and_write_enum_sites_agree():
    read = _enum("schemas/skills/functional-requirement.decision.schema.json")
    write = _enum("schemas/_skill_output/pins/functional-requirement.pins.json")
    assert read and write
    assert set(read) == set(write), (
        f"enum sites diverge: only-read={set(read) - set(write)}, only-write={set(write) - set(read)}"
    )


def test_enum_sites_match_what_the_resolver_can_actually_emit():
    """BIDIRECTIONAL on purpose. Missing-from-enum = a verdict that fails schema validation at
    runtime; extra-in-enum = a token declared but unreachable, i.e. a claim the framework cannot
    make. Both are defects and neither had a gate before this test."""
    emittable = {r["verdict"] for r in RESOLVER["resolve"]} | {RESOLVER["default"]}
    assert emittable
    for rel in (
        "schemas/skills/functional-requirement.decision.schema.json",
        "schemas/_skill_output/pins/functional-requirement.pins.json",
    ):
        declared = set(_enum(rel))
        assert not (emittable - declared), f"{rel} is missing emittable verdict(s): {sorted(emittable - declared)}"
        assert not (declared - emittable), f"{rel} declares unreachable verdict(s): {sorted(declared - emittable)}"


def test_the_four_new_tokens_are_present_at_both_sites():
    """Named explicitly so a rename cannot make the generic parity test above pass vacuously."""
    new = {
        "lineage_selective_in_indication",
        "dependent_in_indication",
        "not_dependent_in_indication",
        "insufficient_underpowered_in_indication",
    }
    for rel in (
        "schemas/skills/functional-requirement.decision.schema.json",
        "schemas/_skill_output/pins/functional-requirement.pins.json",
    ):
        assert new <= set(_enum(rel)), f"{rel} missing {sorted(new - set(_enum(rel)))}"
