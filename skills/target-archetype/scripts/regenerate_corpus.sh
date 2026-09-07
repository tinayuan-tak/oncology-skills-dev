#!/usr/bin/env bash
# regenerate_corpus.sh — regenerate the target-archetype corpus for a re-freeze (Phase 1d).
#
# WHY: the original ~660-run corpus (~/dev/tumor-presence-audit-2026-08-26/) no longer exists on disk, and
# the richer-substrate re-freeze needs a fresh corpus of composed --full-package --ground runs that also
# carry the NUMERIC card summaries the new feature_vectoriser reads (the old corpus predates them). This
# script rebuilds that corpus from the SAME 213 (target, indication) pairs the current atlas froze over —
# reconstructed directly from atlas.json (its targets[]/indications[] arrays ARE the corpus membership) so
# the re-freeze stays comparable to the shipped model.
#
# ── CREDENTIALS / INTERPRETER (must be set by the human runner — this needs live S3 + Bedrock) ──────────
#   export AWS_PROFILE=cbg                       # onc-compbio bucket (the --ground reads live data products)
#   # --ground grounding calls Bedrock; use the interpreter that has `anthropic` on PATH (the pixi env does
#   # NOT). If a run errors on a missing `anthropic`/Bedrock client, run with system python + the grounding
#   # creds your environment uses for --synthesize (e.g. BEDROCK_AWS_PROFILE=cmp-dev). Confirm one target
#   # end-to-end before launching the full sweep.
#
# ── USAGE ───────────────────────────────────────────────────────────────────────────────────────────────
#   cd ~/rnd-computational-biology-oncology-claude-oncology-skills            # run from the HOME checkout
#   AWS_PROFILE=cbg bash skills/target-archetype/scripts/regenerate_corpus.sh [CORPUS_DIR]
# then re-freeze:
#   python skills/target-archetype/scripts/build_atlas.py \
#     --runs   "$CORPUS_DIR" \
#     --panel  "$CORPUS_DIR/panel.tsv" \
#     --out    skills/target-archetype/atlas/atlas.json --emb-dim 16
#   # build_atlas needs numpy+sklearn (conda-base); the shipped runtime stays pure-stdlib. The embedding-
#   # integrity check in atlas_health gates the re-freeze (every corpus row must re-project onto its coord).
#
set -euo pipefail

SKILLS_DIR="$(cd "$(dirname "$0")/../.." && pwd)"          # .../skills
ATLAS="$SKILLS_DIR/target-archetype/atlas/atlas.json"
CORPUS_DIR="${1:-$HOME/dev/target-archetype-corpus-$(date +%Y%m%d)}"
PANEL="$CORPUS_DIR/panel.tsv"
RUN="$SKILLS_DIR/target-profile/scripts/run.py"

mkdir -p "$CORPUS_DIR"

# 1. reconstruct the (target, indication) panel from the frozen atlas (the exact corpus membership).
python3 - "$ATLAS" "$PANEL" <<'PY'
import json, sys
atlas, out = sys.argv[1], sys.argv[2]
d = json.load(open(atlas))
pairs = list(zip(d["targets"], d["indications"]))
with open(out, "w") as fh:
    fh.write("target\tindication\n")
    for t, i in pairs:
        fh.write(f"{t}\t{i}\n")
print(f"panel: {len(pairs)} (target, indication) pairs -> {out}")
PY

# 2. run the composed --full-package --ground profile for each pair, emitting evidence_package.json.
#    corpus_io.iter_corpus_runs (the layout-tolerant reader from PR #1142) reads these back for build_atlas.
n=0; fail=0
while IFS=$'\t' read -r target indication; do
    [ "$target" = "target" ] && continue                  # header
    run_dir="$CORPUS_DIR/${target}-${indication}"
    if [ -f "$run_dir/evidence_package.json" ]; then
        echo "skip (exists): $target/$indication"; continue     # resumable — safe to re-run
    fi
    echo "run: $target / $indication"
    if python3 "$RUN" --target "$target" --indication "$indication" \
        --full-package --ground --emit evidence-package --out "$run_dir" ; then
        n=$((n+1))
    else
        echo "  FAILED: $target/$indication" >&2; fail=$((fail+1))
    fi
done < "$PANEL"

echo "corpus regen complete: $n runs written, $fail failed, under $CORPUS_DIR"
[ "$fail" -eq 0 ] || echo "WARNING: $fail runs failed — corpus_io skips runs with no harvestable claim vectors; investigate before re-freezing."
