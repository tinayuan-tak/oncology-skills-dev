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

# Derived from THIS script's location (methods/<pkg>/ -> repo root), never from a literal path
# and never from $HOME. Two reasons it matters here specifically:
#   1. It feeds PYTHONPATH for the detached child below, so a stale value doesn't fail loudly —
#      the daemon imports a DIFFERENT checkout than the one it was launched from and runs for
#      days against it. A wrong tree here produces valid-looking output, not an error.
#   2. On a dev box $HOME and the checkout parent are the same directory, so the hardcoded path
#      and the correct answer were the same string — which is why this survived AM#631/632/634/
#      635/637. It only diverges in a /tmp worktree or CI, where the launcher would have pointed
#      PYTHONPATH at a checkout that need not exist at all.
METHODS_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

# The INTERPRETER is as load-bearing as the tree above, and was the half left unpinned.
# PYTHONPATH decides WHICH CODE runs; the interpreter decides WHICH DEPENDENCIES EXIST —
# and this pipeline probes `import shap` at RUNTIME inside the worker (cli.py `_has_shap`,
# guarded by a bare `except ImportError`) and DEGRADES to a non-SHAP ranking when it fails.
#
# Measured 2026-09-17: a bare `python` here resolved to /opt/conda/bin/python3.12, which has
# NO `shap` and `xgboost 2.1.4`. That is the exact runtime which made the v3 vintage ship RF
# importances under an XGB label for all 9,240 genes. The daemon ran normally for its whole
# duration and emitted valid-looking parquet — nothing failed. It is reason #2 above one
# layer down: pinning the tree without pinning the interpreter leaves the guarantee half
# built, because the tree cannot supply a dependency.
#
# Overridable so the launcher stays testable against a stub, but it NEVER falls back to a
# PATH lookup: an unusable interpreter is a hard stop, not a silent downgrade.
PYBIN="${DEPMAP_PRECOMPUTE_PYTHON:-$METHODS_REPO/.pixi/envs/default/bin/python}"
if [[ ! -x "$PYBIN" ]]; then
  echo "[launch_daemon] FATAL: no executable interpreter at $PYBIN" >&2
  echo "  Run \`pixi install\` in $METHODS_REPO, or set DEPMAP_PRECOMPUTE_PYTHON." >&2
  exit 2
fi

# Refuse to start unless the ATTRIBUTION dependencies import in THAT interpreter. This is the
# only place the absence can be made loud: downstream `_has_shap` swallows the ImportError by
# design, so the run succeeds and the wrong columns ship. Distinct exit codes (2/3) keep this
# refusal distinguishable from the 2-second liveness failure below, which also exits 1.
if ! "$PYBIN" -c 'import shap, xgboost' >/dev/null 2>&1; then
  echo "[launch_daemon] FATAL: $PYBIN cannot import both shap and xgboost." >&2
  echo "  The run would emit non-SHAP attributions and still look successful." >&2
  exit 3
fi

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
  "$PYBIN" -u -m onc_methods.depmap_predictability_precompute.cli \
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
  # Echo the interpreter, not just the tree: an operator reading this log is the last line of
  # defence against a run whose attribution columns are silently wrong.
  echo "[launch_daemon]   interpreter=$PYBIN"
  echo "[launch_daemon]   Monitor: tail -f $OUT_DIR/daemon.log"
else
  echo "[launch_daemon] ERROR: daemon died within 2s. Check $OUT_DIR/daemon.log"
  exit 1
fi
