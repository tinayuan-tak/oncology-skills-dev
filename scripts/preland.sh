#!/usr/bin/env bash
# preland.sh — run the CI-required gates locally before landing. Mirrors .github/workflows/skills-validate.yml
# (the `pytest` job, which is the REQUIRED status check on v2-architecture). Terse per-step PASS/FAIL;
# nonzero exit on any BLOCKING failure.
#
# RUN THIS FROM THE HOME CHECKOUT (~/rnd-computational-biology-oncology-claude-oncology-skills), NOT a /tmp worktree:
#   pixi's editable sibling deps (analysis-methods, target-contracts, data-catalog/libs/target_id_resolver)
#   resolve only in the home checkout, and `pixi run` in a /tmp worktree deep-copies a multi-GB env -> ENOSPC.
#   To gate worktree code, run from the home checkout against the worktree paths, e.g.
#     pixi run python -m pytest /tmp/wt/<branch>/skills/<skill>/tests/ -q
#
# Mirrors the five CI steps, in order:
#   1. compose-dashboard suite            (BLOCKING)
#   2. _skills_common shared harness      (BLOCKING)
#   3. target-profile suite               (BLOCKING)
#   4. shared cross-skill invariant guards (skills/tests/, --import-mode=importlib)  (BLOCKING)
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
run "compose-dashboard"        pixi run pytest skills/compose-dashboard/tests/ -q
run "_skills_common"           pixi run pytest skills/_skills_common/tests/ -q
run "target-profile"           pixi run pytest skills/target-profile/tests/ -q
run "skills/tests guards"      pixi run pytest skills/tests/ -q --import-mode=importlib

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
  case "$skill" in compose-dashboard|_skills_common|target-profile) continue ;; esac   # own blocking steps above
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
