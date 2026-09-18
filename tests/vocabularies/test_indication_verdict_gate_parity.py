"""Resolver → GATE parity for the indication-conditioned dependency verdicts (Stage 2b).

WHY THIS FILE EXISTS — the direction nothing else covers.

`validate_verdict_tokens` and `test_kill_capable_completeness.py` both walk GATE → RESOLVER: they
catch a gate block naming a verdict the resolver cannot mint. Neither walks RESOLVER → GATE, and that
is exactly where a newly minted verdict sits. The failure mode is not a demotion but an INVISIBILITY:
a resolver verdict that no gate block names is unseen by every gate, so

  * a kill-capable verdict silently stops killing (the dependency axis fails OPEN), and
  * the calibration set's `must_not_veto` assertions pass VACUOUSLY, because the verdict they forbid
    is one no gate can reach.

target-contracts #812 (resolver dependency v1.4.0 → v1.5.0) minted four such verdicts. Three carry a
gate role; one is a deliberate absence. This file asserts the partition is EXHAUSTIVE, so the next
token cannot be added without a decision being recorded here.

DESIGN NOTE — everything derivable is DERIVED. The four tokens are computed from the interpretation
rules (which rules read `indication_dependency_class`) and the resolver ladder, never hand-listed, so
this file cannot pass by agreeing with a stale copy of itself. The one hand-written list is the
cross-repo obligation set, and it is cross-checked against the derived set.
"""

from __future__ import annotations

import glob
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
GATE = REPO / "vocabularies" / "nomination_verdict_gate.yaml"
THESIS = REPO / "vocabularies" / "target_thesis.yaml"
CALIB = REPO / "vocabularies" / "known_target_calibration_set.yaml"
RESOLVER = REPO / "resolvers" / "dependency.resolver.yaml"
RULES_GLOB = str(REPO / "interpretation-rules" / "*.rules.yaml")

POOLED = "non_dependent"
IN_INDICATION = "not_dependent_in_indication"

# The card field that makes a verdict indication-conditioned. Declared once; every derivation below
# keys off it, so renaming the field in the card breaks these tests loudly rather than quietly
# emptying their populations.
INDICATION_FIELD = "indication_dependency_class"


# ---------------------------------------------------------------------------
# Loaders + derivations
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def gate():
    return yaml.safe_load(GATE.read_text())


@pytest.fixture(scope="module")
def resolver():
    return yaml.safe_load(RESOLVER.read_text())


def _rung_rule_ids(rung: dict) -> set[str]:
    out: set[str] = set()
    if "when_fired" in rung:
        out.add(rung["when_fired"])
    for key in ("when_any_fired", "when_all_fired"):
        out |= set(rung.get(key) or [])
    return out


@pytest.fixture(scope="module")
def indication_rule_ids() -> set[str]:
    """Rule ids that fire on the indication-conditioned card field."""
    found: set[str] = set()
    for path in glob.glob(RULES_GLOB):
        for rule in yaml.safe_load(Path(path).read_text()).get("rules") or []:
            when = rule.get("when") or {}
            if when.get("field") == INDICATION_FIELD:
                found.add(rule["rule_id"])
    assert found, (
        f"no interpretation rule reads {INDICATION_FIELD!r} — every derivation in this file would "
        f"have an EMPTY population and pass vacuously"
    )
    return found


@pytest.fixture(scope="module")
def all_dependency_verdicts(resolver) -> set[str]:
    verdicts = {r["verdict"] for r in resolver["resolve"]} | {resolver["default"]}
    assert len(verdicts) > 1, "a one-verdict ladder makes the partition test vacuous"
    return verdicts


@pytest.fixture(scope="module")
def indication_only_verdicts(resolver, indication_rule_ids) -> set[str]:
    """Verdicts reachable ONLY through an indication rule — i.e. the tokens #812 minted.

    Derived, not listed. A verdict is indication-only when EVERY rung producing it references an
    indication rule id. That deliberately excludes `partner_conditional_dependent` and
    `chemical_genetic_confirmed_dependent`: #812's compound veto-suppressor rungs (priorities 6-8)
    mint those from an indication rule, but they are also reachable from pooled rungs, so they are
    pre-existing verdicts and need no new gate wiring.
    """
    by_verdict: dict[str, list[set[str]]] = {}
    for rung in resolver["resolve"]:
        by_verdict.setdefault(rung["verdict"], []).append(_rung_rule_ids(rung))
    derived = {v for v, rungs in by_verdict.items() if all(ids & indication_rule_ids for ids in rungs)}
    assert derived, "no indication-only verdicts derived — the ladder or the rules moved"
    return derived


def _verdict_values(node, path: str = ""):
    """Every (path, value) pair under a `verdict` key, at any depth."""
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _verdict_values(value, f"{path}/{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from _verdict_values(value, f"{path}[{index}]")
    elif path.endswith("/verdict"):
        yield path, node


def _blocks_naming(gate: dict, verdict: str) -> set[str]:
    """Top-level gate blocks that name `verdict` EXACTLY as a verdict value.

    Exact comparison matters: `non_dependent_paralog_buffered` contains the pooled token as a
    substring, and a `in`-based scan would report parity that does not exist.
    """
    return {path.lstrip("/").split("/")[0].split("[")[0] for path, value in _verdict_values(gate) if value == verdict}


# ---------------------------------------------------------------------------
# (1) The exhaustive partition — the resolver → gate direction
# ---------------------------------------------------------------------------

# Verdicts that deliberately carry NO gate role, with the reason each is inert. A verdict absent from
# both the kill registry and positive_signals contributes NOTHING to a nomination, which is either a
# considered decision or a bug; enumerating them here forces the distinction to be made once, in
# writing. Keys are asserted to be exactly the complement of (kill ∪ positive) below, so this is a
# partition and not a wish list.
DELIBERATELY_GATE_INERT = {
    "insufficient": "the default rung: nothing fired, so there is nothing to gate on",
    "insufficient_underpowered": (
        "'we could not look' — an underpowered read must never foreclose a target, and must never "
        "corroborate one either"
    ),
    "insufficient_underpowered_pan_essential": (
        "could-not-look on the SAFETY arm specifically; priority 0 so it pre-empts the pan-essential "
        "killer rather than being gated by it"
    ),
    "insufficient_underpowered_in_indication": (
        "could-not-look at indication grain (#812). Deliberately absent from EVERY gate block — see "
        "test_the_indication_insufficient_arm_is_absent_from_every_gate_block for the fail-closed "
        "hazard this absence creates on the skills side"
    ),
    "non_dependent_paralog_buffered": (
        "a MODALITY preference, not a verdict about the target: the requirement is masked by a "
        "redundant paralog, so a degrader/dual-targeting hypothesis stays open. Neither a kill (the "
        "target may well be required) nor a positive (nothing measured it as required)"
    ),
}


def test_every_resolver_verdict_has_a_declared_gate_role(gate, all_dependency_verdicts):
    """EXHAUSTIVE partition of the dependency ladder into kill / positive / deliberately-inert.

    This is the assertion that would have caught #812's gap at authoring time. It fails when a
    resolver verdict exists that no gate block names and no one has written down why.
    """
    kill = {e["verdict"] for e in gate["kill_capable_verdicts"]["dependency"]}
    positive = {p["verdict"] for p in gate["positive_signals"] if p["sub_skill"] == "dependency"}
    inert = set(DELIBERATELY_GATE_INERT)

    # Anti-vacuity: all three classes must be populated, or the union assertion is trivially
    # satisfiable by one class swallowing the ladder.
    assert kill, "kill_capable_verdicts.dependency is empty"
    assert positive, "no dependency positive_signals"
    assert inert, "the inert declaration is empty"

    unclassified = all_dependency_verdicts - kill - positive - inert
    assert not unclassified, (
        f"dependency verdicts with NO declared gate role: {sorted(unclassified)}. A verdict no gate "
        f"block names is INVISIBLE to every gate, not demoted by it: if it is kill-capable the axis "
        f"fails OPEN, and any calibration assertion forbidding it passes VACUOUSLY. Add it to "
        f"kill_capable_verdicts, to positive_signals, or to DELIBERATELY_GATE_INERT with a reason."
    )

    # The inert list is the COMPLEMENT, not a free-text annex: a verdict that gained a gate role must
    # be removed from it, or the two would disagree about what the framework does with the token.
    overclaimed = inert & (kill | positive)
    assert not overclaimed, (
        f"declared gate-inert but actually gated: {sorted(overclaimed)} — remove from DELIBERATELY_GATE_INERT"
    )
    stale = inert - all_dependency_verdicts
    assert not stale, f"DELIBERATELY_GATE_INERT names verdicts the resolver cannot mint: {sorted(stale)}"

    # A verdict cannot both kill and corroborate.
    assert not (kill & positive), f"verdict is both kill-capable and a positive: {sorted(kill & positive)}"


def test_the_four_minted_tokens_are_exactly_the_indication_only_verdicts(indication_only_verdicts):
    """Pins the SHAPE of what #812 added, derived from the rules + ladder.

    Everything below reasons about "the indication tokens"; if that set silently changed, those tests
    would keep passing against the wrong population. Four tokens: two positives, one kill, one
    deliberate absence.
    """
    assert indication_only_verdicts == {
        "lineage_selective_in_indication",
        "dependent_in_indication",
        IN_INDICATION,
        "insufficient_underpowered_in_indication",
    }, (
        f"the indication-only verdict set moved: {sorted(indication_only_verdicts)}. Re-derive the "
        f"parity obligations below before editing this assertion."
    )


def test_each_indication_token_has_the_gate_role_its_name_claims(gate, indication_only_verdicts):
    """The two positives are positives, the killer kills, the insufficient arm does neither."""
    kill = {e["verdict"] for e in gate["kill_capable_verdicts"]["dependency"]}
    positive = {p["verdict"] for p in gate["positive_signals"] if p["sub_skill"] == "dependency"}

    assert {"lineage_selective_in_indication", "dependent_in_indication"} <= positive, (
        "a POSITIVE verdict absent from positive_signals contributes nothing to the tier — a false "
        "absence no gate catches, because the positive loader reads this list and never the resolver"
    )
    assert IN_INDICATION in kill, "the indication killer must be kill-capable or the axis fails OPEN"
    assert "insufficient_underpowered_in_indication" not in kill | positive, (
        "'we could not look' must neither foreclose nor corroborate"
    )
    # Anti-vacuity: the classification above must actually partition the four, not skip one.
    assert indication_only_verdicts <= positive | kill | set(DELIBERATELY_GATE_INERT)


# ---------------------------------------------------------------------------
# (2) Per-mechanism parity with the pooled arm
# ---------------------------------------------------------------------------


def test_every_gate_mechanism_naming_the_pooled_arm_also_names_the_indication_arm(gate):
    """STRUCTURAL parity, walked rather than hand-listed.

    The pooled and indication arms make the SAME claim at different grains, so any mechanism that
    treats the pooled one specially must treat the indication one the same way — otherwise Stage 5
    silently changes behaviour based on which token happened to win the resolver ladder
    (`not_dependent_in_indication` is priority 9, pooled `non_dependent` is 22, so at indication
    grain the NEW token wins and any mechanism keyed only on the old one stops firing).

    Walked over every `verdict` value in the file, so a mechanism added later is covered without
    editing this test. Comparison is by EXACT value: `non_dependent_paralog_buffered` contains the
    pooled token as a substring and would fake parity under a containment check.
    """
    pooled_blocks = _blocks_naming(gate, POOLED)
    indication_blocks = _blocks_naming(gate, IN_INDICATION)

    assert pooled_blocks, "no block names the pooled arm — this test would be vacuous"
    missing = pooled_blocks - indication_blocks
    assert not missing, (
        f"blocks that treat the pooled arm specially but not the indication arm: {sorted(missing)}. "
        f"At indication grain the new token OUTRANKS the pooled one, so such a block would stop "
        f"firing on exactly the runs it was written for."
    )


def test_the_mirrored_suppressor_arms_have_identical_triggers(gate):
    """The three mirrored veto_suppressors arms must escape on the SAME triggers at both grains.

    A4i (paralog buffering) is a DECLARED EXCEPTION in the other direction — indication-only, with no
    pooled twin — because at pooled grain the resolver relabels the verdict to
    `non_dependent_paralog_buffered` (rung 19) before the gate ever sees a veto. Asserting set
    equality without naming that exception would force someone to add a pooled paralog suppressor
    that can never fire.
    """
    suppressors = gate["veto_suppressors"]

    def triggers(verdict):
        out = set()
        for s in suppressors:
            if s["suppresses"]["verdict"] != verdict:
                continue
            for w in s["when_present"]:
                out.add((w["sub_skill"], w["verdict"]) if "verdict" in w else (w["card_id"], w["field"], w["value"]))
        return out

    pooled = triggers(POOLED)
    indication = triggers(IN_INDICATION)
    assert pooled, "no pooled suppressor arms — parity would be vacuous"

    paralog_exception = {("paralog-buffering", "paralog_buffering_class", "strong")}
    assert paralog_exception <= indication, (
        "the paralog-buffering escape must exist at indication grain: the resolver has no compound "
        "rung outranking the indication killer, so the gate is the only layer that can stop the veto"
    )
    assert not (paralog_exception & pooled), (
        "a pooled paralog suppressor can never fire — resolver rung 19 relabels the verdict first. "
        "If this fails, the resolver changed and the A4i asymmetry needs re-deriving."
    )
    assert pooled == indication - paralog_exception, (
        f"mirrored suppressor triggers diverged: pooled={sorted(pooled)} "
        f"indication={sorted(indication - paralog_exception)}"
    )


def test_positive_weights_are_grain_neutral(gate):
    """The indication positives must carry the SAME weight as the pooled shape verdict they refine.

    This is what makes Stage 5 tier-neutral on the positive path. Promoting
    `lineage_selective_in_indication` to `dominant` would let one CRISPR read reach the `strong` tier
    (>=2 dimensions + a dominant), and `positive_tier_config.forces_nominate_at_tier: strong` turns
    that into a FORCED nominate — i.e. renaming a token would manufacture GOs off the same evidence.
    """
    weights = {p["verdict"]: p["weight"] for p in gate["positive_signals"] if p["sub_skill"] == "dependency"}
    pooled_weight = weights["lineage_selective"]
    assert weights["lineage_selective_in_indication"] == pooled_weight, (
        "the honest-grain form of a claim must not also promote its evidence tier"
    )
    assert weights["dependent_in_indication"] == pooled_weight, (
        "dependent-but-not-selective is WEAKER than the selective arm, so it cannot outrank it"
    )
    assert pooled_weight != "dominant", (
        "guard on the guard: if the pooled arm ever becomes dominant, the equality above would "
        "propagate a forced-nominate path to the indication tokens instead of preventing one"
    )


def test_thesis_lanes_and_routing_escape_both_arms(gate):
    """Both non-dependence arms must be droppable by thesis routing, on every thesis that drops one.

    Omitting the new arm would REGRESS the landed 0/14 surface-antigen fix rather than merely fail to
    extend it: an indication-scoped run on a surface antigen resolves the new token (priority 9), and
    a thesis list naming only the pooled arm would stop dropping the veto it drops today.
    """
    for entry in gate["thesis_axis_relevance"]:
        dropped = {i["verdict"] for i in entry["irrelevant"] if i["sub_skill"] == "dependency"}
        assert (POOLED in dropped) == (IN_INDICATION in dropped), (
            f"thesis {entry['thesis']!r} drops {sorted(dropped)} — a thesis that makes one grain of "
            f"non-dependence irrelevant must make both irrelevant, or the fix depends on which "
            f"token won the ladder"
        )
        assert "pan_essential_killer" not in dropped, (
            f"thesis {entry['thesis']!r} must never drop the broad-tox safety liability"
        )

    lanes = yaml.safe_load(THESIS.read_text())["step_2b_refinement"]
    assert lanes, "no refinement lanes — vacuous"
    for lane in lanes:
        dep = lane["when_verdicts"].get("dependency")
        if dep is None:
            continue
        assert (POOLED in dep) == (IN_INDICATION in dep), (
            f"lane -> {lane['to']!r} escapes {dep}; its `subsumes` claim names a gate mechanism that "
            f"now has twins for both arms, so listing one makes that claim false and Step 2c would "
            f"retire the epicycle out from under the unlisted arm"
        )


def test_calibration_forbids_the_indication_veto_wherever_it_forbids_the_pooled_one():
    """`expected_verdict_not_in` parity, and the ratchet that stops the Stage-5 red being 'fixed'.

    The assertion is INERT TODAY BY REACHABILITY (no producer populates the card field until Stage
    5), so it cannot fail now — which is precisely why it needs pinning: nothing else would notice
    the token being dropped again.
    """
    doc = yaml.safe_load(CALIB.read_text())
    lists = []

    def walk(node):
        if isinstance(node, dict):
            if "expected_verdict_not_in" in node:
                lists.append(node["expected_verdict_not_in"])
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(doc)
    assert lists, "no expected_verdict_not_in lists found — vacuous"
    for forbidden in lists:
        assert (POOLED in forbidden) == (IN_INDICATION in forbidden), (
            f"calibration forbids {forbidden}: an approved target must not read a veto verdict at "
            f"EITHER grain. If this red arrived at Stage 5, fix the resolver (see "
            f"test_resolver_has_no_paralog_twin_for_the_indication_killer), never this list."
        )


# ---------------------------------------------------------------------------
# (3) The deliberate absence, and the cross-repo obligation it creates
# ---------------------------------------------------------------------------


def test_the_indication_insufficient_arm_is_absent_from_every_gate_block(gate):
    """`insufficient_underpowered_in_indication` must appear in NO gate block.

    Only an absence-assertion can see this: a declared-vs-referenced validator walks gate → resolver
    and is structurally blind to a resolver token that appears in no gate block at all.

    ⚠ THE ABSENCE IS CORRECT HERE AND DANGEROUS ONE REPO OVER. skills `tp_gates.py` routes an
    UNRECOGNIZED dependency verdict to a FORCED VETO (`_GATING_AXIS_FAILCLOSED_ACTION["dependency"]
    = "veto"`). Its two vocab→skills coupling tests scan THIS file's blocks, so they will catch the
    other three tokens at pin-bump time — and they cannot catch this one, because a token that
    appears in no block is invisible to a scan of blocks. Net effect after Stage 5 if the skills-side
    delta below is not applied: "we could not look" silently becomes "veto".
    """
    named = {value for _path, value in _verdict_values(gate)}
    assert "insufficient_underpowered_in_indication" not in named, (
        "the could-not-look arm must not be gated: it would foreclose a target for a coverage gap"
    )
    # Anti-vacuity: the walker must actually find verdicts, or this absence proves nothing.
    assert IN_INDICATION in named, "the walker found no verdicts — the absence above is vacuous"


# The forced skills-side delta, declared here because this repo is where the tokens are minted and
# this repo's CI is what a reviewer reads. Not machine-checkable from here (the sibling checkout is
# not guaranteed present, and pinning its line numbers would rot), so it is checked for INTERNAL
# CONSISTENCY against the derived token set instead — a token minted here and missing from the
# obligation list is a real failure this test catches.
SKILLS_SIDE_OBLIGATIONS = {
    "_RECOGNIZED_GATING_VERDICTS['dependency']": {
        "lineage_selective_in_indication",
        "dependent_in_indication",
        IN_INDICATION,
        "insufficient_underpowered_in_indication",
    },
    "_FALLBACK_GATE_VERDICTS (('dependency', <token>) -> 'veto')": {IN_INDICATION},
    "_FALLBACK_KILL_CAPABLE_VERDICTS (('dependency', <token>) -> 'gated')": {IN_INDICATION},
    "test_nomination_gate_fail_closed.py closed-set veto pins": {IN_INDICATION},
}


def test_cross_repo_obligations_cover_every_minted_token(indication_only_verdicts):
    """Every token minted here must appear in the skills-side obligation declaration.

    The recognition list is the one that must be TOTAL: anything it misses is fail-CLOSED to a veto,
    so the failure is a target foreclosed on a token the reader has never seen.
    """
    recognized = SKILLS_SIDE_OBLIGATIONS["_RECOGNIZED_GATING_VERDICTS['dependency']"]
    assert recognized == indication_only_verdicts, (
        f"declared skills-side recognition {sorted(recognized)} != minted tokens "
        f"{sorted(indication_only_verdicts)}. An unrecognized dependency verdict is forced to a VETO "
        f"by tp_gates, so an omission here foreclosed a target."
    )
    for name, tokens in SKILLS_SIDE_OBLIGATIONS.items():
        assert tokens, f"obligation {name!r} declares no tokens"
        assert tokens <= indication_only_verdicts, (
            f"obligation {name!r} names tokens this repo does not mint: {sorted(tokens - indication_only_verdicts)}"
        )


# ---------------------------------------------------------------------------
# (4) The Stage-5 blocker found while building this parity
# ---------------------------------------------------------------------------


def test_resolver_has_no_paralog_twin_for_the_indication_killer(resolver, indication_rule_ids):
    """KNOWN-GAP ANCHOR. Asserts the gap's exact shape so it cannot be silently satisfied or forgotten.

    MEASURED: #812 added compound rungs pairing `not-dependent-in-indication-killer` with
    partner-conditional and chemical-genetic positives (priorities 6-8), so those rescues outrank the
    bare indication killer at 9. It added no such twin for
    `strong-paralog-buffering-degrader-preferred`, whose pooled compound rung sits at 19 — and 9
    outranks 19. So at Stage 5 a paralog-buffered target measured non-dependent in its own indication
    resolves `not_dependent_in_indication` where it resolves `non_dependent_paralog_buffered` today.
    Blast radius on the calibration set: WWTR1/MESO, MARK2/PAAD, MARK3/PAAD — 3 of the 8 live
    `must_not_veto` controls, MARK2/3 being ADVANCED programs.

    veto_suppressors A4i already stops the VETO. What remains is the LABEL, and
    `expected_verdict_not_in` is asserted against the RESOLVER verdict, so the calibration suite goes
    red at Stage 5 until the twin lands.

    THIS TEST PASSES WHILE THE GAP EXISTS, following the repo's `known_gap_expected_fail` idiom. When
    someone adds the twin it FAILS, and the message says what to do: delete this test and refresh the
    three snapshots. It fails equally if the gap deepens (the pooled rung losing its compound form),
    because either direction invalidates the reasoning above.
    """
    paralog_rule = "strong-paralog-buffering-degrader-preferred"
    killer = "not-dependent-in-indication-killer"

    by_priority = {r["priority"]: r for r in resolver["resolve"]}
    indication_killer_priority = next(p for p, r in by_priority.items() if _rung_rule_ids(r) == {killer})

    pooled_paralog = [
        r for r in resolver["resolve"] if paralog_rule in _rung_rule_ids(r) and len(_rung_rule_ids(r)) > 1
    ]
    assert pooled_paralog, (
        "the pooled paralog rescue is no longer a COMPOUND rung — the asymmetry this test documents "
        "rests on it, so re-derive before editing"
    )

    indication_paralog = [
        r for r in resolver["resolve"] if paralog_rule in _rung_rule_ids(r) and killer in _rung_rule_ids(r)
    ]
    assert not indication_paralog, (
        f"GOOD NEWS, ACTION REQUIRED: a paralog twin for the indication killer now exists at "
        f"priority {[r['priority'] for r in indication_paralog]}. (1) Confirm it outranks "
        f"{indication_killer_priority} (the bare killer). (2) Re-capture "
        f"wwtr1_meso / mark2_paad / mark3_paad snapshots. (3) Reconsider veto_suppressors A4i, whose "
        f"asymmetry was justified by this gap. (4) Delete this test — it has done its job."
    )

    # The gap is only a problem because of the ORDERING; assert that rather than trusting the numbers
    # quoted in the docstring, which would rot after any renumber.
    assert all(r["priority"] > indication_killer_priority for r in pooled_paralog), (
        "the pooled paralog rescue now OUTRANKS the indication killer, which would mean the gap "
        "closed by renumbering rather than by adding a twin — re-derive the blast radius"
    )
