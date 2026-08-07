#!/usr/bin/env bash
# launch_daemon.sh — predictability daemon launcher.
#
# The framework-runs harness kills bash-tool subprocesses when the session
# reloads (SIGTERM to the process group). This wrapper uses `setsid` to
# place the Python child in a fresh session (no controlling terminal, no
# parent process group), so it survives session teardowns.
#
# Usage:
#   bash launch_daemon.sh <out_dir> [<gene_set>] [<workers>] [<threshold>]
#
# Defaults:
#   gene_set  = medium (dependency-mappable genes; any-lineage |median| > threshold)
#   workers   = 6      (safe for 62 GB RAM instance; each worker ~5 GB SHM)
#   threshold = 0.3    (lower values extend coverage: 0.15 ≈ +3-4k genes, ~3-4 days)
#
# Monitoring (from any subsequent shell):
#   cat <out_dir>/daemon.pid       # → PID
#   ps -p $(cat <out_dir>/daemon.pid) 2>&1  # alive?
#   tail -f <out_dir>/daemon.log   # progress
#   ls <out_dir>/checkpoint_*.parquet | tail -1  # latest checkpoint

set -euo pipefail

OUT_DIR="${1:?usage: launch_daemon.sh <out_dir> [<gene_set>] [<workers>] [<threshold>]}"
GENE_SET="${2:-medium}"
WORKERS="${3:-6}"
THRESHOLD="${4:-0.3}"

METHODS_REPO="/home/sagemaker-user/rnd-computational-biology-oncology-analysis-methods"

mkdir -p "$OUT_DIR"

# Guard: refuse if an existing daemon is already alive for this out-dir.
PID_FILE="$OUT_DIR/daemon.pid"
if [[ -f "$PID_FILE" ]]; then
  OLD_PID="$(cat "$PID_FILE" 2>/dev/null || echo 0)"
  if [[ "$OLD_PID" -gt 0 ]] && kill -0 "$OLD_PID" 2>/dev/null; then
    echo "ERROR: daemon already alive at PID $OLD_PID (from $PID_FILE)."
    echo "  If you want to relaunch, kill $OLD_PID first."
    exit 1
  fi
fi

# Detect whether we're resuming (existing checkpoints → yes)
RESUME_FLAG=""
if compgen -G "$OUT_DIR/checkpoint_*.parquet" >/dev/null || [[ -f "$OUT_DIR/predictability_per_gene.parquet" ]]; then
  RESUME_FLAG="--resume"
  echo "[launch_daemon] Existing checkpoints found; will resume."
fi

# Detach into a fresh session so SIGTERM to the harness's process group
# doesn't propagate to us.
setsid nohup env \
    PYTHONPATH="$METHODS_REPO" \
    AWS_PROFILE="cbg" \
  python -u -m methods.depmap_predictability_precompute.cli \
    --gene-set "$GENE_SET" \
    --threshold "$THRESHOLD" \
    --workers "$WORKERS" \
    --checkpoint-every 25 \
    --out "$OUT_DIR" \
    $RESUME_FLAG \
    > "$OUT_DIR/daemon.log" 2>&1 < /dev/null &

DAEMON_PID=$!
echo "$DAEMON_PID" > "$PID_FILE"

# Detach from job table so this launcher can exit cleanly.
disown "$DAEMON_PID" 2>/dev/null || true

sleep 2  # give the child a moment to actually start

if kill -0 "$DAEMON_PID" 2>/dev/null; then
  echo "[launch_daemon] Started daemon PID=$DAEMON_PID → $OUT_DIR/daemon.log"
  echo "[launch_daemon]   gene_set=$GENE_SET threshold=$THRESHOLD workers=$WORKERS resume=${RESUME_FLAG:-no}"
  echo "[launch_daemon]   Monitor: tail -f $OUT_DIR/daemon.log"
else
  echo "[launch_daemon] ERROR: daemon died within 2s. Check $OUT_DIR/daemon.log"
  exit 1
fi
