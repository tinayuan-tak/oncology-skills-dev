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
# onc_methods/dge_deseq2/emit_pan_tissue.py + WIRED_INDICATIONS in
# onc_methods/surfaceome_cohort_ranking/cli.py — kept in sync).
DEFAULT_INDICATIONS=(
    COAD READ COADREAD LUAD LUSC BRCA PAAD SKCM STAD PRAD
    OV KIRC GBM LGG BLCA LIHC CESC ESCA HNSC
)

# Derived from THIS script's location, not $HOME. Two reasons it matters here specifically:
#   1. On a dev box $HOME and the checkout parent are the same directory, so a $HOME-anchored
#      default cannot be falsified by a local run — it is only wrong somewhere nobody looks
#      (CI, a second checkout, another user's box, a container).
#   2. CATALOG_REPO is passed through as --catalog-repo on EVERY indication (see run_one), so
#      it OVERRIDES the portable default inside onc_methods/dge_deseq2/cli.py. Leaving it
#      $HOME-anchored silently undoes that fix for the batch path — which is how all 19
#      indications actually run.
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PARALLEL="${PARALLEL:-6}"
DRY_RUN="${DRY_RUN:-}"
RUN_DIR="${RUN_DIR:-$HOME/dev/framework-runs/tvn-batch-$(date -u +%Y-%m-%d)}"
# Precedence matches the Python side and run_subgroup_emit_batch.sh: explicit CATALOG_REPO,
# then DATA_CATALOG_ROOT, then the data-catalog checkout sitting beside this repo.
CATALOG_REPO="${CATALOG_REPO:-${DATA_CATALOG_ROOT:-$(dirname "$REPO_ROOT")/rnd-computational-biology-oncology-data-catalog}}"
RELEASE_PIN="${RELEASE_PIN:-2026-Q3}"
S3_BUCKET="onc-compbio"

# Count substrate. recount3 (default) is the classifier substrate and its product
# id is the bare `-dge-tumor-vs-normal-sensitivity-v1`. xena_toil is the S1b
# secondary/diagnostic substrate (analysis-methods#694): its product carries a
# `-xenatoil` INFIX so it lands on a DISTINCT S3 key/catalog id and, crucially,
# does NOT end in the pancan discovery suffix `-dge-tumor-vs-normal-sensitivity-v1`
# (so list_published_sensitivity_indications / assert_roster_matches_published /
# read_tumor_vs_normal_sensitivity_gene_row never pick it up — mechanically secondary).
SUBSTRATE="${SUBSTRATE:-recount3}"
case "$SUBSTRATE" in
    recount3)  SUBSTRATE_INFIX="" ;;
    xena_toil) SUBSTRATE_INFIX="-xenatoil" ;;
    *) echo "[batch] unknown SUBSTRATE='$SUBSTRATE' (expected recount3|xena_toil)" >&2; exit 2 ;;
esac

# --- helpers -----------------------------------------------------------------

log() { printf '[batch %s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }

# Destination S3 key for a completed indication's sensitivity.parquet.
dest_key() {
    local ind="$1"
    printf 'data-catalog/derived/%s-dge-tumor-vs-normal-sensitivity%s-v1/sensitivity.parquet' \
        "$(printf '%s' "$ind" | tr '[:upper:]' '[:lower:]')" "$SUBSTRATE_INFIX"
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
    printf 's3://%s/data-catalog/derived/%s-dge-tumor-vs-normal-sensitivity%s-v1' \
        "$S3_BUCKET" "$(printf '%s' "$ind" | tr '[:upper:]' '[:lower:]')" "$SUBSTRATE_INFIX"
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
            # Same `((n++))`-under-errexit hazard as the report block below. Harmless TODAY only
            # by accident — errexit is suspended inside an `if` condition, and this function is
            # only ever called as one. Left as `((n++))` it would become fatal the moment
            # someone called upload_indication outside a condition. Fixed, not relied upon.
            n_missing=$((n_missing+1))
            continue
        fi
        local md5
        md5="$(md5sum "$local_path" | awk '{print $1}')"
        if ! aws s3 cp "$local_path" "$pfx/$fname" \
                --metadata "md5=$md5" --no-progress >/dev/null 2>&1; then
            log "  $ind: FAILED to upload $fname ($md5)"
            return 1
        fi
        n_uploaded=$((n_uploaded+1))
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
log "substrate: $SUBSTRATE${SUBSTRATE_INFIX:+ (product id infix ${SUBSTRATE_INFIX})}"
[[ -n "$DRY_RUN" ]] && log "DRY_RUN=1 — printing commands, no execution"

# --- preflight ---------------------------------------------------------------

# Fail fast on a catalog root that isn't there. Before this check, a wrong --catalog-repo was
# discovered 19 times in parallel, an hour into 19 R pipelines — and under DRY_RUN=1 it was
# never discovered at all, because the dry-run branch wrote `ok` without touching an input.
# Runs in BOTH modes, and deliberately AFTER the banner so the resolved root is on the record
# even when the preflight is what rejects it.
#
# Exit 2, not 1: a root that cannot serve any indication is the documented "one or more
# indications failed" outcome, not a usage error.
#
# Scope of the check is only what is UNAMBIGUOUS — the root plus the two directories
# resolve_config() actually searches (onc_methods/dge_deseq2/cli.py). Deliberately NOT checked
# here: RELEASE_PIN. The R stages resolve versioned inputs themselves, so re-deriving that
# mapping in bash would put one rule in two places and let them drift.
preflight_catalog_root() {
    if [[ ! -d "$CATALOG_REPO" ]]; then
        log "PREFLIGHT-FAIL catalog-repo does not exist: $CATALOG_REPO"
        log "  Set CATALOG_REPO (or DATA_CATALOG_ROOT) to your data-catalog checkout, or clone it"
        log "  beside this repo at $(dirname "$REPO_ROOT")/rnd-computational-biology-oncology-data-catalog"
        return 1
    fi
    if [[ ! -d "$CATALOG_REPO/indication-configs" && ! -d "$CATALOG_REPO/manifests/sources" ]]; then
        log "PREFLIGHT-FAIL catalog-repo exists but is not a data-catalog checkout: $CATALOG_REPO"
        log "  Holds neither indication-configs/ nor manifests/sources/ — the only two locations"
        log "  resolve_config() searches. Nothing in this batch could resolve."
        return 1
    fi
    return 0
}

preflight_catalog_root || exit 2

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
        python -m onc_methods.dge_deseq2.cli
        --indication "$ind"
        --contrast four_cell_sensitivity
        --substrate "$SUBSTRATE"
        --release-pin "$RELEASE_PIN"
        --catalog-repo "$CATALOG_REPO"
        --out "$out_dir"
        --parquet-uri "$parquet_uri"
        --threads 4
    )
    if [[ -n "$DRY_RUN" ]]; then
        # A dry run that writes `ok` unconditionally CANNOT FAIL, and a check that cannot fail
        # answers nothing — it just looks like validation. Resolve the SAME two candidates
        # resolve_config() will (onc_methods/dge_deseq2/cli.py), so `ok` means "this would run".
        # Only the config is resolved: the R stages' own inputs stay their business.
        # The xena_toil substrate selects samples by --indication and needs NO config, so the
        # config-existence probe applies only to recount3.
        if [[ "$SUBSTRATE" != "xena_toil" \
           && ! -f "$CATALOG_REPO/indication-configs/$ind.yaml" \
           && ! -f "$CATALOG_REPO/manifests/sources/$ind.yaml" ]]; then
            log "DRY-FAIL $ind — no config at indication-configs/$ind.yaml nor manifests/sources/$ind.yaml under $CATALOG_REPO"
            write_status "$ind" failed
            return 1
        fi
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
    # `n=$((n+1))`, NOT `((n++))`. Under `set -e` these are not interchangeable: `((expr))`
    # returns exit status 1 when the expression evaluates to 0, and POST-increment evaluates to
    # the OLD value — so `((n_ok++))` on the first `ok` row (n_ok still 0) returned 1 and
    # errexit killed the script mid-report. Measured on the pre-fix driver: the header and
    # exactly ONE row printed, then exit 1 — a truncated report that reads like a finished one,
    # and, worse, the documented `exit 2` below became UNREACHABLE, so a batch with failures
    # could not report them. run_subgroup_emit_batch.sh already used the safe form; the
    # "mirrors run_indication_batch.sh" relationship was partial in the one idiom that bites.
    case "$s" in
        ok)             n_ok=$((n_ok+1));;
        skipped-cached) n_skip=$((n_skip+1));;
        upload-failed)  n_upfail=$((n_upfail+1));;
        failed)         n_fail=$((n_fail+1));;
    esac
done
echo "----------------------------------------------------"
printf '  ok=%d  skipped-cached=%d  upload-failed=%d  failed=%d  total=%d\n' \
    "$n_ok" "$n_skip" "$n_upfail" "$n_fail" "${#INDICATIONS[@]}"

if (( n_fail + n_upfail > 0 )); then
    exit 2
fi
