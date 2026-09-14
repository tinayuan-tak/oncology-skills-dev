#!/usr/bin/env bash
# preland.sh — run the CI-required PYTEST gate locally before landing. Mirrors
# .github/workflows/skills-validate.yml (the `pytest` job). Terse per-step PASS/FAIL;
# nonzero exit on any BLOCKING failure.
#
# ⚠️  THIS MIRRORS ONE OF THE TWO REQUIRED CHECKS. Branch protection on v2-architecture requires
#     `pytest` AND `ruff`; nothing below runs ruff, so "ALL GATES PASS" here does NOT mean the PR
#     will go green. Run the ruff gate yourself (ruff 0.16.6 is the CI pin, already on the PATH
#     exported below):
#       ruff format --check .        # tree-wide — identical to CI
#       git diff --name-only --diff-filter=ACMR origin/v2-architecture...HEAD -- '*.py' \
#         | xargs -r ruff check      # diff-aware — CI lints only the PR's changed .py files
#     Deliberately NOT folded into the gates below: CI's `ruff check` is diff-aware against the
#     PR base, while this script runs from the home checkout with no PR context, so a tree-wide
#     `ruff check .` would be STRICTER than CI and red on the grandfathered legacy backlog.
#     If you RECORD the format result anywhere, echo the base SHA beside it
#     (`git rev-parse --short origin/v2-architecture`): the "N files already formatted" count is a
#     function of the BASE plus whatever .py files your branch ADDS (--diff-filter=ACMR includes A),
#     so a bare count cannot be reconciled against a later run and reads as if the tree moved.
#
# RUN THIS FROM THE HOME CHECKOUT (~/rnd-computational-biology-oncology-claude-oncology-skills), NOT a /tmp worktree:
#   pixi's editable sibling deps (analysis-methods, target-contracts, data-catalog/libs/target_id_resolver)
#   resolve only in the home checkout, and `pixi run` in a /tmp worktree deep-copies a multi-GB env -> ENOSPC.
#   To gate worktree code, run from the home checkout against the worktree paths, e.g.
#     pixi run python -m pytest /tmp/wt/<branch>/skills/<skill>/tests/ -q
#
# Mirrors ALL FIVE of the `pytest` job's blocking suite steps, in CI order:
#   1. _skills_common shared harness      (BLOCKING; includes the rehomed live-reader + figure engine)
#   2. target-profile suite               (BLOCKING)
#   3. shared cross-skill invariant guards (skills/tests/, --import-mode=importlib)  (BLOCKING)
#   4. eval/ harness suite                (BLOCKING; loop-health, disposition + discordance ledgers,
#      per-axis backtest, literature harvest). ADDED HERE 2026-09-14: CI has run this step since
#      2026-09-12 and this script never transcribed it, so the old header count of FOUR was a fossil
#      of pre-2026-09-12 CI. eval/ is NOT under skills/, so step 5's `skills/*/tests` glob cannot
#      reach it either — the identical green-by-absence that CI added the step to fix. The guard that
#      keeps CI's list from rotting (skills/tests/test_ci_covers_all_test_files.py) parses the
#      WORKFLOW and is scoped to it, so it is blind to this local mirror falling behind. When CI
#      gains a suite step, add it here too — nothing enforces that.
#   5. remaining per-skill suites loop (skills/*/tests, --import-mode=importlib, blocking-by-default
#      with an empty denylist, each in its OWN pytest process for run.py import isolation)
set -uo pipefail
export PATH="$HOME/.pixi/bin:$HOME/.local/bin:$PATH"
cd "$(cd "$(dirname "$0")/.." && pwd)" || exit 2
fail=0
run() { local label="$1"; shift; local out
  if out=$("$@" 2>&1); then echo "PASS  $label"
  else echo "FAIL  $label"; echo "$out" | tail -n 30 | sed 's/^/      /'; fail=1; fi; }

# --- blocking gates (transcribed from skills-validate.yml, in CI order) ---
run "_skills_common"           pixi run pytest skills/_skills_common/tests/ -q
run "target-profile"           pixi run pytest skills/target-profile/tests/ -q
run "skills/tests guards"      pixi run pytest skills/tests/ -q --import-mode=importlib
run "eval/ harness suite"      pixi run pytest eval/ -q --import-mode=importlib

# --- remaining per-skill suites (CI: blocking-by-default loop with an empty NON_BLOCKING_SKILLS denylist) ---
# Each skill runs in its OWN pytest process (--import-mode=importlib) so `import run` binds to the
# right skill's scripts/run.py instead of whichever loaded first (sys.modules cache order-dependence).
# Keep this list in sync with the workflow's denylist (currently none).
NON_BLOCKING_SKILLS=(
  # (none — add a skill here only with a WHY when it is knowingly red for a reason outside a PR's control)
)
is_nonblocking() { local s="$1" n; for n in "${NON_BLOCKING_SKILLS[@]}"; do [ "$s" = "$n" ] && return 0; done; return 1; }
for d in skills/*/tests; do
  skill=$(basename "$(dirname "$d")")
  case "$skill" in _skills_common|target-profile) continue ;; esac   # own blocking steps above
  ls "$d"/test_*.py >/dev/null 2>&1 || continue
  if out=$(pixi run pytest "$d" -q --import-mode=importlib 2>&1); then
    echo "PASS  $skill"
  elif is_nonblocking "$skill"; then
    echo "WARN  $skill (non-blocking / denylisted)"
  else
    echo "FAIL  $skill"; echo "$out" | tail -n 30 | sed 's/^/      /'; fail=1
  fi
done

[ $fail -eq 0 ] && echo "ALL GATES PASS" || echo "GATES FAILED"
exit $fail
