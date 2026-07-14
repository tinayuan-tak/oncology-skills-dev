#!/usr/bin/env bash
# run_indication_batch.sh — drive dge-deseq2 four-cell sensitivity across
# the 19 wired indications with bounded parallelism.
#
# Invocation:
#     scripts/run_indication_batch.sh                              # all 19
#     scripts/run_indication_batch.sh BRCA                         # subset
#     scripts/run_indication_batch.sh BRCA LUAD PAAD               # subset
#     PARALLEL=4 scripts/run_indication_batch.sh                   # tune fan-out
#     DRY_RUN=1 scripts/run_indication_batch.sh                    # print cmds only
#     RUN_DIR=~/dev/framework-runs/tvn-batch-2026-07-14 \
#         scripts/run_indication_batch.sh
#
# Semantics:
#   - Runs `dge-deseq2 --contrast four_cell_sensitivity` per indication.
#   - Bounded parallelism via a background-job counter (PARALLEL, default 6).
#   - Per-indication output dir: $RUN_DIR/{IND}/. Per-indication log:
#     $RUN_DIR/{IND}/run.log.
#   - Resume-safe: an indication whose destination S3 sensitivity.parquet
#     already exists is skipped (see IS_ALREADY_DONE below). Re-invoke with
#     the same $RUN_DIR to pick up where a previous batch left off.
#   - MD5 stamping happens inside dge-deseq2 / R stage 04_write_parquet.R at
#     upload time; this script does not stamp separately (avoids double-hash
#     drift). Verification is via `aws s3 head-object` post-run.
#
# Exit codes:
#   0 — every requested indication produced a sensitivity.parquet
#       (either freshly built or already-cached).
#   2 — one or more indications failed. Individual $RUN_DIR/{IND}/run.log
#       carries the R traceback. Rerun to retry failed ones (successes are
#       cached and will be skipped).
#
# Not handled here (delegated to dge_deseq2 R stages):
#   - Cells A/B auto-skip when the TCGA cohort has <3 adjacent-normal
#     samples (OV, LGG, SKCM=1, PAAD=4, CESC=3, GBM=5). The output
#     sensitivity.parquet will carry cells C/D only and is still valid.
#   - HNSC has no GTEx tissue mapping (recount3_code: null) — stage 00
#     auto-skips cells C/D and emits cells A/B only.

set -euo pipefail

# --- config ------------------------------------------------------------------

# Canonical 19-indication list (mirrors PAN_TISSUE_INDICATIONS in
# methods/dge_deseq2/emit_pan_tissue.py + WIRED_INDICATIONS in
# methods/surfaceome_cohort_ranking/cli.py — kept in sync).
DEFAULT_INDICATIONS=(
    COAD READ COADREAD LUAD LUSC BRCA PAAD SKCM STAD PRAD
    OV KIRC GBM LGG BLCA LIHC CESC ESCA HNSC
)

PARALLEL="${PARALLEL:-6}"
DRY_RUN="${DRY_RUN:-}"
RUN_DIR="${RUN_DIR:-$HOME/dev/framework-runs/tvn-batch-$(date -u +%Y-%m-%d)}"
CATALOG_REPO="${CATALOG_REPO:-$HOME/rnd-computational-biology-oncology-data-catalog}"
RELEASE_PIN="${RELEASE_PIN:-2026-Q3}"
S3_BUCKET="onc-compbio"

# --- helpers -----------------------------------------------------------------

log() { printf '[batch %s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }

# Destination S3 key for a completed indication's sensitivity.parquet.
dest_key() {
    local ind="$1"
    printf 'data-catalog/derived/%s-dge-tumor-vs-normal-sensitivity-v1/sensitivity.parquet' \
        "$(printf '%s' "$ind" | tr '[:upper:]' '[:lower:]')"
}

# Resume gate: skip an indication if its S3 sensitivity.parquet already exists.
# NOTE: this checks S3, not local. A local half-baked run.log is orphaned only
# if the R stage crashed BEFORE stage 04's S3 upload — in which case the S3
# object legitimately doesn't exist and we correctly re-run. Head-object needs
# GetObject or ListBucket; the cbg role has both.
is_already_done() {
    local ind="$1"
    local key
    key="$(dest_key "$ind")"
    aws s3api head-object --bucket "$S3_BUCKET" --key "$key" >/dev/null 2>&1
}

# Wait until running job count drops below PARALLEL (naive but simple).
throttle() {
    while (( $(jobs -r | wc -l) >= PARALLEL )); do
        sleep 2
    done
}

# --- main --------------------------------------------------------------------

# Positional args = indication subset; empty = all.
if (( $# > 0 )); then
    INDICATIONS=("$@")
else
    INDICATIONS=("${DEFAULT_INDICATIONS[@]}")
fi

mkdir -p "$RUN_DIR"
log "batch RUN_DIR: $RUN_DIR"
log "parallelism: $PARALLEL"
log "indications: ${INDICATIONS[*]}"
log "catalog-repo: $CATALOG_REPO"
log "release-pin: $RELEASE_PIN"
[[ -n "$DRY_RUN" ]] && log "DRY_RUN=1 — printing commands, no execution"

# Per-indication status is written to $RUN_DIR/{IND}/status because bash
# associative-array writes inside a backgrounded `run_one &` don't propagate
# back to the parent shell — each & forks a fresh env. Files-on-disk are the
# authoritative status; the report aggregates them.
write_status() { printf '%s\n' "$2" >"$RUN_DIR/$1/status"; }
read_status()  { cat "$RUN_DIR/$1/status" 2>/dev/null || echo "unknown"; }

run_one() {
    local ind="$1"
    local out_dir="$RUN_DIR/$ind"
    local logf="$out_dir/run.log"
    local key parquet_uri
    key="$(dest_key "$ind")"
    parquet_uri="s3://$S3_BUCKET/$key"
    mkdir -p "$out_dir"

    if is_already_done "$ind"; then
        log "SKIP $ind (already cached at s3://$S3_BUCKET/$key)"
        write_status "$ind" skipped-cached
        return 0
    fi

    log "START $ind -> $parquet_uri"
    local cmd=(
        python -m methods.dge_deseq2.cli
        --indication "$ind"
        --contrast four_cell_sensitivity
        --release-pin "$RELEASE_PIN"
        --catalog-repo "$CATALOG_REPO"
        --out "$out_dir"
        --parquet-uri "$parquet_uri"
        --threads 4
    )
    if [[ -n "$DRY_RUN" ]]; then
        printf '  (dry-run) %s\n' "${cmd[*]}"
        write_status "$ind" ok
        return 0
    fi

    # `setsid` decouples the R subprocess from the parent's terminal so
    # a disconnected shell doesn't SIGHUP the batch. Output goes to $logf.
    if setsid "${cmd[@]}" >"$logf" 2>&1; then
        log "OK    $ind"
        write_status "$ind" ok
    else
        local rc=$?
        log "FAIL  $ind (rc=$rc) — see $logf"
        write_status "$ind" failed
        return "$rc"
    fi
}

# Launch, throttled.
for ind in "${INDICATIONS[@]}"; do
    throttle
    # Fire-and-forget in background; each run_one writes its own status.
    run_one "$ind" &
done

# Wait for all outstanding jobs. `wait` without args waits for ALL bg jobs;
# `|| true` because a single failure shouldn't abort the whole batch.
wait || true

# --- report ------------------------------------------------------------------

echo
echo "=================== batch report ==================="
n_ok=0; n_skip=0; n_fail=0
for ind in "${INDICATIONS[@]}"; do
    s="$(read_status "$ind")"
    printf '  %-8s %s\n' "$ind" "$s"
    case "$s" in
        ok) ((n_ok++));;
        skipped-cached) ((n_skip++));;
        failed) ((n_fail++));;
    esac
done
echo "----------------------------------------------------"
printf '  ok=%d  skipped-cached=%d  failed=%d  total=%d\n' \
    "$n_ok" "$n_skip" "$n_fail" "${#INDICATIONS[@]}"

if (( n_fail > 0 )); then
    exit 2
fi
