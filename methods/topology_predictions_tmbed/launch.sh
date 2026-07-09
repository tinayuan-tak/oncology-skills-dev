#!/usr/bin/env bash
# Full-inference driver: TMbed on ALL UniProt SwissProt human reviewed proteins.
#
# Runs the fetch -> extract -> predict -> reduce -> upload pipeline end-to-end.
# Only launch after a pilot benchmark confirms wall-clock feasibility on the
# target hardware AND the instance has capacity.
#
# Pilot mode:
#   bash launch.sh --pilot 100    # first 100 seqs only; ~7 min CPU
#
# Full mode:
#   nohup bash launch.sh > launch.log 2>&1 &    # ~11-13 hr CPU wall-clock
#
# Prereqs:
#   - AWS_PROFILE=cbg
#   - Adjacent .venv/ with tmbed + biopython + pandas + pyarrow installed
#   - ProtT5 encoder already downloaded (python -m tmbed download)
set -euo pipefail

: "${AWS_PROFILE:=cbg}"
export AWS_PROFILE

SCRIPT_DIR="$(dirname "$(readlink -f "$0")")"
cd "$SCRIPT_DIR"

# Manifest identity — matches the parent UniProt manifest exactly.
PARENT_MANIFEST_ID="uniprot-sprot-human-2026-02-snapshot-2026-06-18"
MANIFEST_ID="topology-predictions-tmbed-v1"
PARENT_S3_URI="s3://onc-compbio/data-catalog/sources/uniprot-sprot-human/2026_02-snapshot-2026-06-18/"
S3_OUT_PREFIX="s3://onc-compbio/data-catalog/derived/${MANIFEST_ID}/"

# Pilot mode
PILOT_N=""
if [[ "${1:-}" == "--pilot" ]]; then
    PILOT_N="$2"
    echo "[launch] PILOT MODE: first ${PILOT_N} sequences"
fi

SCRATCH="${SCRATCH_DIR:-./scratch}"
mkdir -p "$SCRATCH"

DAT_LOCAL="$SCRATCH/uniprot_sprot_human.dat.gz"
FASTA="$SCRATCH/uniprot_sprot_human.fasta"
PRED="$SCRATCH/topology_predictions_tmbed_v1.pred"
PARQUET="$SCRATCH/topology_predictions_tmbed_v1.parquet"

if [[ -n "$PILOT_N" ]]; then
    FASTA="$SCRATCH/pilot_${PILOT_N}.fasta"
    PRED="$SCRATCH/pilot_${PILOT_N}.pred"
    PARQUET="$SCRATCH/pilot_${PILOT_N}.parquet"
fi

echo "[launch] stage A: fetch UniProt DAT from catalog (if not cached)"
if [[ ! -f "$DAT_LOCAL" ]]; then
    aws s3 cp "${PARENT_S3_URI}uniprot_sprot_human.dat.gz" "$DAT_LOCAL"
fi

echo "[launch] stage B: extract cleaned FASTA"
EXTRA=""
[[ -n "$PILOT_N" ]] && EXTRA="--max-records $PILOT_N"
python3 -m methods.topology_predictions_tmbed.prepare_fasta \
    --dat-gz "$DAT_LOCAL" \
    --out-fasta "$FASTA" \
    $EXTRA
grep -c ">" "$FASTA" || true

echo "[launch] stage C: TMbed predict (CPU, 16 threads)"
time python3 -m tmbed predict \
    -f "$FASTA" \
    -p "$PRED" \
    --out-format 3 \
    --no-use-gpu \
    --threads 16

echo "[launch] stage D: reduce .pred -> per-gene Parquet"
python3 -m methods.topology_predictions_tmbed.reduce_predictions \
    --pred "$PRED" \
    --out-parquet "$PARQUET"
ls -lh "$PARQUET"

if [[ -n "$PILOT_N" ]]; then
    echo "[launch] pilot done; skipping S3 upload"
    exit 0
fi

echo "[launch] stage E: upload Parquet + MD5 to S3"
python3 - <<PY
import hashlib, subprocess
from pathlib import Path
p = Path("$PARQUET")
h = hashlib.md5(usedforsecurity=False)
with open(p, "rb") as fh:
    for chunk in iter(lambda: fh.read(1 << 20), b""):
        h.update(chunk)
md5 = h.hexdigest()
print(f"md5={md5} size={p.stat().st_size}")
subprocess.run([
    "aws", "s3", "cp", str(p),
    "${S3_OUT_PREFIX}topology_predictions_tmbed_v1.parquet",
    "--metadata", f"md5={md5}",
], check=True)
PY

echo "[launch] DONE."
