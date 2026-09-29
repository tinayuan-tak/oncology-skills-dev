"""M5 rule-role partition — the verdict-inert rules as an EXPLICIT display channel.

Pins that the committed snapshot is a well-formed, non-overlapping partition of EVERY rule and matches
the live contracts. But the load-bearing half of this module is the set of checks BELOW that, because
of how the previous version of this file failed:

★★ THE OLD GUARD WAS GREEN ON A WRONG PARTITION, AND COULD NOT HAVE BEEN OTHERWISE. It asserted

        set(snapshot["gating"]) == brp._resolver_referenced_rule_ids()

    i.e. it compared the snapshot against the very extractor that built it. Any narrowing of that
    extractor narrowed both sides of the equation at once, so the test moved with the bug. It was a
    tautology wearing a contract's clothes. The extractor read `spec["resolve"]` and nothing else, and
    `post_resolver_clamp` — the only rung-bearing block outside `resolve` anywhere in resolvers/ — was
    invisible to it. All five selectivity KILL/liability arms plus the 3-rule clamp `upgrade`
    requirement were therefore filed `display`.

★★ AND `display` IS NOT A NEUTRAL LABEL. Per the generator's own docstring, the scorecard's I1
    (signal-sink coverage) and I3 (per-coordinate VOI) are measured ONLY against gating rules — so
    `display` REMOVES a rule from the safety scorecard. Mis-filing a KILL arm as `display` is a
    safety-adverse error, not a cosmetic one.

    The rules files show the mis-filing was DELIBERATE, which is the actually interesting part: two of
    the arms carry the comment "Applied by the skills-side clamp (_skills_common/selectivity_veto.py);
    no resolver rung (a conjunction the single-rung resolver cannot express) -> classified `display` in
    rule_role_partition." That reasoning is locally true and globally wrong: `display` was assigned to
    mean "no resolver rung EXECUTES this" while the scorecard reads it as "this cannot MOVE A VERDICT."
    One token, two meanings. `post_resolver_clamp` is a verdict-moving DECLARATION (direction:
    downgrade_only, precedence -> verdict:) regardless of which repo holds the executor.

So the tests here are built to fail the ways the old one could not: the keypath table's COVERAGE is
asserted against what the resolvers actually contain, the clamp ladder is pinned BY NAME, and every
check is mutation-proved non-vacuous — including `duplicate`, which finds nothing today.
"""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "validators"))
import build_rule_role_partition as brp  # noqa: E402

#: The five selectivity clamp arms and the three clamp-upgrade requirements — the rules the old guard
#: filed as verdict-inert. Pinned BY NAME, never by count: a count moves with a swap, and "8 rules are
#: gating" stays true if one KILL arm silently trades places with an unrelated rule.
CLAMP_PRECEDENCE_ARMS = {
    "tvn-stromal-confound-veto": "selective_but_stromal_confound",
    "tvn-no-therapeutic-window-veto": "selective_but_broadly_normal",
    "tvn-no-full-normal-window-veto": "selective_but_broadly_normal",
    "tvn-sc-normal-critical-organ-veto": "selective_with_normal_liability",
    "tvn-tphp-broad-abundant-normal-protein-veto": "selective_with_normal_liability",
}
CLAMP_UPGRADE_REQUIREMENTS = {
    "protein-strongly-up-supportive",
    "protein-modestly-up-neutral",
    "tumor-vs-normal-crossing-strong-supportive",
}


def _committed() -> dict:
    return yaml.safe_load((ROOT / "coverage" / "rule_role_partition.yaml").read_text())


@pytest.fixture
def snapshot_at(tmp_path, monkeypatch):
    """Point the generator at a REWRITTEN copy of the snapshot and return self_check's errors.

    Respells the whole document rather than appending to it: an appended duplicate key is kept as the
    LAST value by PyYAML on some shapes and silently dropped on others, so an append-style mutation can
    neutralise itself and report a false green.
    """

    def _run(mutate) -> list[str]:
        doc = copy.deepcopy(_committed())
        mutate(doc)
        p = tmp_path / "rule_role_partition.yaml"
        p.write_text(yaml.safe_dump(doc, sort_keys=False, width=100))
        monkeypatch.setattr(brp, "PARTITION_PATH", p)
        # Re-read through the generator's own loader, so the assertion is about what the CHECKER sees.
        assert set(yaml.safe_load(p.read_text())["gating"]) == set(doc["gating"]), "mutation did not land"
        ok, errs = brp.self_check()
        assert not ok, "mutated snapshot passed self_check — the mutation was inert"
        return errs

    return _run


# ── 1. the partition itself ───────────────────────────────────────────────────────────────────────
def test_committed_snapshot_matches_live_contracts():
    ok, errs = brp.self_check()
    assert ok, f"rule_role_partition.yaml drifted — regenerate: {errs}"


def test_partition_is_complete_and_disjoint():
    p = _committed()
    gating, display = set(p["gating"]), set(p["display"])
    assert gating.isdisjoint(display), "a rule cannot be both gating and display"
    all_rules = set(brp._rule_definitions())
    assert len(all_rules) > 400, f"only {len(all_rules)} rules discovered — the glob broke, not the repo"
    assert gating | display == all_rules, "partition must cover every defined rule"
    assert p["counts"] == {"total": len(all_rules), "gating": len(gating), "display": len(display)}


def test_display_channel_is_the_inert_majority():
    # sanity: the audit's finding — the majority of rules are annotation-only, not verdict-driving
    p = _committed()
    assert p["counts"]["display"] > p["counts"]["gating"]


# ── 2. the regression pin: the clamp ladder is verdict-moving ─────────────────────────────────────
def test_the_selectivity_clamp_ladder_is_gating():
    """★ THE PIN. Every arm of the selectivity KILL/liability ladder, and every rule its upgrade arm
    requires, must be `gating` — because each one changes the verdict the framework returns, and
    `display` would drop it out of the I1/I3 safety scorecard."""
    gating = set(_committed()["gating"])
    for rid in sorted(set(CLAMP_PRECEDENCE_ARMS) | CLAMP_UPGRADE_REQUIREMENTS):
        assert rid in gating, (
            f"{rid} is not gating — it is referenced by post_resolver_clamp, which REPLACES the "
            f"resolver verdict, so filing it as display hides it from the safety scorecard"
        )


def test_the_clamp_arms_still_mint_the_verdicts_this_test_pins():
    """The pin above names rules; this one proves those rules still carry the verdicts that make them
    worth pinning. Otherwise the ladder could be gutted verdict-side and the name-pin stays green."""
    spec = brp._resolver_docs()["selectivity.resolver.yaml"]
    arms = {a["when_fired"]: a["verdict"] for a in spec["post_resolver_clamp"]["precedence"]}
    assert arms == CLAMP_PRECEDENCE_ARMS, (
        "the clamp precedence ladder changed shape — reconcile this test with the resolver deliberately"
    )
    requires = spec["post_resolver_clamp"]["upgrade"]["requires"]
    assert {r for group in requires for r in group} == CLAMP_UPGRADE_REQUIREMENTS


def test_every_declared_keypath_matches_something_live():
    """A keypath in the table that matches nothing is dead text — it documents a mechanism that either
    never existed or has been renamed, and it would go on 'covering' the resolvers while reading zero."""
    live = {kp for spec in brp._resolver_docs().values() for kp, _ in brp._walk_scalars(spec)}
    for kp in sorted(brp.GATING_KEYPATHS | brp.ATTRIBUTION_KEYPATHS):
        assert kp in live, f"declared keypath {kp!r} matches nothing in resolvers/ — stale table entry"


# ── 3. the four checks, each green on the live repo ───────────────────────────────────────────────
def test_the_keypath_table_covers_every_rule_id_bearing_keypath():
    """★ THE ROOT-CAUSE CHECK: no resolver names rule_ids at a keypath the generator does not read."""
    assert brp.coverage_problems() == []


def test_no_dangling_gating_reference():
    assert brp.dangling_problems() == []


def test_no_duplicate_rule_definitions():
    assert brp.duplicate_problems() == []


def test_every_attribution_reference_is_also_gating():
    assert brp.attribution_problems() == []


# ── 4. ...and each one mutation-proved to be capable of failing ───────────────────────────────────
def test_coverage_check_catches_an_unclassified_rung_bearing_block(monkeypatch):
    """The exact bug, re-injected: a resolver grows a new block that keys on rules. The check must name
    the keypath rather than quietly leaving those rules in `display`."""
    victim = sorted(brp._rule_definitions())[0]
    monkeypatch.setattr(
        brp,
        "_resolver_docs",
        lambda: {"synthetic.resolver.yaml": {"pre_resolver_veto": {"arms": [{"when_fired": victim}]}}},
    )
    problems = brp.coverage_problems()
    assert problems, "an undeclared rule_id-bearing keypath was not reported"
    assert "pre_resolver_veto/arms/[]/when_fired" in problems[0]


def test_coverage_check_ignores_a_rule_id_mentioned_in_prose(monkeypatch):
    """The other direction — the check must not fire on a `reason:`/`note:` that merely CONTAINS a rule
    id. A substring match on prose is not a population, and the live clamp carries exactly such prose."""
    victim = sorted(brp._rule_definitions())[0]
    monkeypatch.setattr(
        brp,
        "_resolver_docs",
        lambda: {"synthetic.resolver.yaml": {"notes": [f"superseded by {victim} in v1.2.0"]}},
    )
    assert brp.coverage_problems() == []


def test_dangling_check_catches_a_reference_to_an_undefined_rule(monkeypatch):
    monkeypatch.setattr(
        brp,
        "_resolver_docs",
        lambda: {"synthetic.resolver.yaml": {"resolve": [{"when_fired": "no-such-rule-id"}]}},
    )
    problems = brp.dangling_problems()
    assert problems and "no-such-rule-id" in problems[0]


def test_duplicate_check_catches_a_shadowed_definition(monkeypatch):
    """Non-vacuity proof for a check that finds NOTHING on the live repo. Without this the duplicate
    guard could be broken from the day it was written and nobody would know."""
    monkeypatch.setattr(brp, "_rule_definitions", lambda: {"some-rule": ["a.rules.yaml", "b.rules.yaml"]})
    problems = brp.duplicate_problems()
    assert problems and "some-rule" in problems[0] and "shadows" in problems[0]


def test_attribution_check_catches_a_driving_rule_nothing_gates_on(monkeypatch):
    victim = sorted(brp._rule_definitions())[0]
    monkeypatch.setattr(
        brp,
        "_resolver_docs",
        lambda: {"synthetic.resolver.yaml": {"resolve": [{"driving_rule": victim}]}},
    )
    problems = brp.attribution_problems()
    assert problems and victim in problems[0]


# ── 5. the snapshot-side checks, on a rewritten snapshot ──────────────────────────────────────────
def test_misdeclaring_a_clamp_arm_as_display_is_reported_safety_adverse(snapshot_at):
    """Re-injects the shipped bug into the snapshot and requires the report to say which direction it
    points. `display` when the truth is `gating` is the dangerous direction and must read as such."""
    arm = "tvn-stromal-confound-veto"

    def mutate(doc):
        doc["gating"] = [r for r in doc["gating"] if r != arm]
        doc["display"] = sorted(doc["display"] + [arm])
        doc["counts"] = {"total": doc["counts"]["total"], "gating": len(doc["gating"]), "display": len(doc["display"])}

    errs = snapshot_at(mutate)
    # Scan every error, not errs[0]: self_check reports structural problems before snapshot ones, so
    # keying on the first message makes this assert about ORDERING instead of about the finding.
    hit = [e for e in errs if arm in e and "misdeclared" in e]
    assert hit, f"the misdeclared clamp arm was not reported: {errs}"
    assert "SAFETY-ADVERSE" in hit[0], f"reported without direction: {hit[0]}"


def test_a_stale_snapshot_entry_is_an_error(snapshot_at):
    def mutate(doc):
        doc["display"] = sorted(doc["display"] + ["retired-rule-that-no-longer-exists"])

    errs = snapshot_at(mutate)
    assert any("stale display entry" in e and "retired-rule" in e for e in errs), errs


def test_a_gating_rule_filed_as_display_is_caught_in_the_other_direction(snapshot_at):
    """The benign direction still has to be reported — a rule claimed gating that nothing gates on
    inflates the scorecard's denominator with a rule that cannot move anything."""
    victim = sorted(_committed()["display"])[0]

    def mutate(doc):
        doc["display"] = [r for r in doc["display"] if r != victim]
        doc["gating"] = sorted(doc["gating"] + [victim])

    errs = snapshot_at(mutate)
    assert any(victim in e and "no verdict-moving keypath" in e for e in errs), errs


# ── 6. regenerate is fail-closed ──────────────────────────────────────────────────────────────────
def test_regenerate_refuses_when_the_contracts_have_a_structural_problem(monkeypatch, tmp_path, capsys):
    """A regenerate that quietly writes a NARROWED partition is the whole failure this module guards.
    `main()` must refuse and leave the committed snapshot untouched."""
    victim = sorted(brp._rule_definitions())[0]
    monkeypatch.setattr(
        brp,
        "_resolver_docs",
        lambda: {"synthetic.resolver.yaml": {"pre_resolver_veto": {"arms": [{"when_fired": victim}]}}},
    )
    target = tmp_path / "would_be_overwritten.yaml"
    monkeypatch.setattr(brp, "PARTITION_PATH", target)
    assert brp.main([]) == 1, "regenerate succeeded despite an unclassified rung-bearing keypath"
    assert not target.exists(), "regenerate wrote a partition it had just been told was incomplete"
    assert "REFUSING" in capsys.readouterr().out
