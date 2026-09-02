#!/usr/bin/env bash
# Produce a target-profile dev package under the framework-runs convention (eval/CONVENTION.md).
#
# This script lives DURABLY in the repo (eval/); it writes OUTPUTS to the ephemeral
# framework-runs workspace (default ~/dev/framework-runs, override FRAMEWORK_RUNS_ROOT) so a
# SageMaker restart wipes the outputs, never the harness.
#
# Usage:
#   eval/run_example.sh <TARGET> <INDICATION> [runtype] [-- <extra run.py args>]
#   runtype ∈ {full (default), verdict-only, review}
# Examples:
#   eval/run_example.sh KRAS COADREAD
#   eval/run_example.sh DLL3 SCLC full
#   eval/run_example.sh KRAS COADREAD full -- --subtypes CMS
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"     # <skills_repo>/eval
SKILLS_ROOT="${CLAUDE_ONCOLOGY_SKILLS_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"

# Default to the committed run.py in this checkout (Phase-0 output-fidelity fixes are on trunk).
# Override with TP_RUN_PY to pin a specific worktree.
TP_RUN_PY="${TP_RUN_PY:-$SKILLS_ROOT/skills/target-profile/scripts/run.py}"
PY="${TP_PY:-/opt/conda/bin/python}"
OUT_ROOT="${FRAMEWORK_RUNS_ROOT:-$HOME/dev/framework-runs}"

TARGET="${1:?TARGET required}"
INDICATION="${2:?INDICATION required}"
RUNTYPE="${3:-full}"
shift $(( $# < 3 ? $# : 3 )) || true
[[ "${1:-}" == "--" ]] && shift || true   # allow optional "--" before passthrough args

case "$RUNTYPE" in
  full)         MODE_ARGS=(--full-package) ;;
  verdict-only) MODE_ARGS=(--verdict-only) ;;
  review)       MODE_ARGS=(--full-package --synthesize-subskills) ;;
  *) echo "unknown runtype: $RUNTYPE (want full|verdict-only|review)" >&2; exit 2 ;;
esac

DATE="$(date +%Y-%m-%d)"
EXAMPLE="${TARGET}-${INDICATION}"
LEAF="${DATE}-${RUNTYPE}"
OUT="${OUT_ROOT}/examples/${EXAMPLE}/${LEAF}"
mkdir -p "$OUT"

echo "[run_example] ${EXAMPLE} ${RUNTYPE} -> ${OUT}"
echo "[run_example] run.py = ${TP_RUN_PY}"

# Data access ALWAYS needs the onc-compbio account (cbg). Force it — do not honor an inherited
# AWS_PROFILE (e.g. cmp-dev), which fails the data-access preflight. Bedrock synthesis uses its
# own BEDROCK_AWS_PROFILE.
AWS_PROFILE=cbg \
BEDROCK_AWS_PROFILE="${BEDROCK_AWS_PROFILE:-cmp-dev}" \
  "$PY" "$TP_RUN_PY" \
    --target "$TARGET" --indication "$INDICATION" \
    --out "$OUT" "${MODE_ARGS[@]}" "$@" \
  > "${OUT}/run.console.log" 2>&1 \
  && STATUS=ok || STATUS=FAILED

# Update the latest pointer only on success.
if [[ "$STATUS" == ok ]]; then
  ln -sfn "$LEAF" "${OUT_ROOT}/examples/${EXAMPLE}/latest"
  echo "[run_example] OK — latest -> ${LEAF}"
else
  echo "[run_example] FAILED — see ${OUT}/run.console.log (latest pointer unchanged)" >&2
  exit 1
fi
