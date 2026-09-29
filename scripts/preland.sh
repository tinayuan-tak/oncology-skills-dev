#!/usr/bin/env bash
# preland.sh — ONE gate dispatcher for the monorepo. Usage:
#   scripts/preland.sh [skills|methods|contracts|all]     (default: all)
#
# Gate audit 2026-09-29 (SK#2094): before this, gating a cross-package change meant an agent
# knowing ~9 invocation forms documented in 6 places (this file's own header, methods/scripts/
# preland.sh, contracts/scripts/preland.sh, and SKILLS_DEV_WORKFLOW.md, each with its own PATH/
# pool-knob boilerplate). All three prelands now live in one tree (SK#2063 consolidation) so
# there is no reason to memorize more than one command:
#   scripts/preland.sh            # = all: skills + methods + contracts + ruff
#   scripts/preland.sh skills      # this repo's skills/ suites only
#   scripts/preland.sh methods     # methods/scripts/preland.sh only
#   scripts/preland.sh contracts   # contracts/scripts/preland.sh only (validator/self-check pool)
#
# `all` chains the three package prelands (skills inline below, since skills/ lives at the repo
# root rather than under its own scripts/preland.sh; methods and contracts by exec'ing their own
# scripts) plus ONE tree-wide ruff pass at the end. `all` is deliberately the DEFAULT — the one
# invocation an agent should memorize for a change that could touch more than one package (a
# card + rule + method + skill change is landed as ONE atomic PR per SKILLS_DEV_WORKFLOW.md, so
# the default gate should cover all three, not just the package under the cursor).
#
# RUN THIS FROM THE HOME CHECKOUT (~/rnd-computational-biology-oncology-claude-oncology-skills),
# NOT a /tmp worktree: pixi's editable sibling deps (methods, contracts, data-catalog/libs/
# target_id_resolver) resolve only in the home checkout, and `pixi run` in a /tmp worktree
# deep-copies a multi-GB env -> ENOSPC. To gate worktree code, run from the home checkout against
# the worktree paths, e.g. `pixi run python -m pytest /tmp/wt/<branch>/skills/<skill>/tests/ -q`.
#
# Mirrors the required `pytest` fan-in in .github/workflows/skills-validate.yml: the `skills`
# subcommand mirrors pytest-shards (all 4 big suites + the per-skill loop); `methods` mirrors the
# methods-pytest job; `contracts` mirrors contracts-static's validator/self-check pool (the unique
# coverage plain pytest never runs — contracts-pytest's own whole-package suite is CI-only, since
# it is fully redundant with contracts/tests/ and adds nothing a local run needs); `all` additionally
# runs the tree-wide `ruff.yml` gate once, centrally, instead of leaving it undocumented per package.
#
# ── HOST-PROTECTION KNOBS (UNIFIED HERE 2026-09-29 — previously declared independently, with
#    independent defaults, in this file, methods/scripts/preland.sh, and contracts/scripts/
#    preland.sh; a reader had to diff three files to know the actual defaults in force). Exported
#    here so every child preland inherits them (each still honors an explicit caller override via
#    its own `${VAR:-default}`, and each still declares its OWN default so it is not silently
#    broken when run standalone without this wrapper). This is a shared, no-swap 32-core host —
#    these caps are load-bearing, not cosmetic. ──────────────────────────────────────────────────
#   PRELAND_JOBS       xdist workers for the 4 big skills suites                default 8
#   PRELAND_LOOP_POOL  concurrent per-skill suites in the skills trailing loop  default 4
#   PRELAND_POOL       concurrent contracts validator/self-check steps         default 8
#   SKILLS_READ_POOL   card/method reader concurrency model (thread, not fork)  default thread
set -uo pipefail
export PATH="$HOME/.pixi/bin:$HOME/.local/bin:$PATH"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" || exit 2

export PRELAND_JOBS="${PRELAND_JOBS:-8}"
export PRELAND_LOOP_POOL="${PRELAND_LOOP_POOL:-4}"
export PRELAND_POOL="${PRELAND_POOL:-8}"
export SKILLS_READ_POOL="${SKILLS_READ_POOL:-thread}"
xdist=()
if [ "$PRELAND_JOBS" != "0" ]; then xdist=(-n "$PRELAND_JOBS"); fi

fail=0
run() { local label="$1"; shift; local out
  if out=$("$@" 2>&1); then echo "PASS  $label"
  else echo "FAIL  $label"; echo "$out" | tail -n 30 | sed 's/^/      /'; fail=1; fi; }

# ── skills/ (this repo's own suites — transcribed from the pytest-shards job, in CI order) ──────
# Mirrors ALL of the pytest-shards job's blocking suite steps:
#   1. _skills_common shared harness      (BLOCKING; includes the rehomed live-reader + figure engine)
#   2. target-profile suite               (BLOCKING)
#   3. shared cross-skill invariant guards (skills/tests/, --import-mode=importlib)  (BLOCKING)
#   4. eval/ harness suite                (BLOCKING; loop-health, disposition + discordance ledgers,
#      per-axis backtest, literature harvest)
#   5. remaining per-skill suites loop (skills/*/tests, --import-mode=importlib, blocking-by-default
#      with an empty denylist, each in its OWN pytest process for run.py import isolation)
run_skills() {
  local sfail=0
  run "_skills_common"           pixi run pytest skills/_skills_common/tests/ -q "${xdist[@]}"
  [ $fail -ne 0 ] && sfail=1; fail=0
  run "target-profile"           pixi run pytest skills/target-profile/tests/ -q "${xdist[@]}"
  [ $fail -ne 0 ] && sfail=1; fail=0
  run "skills/tests guards"      pixi run pytest skills/tests/ -q --import-mode=importlib "${xdist[@]}"
  [ $fail -ne 0 ] && sfail=1; fail=0
  run "eval/ harness suite"      pixi run pytest eval/ -q --import-mode=importlib "${xdist[@]}"
  [ $fail -ne 0 ] && sfail=1; fail=0

  # Keep this denylist in sync with the workflow's NON_BLOCKING_SKILLS (currently none).
  local NON_BLOCKING_SKILLS=(
    # (none — add a skill here only with a WHY when it is knowingly red for a reason outside a PR's control)
  )
  is_nonblocking() { local s="$1" n; for n in "${NON_BLOCKING_SKILLS[@]}"; do [ "$s" = "$n" ] && return 0; done; return 1; }

  local loop_dirs=()
  local d skill
  for d in skills/*/tests; do
    skill=$(basename "$(dirname "$d")")
    case "$skill" in _skills_common|target-profile) continue ;; esac   # own blocking steps above
    ls "$d"/test_*.py >/dev/null 2>&1 || continue
    loop_dirs+=("$d")
  done

  # PRELAND_LOOP_POOL-wide concurrency; each background job writes "<rc>\n<output>" to its own
  # file so the main shell reports in a STABLE (sorted) order and sets `sfail` itself (a subshell's
  # assignment would not survive).
  local resdir; resdir=$(mktemp -d)
  run_one() {
    local dd="$1" ss="$2" out rc
    if out=$(pixi run pytest "$dd" -q --import-mode=importlib 2>&1); then rc=0; else rc=$?; fi
    { printf '%s\n' "$rc"; printf '%s\n' "$out"; } > "$resdir/$ss"
  }
  for d in "${loop_dirs[@]}"; do
    skill=$(basename "$(dirname "$d")")
    run_one "$d" "$skill" &
    while [ "$(jobs -r -p | wc -l)" -ge "$PRELAND_LOOP_POOL" ]; do wait -n; done
  done
  wait

  for skill in $(ls "$resdir" | sort); do
    local rc; rc=$(head -n1 "$resdir/$skill")
    if [ "$rc" = "0" ]; then
      echo "PASS  $skill"
    elif is_nonblocking "$skill"; then
      echo "WARN  $skill (non-blocking / denylisted)"
    else
      echo "FAIL  $skill"; tail -n +2 "$resdir/$skill" | tail -n 30 | sed 's/^/      /'; sfail=1
    fi
  done
  rm -rf "$resdir"
  return $sfail
}

run_methods() {
  echo "── methods ──"
  bash "$ROOT/methods/scripts/preland.sh"
}

run_contracts() {
  echo "── contracts ──"
  bash "$ROOT/contracts/scripts/preland.sh"
}

# ── tree-wide ruff (.github/workflows/ruff.yml) — the one gate `all` adds beyond the three
#    package prelands. `ruff format --check` is WHOLE-TREE (the tree is fully formatted); `ruff
#    check` is DIFF-AWARE in CI, so it is run here only on the .py files this branch changed vs
#    origin/main, matching the grandfathered lint backlog. ruff is pinned in the workflow: a
#    different local version formats differently, so the version is asserted rather than assumed.
#    An ABSENT/mismatched ruff is a loud WARN, never a silent skip.
run_ruff() {
  local rfail=0
  local RUFF_PIN=0.16.6
  if ! command -v ruff >/dev/null 2>&1; then
    echo "WARN  ruff NOT INSTALLED — the ruff job was NOT checked locally; install with 'pipx install ruff==$RUFF_PIN'"
    return 0
  fi
  if [ "$(ruff --version | awk '{print $2}')" != "$RUFF_PIN" ]; then
    echo "WARN  ruff $(ruff --version | awk '{print $2}') != CI pin $RUFF_PIN — formatting may differ from the ruff job; NOT checked"
    return 0
  fi
  run "ruff format --check (tree)" ruff format --check .
  [ $fail -ne 0 ] && rfail=1; fail=0
  local base="${PRELAND_BASE:-origin/main}"
  if git rev-parse --verify -q "$base" >/dev/null; then
    local changed
    changed=$(git diff --name-only --diff-filter=ACMR "$base"...HEAD -- '*.py' || true)
    if [ -n "$changed" ]; then
      echo "      (ruff check scope vs $base: $(echo "$changed" | tr '\n' ' '))"
      # shellcheck disable=SC2086
      run "ruff check (changed .py)" ruff check $changed
      [ $fail -ne 0 ] && rfail=1; fail=0
    else
      echo "PASS  ruff check (changed .py) — this branch changes no .py vs $base"
    fi
  else
    echo "WARN  ruff check SKIPPED — '$base' not fetched; set PRELAND_BASE or run 'git fetch origin main'"
  fi
  return $rfail
}

MODE="${1:-all}"
case "$MODE" in
  skills)
    run_skills; fail=$?
    ;;
  methods)
    run_methods; fail=$?
    ;;
  contracts)
    run_contracts; fail=$?
    ;;
  all)
    fail=0
    run_skills;    r=$?; [ "$r" -ne 0 ] && fail=1
    run_methods;   r=$?; [ "$r" -ne 0 ] && fail=1
    run_contracts; r=$?; [ "$r" -ne 0 ] && fail=1
    run_ruff;      r=$?; [ "$r" -ne 0 ] && fail=1
    ;;
  -h|--help)
    echo "usage: $0 [skills|methods|contracts|all]   (default: all)"
    exit 0
    ;;
  *)
    echo "usage: $0 [skills|methods|contracts|all]   (default: all)" >&2
    exit 2
    ;;
esac

[ "$fail" -eq 0 ] && echo "ALL GATES PASS" || echo "GATES FAILED"
exit "$fail"
