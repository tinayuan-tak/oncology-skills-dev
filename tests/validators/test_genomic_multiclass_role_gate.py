"""Regression guard: multi_class_driver rungs must be alteration-role-gated (genomic redesign Stage 1).

The framework-wide rule audit found the genomic verdict called a PASSENGER a multi_class_driver
(CEACAM5/COADREAD: missense-dominant SHAPE + a CN-shape signal, but alteration_role=data_unavailable).
Cause: the multi_class rungs fired on [mut-driver-shape AND cn-driver-shape] with NO role co-signal,
unlike the confirmed_driver rungs. Fix: every REACHABLE mut-class multi_class rung now also requires an
alteration-role DRIVER rule (gof-supportive or lof-neutral). This pins that gate so the passenger FP
can't return. (Recurrence is deliberately NOT gated — mutation-hotspot-frequency has a data_unavailable
bin that would demote genuine drivers, §2e.)
"""

from __future__ import annotations

from pathlib import Path

import yaml

RESOLVER = Path(__file__).resolve().parents[2] / "resolvers" / "genomic_alteration.resolver.yaml"
RULES_DIR = Path(__file__).resolve().parents[2] / "interpretation-rules"
# variant-class SHAPE rules — reachable multi_class drivers key on these (the mutant-dependent
# multi_class rungs are shadowed-dead under the N1 precedence hoist, so they're exempt).
_SHAPE_DRIVER_RULES = {"mut-lof-dominant-supportive", "mut-missense-dominant-supportive"}
_ROLE_RULES = {"alteration-role-gof-driver-supportive", "alteration-role-lof-driver-neutral"}
_GOF_ROLE = "alteration-role-gof-driver-supportive"
# ★ Every deletion predicate the resolver can key on. This set was a HARDCODED LITERAL PAIR
# ({cn-recurrently-deleted-supportive, cn-patient-focal-deleted-supportive}) and went stale the moment
# resolver 1.9.0 SPLIT the deletion arm: it dropped the shallow cn-recurrently-deleted-supportive (60.1%
# genome-wide null) and introduced the biallelic cn-recurrent-homozygous-deletion-supportive, which the
# literal set did not name. The CASE-028 guard below therefore did not look at the new predicate at all —
# a GoF+homozygous-deletion driver rung would have been INVISIBLE to it and the file would have stayed
# green while the false positive it exists to prevent came back through the new arm. Same class as a split
# vocabulary token killing readers that pin the old literal: the guard's SCOPE must be derived from the
# thing under test, not restated next to it. `test_every_deletion_predicate_is_classified` below is what
# makes the derivation enforceable — it fails when a new deletion rule appears and is not listed here.
_DELETION_RULES = {
    "cn-recurrently-deleted-supportive",  # retired from the ladder in 1.9.0; kept so a re-add is still caught
    "cn-patient-focal-deleted-supportive",
    "cn-recurrent-homozygous-deletion-supportive",
}
_DELETION_TOKENS = ("deleted", "deletion")


# ★ The three positive rung forms, and the reason there are TWO derivations below rather than one.
# A rung expresses its condition in exactly one of these (census over all 9 resolvers, 159 rungs:
# when_all_fired ×79, when_fired ×76, when_any_fired ×4 — 3 in dependency, 1 in safety; 0 rungs mix forms;
# `when_none_fired` occurs 0 times anywhere). genomic_alteration.resolver.yaml uses only the first two
# today, so the `when_any_fired` handling here is latent hardening.
#
# The two derivations are NOT interchangeable, because the forms differ in QUANTIFIER:
#   * when_fired / when_all_fired members are REQUIRED — the rung matches only if all of them fired.
#   * when_any_fired members are SUFFICIENT — each one alone can reach the rung.
# Collapsing both into one set flattens that distinction, and the checks in this file ask both kinds of
# question, sometimes in adjacent clauses: "can a deletion REACH this rung" (sufficiency) versus "does this
# rung REQUIRE a role co-signal" (obligation). Answering an obligation question with a reachability set
# would treat a rule that is merely one alternative as a guarantee — which in a safety guard is a
# false negative, the direction that matters.
_WHEN_FORMS = ({"when_fired"}, {"when_all_fired"}, {"when_any_fired"})


def _required_fired(rung) -> set:
    """Rules the rung REQUIRES to have fired — its obligations. Empty for a `when_any_fired` rung, which
    requires nothing in particular. Use for "does this rung demand X" assertions."""
    required = set(rung.get("when_all_fired") or [])
    if rung.get("when_fired"):
        required.add(rung["when_fired"])
    return required


def _reachable_fired(rung) -> set:
    """Every rule that can participate in reaching this rung — obligations PLUS sufficient alternatives.
    Use for "can X reach this rung" filters. A one-element `when_all_fired` is semantically identical to a
    `when_fired`, and both are identical to a one-element `when_any_fired`; reading the KEY instead of the
    meaning lets a rung evade a check by being respelled, which is what these two helpers exist to stop.

    Both helpers also normalise the empty forms: an explicit `when_all_fired:` with no value parses to None,
    so a bare `set(rung["when_all_fired"])` is a TypeError — a crashed test where the intent was "matches
    nothing". `when_none_fired` is excluded from both: it is a NEGATIVE condition, so a rule named there is
    one the rung requires NOT to have fired, and folding it in would invert every check that reads these.
    """
    return _required_fired(rung) | set(rung.get("when_any_fired") or [])


def test_every_rung_uses_a_known_when_form():
    """★ SCOPE guard for `_required_fired` / `_reachable_fired`, and the thing that stops this bug class
    recurring at the rung level: a rung written in a form neither helper knows contributes NOTHING to either
    set, so every check in this file skips it silently. A fourth `when_*` form, or a rung mixing two forms
    (which would make its quantifier ambiguous — no rung does today), reddens here instead."""
    rungs = yaml.safe_load(RESOLVER.read_text())["resolve"]
    unknown = [
        (i, sorted(k for k in r if k.startswith("when")))
        for i, r in enumerate(rungs)
        if {k for k in r if k.startswith("when")} not in _WHEN_FORMS
    ]
    assert not unknown, (
        f"rung(s) use a when-form that _required_fired/_reachable_fired do not model, so every check in "
        f"this file silently ignores them: {unknown}. Known forms: when_fired | when_all_fired | "
        f"when_any_fired (exactly one per rung). If this is a new form, decide whether its members are "
        f"REQUIRED or SUFFICIENT and add it to the matching helper — not to both."
    )


def _referenced_rule_ids(rungs) -> set:
    out = set()
    for r in rungs:
        out |= _reachable_fired(r)
    return out


def _declared_rule_ids() -> set:
    """Every rule_id the contracts repo declares, across all interpretation-rules files."""
    out = set()
    for path in sorted(RULES_DIR.glob("*.rules.yaml")):
        for rule in (yaml.safe_load(path.read_text()) or {}).get("rules") or []:
            if isinstance(rule, dict) and rule.get("rule_id"):
                out.add(rule["rule_id"])
    return out


def test_every_deletion_predicate_is_classified():
    """★ SCOPE guard for the CASE-028 check below, which iterates `_DELETION_RULES`: any rule the guard does
    not name is a rule the guard cannot see. Rather than trusting the literal list to be maintained, derive
    the population from the resolver itself and assert the list covers it — so adding a deletion predicate
    to a rung reddens THIS test (a one-line fix) instead of silently narrowing the guard.

    Deliberately name-based (`deleted` / `deletion` in the rule id) because that is the only signal available
    in the resolver, and the repo's rule-id convention makes it reliable. A deletion rule named without
    either token would evade this — which is a naming-convention bug, not a reason to weaken the check.
    """
    rungs = yaml.safe_load(RESOLVER.read_text())["resolve"]
    referenced = _referenced_rule_ids(rungs)
    looks_like_deletion = {r for r in referenced if any(t in r for t in _DELETION_TOKENS)}
    assert looks_like_deletion, (
        "no deletion-looking rule id is referenced by ANY resolver rung — either the deletion arm was "
        "removed wholesale (then the CASE-028 guard is decoration and this file needs re-reading) or the "
        "rule-id naming convention changed and this check has gone blind"
    )
    unclassified = looks_like_deletion - _DELETION_RULES
    assert not unclassified, (
        f"resolver rung(s) key on deletion predicate(s) that _DELETION_RULES does not name: "
        f"{sorted(unclassified)}. Until they are added, test_a_deletion_never_confers_a_driver_verdict_on_"
        f"a_gof_role does NOT check them — a GoF+deletion driver rung through this predicate would pass. "
        f"Add them to _DELETION_RULES."
    )


def test_every_deletion_rule_is_a_declared_rule():
    """The OTHER direction of the scope guard above, which only sees rules the resolver REFERENCES and so
    catches under-scoping alone. It cannot catch DECAY: a typo'd member, or a member whose rule_id was
    renamed out of existence, silently shrinks `_DELETION_RULES` — and every test in this file stays green,
    because a name that matches nothing simply never intersects anything. Asserting each member is a
    DECLARED rule id catches both, and still admits `cn-recurrently-deleted-supportive`, which is declared
    but referenced by no rung since 1.9.0 retired it."""
    undeclared = _DELETION_RULES - _declared_rule_ids()
    assert not undeclared, (
        f"_DELETION_RULES names rule id(s) that no interpretation-rules file declares: {sorted(undeclared)}. "
        f"A member matching nothing is a silently NARROWED safety guard, not a harmless leftover — either "
        f"fix the typo or, if the rule was genuinely deleted (not just retired from the ladder), drop it."
    )


# ---------------------------------------------------------------------------------------------------
# ★ Which verdicts ASSERT the gene is a driver. Same hardcoded-population bug as `_DELETION_RULES` had,
# one level up: this was the literal 4-set {multi_class_driver, multi_class_lof_driver, confirmed_driver,
# confirmed_lof_driver} while the resolver actually mints NINE driver-bearing verdicts. The five it omitted
# — recurrent_{deletion,snv,amplification,fusion}_driver and splice_exon_skip_driver — are exactly the
# verdicts the bare single-predicate rungs at the BOTTOM of the ladder emit, so a rung
# `GoF + <deletion predicate> -> recurrent_deletion_driver` was invisible to the CASE-028 guard.
# Classified explicitly rather than by a `"driver" in verdict` substring test, because a substring is the
# same guess-from-the-name shortcut that made this narrow in the first place: a verdict renamed to drop
# the token would silently leave the driver set. `test_every_verdict_is_classified` keeps this honest by
# requiring the table to cover the resolver's minted set EXACTLY, in both directions.
# ---------------------------------------------------------------------------------------------------
_VERDICT_ASSERTS_DRIVER = {
    # driver-bearing: the verdict's whole content is "this gene drives, via these alteration classes"
    "confirmed_driver": True,
    "confirmed_lof_driver": True,
    "multi_class_driver": True,
    "multi_class_lof_driver": True,
    "recurrent_amplification_driver": True,
    "recurrent_deletion_driver": True,
    "recurrent_fusion_driver": True,
    "recurrent_snv_driver": True,
    "splice_exon_skip_driver": True,
    # not driver claims: dependency/response findings, mutation-SHAPE descriptions, and abstentions
    "biomarker_stratified_dependency": False,
    "moderate_biomarker_dependency": False,
    "drug_response_biomarker": False,
    "lof_dominant_pattern": False,
    "missense_dominant_pattern": False,
    "mixed_pattern": False,
    "passenger_pattern": False,
    "recurrent_snv_subclonal_uncertain": False,
    "insufficient": False,
}
_DRIVER_VERDICTS = {v for v, is_driver in _VERDICT_ASSERTS_DRIVER.items() if is_driver}


def _minted_verdicts() -> set:
    """Every verdict this resolver can produce: each rung's plus the explicit fall-through default."""
    doc = yaml.safe_load(RESOLVER.read_text())
    out = {r["verdict"] for r in doc["resolve"] if r.get("verdict")}
    if doc.get("default"):
        out.add(doc["default"])
    return out


def test_every_verdict_is_classified():
    """★ SCOPE guard, both directions, for every check below that filters on `_DRIVER_VERDICTS`.

    Unclassified: a NEW verdict the table does not name is a verdict the driver checks cannot see — the
    exact failure that let the five `recurrent_*_driver` verdicts sit outside the CASE-028 guard.
    Stale: a member the resolver no longer mints means a rename happened, and the OLD name matching
    nothing makes the driver set silently smaller while every test stays green.
    """
    minted = _minted_verdicts()
    classified = set(_VERDICT_ASSERTS_DRIVER)
    unclassified = minted - classified
    assert not unclassified, (
        f"resolver mints verdict(s) that _VERDICT_ASSERTS_DRIVER does not classify: {sorted(unclassified)}. "
        f"Decide for each whether it ASSERTS the gene is a driver; until then the deletion/role safety "
        f"checks in this file do not look at it."
    )
    stale = classified - minted
    assert not stale, (
        f"_VERDICT_ASSERTS_DRIVER classifies verdict(s) the resolver no longer mints: {sorted(stale)}. "
        f"If these were RENAMED, the driver set has silently shrunk — map them to the new names."
    )


def test_shape_driven_multiclass_rungs_require_alteration_role():
    resolver = yaml.safe_load(RESOLVER.read_text())
    mc = [r for r in resolver["resolve"] if r.get("verdict") == "multi_class_driver"]
    # Filter on REACHABLE (can a shape rule reach this multi_class rung), assert on REQUIRED (does the rung
    # demand a role co-signal) — the two clauses ask different questions and need different derivations.
    # Read via the helpers for the same reason as the deletion checks: this read the `when_all_fired` key
    # directly, so a rung spelled `when_fired: mut-lof-dominant-supportive -> multi_class_driver` — ONE shape
    # rule, no role gate, i.e. precisely the CEACAM5/COADREAD passenger this test exists to prevent — was
    # invisible to it. The unguarded `set(r["when_all_fired"])` below was also a KeyError/TypeError waiting
    # on such a rung rather than a failed assertion.
    shape_rungs = [r for r in mc if _SHAPE_DRIVER_RULES & _reachable_fired(r)]
    assert shape_rungs, "expected reachable shape-driven multi_class rungs"
    for r in shape_rungs:
        fired = _required_fired(r)
        assert fired & _ROLE_RULES, (
            f"multi_class rung {sorted(fired)} keys on a variant-SHAPE driver rule but has NO "
            f"alteration-role driver co-signal — a passenger (missense-dominant shape, no driver role) "
            f"could be called multi_class_driver. Add gof-driver-supportive / lof-driver-neutral."
        )


def test_a_deletion_never_confers_a_driver_verdict_on_a_gof_role():
    """CASE-028 (genomic-20 panel): a copy-number DELETION is a driver CLASS only for a LoF/neutral role
    (a TSG's mechanism). For a GoF/activating oncogene the driver mechanism is amplification / mutation /
    fusion, so a co-occurring deletion is a PASSENGER — it must never, on its own or as a second class,
    produce a driver verdict paired with the GoF role.

    Two failure modes this pins, both live-observed:
      * single-class: IDH2/AML fired [cn-recurrently-deleted + GoF role] with its SNV axis data_unavailable
        and read confirmed_driver off the deletion. The deletion+GoF rungs now read mixed_pattern.
      * multi-class: FGFR3/BLCA fired [missense + cn-recurrently-deleted + GoF role] and read
        multi_class_driver, over-crediting the deletion as a second class. The GoF+deletion multi_class
        rungs are removed; such a gene falls through to the single-class confirmed_driver (missense only).

    A regression here re-opens the "a passenger deletion drives / co-drives a GoF oncogene" false-positive.
    """
    rungs = yaml.safe_load(RESOLVER.read_text())["resolve"]
    # ★ REACHABILITY on BOTH clauses, unlike the obligation-style checks elsewhere in this file. The question
    # is not "does this rung require a deletion and require a GoF role" but "can a gene that HAS both land on
    # this rung and be handed a driver verdict" — and a gene either has the deletion and the GoF role or it
    # does not. So for `when_any_fired: [<deletion predicate>, <GoF role>] -> <driver verdict>`, a GoF gene
    # with a passenger deletion reaches the rung and is credited, which is exactly the CASE-028 defect; using
    # the obligation set for the role clause would call it clean because the role is only an alternative.
    # There is no false positive in the other direction: an ANY rung naming both a deletion predicate and the
    # GoF role IS reachable by a gene carrying both, and if its verdict is non-driver (e.g. the mixed_pattern
    # shields) it never enters _DRIVER_VERDICTS and is not considered here at all.
    offenders = [
        r
        for r in rungs
        if r.get("verdict") in _DRIVER_VERDICTS
        and _DELETION_RULES & _reachable_fired(r)
        and _GOF_ROLE in _reachable_fired(r)
    ]
    assert not offenders, (
        "genomic resolver rung(s) let a copy-number DELETION confer a DRIVER verdict on a GoF/activating "
        f"role — a deletion is not a GoF driver mechanism, so this is a passenger being credited: {offenders}"
    )


def test_deletion_still_confers_a_driver_on_a_lof_role():
    """The other side of the gate: a deletion IS the mechanism for a TSG, so LoF+deletion rungs must remain
    (else this fix would blind the framework to real deletion drivers like PTEN/SMARCA4). Anti-vacuity for
    the guard above — proves it removed only the GoF pairing, not the deletion-driver concept."""
    rungs = yaml.safe_load(RESOLVER.read_text())["resolve"]
    lof_deletion_driver = [
        r
        for r in rungs
        if r.get("verdict") in _DRIVER_VERDICTS
        and _DELETION_RULES & _required_fired(r)
        and "alteration-role-lof-driver-neutral" in _required_fired(r)
    ]
    assert lof_deletion_driver, "LoF+deletion driver rungs vanished — a real TSG deletion driver would now be missed"


def test_gof_shield_rung_precedes_the_bare_deletion_driver_rung():
    """★ The CASE-028 property does NOT rest on the absence of a bad rung — it rests on LADDER ORDER, and
    until this test nothing asserted that order.

    Near the bottom of the first-match ladder each deletion predicate has a BARE single-predicate rung
    (`when_fired: <predicate>` -> recurrent_deletion_driver) with no role gate at all. A GoF oncogene that
    fires a deletion predicate is kept off it only because a higher rung — `[<predicate>, GoF role] ->
    mixed_pattern` — matches first and short-circuits. Those mixed_pattern rungs are therefore SHIELDS, not
    verdict claims: deleting one does not yield "no verdict for GoF+deletion", it hands the target to
    recurrent_deletion_driver and reinstates the IDH2/AML passenger-deletion false positive under a
    different label. `test_a_deletion_never_confers_a_driver_verdict_on_a_gof_role` cannot catch that,
    because after the deletion there is no offending rung left to find — the defect is a FALL-THROUGH.

    (This is why the GoF + cn-recurrent-homozygous-deletion-supportive rung is kept even though it appears
    in neither of the two passes composed into 1.10.0: the biallelic predicate is new in this version, so
    its bare rung at the ladder bottom is new too, and it arrived unshielded.)
    """
    rungs = yaml.safe_load(RESOLVER.read_text())["resolve"]
    checked = []
    for predicate in sorted(_DELETION_RULES):
        # "Bare" is a property of the FIRED SET — fires the predicate, gated by no role rule — not of which
        # YAML key the author used. Defining it as `when_fired == predicate` would let an identical rung
        # written `when_all_fired: [<predicate>]` (a one-element list) skip the shield requirement entirely
        # and leave the fall-through live with this test green. There are 0 such rungs today and 12
        # `when_fired` rungs, so this is latent, not live — but it is the same evasion-by-restatement the
        # rest of this file exists to close.
        bare = [
            i
            for i, r in enumerate(rungs)
            if r.get("verdict") in _DRIVER_VERDICTS
            and predicate in _reachable_fired(r)
            and not (_required_fired(r) & _ROLE_RULES)
        ]
        if not bare:
            continue  # no unguarded driver rung for this predicate — nothing to shield
        shields = [i for i, r in enumerate(rungs) if {predicate, _GOF_ROLE} <= _required_fired(r)]
        assert shields, (
            f"deletion predicate {predicate!r} has a BARE driver rung at index {bare[0]} "
            f"(verdict={rungs[bare[0]].get('verdict')!r}, no role gate) and NO higher rung pairing it with "
            f"the GoF role. A GoF oncogene firing this predicate falls straight through to a driver verdict "
            f"— the CASE-028 false positive, re-opened via fall-through rather than via a bad rung."
        )
        assert min(shields) < min(bare), (
            f"deletion predicate {predicate!r}: its GoF rung sits at index {min(shields)} but the BARE "
            f"driver rung is EARLIER at index {min(bare)}. First-match means the bare rung wins, so a GoF "
            f"oncogene reads {rungs[min(bare)].get('verdict')!r} off a passenger deletion."
        )
        checked.append(predicate)
    assert checked, (
        "no deletion predicate has a bare unguarded driver rung — if the bare recurrent_deletion_driver "
        "rungs were removed this test is now decoration and the docstring above needs re-reading"
    )


def test_multiclass_precedes_confirmed_driver():
    """Stage 2 precedence: in the first-match ladder, multi_class_driver must appear BEFORE
    confirmed_driver (so a dually-altered driver surfaces multi-class instead of collapsing to a
    single-class confirmed_driver), and both must sit BELOW the stratified biomarker verdict and
    ABOVE the drug_response pattern layer."""
    import yaml

    rungs = yaml.safe_load(RESOLVER.read_text())["resolve"]

    def first(v):
        return next((i for i, r in enumerate(rungs) if r.get("verdict") == v), None)

    bm, mc, cd, dr = (
        first("biomarker_stratified_dependency"),
        first("multi_class_driver"),
        first("confirmed_driver"),
        first("drug_response_biomarker"),
    )
    assert None not in (bm, mc, cd, dr), (bm, mc, cd, dr)
    assert bm < mc < cd < dr, (
        f"first-match order must be biomarker({bm}) < multi_class({mc}) < confirmed_driver({cd}) "
        f"< drug_response({dr}) — else EGFR-style dually-altered drivers collapse to confirmed_driver."
    )
