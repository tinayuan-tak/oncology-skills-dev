#!/usr/bin/env bash
# regenerate_corpus.sh — regenerate the target-archetype corpus for a re-freeze (Phase 1d).
#
# WHY: the original ~660-run corpus (~/dev/tumor-presence-audit-2026-08-26/) no longer exists on disk, and
# the richer-substrate re-freeze needs a fresh corpus of composed --full-package runs that also carry the
# NUMERIC card summaries the new feature_vectoriser reads (the old corpus predates them). This script
# rebuilds that corpus from the SAME 213 (target, indication) pairs the current atlas froze over —
# reconstructed directly from atlas.json (its targets[]/indications[]/labels[] arrays ARE the corpus
# membership) so the re-freeze stays comparable to the shipped model.
#
# ── CREDENTIALS / INTERPRETER (this needs live S3; it does NOT need Bedrock) ─────────────────────────────
#   export AWS_PROFILE=cbg      # onc-compbio bucket — the card reads hit live data products
#   The runs are LLM-free (--emit evidence-package + the substrate chain suppressed), so no Bedrock creds
#   and no `anthropic` are required. Use the pixi env (the CI-validated interpreter): a bare/conda python
#   silently drops card reads (openpyxl/lifelines/pyreadr/gseapy) and a sub-verdict can FLIP.
#   run.py needs `PYTHONPATH=<skills root>` — its `from _skills_common import …` is above the sys.path
#   bootstrap in tp_common — so this script exports it for you.
#
# ── USAGE ───────────────────────────────────────────────────────────────────────────────────────────────
#   cd ~/rnd-computational-biology-oncology-claude-oncology-skills            # run from the HOME checkout
#   AWS_PROFILE=cbg bash skills/target-archetype/scripts/regenerate_corpus.sh [CORPUS_DIR]
#   # ~2m20s per pair => ~8h serial for 213. To parallelise, feed `cut -f1,2 panel.tsv` to
#   # `xargs -P 5` over the same run.py invocation (the per-pair skip-if-exists makes it resumable);
#   # 5 workers on a 16-core box finished the 213-pair sweep in well under 2h.
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
export PYTHONPATH="$SKILLS_DIR${PYTHONPATH:+:$PYTHONPATH}"   # run.py imports _skills_common before tp_common

mkdir -p "$CORPUS_DIR"

# 1. reconstruct the (target, indication) panel from the frozen atlas (the exact corpus membership).
#    ★ THREE tab-separated columns, NO header: build_atlas._load_panel only accepts len(parts) == 3 rows,
#    so a 2-column panel (or a header line) silently degrades EVERY curated label to "?" — the build still
#    succeeds, but meta.classes collapses and the curated/soft-label distinction is lost. The labels are
#    carried forward from the frozen atlas so the re-freeze stays comparable to the shipped model.
python3 - "$ATLAS" "$PANEL" <<'PY'
import json, sys
atlas, out = sys.argv[1], sys.argv[2]
d = json.load(open(atlas))
labels = d.get("labels") or ["?"] * len(d["targets"])
rows = list(zip(d["targets"], d["indications"], labels))
with open(out, "w") as fh:
    for t, i, lab in rows:
        fh.write(f"{t}\t{i}\t{lab}\n")
n_lab = sum(1 for _, _, lab in rows if lab != "?")
print(f"panel: {len(rows)} (target, indication, label) rows ({n_lab} curated labels) -> {out}")
PY

# 2. run the composed --full-package profile for each pair, emitting evidence_package.json.
#    corpus_io.iter_corpus_runs (the layout-tolerant reader from PR #1142) reads these back for build_atlas.
#    ★ DETERMINISTIC SPINE ONLY (--no-ground/--no-risk/--no-hypothesis): the substrate chain runs AFTER the
#    fan-out, OVER the already-assembled package, so it cannot touch the claim vectors or card summaries the
#    atlas reads — and the axes it feeds (literature_context, translational_readiness) are excluded from the
#    frozen feature space anyway. VERIFIED on EGFR/LUAD 2026-09-11: grounded vs suppressed produced an
#    IDENTICAL 182-feature vector and identical sub-verdicts, at 2m20s instead of ~20min per pair (no
#    Bedrock, no PubMed, no network nondeterminism → the corpus is replayable).
n=0; fail=0
while IFS=$'\t' read -r target indication label; do
    [ -z "${target:-}" ] && continue
    run_dir="$CORPUS_DIR/${target}-${indication}"
    if [ -f "$run_dir/evidence_package.json" ]; then
        echo "skip (exists): $target/$indication"; continue     # resumable — safe to re-run
    fi
    echo "run: $target / $indication"
    if python3 "$RUN" --target "$target" --indication "$indication" \
        --full-package --emit evidence-package --no-ground --no-risk --no-hypothesis --out "$run_dir" ; then
        n=$((n+1))
    else
        echo "  FAILED: $target/$indication" >&2; fail=$((fail+1))
    fi
done < "$PANEL"

echo "corpus regen complete: $n runs written, $fail failed, under $CORPUS_DIR"
[ "$fail" -eq 0 ] || echo "WARNING: $fail runs failed — corpus_io skips runs with no harvestable claim vectors; investigate before re-freezing."
