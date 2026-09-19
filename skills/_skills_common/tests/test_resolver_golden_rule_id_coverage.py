"""ANTI-VACUITY guard for the resolver golden oracle: a rung the table never exercises.

THE DEFECT THIS CATCHES (2026-09-12, found while fixing dependency precedence). Each gate's
frozen golden table is enumerated from `resolver_golden_snapshots.json[gate]["rule_ids"]` -- a
HAND-MAINTAINED list (regenerate_resolver_golden.py deliberately keeps it, it does not derive
it). So a rule_id that the resolver REFERENCES but the list OMITS is invisible: the enumerator
never produces a fired-set containing it, so no frozen row can reach any rung keyed on it. Those
rungs are unexercised, and -- worse -- a precedence edit touching them looks like a NO-OP.

Concretely: `dependency` listed 15 of the 22 rule ids its resolver references. Both
partner-conditional rules (Track PC, 2026-08-09) and all five data-unavailable rules (v1.1.0)
were never added, leaving 5 of 18 rungs dead to the oracle. `partner_conditional_dependent` --
a shipped verdict token, `dominant` in the nomination gate -- appeared on ZERO of the 840 frozen
rows. Raising those rungs above `discordant` (resolver v1.4.0) then moved 4/840 rows in the
committed table but 374/8,640 once the ids were listed, so the shipped oracle would have
green-lit a verdict-moving change as near-inert. Cf. the standing rule: for any check, ask
"CAN this fail?" -- for 5 of 18 dependency rungs, it could not.

WHY THIS IS A SEPARATE TEST rather than an assert inside the regenerator: the regenerator only
runs when someone deliberately re-baselines. This must fail in CI on the commit that adds an
unlisted rung, which is exactly when nobody is thinking about the oracle.

DECLARED DEBT, not a silent skip. Four gates have referenced ids the list omits, for TWO distinct
reasons. THREE (genomic_alteration, surface_modality, tractability_small_molecule) are COST debt:
the frozen table is the full co-emission CROSS-PRODUCT, so each additional (card, field) dimension
multiplies the row count. Measured 2026-09-13, at the CURRENT listing (the 2026-09-12 figures
below it were taken before contracts resolver 1.10.0 and three ids were paid for since):
    genomic_alteration          18 -> 30 ids  25,920 -> 29,859,840 rows  (~25 GB, unshippable)
    tractability_small_molecule 20 -> 22 ids  24,576 ->     73,728 rows  (+17 MB)
    surface_modality            17 -> 19 ids   8,064 ->     32,256 rows  (+7.7 MB)
THE COST IS NOT PER-ID AND THAT IS THE WHOLE TRAP. Each genomic debt id listed ALONE costs only
2x (25,920 -> 51,840; `cn-data-unavailable-insufficient` 34,560, it joins an existing group), so
"just add the one you need" reads cheap twelve times in a row and multiplies to 1,152x. Read the
marginal cost against the ids you would list TOGETHER, never one at a time.
For reference the whole snapshot is 21.7 MB today (14 MB before the three genomic ids below were
paid for) and was 41.5 MB before the co-emission migration shrank it, so paying ~29 MB is the
right trade for the other two gates and ~25 GB is not -- the fix is a cheaper ENUMERATION REGIME
(e.g. freeze all co-firing sets up to order k plus the full set: precedence defects are pairwise,
and size<=2 over 30 ids is 466 rows, not 29.9 M), which is a design change this guard deliberately
does not smuggle in. Until then the gap is recorded below WITH its measured cost, and the
assertions below let it only SHRINK.

WHAT THE THREE PAID-FOR IDS BOUGHT (2026-09-13, contracts resolver 1.10.0): 3,240 -> 25,920 rows,
14 -> 21.7 MB, to list `cn-recurrent-homozygous-deletion-supportive`,
`fusion-landscape-recurrent-driver-supportive` and `fusion-recurrence-high-partner-context`. Before
that, `recurrent_fusion_driver` -- a SHIPPED verdict token -- was on ZERO of the 3,240 rows, so
#739's fusion demotion was unmeasurable here. See
test_genomic_gate_exercises_the_two_arms_resolver_1_10_0_rewrote for the reachability assertions,
including why listing ONE clause of a two-clause guard bought a 2x row cost for zero coverage.

THE FOURTH GATE, `selectivity`, is a DIFFERENT KIND of debt (added 2026-09-19, F3 of the
tumor-selectivity content audit). Until then `_referenced_rule_ids` walked only `spec['resolve']`,
never `post_resolver_clamp`, so the gate's 5 precedence veto arms + the 3-conjunct #978 rescue
upgrade were referenced-but-unlisted while the coverage test PASSED -- a green that could not fail,
the exact failure mode this module exists to catch, one layer deeper. Widening the walk (see
_referenced_rule_ids) surfaced 7 unlisted ids -- the plan estimated 5; `tvn-no-full-normal-window-veto`
and the `protein-modestly-up-neutral` OR-clause were missed by eye. But these ids are NOT
listable-with-benefit: the golden table is built from resolve_verdict, which evaluates ONLY the
resolve ladder -- the post_resolver_clamp precedence + upgrade run DOWNSTREAM in
skills/_skills_common/selectivity_veto.py. Measured 2026-09-19: listing all 7 grows selectivity
16 -> 1,536 rows (+0.35 MB) and adds ZERO verdict tokens, ZERO driving tokens, and none of the 7 ever
becomes a driving_rule -- pure enumeration padding that would LOOK like coverage while exercising
nothing. So selectivity is declared debt not because listing is expensive but because listing is
INERT here; a null-diff also confirmed the would-be 1,536-row table is byte-identical against the
live contracts tree and the skills-CI contracts pin, so nothing was gained by coupling it to the
pin either. The clamp layer is exercised by selectivity_veto.py's own behavioural tests
(test_compose_core, test_selectivity_hero, tumor-selectivity/test_verdict, and ~16 others). See
test_selectivity_debt_is_exactly_the_post_resolver_clamp_layer, which pins the debt to precisely
the clamp-only ids so a NEW clamp arm still reds this module.

The debt map is checked for EQUALITY, not containment, so it cannot drift in either direction:
  - add an unlisted rung to a debt gate  -> this test fails (the set no longer matches)
  - fix a debt gate by listing its ids   -> this test fails until the entry is deleted
  - add an unlisted rung to any OTHER gate -> this test fails (no entry covers it)
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

SKILLS = Path(__file__).resolve().parents[2]  # .../skills
CONTRACTS = Path(
    os.environ.get("TARGET_CONTRACTS_ROOT", "/home/sagemaker-user/rnd-computational-biology-oncology-target-contracts")
)
SNAPSHOT = Path(__file__).resolve().parent / "resolver_golden_snapshots.json"
_GOLDEN = json.loads(SNAPSHOT.read_text())

# gate -> rule ids the resolver references that the golden's rule_ids list does NOT carry, because
# listing them would blow the frozen cross-product up (row counts in the module docstring). Shrink
# this map; do not grow it without the measured row count that justifies the entry.
RULE_ID_COVERAGE_DEBT: dict[str, set[str]] = {
    "genomic_alteration": {
        "amp-expr-indication-scoped-context",
        "amp-expr-moderately-dependent-supportive",
        "amp-expr-strongly-dependent-supportive",
        "cn-amplified-indication-scoped-context",
        "cn-amplified-moderately-dependent-supportive",
        "cn-amplified-strongly-dependent-supportive",
        "cn-data-unavailable-insufficient",
        "fusion-positive-indication-scoped-context",
        "fusion-positive-moderately-dependent-supportive",
        "fusion-positive-strongly-dependent-supportive",
        "mutant-indication-scoped-context",
        "mutation-drug-response-strongly-sensitive-supportive",
    },
    # DIFFERENT KIND of debt from the other three (which are cross-product COST): the selectivity
    # veto/upgrade layer is applied by selectivity_veto.py DOWNSTREAM of resolve_verdict, so listing
    # these in the golden's rule_ids enumerates rows that CANNOT exercise them (measured 16 -> 1,536
    # rows, +0 verdicts, +0 drivers). See the module docstring + the boundary-pin test below.
    "selectivity": {
        "protein-modestly-up-neutral",
        "protein-strongly-up-supportive",
        "tumor-vs-normal-crossing-strong-supportive",
        "tvn-no-full-normal-window-veto",
        "tvn-no-therapeutic-window-veto",
        "tvn-sc-normal-critical-organ-veto",
        "tvn-stromal-confound-veto",
    },
    "surface_modality": {
        "exon-window-essential-liability-tce-opposing",
        "pmhc-broadly-presented-normal-tce-opposing",
    },
    "tractability_small_molecule": {
        "measured-potent-ligand-sm-supportive",
        "measured-weak-ligand-sm-supportive",
    },
}


def _flatten_rule_ids(node) -> set[str]:
    """Collect every rule_id string from a nested list/str structure. `upgrade.requires` is a
    list-of-lists of rule_ids (a conjunction of OR-groups), so it needs recursive flattening."""
    out: set[str] = set()
    if isinstance(node, str):
        out.add(node)
    elif isinstance(node, list):
        for item in node:
            out |= _flatten_rule_ids(item)
    return out


def _referenced_rule_ids(gate: str) -> set[str]:
    """Every rule_id a resolver spec mentions: in any `resolve` when-clause or driving_rule, AND in
    the `post_resolver_clamp` layer (each precedence arm's when-clause + every `upgrade.requires`
    conjunct).

    The clamp/upgrade layer was INVISIBLE here until 2026-09-19: this walked only `spec['resolve']`,
    so the selectivity gate's 5 precedence veto arms and the #978 upgrade's 3 requires-conjuncts were
    referenced-but-unlisted while the coverage test still passed -- a green that could not fail (see
    the module docstring, "the clamp layer"). Only `selectivity` ships a `post_resolver_clamp` today,
    but the walk is generic. `modality_conditional.expected_inert_arms[].rule_id` is deliberately NOT
    walked -- those arms are already surfaced by `precedence`, and treating that block as a third
    aperture would exceed what the reachability tests below cover."""
    spec = yaml.safe_load((CONTRACTS / "resolvers" / f"{gate}.resolver.yaml").read_text())
    out: set[str] = set()

    def _add_when_clauses(node: dict) -> None:
        for key in ("when_fired", "when_all_fired", "when_any_fired", "when_not_fired"):
            val = node.get(key)
            if isinstance(val, str):
                out.add(val)
            elif isinstance(val, list):
                out.update(val)

    for rung in spec.get("resolve") or []:
        _add_when_clauses(rung)
        if rung.get("driving_rule"):
            out.add(rung["driving_rule"])

    clamp = spec.get("post_resolver_clamp") or {}
    for arm in clamp.get("precedence") or []:
        _add_when_clauses(arm)
        if arm.get("driving_rule"):
            out.add(arm["driving_rule"])
    upgrade = clamp.get("upgrade")
    for up in upgrade if isinstance(upgrade, list) else [upgrade] if upgrade else []:
        out |= _flatten_rule_ids(up.get("requires"))

    return out


@pytest.mark.parametrize("gate", sorted(_GOLDEN.keys()))
def test_golden_rule_ids_cover_every_rule_the_resolver_references(gate):
    """No rung may be unreachable from the frozen table's enumeration, except as DECLARED debt."""
    missing = _referenced_rule_ids(gate) - set(_GOLDEN[gate]["rule_ids"])
    declared = RULE_ID_COVERAGE_DEBT.get(gate, set())
    assert missing == declared, (
        f"{gate}: golden rule_ids coverage drifted.\n"
        f"  unlisted but referenced : {sorted(missing) or '(none)'}\n"
        f"  declared debt           : {sorted(declared) or '(none)'}\n"
        f"Any rung keyed on an unlisted rule_id is UNEXERCISED by the golden table, so a "
        f"precedence edit touching it will look inert. Add the id to "
        f"resolver_golden_snapshots.json[{gate!r}]['rule_ids'] and re-run "
        f"regenerate_resolver_golden.py; if the resulting row count is prohibitive, extend "
        f"RULE_ID_COVERAGE_DEBT with the MEASURED count. If you FIXED a debt entry, delete it here."
    )


def test_every_referenced_rule_id_exists_in_the_rule_index():
    """Complementary direction: a resolver must not reference a rule_id no interpretation rule
    emits (a typo or a retired rule) -- that rung is dead for the opposite reason."""
    from _test_support import load_module

    coemit = load_module(SKILLS / "_skills_common" / "tests" / "coemission.py", "coemission_cov_ut")
    known = set(coemit.load_rule_index(CONTRACTS))
    dead: dict[str, list[str]] = {}
    for gate in sorted(_GOLDEN):
        unknown = sorted(_referenced_rule_ids(gate) - known)
        if unknown:
            dead[gate] = unknown
    assert not dead, f"resolvers reference rule_ids no interpretation rule emits: {dead}"


def test_the_debt_map_names_only_shipped_gates_and_real_rule_ids():
    """The debt map itself must stay honest: no entry for a retired gate, and no entry naming a
    rule_id the resolver no longer references (which would let a REAL gap hide behind a stale
    exemption of the same size)."""
    assert set(RULE_ID_COVERAGE_DEBT) <= set(_GOLDEN), (
        f"debt map names gates with no golden table: {sorted(set(RULE_ID_COVERAGE_DEBT) - set(_GOLDEN))}"
    )
    for gate, ids in RULE_ID_COVERAGE_DEBT.items():
        stale = sorted(ids - _referenced_rule_ids(gate))
        assert not stale, f"{gate}: debt names rule_ids the resolver no longer references: {stale}"


def test_dependency_gate_exercises_partner_conditional_dependent():
    """The specific regression: `partner_conditional_dependent` is a shipped verdict token and a
    `dominant` nomination-gate positive_signal, yet ZERO of the 840 frozen dependency rows could
    emit it because both partner-conditional rule ids were unlisted. Pin that it is reachable.

    Deliberately named per-verdict rather than folded into the coverage test above: the coverage
    test is about rule IDS, this is about the VERDICT the missing ids gated, which is the thing a
    reviewer actually cares about.
    """
    verdicts = {v for v, _ in _GOLDEN["dependency"]["table"].values()}
    assert "partner_conditional_dependent" in verdicts
    assert "insufficient_underpowered" in verdicts  # the other rung the 15-id list starved


def test_genomic_gate_exercises_the_two_arms_resolver_1_10_0_rewrote():
    """The same regression, one gate over: contracts #739/#760 rewrote the CN-deletion and fusion
    arms, and the 15-id list made BOTH invisible to this oracle.

    `recurrent_fusion_driver` is a shipped verdict token that appeared on ZERO of the 3,240 frozen
    rows, because `fusion-landscape-recurrent-driver-supportive` was declared debt -- so #739's
    fusion demotion (promiscuous bare-fusion rung dropped BELOW the SNV-recurrence rungs, the
    STK11/LUAD false positive) was unmeasurable here. Listing it makes both fusion rungs reachable
    and the demotion observable in both directions, asserted below.

    Note on the partner-context gate: `fusion-recurrence-high-partner-context` co-gates the TOP
    fusion rung and never becomes a `driving_rule_id` of its own, so listing it ALONE bought a 2x
    row cost for zero coverage -- its partner had to be listed too. Listing one clause of a
    two-clause guard does not make the rung reachable; that is why both went in together."""
    gate = "genomic_alteration"
    table = _GOLDEN[gate]["table"]
    verdicts = {v for v, _ in table.values()}
    assert "recurrent_fusion_driver" in verdicts, "the fusion arm is unexercised again"
    assert "recurrent_deletion_driver" in verdicts

    # The biallelic deletion predicate #739 introduced must actually DRIVE rows, not merely appear.
    assert any(d == "cn-recurrent-homozygous-deletion-supportive" for _, d in table.values()), (
        "cn-recurrent-homozygous-deletion-supportive drives no frozen row"
    )

    # #739's fusion demotion, both directions: with the high-partner-context gate the fusion rung
    # wins; without it the SNV-recurrence rung does. If a future edit re-promotes the bare fusion
    # rung above SNV recurrence, the second set gains recurrent_fusion_driver and this fails.
    fus, hp, snv = (
        "fusion-landscape-recurrent-driver-supportive",
        "fusion-recurrence-high-partner-context",
        "snv-recurrence-top-driver-supportive",
    )

    def verdicts_where(required: set[str], excluded: set[str]) -> set[str]:
        out = set()
        for key, (verdict, _driving) in table.items():
            fired = {r for r in key.split(",") if r}
            if required <= fired and not (excluded & fired):
                out.add(verdict)
        return out

    with_hp = verdicts_where({fus, snv, hp}, set())
    without_hp = verdicts_where({fus, snv}, {hp})
    assert with_hp and without_hp, "the fusion x SNV co-emission rows vanished"
    assert "recurrent_fusion_driver" in with_hp
    assert "recurrent_fusion_driver" not in without_hp, (
        "a promiscuous bare fusion now outranks SNV recurrence again — this is the STK11/LUAD defect"
    )
    assert "recurrent_snv_driver" in without_hp


def test_selectivity_debt_is_exactly_the_post_resolver_clamp_layer():
    """Selectivity's coverage debt is a DIFFERENT KIND from the other three gates' (cross-product
    COST). Selectivity does ALL its veto/upgrade work in `post_resolver_clamp`, applied by
    skills/_skills_common/selectivity_veto.py DOWNSTREAM of resolve_verdict -- the function the golden
    table is built from. So the golden STRUCTURALLY cannot exercise the clamp: listing the clamp ids
    in selectivity.rule_ids enumerates 16 -> 1,536 rows that add ZERO verdicts and ZERO drivers
    (measured 2026-09-19), padding that would LOOK like coverage while exercising nothing. The clamp
    layer is exercised by selectivity_veto.py's own behavioural tests instead.

    Pin the boundary so the debt stays HONEST and NON-VACUOUS: it must equal EXACTLY the rule_ids the
    clamp layer references and the resolve ladder does not. A new clamp arm must appear here (or the
    coverage test above reds); MOVING an arm into the resolve ladder -- where the golden CAN exercise
    it -- must shrink this set. This is the verdict-aware analogue of the dependency/genomic
    reachability tests: for a layer the golden cannot reach, we pin WHY rather than assert a verdict
    the frozen table will never carry.
    """
    gate = "selectivity"
    spec = yaml.safe_load((CONTRACTS / "resolvers" / f"{gate}.resolver.yaml").read_text())

    resolve_referenced: set[str] = set()
    for rung in spec.get("resolve") or []:
        for key in ("when_fired", "when_all_fired", "when_any_fired", "when_not_fired"):
            val = rung.get(key)
            if isinstance(val, str):
                resolve_referenced.add(val)
            elif isinstance(val, list):
                resolve_referenced.update(val)
        if rung.get("driving_rule"):
            resolve_referenced.add(rung["driving_rule"])

    # clamp_only = ids the resolver references ONLY through post_resolver_clamp (precedence when-
    # clauses + upgrade.requires), never through a resolve rung. resolve_verdict cannot reach these.
    clamp_only = _referenced_rule_ids(gate) - resolve_referenced
    assert clamp_only, (
        "selectivity referenced NO clamp-only rule_ids -- either the resolver dropped its "
        "post_resolver_clamp, or _referenced_rule_ids regressed to walking only spec['resolve'] "
        "(the F3 aperture bug). This assertion is the anti-vacuity guard for the widened walk."
    )
    # Every debt id must live in the clamp layer (none is resolve-exercisable, so none is a lazy
    # cheap-to-list omission)...
    debt = RULE_ID_COVERAGE_DEBT.get(gate, set())
    assert debt & resolve_referenced == set(), (
        f"selectivity debt names resolve-ladder ids the golden CAN exercise -- list them, not debt "
        f"them: {sorted(debt & resolve_referenced)}"
    )
    # ...and the debt is EXACTLY the clamp-only ids not already carried in rule_ids. (One clamp arm,
    # tvn-tphp-broad-abundant-normal-protein-veto, is historically listed though equally inert in
    # resolve_verdict; it is therefore not missing and not debt.) Moving a clamp arm INTO the resolve
    # ladder -- where the golden can exercise it -- must shrink this set; adding a new clamp arm grows it.
    listed = set(_GOLDEN[gate]["rule_ids"])
    assert debt == clamp_only - listed, (
        f"selectivity debt must equal the UNLISTED clamp-only rule_ids.\n"
        f"  clamp-only referenced : {sorted(clamp_only)}\n"
        f"  already listed        : {sorted(clamp_only & listed)}\n"
        f"  expected debt         : {sorted(clamp_only - listed)}\n"
        f"  declared debt         : {sorted(debt)}"
    )
