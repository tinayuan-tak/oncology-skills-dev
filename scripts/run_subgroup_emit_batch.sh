#!/usr/bin/env bash
# run_subgroup_emit_batch.sh — Phase 2b/c shard-matrix driver.
#
# Iterates over scripts/subgroup_emit_shards.tsv (20 shards) and invokes
# scripts/emit_subgroup_assignments.py per shard with bounded parallelism +
# resume-safe S3 cache check + per-shard logging + status tracking.
#
# Mirrors the run_indication_batch.sh pattern (PR #23; DGE 19-indication batch).
#
# Invocation:
#     scripts/run_subgroup_emit_batch.sh                       # all 20 shards
#     scripts/run_subgroup_emit_batch.sh COADREAD              # only COADREAD's 3
#     scripts/run_subgroup_emit_batch.sh COADREAD NSCLC        # 2-indication subset
#     PARALLEL=4 scripts/run_subgroup_emit_batch.sh            # tune fan-out
#     DRY_RUN=1 scripts/run_subgroup_emit_batch.sh             # print + emit stubs, no S3
#     RUN_DIR=~/dev/framework-runs/subgroup-emit-2026-07-15 \
#         scripts/run_subgroup_emit_batch.sh
#
# Sequencing per user 2026-07-15 direction:
#   Ship COADREAD's 3 shards FIRST as a vertical-slice validation. Confirm
#   parquet emission + S3 upload + derived-manifest stub work end-to-end.
#   Then remaining 17 shards can batch in a follow-up invocation.
#
# Exit codes:
#   0 — every requested shard emitted (or was cached).
#   2 — one or more shards failed. Individual $RUN_DIR/{IND}/{SOURCE}/run.log
#       carries the assigner traceback. Rerun to retry (successes cached).
#
# Not handled here (delegated to emit_subgroup_assignments.py):
#   - Cache-fallback path resolution for source data (see subgroup_common/loaders.py)
#   - Classifier-config resolution for Modality-C shards
#   - MD5 stamping + x-amz-meta-md5 metadata on uploads
#   - Derived-manifest stub emission at data-catalog/manifests/derived/

set -euo pipefail

# --- config ------------------------------------------------------------------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SHARD_FILE="$REPO_ROOT/scripts/subgroup_emit_shards.tsv"

PARALLEL="${PARALLEL:-4}"
DRY_RUN="${DRY_RUN:-}"
RUN_DIR="${RUN_DIR:-$HOME/dev/framework-runs/subgroup-emit-$(date -u +%Y-%m-%d)}"
# Derived from THIS script's location, not $HOME. Two reasons it matters here specifically:
#   1. On a dev box $HOME and the checkout parent are the same directory, so a $HOME-anchored
#      default cannot be falsified by a local run — it is only wrong somewhere nobody looks.
#   2. This value is passed through as --catalog-repo on every shard invocation (see below), so it
#      OVERRIDES the portable default inside emit_subgroup_assignments.py. Leaving it $HOME-anchored
#      would silently undo that fix for the batch path, which is how all 20 shards actually run.
# Precedence matches the Python side: explicit CATALOG_REPO, then DATA_CATALOG_ROOT, then the sibling.
CATALOG_REPO="${CATALOG_REPO:-${DATA_CATALOG_ROOT:-$(dirname "$REPO_ROOT")/rnd-computational-biology-oncology-data-catalog}}"
CLASSIFIER_CONFIG_DIR="${CLASSIFIER_CONFIG_DIR:-$REPO_ROOT/methods/subgroup_assigner_classifier/example-configs}"
S3_BUCKET="onc-compbio"

# --- helpers -----------------------------------------------------------------

log() { printf '[subgroup-emit-batch %s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }

# S3 URI base for a completed shard's parquet.
s3_uri_base() {
    local source="$1" indication="$2" release_pin="$3"
    local ind_lower rp_lower
    ind_lower="$(printf '%s' "$indication" | tr '[:upper:]' '[:lower:]')"
    rp_lower="$(printf '%s' "$release_pin" | tr '[:upper:]' '[:lower:]')"
    printf 's3://%s/derived/subgroup-assignments/%s/%s/%s' \
        "$S3_BUCKET" "$ind_lower" "$source" "$rp_lower"
}

# Resume gate: skip if the shard's assignments.parquet already exists in S3.
is_already_done() {
    local source="$1" indication="$2" release_pin="$3"
    local pfx
    pfx="$(s3_uri_base "$source" "$indication" "$release_pin")"
    aws s3api head-object \
        --bucket "$S3_BUCKET" \
        --key "${pfx#s3://$S3_BUCKET/}/assignments.parquet" \
        >/dev/null 2>&1
}

# Throttle: block until parallel-job count drops.
throttle() {
    while (( $(jobs -r | wc -l) >= PARALLEL )); do
        sleep 2
    done
}

write_status() { printf '%s\n' "$3" >"$RUN_DIR/$2/$1/status"; }
read_status()  { cat "$RUN_DIR/$2/$1/status" 2>/dev/null || echo "unknown"; }

# --- main loop ---------------------------------------------------------------

# Positional args = indication subset; empty = all indications.
FILTER_INDICATIONS=("$@")

should_include() {
    local ind="$1"
    if (( ${#FILTER_INDICATIONS[@]} == 0 )); then
        return 0
    fi
    for want in "${FILTER_INDICATIONS[@]}"; do
        [[ "$ind" == "$want" ]] && return 0
    done
    return 1
}

run_one_shard() {
    local source="$1" indication="$2" release_pin="$3" classifier_config="$4"
    local shard_dir="$RUN_DIR/$indication/$source"
    local logf="$shard_dir/run.log"
    mkdir -p "$shard_dir"

    # In dry-run we skip the is_already_done S3 check entirely — the intent is
    # to see the plan for every shard, not to short-circuit on cache hits.
    if [[ -z "$DRY_RUN" ]]; then
        if is_already_done "$source" "$indication" "$release_pin"; then
            log "SKIP $source × $indication (S3 cached)"
            write_status "$source" "$indication" skipped-cached
            return 0
        fi
    fi

    log "START $source × $indication → $(s3_uri_base "$source" "$indication" "$release_pin")"

    local cmd=(
        python -m scripts.emit_subgroup_assignments
        --source "$source"
        --indication "$indication"
        --release-pin "$release_pin"
        --catalog-repo "$CATALOG_REPO"
        --run-dir "$RUN_DIR"
    )
    if [[ "$classifier_config" != "-" ]]; then
        cmd+=("--classifier-config" "$CLASSIFIER_CONFIG_DIR/$classifier_config")
    fi

    if [[ -n "$DRY_RUN" ]]; then
        printf '  (dry-run) %s\n' "${cmd[*]}" >&2
        write_status "$source" "$indication" ok
        return 0
    fi

    if setsid "${cmd[@]}" >"$logf" 2>&1; then
        log "OK    $source × $indication"
        write_status "$source" "$indication" ok
    else
        local rc=$?
        log "FAIL  $source × $indication (rc=$rc) — see $logf"
        write_status "$source" "$indication" failed
        return "$rc"
    fi
}

mkdir -p "$RUN_DIR"
log "batch RUN_DIR: $RUN_DIR"
log "parallelism:   $PARALLEL"
log "shard-file:    $SHARD_FILE"
log "catalog-repo:  $CATALOG_REPO"
if (( ${#FILTER_INDICATIONS[@]} > 0 )); then
    log "filter:        ${FILTER_INDICATIONS[*]}"
else
    log "filter:        (all shards in matrix)"
fi
[[ -n "$DRY_RUN" ]] && log "DRY_RUN=1 — printing commands, no S3 or method invocation"

TOTAL=0
LAUNCHED=0
while IFS=$'\t' read -r source indication release_pin classifier_config || [[ -n "$source" ]]; do
    # Skip comments + blank lines
    [[ "$source" =~ ^#.*$ || -z "$source" ]] && continue
    TOTAL=$((TOTAL+1))
    if ! should_include "$indication"; then
        continue
    fi
    LAUNCHED=$((LAUNCHED+1))
    throttle
    run_one_shard "$source" "$indication" "$release_pin" "$classifier_config" &
done < "$SHARD_FILE"

wait || true

log "$LAUNCHED of $TOTAL shards launched"

# --- report ------------------------------------------------------------------

echo
echo "=================== subgroup emit report ==================="
n_ok=0; n_skip=0; n_fail=0

while IFS=$'\t' read -r source indication release_pin classifier_config || [[ -n "$source" ]]; do
    [[ "$source" =~ ^#.*$ || -z "$source" ]] && continue
    should_include "$indication" || continue
    s="$(read_status "$source" "$indication")"
    printf '  %-30s %s\n' "$source × $indication" "$s"
    case "$s" in
        ok)             n_ok=$((n_ok+1));;
        skipped-cached) n_skip=$((n_skip+1));;
        failed)         n_fail=$((n_fail+1));;
    esac
done < "$SHARD_FILE"

echo "------------------------------------------------------------"
printf '  ok=%d  skipped-cached=%d  failed=%d  total-launched=%d\n' \
    "$n_ok" "$n_skip" "$n_fail" "$LAUNCHED"

if (( n_fail > 0 )); then
    exit 2
fi
