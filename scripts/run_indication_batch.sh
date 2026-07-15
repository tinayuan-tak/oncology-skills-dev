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
#   - S3 upload is handled BY THIS SCRIPT after the R pipeline exits
#     successfully (see upload_indication below). The four_cell_sensitivity
#     branch of run_pipeline.R invokes stage 00 -> stage 06 and then quit(0);
#     it does NOT invoke stage 04's S3 write. So the batch driver takes on
#     the upload responsibility for this contrast. MD5 is computed locally
#     with md5sum and stamped as x-amz-meta-md5 on each upload.
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

# S3 prefix for a completed indication's outputs.
dest_prefix() {
    local ind="$1"
    printf 's3://%s/data-catalog/derived/%s-dge-tumor-vs-normal-sensitivity-v1' \
        "$S3_BUCKET" "$(printf '%s' "$ind" | tr '[:upper:]' '[:lower:]')"
}

# Upload every artifact the R pipeline emitted to $out_dir up to the
# indication's S3 prefix, stamping x-amz-meta-md5 for content integrity.
# sensitivity.parquet is the primary product; tumor_vs_adjacent.parquet
# and tumor_vs_gtex.parquet are byproducts of the same DESeq2 run;
# provenance.yaml records inputs + software versions. All four ship
# together so the derived manifest catalogs a coherent unit.
#
# The four_cell driver skips cells based on cohort composition — so not
# every indication will emit every parquet. We upload whichever files
# actually exist on disk and log a note for the missing ones (this is a
# valid outcome for e.g. OV/LGG where adjacent-normal=0 skips cells A/B,
# and HNSC where no GTEx mapping skips cells C/D).
upload_indication() {
    local ind="$1"
    local out_dir="$2"
    local pfx
    pfx="$(dest_prefix "$ind")"

    local n_uploaded=0 n_missing=0
    for fname in sensitivity.parquet tumor_vs_adjacent.parquet tumor_vs_gtex.parquet provenance.yaml; do
        local local_path="$out_dir/$fname"
        if [[ ! -f "$local_path" ]]; then
            log "  $ind: $fname absent locally (expected for some sparse-cohort configurations); skipping upload"
            ((n_missing++))
            continue
        fi
        local md5
        md5="$(md5sum "$local_path" | awk '{print $1}')"
        if ! aws s3 cp "$local_path" "$pfx/$fname" \
                --metadata "md5=$md5" --no-progress >/dev/null 2>&1; then
            log "  $ind: FAILED to upload $fname ($md5)"
            return 1
        fi
        ((n_uploaded++))
    done
    log "  $ind: uploaded $n_uploaded file(s); $n_missing not emitted by pipeline"
    return 0
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
        log "COMPUTE-OK $ind — uploading to S3"
        if upload_indication "$ind" "$out_dir" >>"$logf" 2>&1; then
            log "OK    $ind"
            write_status "$ind" ok
        else
            log "UPLOAD-FAIL $ind — see $logf; compute artifacts stay in $out_dir for retry"
            write_status "$ind" upload-failed
            return 1
        fi
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
n_ok=0; n_skip=0; n_fail=0; n_upfail=0
for ind in "${INDICATIONS[@]}"; do
    s="$(read_status "$ind")"
    printf '  %-8s %s\n' "$ind" "$s"
    case "$s" in
        ok) ((n_ok++));;
        skipped-cached) ((n_skip++));;
        upload-failed) ((n_upfail++));;
        failed) ((n_fail++));;
    esac
done
echo "----------------------------------------------------"
printf '  ok=%d  skipped-cached=%d  upload-failed=%d  failed=%d  total=%d\n' \
    "$n_ok" "$n_skip" "$n_upfail" "$n_fail" "${#INDICATIONS[@]}"

if (( n_fail + n_upfail > 0 )); then
    exit 2
fi
