#!/usr/bin/env bash
# preland.sh — run the methods-pytest gate locally before landing. Mirrors the `methods-pytest`
# job in .github/workflows/skills-validate.yml (the former methods-validate.yml, folded into the
# monorepo's single required `pytest` fan-in at the SK#2063 consolidation).
# RUN FROM THE HOME CHECKOUT (~/rnd-computational-biology-oncology-claude-oncology-skills), NOT a
# /tmp worktree (`pixi run` in a /tmp worktree deep-copies a multi-GB env -> ENOSPC).
# Invoked by the root dispatcher (scripts/preland.sh methods / all) — this package's unique gate
# folds to the single `run` line below; the host-protection knobs are unified at the root, but
# this script still runs standalone (its own PATH/env exports are its half of that contract).
set -uo pipefail
export PATH="$HOME/.pixi/bin:$HOME/.local/bin:$PATH"
# Mirror CI: no AWS creds -> live-S3 tests self-skip via conftest (SKILLS_SKIP_LIVE_DATA).
export SKILLS_SKIP_LIVE_DATA="1"
# Shared 32-core no-swap host: NEVER `-n auto` here (CI runners are dedicated; this host is not).
# Fixed -n 8 mirrors CI's parallelization without risking an OOM/thrash on a shared box. If any AM
# reader uses a process fork-pool internally, a fork-pool x 8 pytest workers can starve the host —
# default it to a thread pool defensively (harmless if unused).
export SKILLS_READ_POOL="${SKILLS_READ_POOL:-thread}"
cd "$(cd "$(dirname "$0")/.." && pwd)" || exit 2
fail=0
run() { local label="$1"; shift; local out
  if out=$("$@" 2>&1); then echo "PASS  $label"
  else echo "FAIL  $label"; echo "$out" | tail -n 30 | sed 's/^/      /'; fail=1; fi; }
# --- the one gate (transcribed from the methods-pytest job) ---
# --import-mode=importlib is REQUIRED: several method test files share a basename and collide under the default import mode.
# `pixi` resolves the ONE workspace manifest at the repo root (SK#2145 deleted methods/pixi.toml);
# `pixi run` preserves cwd, so pytest's rootdir is still methods/ and its pyproject addopts apply.
# NO `-q` here — that addopts already carries it, and `-qq` suppresses pytest's final
# `N passed, M skipped` line entirely (see the note on the methods-pytest job in skills-validate.yml).
# `-rsfE`, not `-rs`: pytest's default -r value is `fE`, and passing `-rs` REPLACES it, so the
# summary would name every SKIP and no FAILURE. This `run` helper only echoes the last 30 lines on a
# red, which is precisely where the `FAILED <nodeid>` list needs to be.
run "methods+tests" pixi run pytest methods/ tests/ -rsfE --import-mode=importlib -n 8
[ $fail -eq 0 ] && echo "ALL GATES PASS" || echo "GATES FAILED"
exit $fail
