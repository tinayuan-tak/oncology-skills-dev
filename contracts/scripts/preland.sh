#!/usr/bin/env bash
# preland.sh — run the contracts-static validator/self-check pool locally before landing.
# Mirrors the `contracts-static` job in .github/workflows/skills-validate.yml (the former
# contracts-validate.yml's static leg, folded into the monorepo's single required `pytest`
# fan-in at the SK#2063 consolidation — contracts-static AND contracts-pytest now BOTH feed
# that required check, so a schema violation here turns the required check RED, not just
# trunk). Bare python (no pixi in this repo).
#
# SCOPE (narrowed 2026-09-29, SK#2094): this script carries ONLY the validator/self-check
# pool — direct `python validators/validate_*.py` / `build_*.py --self-check` invocations
# that plain pytest never runs. The single-file `python -m pytest tests/...` steps this
# script used to hand-list (one per named test file) are GONE: `contracts-pytest`'s
# whole-package suite (`pytest -q -n auto --splits 4`, no path filter) already collects
# every file under contracts/tests/ — including every file those hand-listed steps named —
# and, since the consolidation, that job is itself part of the required `pytest` check. The
# hand-listing predates the merge, when contracts-validate.yml was NOT required and this
# script was the only local net; that gap is closed, so the duplication is pure debt now.
# Run this before landing any cards/ | interpretation-rules/ | resolvers/ | vocabularies/
# change (the validator pool is the coverage plain pytest still can't reach); land-pr's CI
# fan-in is the authoritative gate for everything else in contracts/tests/.
# Prefer the root dispatcher (scripts/preland.sh contracts) so the host-protection knobs
# stay in one place; this script also runs standalone.
set -uo pipefail
cd "$(cd "$(dirname "$0")/.." && pwd)" || exit 2
fail=0

# ── PARALLELISM (2026-09-25) ──────────────────────────────────────────────────────────────────
# The gate steps below are independent and READ-ONLY (validators re-derive + compare committed
# artifacts under --self-check; pytest steps use tmp_path fixtures and read-only session loaders),
# so they were fully serial for no reason on a 32-core host — dominated by the two whole-corpus /
# whole-sibling recomputes (test_wiring_ledger + the emission/wiring self-checks, ~70s each) plus
# ~30 interpreter+import cold starts. They now run in a CONCURRENCY POOL: `run` ENQUEUES a step to
# the pool, `report_pool` drains it and prints PASS/FAIL in the SAME launch order as before (so the
# transcript still reads in contracts-validate.yml order). Wall-clock collapses from the sum of the
# steps to roughly the single tall pole. Modest default for a shared, no-swap host where peers may
# run concurrently; override per-run. PRELAND_POOL=1 restores fully-serial behaviour for debugging.
#   PRELAND_POOL   concurrent gate steps                                           default 8
# NB: the pytest steps are deliberately NOT given `-n` (xdist) — each names one small file, which
# LOSES to worker-spawn overhead; the parallelism that pays here is ACROSS steps (this pool), and
# the whole-repo safety net in CI is the single place a within-suite `-n auto` earns its keep.
PRELAND_POOL="${PRELAND_POOL:-8}"
resdir=$(mktemp -d)
trap 'rm -rf "$resdir"' EXIT
_seq=0
# `run` enqueues one gate step. Each background job writes "<rc>" and its captured output to files
# keyed by a zero-padded launch ordinal, so report_pool can print in launch order and set `fail` in
# the MAIN shell (a subshell's `fail=1` would not survive). Output is captured, never streamed, so
# concurrent steps never interleave.
run() { local label="$1"; shift
  local i; i=$(printf '%03d' "$_seq"); _seq=$((_seq + 1))
  printf '%s' "$label" > "$resdir/$i.label"
  ( local out rc
    if out=$("$@" 2>&1); then rc=0; else rc=$?; fi
    # Trailing newline is load-bearing: report_pool tails this file, and an output without one
    # would glue the NEXT step's PASS/FAIL line onto it (looks like a dropped step).
    printf '%s\n' "$out" > "$resdir/$i.out"
    printf '%s' "$rc" > "$resdir/$i.rc" ) &
  while [ "$(jobs -r -p | wc -l)" -ge "$PRELAND_POOL" ]; do wait -n; done
}
# Iterate the LABEL files (written synchronously in the main shell, so one exists for every enqueued
# step) rather than the .rc files: a step whose background job vanished without writing a result must
# read as a LOUD FAIL, never silently drop out of both the PASS and FAIL lists.
report_pool() { wait
  local lf i label rc
  for lf in $(ls "$resdir"/*.label 2>/dev/null | sort); do
    i="${lf%.label}"; label=$(cat "$lf")
    if [ ! -f "$i.rc" ]; then
      echo "FAIL  $label (no result written — pool job vanished)"; fail=1; continue
    fi
    rc=$(cat "$i.rc")
    if [ "$rc" = "0" ]; then echo "PASS  $label"
    else echo "FAIL  $label"; tail -n 30 "$i.out" | sed 's/^/      /'; fail=1; fi
  done
}
# --- gates (transcribed in order from contracts-validate.yml; enqueued to the pool above) ---
run "validate_cards"                     python validators/validate_cards.py cards/
run "validate_evidence_graph"            python validators/validate_evidence_graph.py --self-check
run "validate_questions"                 python validators/validate_questions.py
run "validate_measurement_types"         python validators/validate_measurement_types.py
run "validate_interpretation_rules"      python validators/validate_interpretation_rules.py --rules interpretation-rules/ --cards cards/
run "validate_resolvers"                 python validators/validate_resolvers.py --resolvers resolvers/ --rules interpretation-rules/
run "validate_verdict_tokens"            python validators/validate_verdict_tokens.py --gate vocabularies/nomination_verdict_gate.yaml --resolvers resolvers/
run "validate_certainty_disjointness"    python validators/validate_certainty_disjointness.py
run "validate_card_resolver_consumption" python validators/validate_card_resolver_consumption.py
run "validate_claim_record"              python validators/validate_claim_record.py --schema schemas/claim_record.schema.json --examples docs/design/examples/ --resolvers resolvers/
run "rule_role_partition --self-check"   python validators/build_rule_role_partition.py --self-check
run "validate_fold_migration"            python validators/validate_fold_migration.py --resolvers resolvers/
run "build_eval_ledger --self-check"     python validators/build_eval_ledger.py --self-check
run "build_emission_ledger --self-check" python validators/build_emission_ledger.py --self-check
run "build_wiring_reconciliation --self-check" python validators/build_wiring_reconciliation.py --self-check
run "build_wiring_ledger --self-check"   python validators/build_wiring_ledger.py --self-check
run "living_doc --self-check"            python validators/architecture_dashboard/living/build_living_doc.py --self-check
run "validate_property_catalog"          python validators/validate_property_catalog.py --catalog vocabularies/property_catalog --cards cards/

# Drain the pool and print every gate's PASS/FAIL in launch (CI) order before the ruff/advisory
# steps below, which stay SYNCHRONOUS (fast, and the ruff block has its own version-gate control
# flow). Restore the plain serial `run` for them so that block is unchanged from its original form.
report_pool
run() { local label="$1"; shift; local out
  if out=$("$@" 2>&1); then echo "PASS  $label"
  else echo "FAIL  $label"; echo "$out" | tail -n 30 | sed 's/^/      /'; fail=1; fi; }

# --- property-catalog ADDITIVITY (vocabularies/property_catalog/) ---
# The shape/referential clauses ran in the pool above. Additivity needs a git ref to compare against,
# so it follows the ruff block's convention: resolve the PR BASE, and if it is not fetched emit a loud
# WARN rather than a silent skip — a gate that did not run must not read as a gate that passed. The
# validator itself goes RED on an unresolvable ref when the flag IS passed, so the guard here is only
# about whether to pass it at all.
pc_base="${PRELAND_BASE:-origin/main}"
if git rev-parse --verify -q "$pc_base" >/dev/null; then
  run "validate_property_catalog --additive-against $pc_base" \
      python validators/validate_property_catalog.py --catalog vocabularies/property_catalog \
             --cards cards/ --additive-against "$pc_base"
else
  echo "WARN  property-catalog additivity SKIPPED — '$pc_base' not fetched; set PRELAND_BASE or run 'git fetch origin main'"
fi

# --- ruff (.github/workflows/ruff.yml) ---
# 2026-09-13: this script mirrored contracts-validate.yml and NOTHING ELSE, so "ALL GATES PASS" was
# reported on a branch whose ruff job then failed on the PR — format-only, but a red check either way.
# `ruff format --check` is WHOLE-TREE (the tree is fully formatted); `ruff check` is DIFF-AWARE in CI,
# so it is run here only on the .py files this branch changed, matching the grandfathered lint backlog.
# ruff is pinned in the workflow: a different local version formats differently, so the version is
# asserted rather than assumed. An ABSENT/mismatched ruff is a loud WARN, never a silent skip — a gate
# that did not run must not read as a gate that passed.
RUFF_PIN=0.16.6
if ! command -v ruff >/dev/null 2>&1; then
  echo "WARN  ruff NOT INSTALLED — the ruff job was NOT checked locally; install with 'pipx install ruff==$RUFF_PIN'"
elif [ "$(ruff --version | awk '{print $2}')" != "$RUFF_PIN" ]; then
  echo "WARN  ruff $(ruff --version | awk '{print $2}') != CI pin $RUFF_PIN — formatting may differ from the ruff job; NOT checked"
else
  run "ruff format --check (tree)"       ruff format --check .
  # The base is the PR BASE (trunk), NOT @{upstream}: @{upstream} is the branch's own remote-tracking
  # ref, so diffing against it yields ZERO changed files on any pushed branch — a vacuous pass.
  base="${PRELAND_BASE:-origin/main}"
  if git rev-parse --verify -q "$base" >/dev/null; then
    changed=$(git diff --name-only --diff-filter=ACMR "$base"...HEAD -- '*.py' || true)
    if [ -n "$changed" ]; then
      echo "      (ruff check scope vs $base: $(echo "$changed" | tr '\n' ' '))"
      # shellcheck disable=SC2086
      run "ruff check (changed .py)"     ruff check $changed
    else
      echo "PASS  ruff check (changed .py) — this branch changes no .py vs $base"
    fi
  else
    echo "WARN  ruff check SKIPPED — '$base' not fetched; set PRELAND_BASE or run 'git fetch origin main'"
  fi
fi

# --- ADVISORY (non-fatal): cross-repo dashboard-feed drift. The framework-health-cross-repo CI job is
#     PARKED (its token PAT lacks skills + data-products access); this surfaces the same framework_health
#     --check locally. NON-FATAL because local sibling clones may lag origin. For the authoritative
#     both-guards gate run `make drift-check`; regen a stale feed with `make atlas` + the health build. ---
if out=$(python validators/framework_health/build_framework_health.py --check --json-only 2>&1); then
  echo "PASS  drift(framework_health) [advisory]"
else
  echo "WARN  drift(framework_health) [advisory] — committed health/ feed differs from local wiring; run 'make drift-check' + regenerate before landing feed-moving changes"
  echo "$out" | tail -n 5 | sed 's/^/      /'
fi
[ $fail -eq 0 ] && echo "ALL GATES PASS" || echo "GATES FAILED"
exit $fail
