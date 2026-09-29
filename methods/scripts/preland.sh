#!/usr/bin/env bash
# preland.sh — run the methods-validate gates locally before landing. Mirrors .github/workflows/methods-validate.yml.
# RUN FROM THE HOME CHECKOUT (~/rnd-computational-biology-oncology-analysis-methods), NOT a /tmp worktree
# (`pixi run` in a /tmp worktree deep-copies a multi-GB env -> ENOSPC).
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
# --- gates (transcribed from methods-validate.yml) ---
# --import-mode=importlib is REQUIRED: several method test files share a basename and collide under the default import mode.
run "methods+tests" pixi run pytest methods/ tests/ -q --import-mode=importlib -n 8
[ $fail -eq 0 ] && echo "ALL GATES PASS" || echo "GATES FAILED"
exit $fail
