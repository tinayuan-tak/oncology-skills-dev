"""Skip-budget ratchet — the enforcer, its baseline, and its CI wiring (skills#2127).

``SKIP != PASS``, and under ``-q`` a skip is invisible. ~45 contract-driven guards in this
repo (including the #1644 fleet vocab-exhaustiveness ratchet and the
``skills/conftest.py`` hierarchy-connectivity ratchet) ``skipif`` target-contracts is
unresolvable; they run on CI ONLY because the shard job exports ``TARGET_CONTRACTS_ROOT``
to the in-repo ``contracts/``. If that export regresses, or ``contracts/cards`` moves, the
whole family goes silently SKIPPED and CI stays green. The counter-measures are:

  * ``-rsfE`` on every skills shard pytest invocation (skip made VISIBLE, and the FAILED/ERROR
    short-summary preserved — a bare ``-rs`` REPLACES pytest's default ``-r`` value ``fE``
    instead of adding to it, per skills#2236) — and, MEASURED while doing it, removal of the
    redundant CLI ``-q``: pyproject's ``addopts`` already pass ``-q -rsfE``, so the shards were
    running at ``-qq``, which prints skip REASONS but suppresses the ``N passed, M skipped in
    Xs`` COUNT line — no totals, no ratchet;
  * ``scripts/check_skip_budget.py`` + ``.github/skills-skip-budget.json``: a per-leg
    CEILING on skips, so an *inflation* goes RED.

This file is the guard for that machinery — the enforcer is bash-driven in CI, so its
logic is proved here in-process rather than by trusting the workflow:

  1. the checker's own CARDINALITY FLOOR (a leg reporting no outcomes FAILS — otherwise a
     budget guard that measures nothing passes green, and a silent un-cover reads as
     "0 skips, fine");
  2. the checker discriminates over-budget from within-budget, and gives an unknown leg a
     ceiling of 0 rather than an unbounded pass;
  3. the committed baseline is well-formed and free of stale keys;
  4. the workflow actually WIRES it: every skills shard invocation carries ``-rsfE``,
     redirects to a log, and hands that log to the checker. A workflow file is not a
     running workflow, but a workflow that no longer calls the checker at all is a
     regression this catches at the file level.

RATCHET DIRECTION — the budget is a CEILING, so it only ever gets LOWERED. The numbers
live in ``.github/skills-skip-budget.json``. **skills#2090 (un-skip the contracts
validators) removes skips and MUST ratchet those numbers down in the same PR**; slack left
behind becomes a permanent ceiling that hides the next regression beneath it.
"""

from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "skills-validate.yml"
BASELINE = REPO_ROOT / ".github" / "skills-skip-budget.json"
CHECKER = REPO_ROOT / "scripts" / "check_skip_budget.py"

# literal (non-glob) leg labels the shard step runs; the rest of the legs are the per-skill
# suite directory names, enumerated from the tree below.
_LITERAL_LEGS = {"_skills_common", "skills-guards", "eval", "target-profile"}


def _load_checker():
    spec = importlib.util.spec_from_file_location("check_skip_budget", CHECKER)
    assert spec and spec.loader, f"cannot load {CHECKER}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def checker():
    return _load_checker()


def _shard_run_block() -> str:
    """The bash body of the ``run shard`` step — the single place the legs are invoked."""
    doc = yaml.safe_load(WORKFLOW.read_text())
    steps = doc["jobs"]["pytest-shards"]["steps"]
    blocks = [s["run"] for s in steps if str(s.get("name", "")).startswith("run shard")]
    assert len(blocks) == 1, f"expected exactly one 'run shard' step, found {len(blocks)}"
    return blocks[0]


def _shard_pytest_invocations(block: str) -> tuple[list[str], list[str]]:
    """``(literal invocations, run_suite call sites)``.

    The per-skill loop passes its pytest args THROUGH ``run_suite "<label>" "<args>"``, so the
    flags for those legs live at the call site, not on the ``pixi run pytest $2`` line."""
    literals, call_sites = [], []
    for raw in block.splitlines():
        ln = raw.strip()
        if re.search(r"\bpixi run pytest\b", ln) and not re.search(r"pixi run pytest\s+\$", ln):
            literals.append(ln)
        if re.match(r"run_suite\s+\"", ln):
            call_sites.append(ln)
    return literals, call_sites


def _valid_leg_labels() -> set[str]:
    skills = {p.parent.name for p in REPO_ROOT.glob("skills/*/tests") if p.is_dir()}
    return _LITERAL_LEGS | skills


# ---------------------------------------------------------------- the enforcer's teeth


def test_checker_cardinality_floor_rejects_a_leg_that_measured_nothing(checker):
    """ANTI-VACUITY, first: 'no tests ran' and a truncated log must both be RED. A budget
    guard that treats an un-run leg as 0 skips is the very green-blindness it exists to stop."""
    for label, log in (
        ("no-tests", "no tests ran in 0.01s\n"),
        ("truncated", "collecting ...\n"),  # crashed before any summary line
        ("deselected-only", "5 deselected in 0.10s\n"),  # deselected is not an outcome
    ):
        rc, msg = checker.check(label, log, {label: 99})
        assert rc == 1, f"{label}: a leg with no outcomes passed the budget — the guard is vacuous ({msg})"


def test_checker_discriminates_over_and_under_budget(checker):
    over_rc, over_msg = checker.check("skills-guards", "100 passed, 12 skipped in 60.0s\n", {"skills-guards": 11})
    under_rc, _ = checker.check("skills-guards", "100 passed, 11 skipped in 60.0s\n", {"skills-guards": 11})
    exact_rc, _ = checker.check("skills-guards", "100 passed, 0 skipped in 60.0s\n", {"skills-guards": 11})
    assert over_rc == 1, "12 skipped under a budget of 11 passed — the ceiling is not enforced"
    assert "12 skipped" in over_msg and "budget 11" in over_msg
    assert under_rc == 0, "11 skipped under a budget of 11 failed — the ceiling is off by one"
    assert exact_rc == 0, "a leg with zero skips failed — the guard is not a ceiling"


def test_checker_gives_an_unrecorded_leg_a_ceiling_of_zero_not_a_free_pass(checker):
    """A new leg (or a renamed skill) must not escape the budget by being absent from the
    baseline — omission means ceiling 0, so its first skip reds with instructions."""
    rc_skips, msg = checker.check("brand-new-skill", "9 passed, 1 skipped in 3.0s\n", {})
    rc_clean, _ = checker.check("brand-new-skill", "9 passed in 3.0s\n", {})
    assert rc_skips == 1, "an unrecorded leg with skips passed — labels escape the budget by omission"
    assert "NO entry" in msg or "no entry" in msg.lower()
    assert rc_clean == 0, "an unrecorded leg with zero skips failed — that would red every new suite"


def test_checker_reads_the_last_summary_line(checker):
    """xdist/pixi logs contain earlier noise; the authoritative numbers are the final summary."""
    log = "1 passed, 99 skipped in 1.0s\n=== rerun ===\n50 passed, 2 skipped in 30.0s\n"
    rc, msg = checker.check("eval", log, {"eval": 2})
    assert rc == 0, f"stale earlier summary line won over the final one: {msg}"


def test_checker_parses_real_shard_log_shapes(checker):
    """Verbatim tails of two REAL runs of skills/tests/test_fleet_subgroup_vocab_exhaustiveness.py
    under `pixi run pytest <file> -rs -n auto` — the second with TARGET_CONTRACTS_ROOT pointed at a
    nonexistent path, i.e. the exact regression this ratchet exists to catch (the contract-driven
    guard family going dark). Raw tool output, not hand-derived numbers."""
    real_ok = "bringing up nodes...\n\n...............                          [100%]\n15 passed in 2.95s\n"
    real_dark = (
        "bringing up nodes...\n\nsssssssssssssss                          [100%]\n"
        "=========================== short test summary info ============================\n"
        "SKIPPED [12] skills/tests/test_fleet_subgroup_vocab_exhaustiveness.py:569: "
        "target-contracts not checked out; the fleet vocab-exhaustiveness guard is contract-driven\n"
        "15 skipped in 2.63s\n"
    )
    budgets = {"skills-guards": 0}
    assert checker.check("skills-guards", real_ok, budgets)[0] == 0
    rc, msg = checker.check("skills-guards", real_dark, budgets)
    assert rc == 1, f"a whole contract-driven guard file going SKIPPED passed the budget: {msg}"
    assert "15 skipped" in msg


# ---------------------------------------------------- the #2305 live-data-skip exclusion

# One real ``SKIPPED`` line of the benign, VARIABLE live-data class the exclusion targets.
_LIVEDATA_SKIP = (
    "SKIPPED [1] skills/tests/test_graduated_skills_run_wired.py:287: "
    "{skill}: all cards _missing on KRAS/COADREAD (data availability, not a decision-layer bug)."
)
# Verbatim tail of the RED merge_group run (36747421555) that ejected PR #2304 fleet-wide: the
# same tree's PR run reported 17 skips, this one 18, the sole difference one extra live-data skip.
_RED_RUN_TAIL = (
    "=========================== short test summary info ============================\n"
    + "".join(
        _LIVEDATA_SKIP.format(skill=s) + "\n"
        for s in (
            "tumor-presence",
            "tractability-small-molecule",
            "mechanism-and-pharmacology",
            "differentiation-landscape",
            "cis-feature-coherence",
        )
    )
    + "587 passed, 18 skipped in 146.63s\n"
)


def test_checker_excludes_the_2305_variable_livedata_skip_from_the_budget(checker):
    """skills#2305: the fleet-wide flake. 18 skips against a budget of 17 reds ONLY because the
    variable live-data count from test_graduated_skills_run_wired.py tipped it — those skips are
    -rsfE-visible data-availability skips, not a dark guard, so they are subtracted before the
    ceiling. TOOTH: strip the subtraction and this 18-skip real run reds against 17 again."""
    budgets = {"skills-guards": 17}
    rc, msg = checker.check("skills-guards", _RED_RUN_TAIL, budgets)
    assert rc == 0, f"the #2305 flake still reds — the live-data exclusion is not applied: {msg}"
    assert "13 skipped" in msg and "5 excluded" in msg and "18 raw" in msg, (
        f"exclusion not reported transparently: {msg}"
    )
    # CONTROL — the exact same summary count with NONE of those excludable lines present must
    # still red at 18 > 17, proving the green above is the exclusion at work, not a loosened ceiling.
    bare = "587 passed, 18 skipped in 146.63s\n"
    assert checker.check("skills-guards", bare, budgets)[0] == 1, (
        "18 raw skips with nothing excludable passed budget 17 — the ceiling itself loosened"
    )


def test_exclusion_is_pinned_to_both_the_file_and_the_reason(checker):
    """The match must be NARROW: a differently-worded skip in the SAME file, and a
    data-availability-worded skip in a DIFFERENT file, must BOTH still count — otherwise a real
    guard going dark could hide behind the exclusion. One skip over a zero budget isolates each."""
    budgets = {"skills-guards": 0}
    # same file, DIFFERENT reason (surfaceome has no SKILL.md) — not the live-data class
    same_file_other_reason = (
        "SKIPPED [1] skills/tests/test_graduated_skills_run_wired.py:114: surfaceome-cohort-ranking has no SKILL.md\n"
        "1 passed, 1 skipped in 2.0s\n"
    )
    rc, msg = checker.check("skills-guards", same_file_other_reason, budgets)
    assert rc == 1, f"a non-live-data skip from the same file was wrongly excluded: {msg}"
    # data-availability WORDING but a DIFFERENT file — a hypothetical guard borrowing the phrase
    other_file_livedata_words = (
        "SKIPPED [1] skills/tests/test_some_other_guard.py:99: foo: all cards _missing on KRAS/COADREAD (data availability, not a decision-layer bug).\n"
        "1 passed, 1 skipped in 2.0s\n"
    )
    rc2, msg2 = checker.check("skills-guards", other_file_livedata_words, budgets)
    assert rc2 == 1, f"a data-availability skip from a different file was wrongly excluded: {msg2}"


def test_exclusion_never_drives_the_count_negative_or_masks_a_real_overage(checker):
    """A malformed log that lists MORE excludable lines than the summary counted must clamp to a
    budgeted 0, never a negative that could paper over a genuinely over-budget leg. Here 6
    excludable lines but a summary of only 2 skipped: budgeted = max(2-6,0) = 0 <= budget, and the
    raw 2 is still reported."""
    budgets = {"skills-guards": 0}
    many_lines = (
        "".join(_LIVEDATA_SKIP.format(skill=f"s{i}") + "\n" for i in range(6)) + "10 passed, 2 skipped in 3.0s\n"
    )
    rc, msg = checker.check("skills-guards", many_lines, budgets)
    assert rc == 0 and "0 skipped" in msg and "2 raw" in msg, f"clamp/report wrong on an over-matched log: {msg}"


# ---------------------------------------------------------------- the committed baseline


def test_baseline_is_wellformed_and_has_no_stale_keys(checker):
    budgets = checker.load_baseline(BASELINE)
    valid = _valid_leg_labels()
    assert valid, "enumerated no valid leg labels — the enumeration is broken, not the baseline"
    stale = sorted(k for k in budgets if k not in valid)
    assert not stale, (
        "these skip-budget keys match no CI leg, so they protect nothing (a typo'd key silently "
        f"leaves the real leg on a ceiling of 0): {stale}. Valid labels are the literal legs "
        f"{sorted(_LITERAL_LEGS)} plus the skills/*/tests directory names."
    )


def test_baseline_documents_the_ratchet_direction_and_2090():
    """The number must not become a permanent ceiling: whoever lands #2090 has to find the
    instruction to lower it, in the file that holds the number."""
    text = BASELINE.read_text()
    assert "2090" in text, "the baseline must name skills#2090 as an obligation to ratchet DOWN"
    assert "RATCHET" in text.upper()


# ---------------------------------------------------------------- the CI wiring


def test_every_skills_shard_invocation_is_skip_visible_and_budgeted():
    block = _shard_run_block()
    literals, call_sites = _shard_pytest_invocations(block)
    assert len(literals) >= 4, (
        f"parsed only {len(literals)} literal pytest invocations out of the shard step — the "
        "parser regressed, so the assertions below prove nothing"
    )
    assert call_sites, "parsed no run_suite call sites — the per-skill loop parser regressed"
    # skills#2236: the standalone token must be `-rsfE`, not bare `-rs`. pytest's `-r` is
    # action="store" with default "fE"; a bare `-rs` REPLACES that default rather than adding to
    # it, which drops the FAILED/ERROR short-summary lines entirely (measured: a run reported
    # "1 failed, 4817 passed" with the failing node id nowhere in the log). Anchored so `-rsfE`
    # passes but a regression back to bare `-rs` still fails this test.
    missing_rs = [ln for ln in literals + call_sites if not re.search(r"(?<!\S)-rsfE(?!\S)", ln)]
    assert not missing_rs, (
        "these skills shard invocations run without -rsfE, so either their skips or their "
        f"FAILED/ERROR short-summary lines are invisible in the log (SKIP != PASS): {missing_rs}"
    )
    # MEASURED coupling: pyproject's addopts already supply `-q -rs`, so a SECOND `-q` on the
    # command line takes verbosity to -2, which suppresses pytest's `N passed, M skipped in Xs`
    # line — skip reasons still print, but the COUNTS vanish and the budget has nothing to parse
    # (and no cardinality instrument). Re-adding `-q` here silently defeats the ratchet.
    double_quiet = [ln for ln in literals + call_sites if re.search(r"(?<!\S)-q(?!\S)", ln)]
    assert not double_quiet, (
        "these shard invocations pass -q on top of pyproject's addopts `-q`, i.e. -qq, which "
        "suppresses the skip/pass COUNT summary line the skip budget parses: " + str(double_quiet)
    )
    addopts = (REPO_ROOT / "pyproject.toml").read_text()
    assert re.search(r"addopts\s*=\s*\"[^\"]*-q[^\"]*\"", addopts), (
        "pyproject addopts no longer supplies -q, so the shard legs now run verbose — re-decide "
        "the verbosity story in the workflow (see the -q/-rs comment in skills-validate.yml)"
    )
    assert re.search(r"addopts\s*=\s*\"[^\"]*-rs[^\"]*\"", addopts), (
        "pyproject addopts no longer supplies -rs; the shard legs pass it explicitly, but every "
        "OTHER suite invocation in the repo just went skip-blind"
    )
    unlogged = [ln for ln in literals if ">" not in ln]
    assert not unlogged, (
        "these invocations do not redirect their output to a log, so the skip-budget checker has "
        f"nothing to parse for them: {unlogged}"
    )
    assert "| tee" not in block, (
        "a pytest invocation piped to tee reports tee's exit code — a RED suite would read as green"
    )
    assert block.count("check_budget") >= 5, (
        "the shard step no longer calls check_budget for its legs (expected the helper plus one "
        "call per literal leg and one inside run_suite) — the skip budget is not enforced"
    )
    tail = block.split("run_suite() {", 1)
    assert len(tail) == 2, "run_suite() not found in the shard step"
    body = re.split(r"\n\s*\}\s*\n", tail[1], maxsplit=1)[0]
    assert "check_budget" in body, (
        "run_suite() (which runs every per-skill suite) does not call check_budget — the per-skill legs are unbudgeted"
    )


def test_checker_and_baseline_are_committed_where_ci_expects_them():
    assert CHECKER.is_file(), f"{CHECKER} missing — the shard step calls it by path"
    assert BASELINE.is_file(), f"{BASELINE} missing — the checker reads it by default"
    block = _shard_run_block()
    assert "scripts/check_skip_budget.py" in block, "the shard step no longer invokes the checker"
    assert json.loads(BASELINE.read_text())["budgets"] is not None
