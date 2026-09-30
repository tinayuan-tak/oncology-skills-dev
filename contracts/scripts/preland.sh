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
run "validate_concordance_enum"          python validators/validate_concordance_enum.py --enum vocabularies/concordance_class.enum.yaml --families vocabularies/property_catalog/integrated_families.yaml
run "validate_comparability_state"       python validators/validate_comparability_state.py --enum vocabularies/comparability_state.enum.yaml --families vocabularies/property_catalog/integrated_families.yaml --concordance-enum vocabularies/concordance_class.enum.yaml

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

# --- concordance-enum TOKEN additivity (vocabularies/concordance_class.enum.yaml) ---
# Same shape and the same reason as the block above: the shape clauses ran in the pool, additivity
# needs a ref. concordance_class tokens are PUBLISHED wire names, string-matched by consumers that
# fail OPEN when a match stops happening, so a quiet removal is the failure this clause exists for.
if git rev-parse --verify -q "$pc_base" >/dev/null; then
  run "validate_concordance_enum --additive-against $pc_base" \
      python validators/validate_concordance_enum.py --enum vocabularies/concordance_class.enum.yaml \
             --families vocabularies/property_catalog/integrated_families.yaml --additive-against "$pc_base"
else
  echo "WARN  concordance-enum additivity SKIPPED — '$pc_base' not fetched; set PRELAND_BASE or run 'git fetch origin main'"
fi

# --- comparability-state TOKEN additivity (vocabularies/comparability_state.enum.yaml) ---
# Third instance of the same shape, same reason. This vocabulary is YOUNG (3 tokens, 1 piloted family),
# which is exactly when additivity is cheap to enforce and exactly when it is tempting to skip: the 44
# concordance_class tokens above cost a 650-line retrospective registration precisely because nothing
# governed them at birth. `comparability_state` is emitted into claim records, so a removed or renamed
# token is a wire-name break with the same fail-open consumers.
if git rev-parse --verify -q "$pc_base" >/dev/null; then
  run "validate_comparability_state --additive-against $pc_base" \
      python validators/validate_comparability_state.py --enum vocabularies/comparability_state.enum.yaml \
             --families vocabularies/property_catalog/integrated_families.yaml \
             --concordance-enum vocabularies/concordance_class.enum.yaml --additive-against "$pc_base"
else
  echo "WARN  comparability-state additivity SKIPPED — '$pc_base' not fetched; set PRELAND_BASE or run 'git fetch origin main'"
fi

# --- ruff (.github/workflows/ruff.yml) ---
# 2026-09-13: this script mirrored contracts-validate.yml and NOTHING ELSE, so "ALL GATES PASS" was
# reported on a branch whose ruff job then failed on the PR — format-only, but a red check either way.
# `ruff format --check` is WHOLE-TREE (the tree is fully formatted); `ruff check` is DIFF-AWARE in CI,
# so it is run here only on the .py files this branch changed, matching the grandfathered lint backlog.
# ruff is pinned in the workflow: a different local version formats differently, so the version is
# asserted rather than assumed. An ABSENT/mismatched ruff is a loud WARN, never a silent skip — a gate
# that did not run must not read as a gate that passed.
# `ruff check`, plus the assertion that every path on the argv was actually readable. ruff exits 0
# on a file it could not open (stderr `warning: Failed to lint <p>: No such file or directory`), and
# `run` captures output and discards it on rc 0, so that warning was invisible AND non-fatal. rc 3
# distinguishes "could not read" from ruff's own rc 1 "found violations" in the transcript.
_ruff_check_readable() {
  local out rc
  out=$(ruff check "$@" 2>&1); rc=$?
  printf '%s\n' "$out"
  if printf '%s' "$out" | grep -q 'Failed to lint'; then
    echo "ruff could not READ one or more paths above — the argv is wrong for this cwd ($PWD);" \
         "a lint that opened no file is not a pass"
    return 3
  fi
  return $rc
}

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
    # `--relative` is LOAD-BEARING (added 2026-09-30). This script runs from contracts/, but
    # `git diff --name-only` emits REPO-ROOT-relative paths, so the argv was `ruff check
    # contracts/validators/x.py` evaluated from INSIDE contracts/ — resolving to nothing. ruff
    # treats an unreadable path as a WARNING on stderr and still exits 0 with "All checks
    # passed!", so this step reported PASS having linted ZERO files, on every branch that
    # changed a .py under contracts/. Trunk never exposed it: trunk changes no .py and takes the
    # honest else-branch below, so the live path was only ever reached on a branch. The first
    # branch to actually exercise it (this one) was carrying a real I001.
    changed=$(git diff --name-only --relative --diff-filter=ACMR "$base"...HEAD -- '*.py' || true)
    if [ -n "$changed" ]; then
      echo "      (ruff check scope vs $base: $(echo "$changed" | tr '\n' ' '))"
      # Assert ruff READ the files rather than trusting that it was happy: `--relative` fixes
      # today's breakage, but the failure mode is silent and the next path-shape change would
      # reintroduce it identically. A lint of zero files must not read as a lint that passed.
      # shellcheck disable=SC2086
      run "ruff check (changed .py)"     _ruff_check_readable $changed
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
