"""Roster reconciliation — every vocabulary validator WIRED into contracts/scripts/preland.sh
carries a gate-argv **A test** AND a **B test**. (#2247, correction 8 of arc #2210.)

## Why this file exists

The five vocabulary validators (`validate_property_catalog`, `validate_concordance_enum`,
`validate_comparability_state`, `validate_expression_property_enum`, `validate_claim_axis`) are each
wired into `preland.sh` and each carries a gate-argv **A** test (invoke the validator with the literal
relative argv the gate runs) and a **B** test (read `preland.sh` and pin the wired flags to what A
hardcodes). But until this file landed, **nothing asserted that the pair EXISTS for every wired
validator** — the completeness property was maintained by hand, one validator at a time. That is
exactly how 0a shipped without an A test and went unnoticed for two sessions (#2244), and how
`validate_expression_property_enum` shipped without an additivity wiring (#2249). A sixth vocabulary
validator would recreate the same gap.

This is the SINGLE roster parser the issue asked for — folded onto one place rather than a sixth
per-validator copy of the `test_the_two_gate_argv_tests_match_what_preland_sh_ACTUALLY_RUNS` clause.
It reconciles, in BOTH directions, the roster wired in `preland.sh` against the validators that carry
an A+B pair:

  * **wired-but-untested** — a validator on a `preland.sh` vocab `run` line with no A+B pair
    (the 0a shape). A sixth validator wired without a pair reds here instead of shipping silently.
  * **tested-but-unwired** — an A+B pair naming a validator `preland.sh` no longer runs (a stale test
    that keeps a dropped validator looking covered — the guard-that-deletes-its-own-subject shape).

## What is NOT here (scope)

The issue's companion reconciliation — pinning these validators as *explicit named steps in the
`contracts-static` CI job* and reconciling that against this roster — is a `.github/workflows/` edit,
which is its own PR and permission-gated (arc rule; #2237/#2258). It is intentionally absent; this
file is the always-deliverable contracts-side half. When the workflow steps land, extend
`_validators_named_as_ci_steps()` over the SAME `preland_vocab_roster()` here rather than writing a
new parser.

## A test vs in-process call (arc trap §2.6)

The A set is deliberately restricted to tests that shell the validator out as a **subprocess** with
`cwd=CONTRACTS` and assert a clean exit. An in-process `_main(argv)` / `check_*()` call proves the
argv parses and the clauses run, but not the `__main__` entrypoint / process boundary the gate
actually crosses — and per trap §2.6 "a test that calls the checker function in-process is NOT an A
test." Every test added here was proven able to fail by planting the mutant it defends against (a
deleted `run` line, a deleted A or B test, an unwired validator) — no inertness proof, per SK#2091.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

CONTRACTS = Path(__file__).resolve().parents[2]
PRELAND = CONTRACTS / "scripts" / "preland.sh"
VALIDATOR_TESTS_DIR = Path(__file__).resolve().parent

# A floor, not a ceiling: the vocabulary validators governed by arc #2210 as of 2026-09-30
# (0a `f4a01c96` / 0b `c118fd28` / 0c `7449c66f` / #2233 `d177769a` / 0d `5d7980cd`). A sixth is
# expected and welcome — but it must arrive WIRED into preland.sh AND carrying an A+B pair, which is
# what the equality clause below enforces. Named here only so a parser that silently drops one of the
# known five reds with its name rather than passing vacuously (set() == set()).
_KNOWN_VOCAB_VALIDATORS = frozenset(
    {
        "validate_property_catalog",
        "validate_concordance_enum",
        "validate_comparability_state",
        "validate_expression_property_enum",
        "validate_claim_axis",
    }
)

_INVOKE = re.compile(r"validators/(validate_\w+)\.py")
# A "vocabulary" validator is one whose preland invocation governs a vocabulary artifact: a
# `*.enum.yaml` file or the `property_catalog/` directory. This EXCLUDES the legacy validator pool
# (validate_cards, validate_verdict_tokens' `nomination_verdict_gate.yaml`, …) without a
# hand-maintained denylist, and AUTO-INCLUDES a sixth validator the day it governs a new enum — even
# if it is (like expression_property before #2249) wired with only a shape line and no additivity.
_VOCAB_ARTIFACT = re.compile(r"vocabularies/(?:property_catalog\b|[\w.]+\.enum\.yaml)")


def _joined_preland() -> str:
    # Join backslash continuations FIRST (mirrors the per-validator ACTUALLY_RUNS tests), or this
    # reconciliation reds on a reflow of preland.sh rather than on a real drift.
    return PRELAND.read_text().replace("\\\n", " ")


def preland_vocab_roster() -> set[str]:
    """Every validator stem invoked on a non-comment preland.sh line whose argv references a
    vocabulary artifact. Deduped by stem, so a validator wired on both a shape line and an additivity
    line is one roster entry."""
    roster: set[str] = set()
    for raw in _joined_preland().splitlines():
        line = raw.strip()
        if line.startswith("#") or "validators/validate" not in line:
            continue
        if not _VOCAB_ARTIFACT.search(line):
            continue
        roster.update(_INVOKE.findall(line))
    return roster


def _test_functions():
    """Yield the source segment of every top-level `test_*` function under
    contracts/tests/validators/. AST-based (fail-loud on a syntax error), so a function's body is
    scoped correctly rather than by brittle line ranges."""
    for f in sorted(VALIDATOR_TESTS_DIR.glob("*.py")):
        if f.name == Path(__file__).name:
            continue
        src = f.read_text()
        tree = ast.parse(src)
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                yield f.name, node.name, (ast.get_source_segment(src, node) or "")


def validators_with_A_test() -> set[str]:
    """Validators carrying a genuine gate-argv **A** test: a test that shells the validator out as a
    SUBPROCESS with the literal relative argv from cwd contracts/ and asserts a clean exit
    (`subprocess` + `cwd=CONTRACTS` + `returncode == 0`). Per arc trap §2.6 an in-process
    `_main(argv)` / `check_*()` call is NOT an A test — it proves the clause logic but not the argv
    the gate actually executes."""
    found: set[str] = set()
    for _fname, _name, seg in _test_functions():
        if "subprocess" not in seg or "cwd=CONTRACTS" not in seg or "returncode == 0" not in seg:
            continue
        found.update(_INVOKE.findall(seg))
    return found


def validators_with_B_test() -> set[str]:
    """Validators carrying a gate-argv **B** test: a test that READS the preland.sh file and asserts
    against the wired invocation for that validator, so the A test cannot stay green against an argv
    the gate no longer runs (arc trap §2.6). Requiring an actual `read_text()` of preland.sh — not
    merely the string "preland.sh" — keeps a mention in another test's docstring from being counted
    as a B test."""
    found: set[str] = set()
    for _fname, _name, seg in _test_functions():
        if "preland.sh" not in seg or "read_text" not in seg or "assert" not in seg:
            continue
        found.update(m.group(1) for m in re.finditer(r"(validate_\w+)\.py", seg))
    return found


# --------------------------------------------------------------------------- anti-vacuity floors


def test_preland_vocab_roster_is_populated():
    """If the roster parser silently returned an empty (or shrunken) set — a reflow of preland.sh, a
    regex drift — the equality below could pass vacuously. Pin the known five as a SUBSET and floor
    the count, so a parser that drops one reds here with its name while a sixth is free to grow it."""
    roster = preland_vocab_roster()
    missing = _KNOWN_VOCAB_VALIDATORS - roster
    assert not missing, (
        f"preland.sh vocab-roster parser lost {sorted(missing)}; found {sorted(roster)}. "
        "The parser or preland.sh drifted — fix before trusting the reconciliation below."
    )
    assert len(roster) >= len(_KNOWN_VOCAB_VALIDATORS), (
        f"roster shrank below the known {len(_KNOWN_VOCAB_VALIDATORS)}: {sorted(roster)}"
    )


def test_A_and_B_test_scanners_are_populated():
    """Companion anti-vacuity floor for the two test-scanning parsers: a broken AST scan returning
    empty sets would make the equality fail LOUD (good) but let a future subset check pass vacuously.
    Pin the known five as a subset of each set independently."""
    A = validators_with_A_test()
    B = validators_with_B_test()
    assert _KNOWN_VOCAB_VALIDATORS <= A, (
        f"missing a genuine SUBPROCESS A test (arc §2.6) for {sorted(_KNOWN_VOCAB_VALIDATORS - A)}"
    )
    assert _KNOWN_VOCAB_VALIDATORS <= B, f"missing a preland-pinning B test for {sorted(_KNOWN_VOCAB_VALIDATORS - B)}"


# --------------------------------------------------------------------------- THE reconciliation


def test_every_wired_vocab_validator_has_an_A_and_B_test_pair():
    """Correction 8: fold BOTH directions onto one parsed roster so the next vocabulary validator
    cannot be added silently.

      * wired-but-untested (`roster - paired`) — a validator on a preland.sh vocab `run` line with no
        A+B pair. This is the 0a shape: it shipped wired but with no gate-argv A test and nothing
        asserted the pair existed.
      * tested-but-unwired (`paired - roster`) — an A+B pair naming a validator preland.sh no longer
        runs; a stale test that would keep a dropped validator looking covered.
    """
    roster = preland_vocab_roster()
    paired = validators_with_A_test() & validators_with_B_test()
    assert paired == roster, (
        "validator gate-argv coverage is out of sync with preland.sh:\n"
        f"  wired into preland.sh but missing an A+B pair: {sorted(roster - paired)}\n"
        f"  carry an A+B pair but preland.sh no longer runs them: {sorted(paired - roster)}\n"
        "Add the missing subprocess A test + preland-pinning B test, or wire/unwire the validator."
    )
