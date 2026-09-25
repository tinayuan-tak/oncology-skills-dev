#!/usr/bin/env bash
# preland.sh — run the contracts-validate gates locally before landing. Mirrors .github/workflows/contracts-validate.yml.
# NOTE: plain `pytest` does NOT invoke validators/validate_*.py, and contracts-validate is not a branch-protection-required
# check — so a schema violation can pass pytest yet turn trunk RED. Run THIS before landing any cards/ | interpretation-rules/
# | resolvers/ | vocabularies/ change. Bare python (no pixi in this repo).
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
run "pytest rule_role_partition"         python -m pytest tests/validators/test_rule_role_partition.py -q
run "validate_fold_migration"            python validators/validate_fold_migration.py --resolvers resolvers/
run "pytest tests/schemas"               python -m pytest tests/schemas/ -q
run "pytest test_eval_ledger"            python -m pytest tests/validators/test_eval_ledger.py -q
run "build_eval_ledger --self-check"     python validators/build_eval_ledger.py --self-check
# T1 reachability. Unlike CI, a local run usually HAS the corpus, so the corpus half also verifies
# the committed counts — set EMISSION_CORPUS to point at a vintage other than the ledger's.
run "pytest test_emission_ledger"        python -m pytest tests/validators/test_emission_ledger.py -q
run "build_emission_ledger --self-check" python validators/build_emission_ledger.py --self-check
# I.3 wiring reconciliation (READS vs DECLARES vs EMITS). Locally the siblings are usually present,
# so the LIVE half also re-extracts reads and diffs the committed snapshot; CI runs the hermetic half.
run "pytest test_wiring_reconciliation"      python -m pytest tests/validators/test_wiring_reconciliation.py -q
run "build_wiring_reconciliation --self-check" python validators/build_wiring_reconciliation.py --self-check
# I.4 wiring ledger (dataset-grain: read / declared_only / dark). Locally the siblings are usually
# present, so the LIVE half recomputes the whole ledger and diffs it; CI runs the hermetic half.
run "pytest test_wiring_ledger"          python -m pytest tests/validators/test_wiring_ledger.py -q
run "build_wiring_ledger --self-check"   python validators/build_wiring_ledger.py --self-check
run "pytest subgroup+coverage"           python -m pytest tests/validators/test_subgroup_assignments_and_coverage.py -q
run "pytest framework_discrimination"    python -m pytest tests/calibration/test_framework_discrimination.py -q
run "pytest card_concept_discipline"     python -m pytest tests/validators/test_card_concept_discipline.py -q
run "pytest shared-mt vocabularies"      python -m pytest tests/validators/test_shared_measurement_type_vocabularies.py -q
run "pytest card vocab-declaration"      python -m pytest tests/validators/test_card_vocabulary_declaration.py -q
run "pytest card method-wiring"          python -m pytest tests/validators/test_card_method_wiring.py -q
run "pytest nomination-gate+subtype-tier" python -m pytest tests/vocabularies/test_nomination_verdict_gate.py tests/validators/test_subtype_tier_rules.py -q
run "pytest target-profiling-axes ontology" python -m pytest tests/vocabularies/test_target_profiling_axes.py tests/vocabularies/test_question_hierarchies.py -q
# 2026-09-18: the indication-conditioned dependency spine (card field -> 4 rules -> 4 rungs, plus the
# two-site dependency_verdict_enum parity and the DELIBERATE `indication_not_supplied` absence).
# Gated HERE and not in contracts-validate.yml on purpose: CI's "Whole-repo test suite (safety net)"
# step already collects it, but THIS script has no such net — every pytest gate above names one file
# — so without this line the guard would be absent from the pre-land gate that peers actually run.
run "pytest dependency indication spine" python -m pytest tests/vocabularies/test_indication_dependency_class_partition.py -q
# 2026-09-18 (Stage 2b): the RESOLVER -> GATE parity guard, plus the three files whose closed-set veto
# pins it widens. Same no-net argument as the line above, with a sharper edge: the pins live in files
# this script NEVER collected (only test_nomination_verdict_gate.py was gated), so the widening of
# test_kill_capable_completeness / test_target_thesis / test_known_target_calibration would have been
# invisible to every pre-land run and first observed in CI. test_known_target_calibration also carries
# the VETO_VERDICTS mirror, whose staleness fails OPEN — a `must_not_veto` assertion blind to a veto
# arm reports PASS — so it is the last file that should be gated only by the safety net.
run "pytest indication gate parity"      python -m pytest tests/vocabularies/test_indication_verdict_gate_parity.py tests/vocabularies/test_kill_capable_completeness.py tests/vocabularies/test_target_thesis.py tests/calibration/test_known_target_calibration.py -q
# 2026-09-18: the three by-subtype arms' `subtype_signal` vocabulary, which they spelled TWO ways
# (tumour RNA prefixed, cell-line RNA and tumour protein bare). Same no-net argument as the two lines
# above. The reason this file in particular must be gated here rather than left to CI's safety net is
# that it guards a MIGRATION: it is the assertion that lets the later bare-token REMOVAL be attempted
# safely, by reding when a rule keys on a token its own card no longer declares. A migration guard
# first observed in CI is a guard that was absent exactly when the removal commit was written.
run "pytest subtype_signal vocabulary"   python -m pytest tests/validators/test_subtype_signal_vocabulary_alignment.py -q

# Drain the pool and print every gate's PASS/FAIL in launch (CI) order before the ruff/advisory
# steps below, which stay SYNCHRONOUS (fast, and the ruff block has its own version-gate control
# flow). Restore the plain serial `run` for them so that block is unchanged from its original form.
report_pool
run() { local label="$1"; shift; local out
  if out=$("$@" 2>&1); then echo "PASS  $label"
  else echo "FAIL  $label"; echo "$out" | tail -n 30 | sed 's/^/      /'; fail=1; fi; }

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
