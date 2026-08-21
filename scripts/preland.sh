#!/usr/bin/env bash
# preland.sh — run the methods-validate gates locally before landing. Mirrors .github/workflows/methods-validate.yml.
# RUN FROM THE HOME CHECKOUT (~/rnd-computational-biology-oncology-analysis-methods), NOT a /tmp worktree
# (`pixi run` in a /tmp worktree deep-copies a multi-GB env -> ENOSPC).
set -uo pipefail
export PATH="$HOME/.pixi/bin:$HOME/.local/bin:$PATH"
# Mirror CI: no AWS creds -> live-S3 tests self-skip via conftest (SKILLS_SKIP_LIVE_DATA).
export SKILLS_SKIP_LIVE_DATA="1"
cd "$(cd "$(dirname "$0")/.." && pwd)" || exit 2
fail=0
run() { local label="$1"; shift; local out
  if out=$("$@" 2>&1); then echo "PASS  $label"
  else echo "FAIL  $label"; echo "$out" | tail -n 30 | sed 's/^/      /'; fail=1; fi; }
# --- gates (transcribed from methods-validate.yml) ---
# --import-mode=importlib is REQUIRED: several method test files share a basename and collide under the default import mode.
run "methods+tests" pixi run pytest methods/ tests/ -q --import-mode=importlib
[ $fail -eq 0 ] && echo "ALL GATES PASS" || echo "GATES FAILED"
exit $fail
