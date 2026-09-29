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
# (4) The Stage-5 blocker found while building this parity — CLOSED by resolver v1.6.0
# ---------------------------------------------------------------------------
#
# This section previously held `test_resolver_has_no_paralog_twin_for_the_indication_killer`, a
# known-gap anchor that PASSED while the gap existed and failed with a 4-step instruction when it
# closed. The twin landed (resolver v1.6.0, rung 9), the anchor fired as designed, and per its own
# step (4) it is deleted rather than inverted: an anchor kept past its subject becomes a test whose
# name asserts the opposite of the truth.
#
# Its three surviving obligations, discharged:
#   (1) the twin outranks the bare killer  -> asserted below, and structurally in
#       test_indication_dependency_class_partition.py, which now also asserts the GENERAL invariant
#       (every pooled veto escape has an indication twin) that the gap slipped through.
#   (2) re-capture wwtr1_meso / mark2_paad / mark3_paad -> NOT a v1.6.0 obligation. The rung is inert
#       by REACHABILITY: no producer populates `indication_dependency_class`, so the killer cannot
#       fire, so the rung cannot match and no snapshot verdict moves. It is a STAGE-5 obligation,
#       recorded in the calibration set's v1.5.0 changelog.
#   (3) reconsider A4i -> KEPT, with a corrected rationale. See the test below.


def test_the_indication_paralog_twin_exists_and_outranks_the_bare_killer(resolver):
    """Closure guard for the v1.5.0 regression: the paralog rescue must outrank the indication veto.

    Stated as an ORDERING over derived priorities, never as literals, so a renumber cannot rot it —
    the same discipline the anchor it replaces used."""
    paralog_rule = "strong-paralog-buffering-degrader-preferred"
    killer = "not-dependent-in-indication-killer"

    twin = [r for r in resolver["resolve"] if _rung_rule_ids(r) == {killer, paralog_rule}]
    assert len(twin) == 1, f"expected exactly one indication paralog twin, found {len(twin)}"
    assert twin[0]["verdict"] == "non_dependent_paralog_buffered", (
        f"the twin must emit the same relabel as its pooled counterpart, not {twin[0]['verdict']!r}: "
        f"a different verdict would change the GATE ROLE of the escape, and this one is gate-INERT"
    )
    assert twin[0].get("driving_rule") == paralog_rule, "the twin must anchor provenance to the buffer rule"

    bare_killer = [r for r in resolver["resolve"] if _rung_rule_ids(r) == {killer}]
    assert len(bare_killer) == 1
    assert twin[0]["priority"] < bare_killer[0]["priority"], (
        f"the paralog twin @{twin[0]['priority']} must outrank the bare indication killer "
        f"@{bare_killer[0]['priority']}, or the veto wins and the twin is dead code"
    )


def test_a4i_is_kept_as_defence_in_depth_not_as_redundancy(gate, resolver):
    """A4i (gate-side suppressor) and resolver rung 9 (resolver-side relabel) now BOTH cover the
    paralog case. That looks redundant and is not — deleting either one opens a real window.

    The two repos are PIN-DECOUPLED: claude-oncology-skills pins a target-contracts SHA. So there is a
    window in which skills runs an OLD resolver (no rung 9, indication killer wins) against a NEW gate
    vocabulary (A4i present) — during which A4i is the ONLY thing standing between the three ADVANCED
    controls and a false veto. The reverse window exists too: a new resolver with an old gate vocab
    relabels the verdict before any gate reads it, so the rung covers A4i's absence.

    A4i's ORIGINAL rationale said the asymmetry was justified by the absence of this rung. That
    justification is now false, and a stale justification is what makes a correct guard look deletable.
    This test pins the CORRECTED reason in place: the rationale must ground A4i in the pin lag, not in
    a resolver gap, and must not claim the gap still exists."""
    a4i = [
        s
        for s in gate["veto_suppressors"]
        if s.get("suppresses", {}).get("verdict") == "not_dependent_in_indication"
        and any(t.get("field") == "paralog_buffering_class" for t in s.get("when_present", []))
    ]
    assert len(a4i) == 1, f"expected exactly one paralog suppressor for the indication veto, found {len(a4i)}"
    rationale = a4i[0]["rationale"]

    # The resolver rung it used to be justified by the ABSENCE of must now exist...
    assert any(
        _rung_rule_ids(r) == {"not-dependent-in-indication-killer", "strong-paralog-buffering-degrader-preferred"}
        for r in resolver["resolve"]
    ), "this test's premise is that the rung exists; if it does not, A4i's original rationale applies again"

    # ...so the rationale must no longer claim there is no such rung.
    stale = "there is no such rung for the indication killer"
    assert stale not in rationale, (
        f"A4i's rationale still asserts {stale!r}, which resolver v1.6.0 made FALSE. Ground it in the "
        f"pin lag between the two repos instead — that is what still makes A4i load-bearing."
    )
    # Two INDEPENDENT content requirements, not a byte-pin of the current prose: the pin-lag argument
    # is unstatable without naming (a) the decoupling and (b) WHICH repo's pin creates the lag. A
    # reworded-but-correct paragraph keeps both; a paragraph that drops the argument loses both.
    #
    # Deliberately NOT `"pin" in rationale.lower()`, which is what this assert said first and which a
    # mutant SURVIVED: the rationale also ends with "Pinned by <this test>", so a bare "pin" substring
    # was satisfied by a sentence about test coverage while the actual argument had been deleted. A
    # common word is not a claim.
    low = rationale.lower()
    assert "pin-decoupled" in low or "pin decoupled" in low, (
        "A4i's rationale must name the DECOUPLING explicitly — it is the whole reason two layers "
        "cover one hazard, and without it the overlap reads as duplication to be cleaned up"
    )
    assert "claude-oncology-skills" in low, (
        "A4i's rationale must name the repo whose SHA pin creates the lag window. 'The repos are "
        "decoupled' without a direction does not tell the reader which side runs stale code, which "
        "is the fact that makes THIS layer (the gate one) the load-bearing half during the window."
    )
