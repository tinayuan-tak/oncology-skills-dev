#!/usr/bin/env bash
# regenerate_corpus.sh — regenerate the target-archetype corpus for a re-freeze.
#
# WHY A REGEN IS A SEPARATE HOP: the atlas builder imports NONE of the claim modules. It reads composed
# PACKAGES off disk (corpus_io.claim_vectors_for_run / archetype_core.claim_features), so a claims-ladder
# change reaches the atlas over TWO hops — regen THEN re-freeze — and the regen must PRECEDE the freeze
# rather than sit beside it in one bundle. Measured for #1371 (the single_arm split): 17530 of 32500
# control-clean claim cells flip (53.9%), 58 of 65 coordinates, 504 of 504 packages. So "the diff looks
# empty, just re-freeze" is not an available branch, and neither is "regen and re-freeze in one PR".
#
# ★★ THIS DRIVER REFUSES RATHER THAN NO-OPS, because the job is multi-hour against live S3 and its
# historical failure mode was a SILENT SUCCESS. Three independent ways it used to burn nothing and look
# fine, all now guarded:
#   1. the panel was DERIVED from the frozen atlas.json — n=297 — instead of describing the corpus being
#      regenerated (n=504), so the run covered the wrong membership and left regen and re-freeze
#      disagreeing about it;
#   2. skip-if-exists then skipped every pre-existing package, so a regen over an existing corpus dir ran
#      zero pairs;
#   3. the completion line printed `0 runs written, 0 failed` and exited 0 — the only warning was gated on
#      `fail > 0`, which a total skip never trips.
# Now: the panel is PINNED or the run is refused, a would-be no-op is refused BEFORE any work, and
# completion is RECONCILED against the panel row count instead of inferred from the absence of errors.
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
#   AWS_PROFILE=cbg bash skills/target-archetype/scripts/regenerate_corpus.sh CORPUS_DIR \
#       --panel ~/dev/target-archetype-corpus-20260914/panel_504.tsv --jobs 4
#
#   --panel PATH   the (target, indication, label) panel defining corpus membership. STRONGLY preferred:
#                  omit it only for a virgin dir, where it is derived from the frozen atlas (see below).
#   --jobs N       parallel workers, 1..4. ★ Parallelism goes THROUGH this script so the guards apply.
#                  An earlier header told you to bypass it with `cut -f1,2 panel.tsv | xargs -P 5`, which
#                  is exactly how you skip every check here. N is CAPPED AT 4: this host runs swap=0 with
#                  vm.overcommit_memory=1, so an overcommit is an OOM-kill or a hard reboot, never a clean
#                  MemoryError — a 6-wide sweep has rebooted it.
#   --resume       allow pre-existing packages and fill only the gaps. Without it, a non-empty corpus dir
#                  is REFUSED: a regen means re-running the pairs, not skipping them.
#   --dry-run      run every guard and print the plan, then stop before any run.py invocation. Needs no S3.
#
#   Timing, from the 504 per-pair durations the n=504 build actually LOGGED (corpus-20260914/logs/driver*.log),
#   not derived from package mtimes: a wall-clock-per-package figure off a PARALLEL run is not a per-pair cost,
#   and reading 36.3 s/package off those mtimes understated the true pair by 3.5x.
#     per pair: min 83s  median 123s  mean 127s  p90 165s  max 222s   ⇒  SERIAL ~17.8 h
#     ideal:    --jobs 2 ~8.9 h    --jobs 3 ~5.9 h    --jobs 4 ~4.5 h
#   ★ --jobs 4 is the CAP, not a safe setting. The reference n=504 build ran 4-wide for 2h37m, hit its 25 G
#     memory floor at 276/504, and had to finish 3-wide (2h27m; 5.09 h total). Budget for that: the recovery
#     loop here is `reconciliation exits 3 and NAMES the gaps` -> re-run with --resume. This driver has no
#     automatic mid-run drain -- the hand-rolled step5 driver that built corpus-20260914 did.
#
# then re-freeze (a SEPARATE step, after this one reports a reconciled completion):
#   python skills/target-archetype/scripts/build_atlas.py \
#     --runs   "$CORPUS_DIR" \
#     --panel  "$CORPUS_DIR/<the same panel>" \
#     --out    skills/target-archetype/atlas/atlas.json --emb-dim 16
#   # build_atlas needs numpy+sklearn (conda-base); the shipped runtime stays pure-stdlib. The embedding-
#   # integrity check in atlas_health gates the re-freeze (every corpus row must re-project onto its coord).
#   # ★ If the corpus changed SIZE, also re-run anchor_separation_test.py for every deferred anchor: the
#   #   p90 NN scale is a property of the corpus, so the bar moves with n.
#
# ── EXIT CODES ──────────────────────────────────────────────────────────────────────────────────────────
#   0  reconciled completion (or a --dry-run whose guards all passed)
#   1  REGEN REFUSED — a pre-flight guard fired; nothing was run
#   2  usage error
#   3  INCOMPLETE — runs happened but the corpus does not cover the panel (named pairs are missing)
#
set -euo pipefail

# ── --run-one re-entry: MUST be first, and it deliberately bypasses the pre-flight guards ───────────────
# This is how --jobs parallelises: xargs re-enters this same script once per pair. The guards already ran
# in the parent, and re-running them per pair would not just be 504× redundant — it would REFUSE, because
# the parent's own completed packages make the dir look dirty to every child after the first.
if [ "${1:-}" = "--run-one" ]; then
    shift
    _t="${1:?--run-one needs TARGET}"; _i="${2:?--run-one needs INDICATION}"; _o="${3:?--run-one needs OUTDIR}"
    _log="${REGEN_LOG_DIR:?--run-one needs REGEN_LOG_DIR exported}/${_t}-${_i}.log"
    if python3 "${REGEN_RUN_PY:?--run-one needs REGEN_RUN_PY exported}" --target "$_t" --indication "$_i" \
        --full-package --emit evidence-package --no-ground --no-risk --no-hypothesis --out "$_o" \
        >"$_log" 2>&1
    then
        echo "  ok:     $_t / $_i"
    else
        # ★ Swallow the per-pair failure on purpose so xargs keeps going: RECONCILIATION is the authority
        #   on completeness, never a per-pair exit code. A 5 h sweep must not die on pair 300 — and a
        #   sweep that dies at 60% with exit 0 is precisely the silent success this driver exists to stop.
        echo "  FAILED: $_t / $_i (log: $_log)" >&2
    fi
    exit 0
fi

# ★ Derive the help text from the header instead of a hardcoded line range: the first version said
#   `sed -n '2,70p'` and had ALREADY rotted past the header into the script body, printing
#   `set -euo pipefail` as if it were documentation. Stop at the first line that is not a comment.
usage() { awk 'NR > 1 && !/^#/ { exit } NR > 1 { sub(/^# ?/, ""); print }' "$0"; }

SKILLS_DIR="$(cd "$(dirname "$0")/../.." && pwd)"          # .../skills
ATLAS="$SKILLS_DIR/target-archetype/atlas/atlas.json"
# ★ REGEN_RUN_PY is a TEST SEAM as well as the child-process handoff: honouring it in the parent lets
#   the guards and the reconciliation be exercised against a stub that writes packages, with no S3
#   and no 2-minute-per-pair cost. Unset (the only way it is ever run for real) it is the real run.py.
RUN="${REGEN_RUN_PY:-$SKILLS_DIR/target-profile/scripts/run.py}"
MAX_JOBS=4

CORPUS_DIR=""; PANEL=""; JOBS=1; RESUME=0; DRY_RUN=0
while [ $# -gt 0 ]; do
    case "$1" in
        --panel)   PANEL="${2:?--panel needs a path}"; shift 2 ;;
        --jobs)    JOBS="${2:?--jobs needs an integer}"; shift 2 ;;
        --resume)  RESUME=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        --*)       echo "usage error: unknown flag $1" >&2; exit 2 ;;
        *)         [ -z "$CORPUS_DIR" ] || { echo "usage error: unexpected extra argument $1" >&2; exit 2; }
                   CORPUS_DIR="$1"; shift ;;
    esac
done
CORPUS_DIR="${CORPUS_DIR:-$HOME/dev/target-archetype-corpus-$(date +%Y%m%d)}"

case "$JOBS" in
    ''|*[!0-9]*) echo "usage error: --jobs must be a positive integer, got '$JOBS'" >&2; exit 2 ;;
esac
[ "$JOBS" -ge 1 ] || { echo "usage error: --jobs must be >= 1, got $JOBS" >&2; exit 2; }
if [ "$JOBS" -gt "$MAX_JOBS" ]; then
    echo "REGEN REFUSED: --jobs $JOBS exceeds the cap of $MAX_JOBS. This host runs swap=0 with" >&2
    echo "  vm.overcommit_memory=1, so an overcommit is an OOM-kill or a hard REBOOT, never a clean" >&2
    echo "  MemoryError -- a 6-wide sweep has rebooted it mid-corpus. Use --jobs $MAX_JOBS or fewer" >&2
    echo "  (2 if other sessions are active). Note $MAX_JOBS is a ceiling against a REBOOT, not a promise" >&2
    echo "  of headroom: the reference n=504 build stalled 4-wide at 276/504 and finished 3-wide." >&2
    exit 1
fi

mkdir -p "$CORPUS_DIR"
export PYTHONPATH="$SKILLS_DIR${PYTHONPATH:+:$PYTHONPATH}"   # run.py imports _skills_common before tp_common

# ── 1. resolve the panel. PINNED, or derived only for a virgin dir. ─────────────────────────────────────
# ★ The panel is corpus MEMBERSHIP, and deriving it from the frozen atlas silently answers a different
#   question: "what did the LAST freeze cover?" rather than "what does THIS corpus contain?". Those
#   diverged the moment the panel expanded 297 -> 504, and the derived answer is the stale one.
shopt -s nullglob
_existing_panels=("$CORPUS_DIR"/panel*.tsv)
shopt -u nullglob
if [ -z "$PANEL" ]; then
    if [ "${#_existing_panels[@]}" -gt 0 ]; then
        echo "REGEN REFUSED: no --panel given, but $CORPUS_DIR already carries ${#_existing_panels[@]}" >&2
        echo "  panel file(s): ${_existing_panels[*]}" >&2
        echo "  Deriving one from the frozen atlas would answer the WRONG question (what the last freeze" >&2
        echo "  covered, not what this corpus contains) and could disagree with every package on disk." >&2
        echo "  Pass --panel <one of the above> explicitly." >&2
        exit 1
    fi
    PANEL="$CORPUS_DIR/panel.tsv"
    echo "no --panel given and $CORPUS_DIR is virgin => deriving membership from the frozen atlas"
    # ★ THREE tab-separated columns, NO header: build_atlas._load_panel only accepts len(parts) == 3 rows,
    #   so a 2-column panel (or a header line) silently degrades EVERY curated label to "?" — the build
    #   still succeeds, but meta.classes collapses and the curated/soft-label distinction is lost.
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
meta = d.get("meta") or {}
# ★ Print the PROVENANCE of the derived panel, so an operator can see at a glance whether it describes the
#   corpus they meant. The shipped atlas is n=297 off corpus-20260911; a 504-package corpus is NOT that.
print(f"panel: {len(rows)} rows ({n_lab} curated labels) derived from atlas "
      f"corpus={meta.get('corpus')!r} build_date={meta.get('build_date')!r} -> {out}")
PY
else
    [ -f "$PANEL" ] || { echo "REGEN REFUSED: --panel $PANEL does not exist" >&2; exit 1; }
    echo "panel (pinned): $PANEL"
fi

# ── 2. pre-flight: validate the panel, prove it describes THIS corpus, and refuse a would-be no-op ──────
TODO="$(mktemp)"; trap 'rm -f "$TODO"' EXIT
python3 - "$CORPUS_DIR" "$PANEL" "$TODO" "$RESUME" <<'PY'
import os, sys

corpus, panel, todo_out, resume = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] == "1"


def die(msg: str) -> None:
    sys.stderr.write("REGEN REFUSED: " + msg + "\n")
    raise SystemExit(1)


rows, bad = [], []
with open(panel) as fh:
    for lineno, line in enumerate(fh, 1):
        if not line.strip():
            continue
        parts = line.rstrip("\n").split("\t")
        (rows if len(parts) == 3 else bad).append((lineno, parts))
if bad:
    lineno, parts = bad[0]
    die(
        f"{panel} has {len(bad)} row(s) that are not 3 tab-separated columns (first: line {lineno} has "
        f"{len(parts)}). build_atlas._load_panel accepts ONLY len(parts) == 3, so a 2-column panel or a "
        f"header line degrades EVERY curated label to '?' -- the build still SUCCEEDS while meta.classes "
        f"collapses, which is why this is a refusal here and not a warning later."
    )
if not rows:
    die(f"{panel} has no usable rows")

pairs = [(p[0], p[1]) for _, p in rows]
seen, dups = set(), []
for p in pairs:
    if p in seen:
        dups.append(p)
    else:
        seen.add(p)
if dups:
    die(f"{panel} has {len(dups)} duplicate (target, indication) pair(s), first {dups[0]} -- a duplicated "
        f"row makes the reconciliation count below unachievable and double-books a multi-hour slot")

want = {f"{t}-{i}": (t, i) for t, i in pairs}
have = {d for d in os.listdir(corpus) if os.path.isfile(os.path.join(corpus, d, "evidence_package.json"))}

# ★ THE 297-OVER-504 CATCH. If the corpus holds packages the panel does not name, the panel is not
#   describing this corpus -- regen would cover one membership and the re-freeze another.
uncovered = sorted(have - set(want))
if uncovered:
    die(
        f"the panel does not describe this corpus: {len(uncovered)} existing package(s) are absent from "
        f"{os.path.basename(panel)} ({len(want)} rows), e.g. {uncovered[:5]}. This is exactly what a "
        f"297-row panel over a 504-package corpus looks like, and it would leave the regen and the "
        f"re-freeze disagreeing about membership. Pass --panel for the panel this corpus was built from."
    )

todo = [(t, i, lab) for _, (t, i, lab) in rows if f"{t}-{i}" not in have]

if have and not resume:
    if not todo:
        die(
            f"all {len(want)} panel rows already have an evidence_package.json under {corpus}. A REGEN "
            f"means RE-RUNNING them, and skip-if-exists would instead report `0 runs written, 0 failed` "
            f"and exit 0 -- burning nothing while looking fine. Point --out at a FRESH dir for the new "
            f"SHA, or pass --resume if you only meant to fill gaps."
        )
    die(
        f"{len(have)} of {len(want)} packages already exist under {corpus}, so this run would SKIP them "
        f"and regenerate only the {len(todo)} remaining -- yielding a corpus MIXED across two code "
        f"versions, which is unusable for a freeze and undetectable in the artefact. Use a FRESH dir, or "
        f"pass --resume if these packages are already at the target SHA and you are filling gaps."
    )

with open(todo_out, "w") as fh:
    for t, i, _ in todo:
        fh.write(f"{t}\t{i}\n")

print(f"pre-flight OK: panel {len(want)} rows | present {len(have)} | to run {len(todo)}")
if resume and not todo:
    print("nothing to do: every panel row already has a package (--resume)")
PY

TODO_N=$(wc -l < "$TODO" | tr -d ' ')
PANEL_N=$(awk 'NF' "$PANEL" | wc -l | tr -d ' ')

if [ "$DRY_RUN" = "1" ]; then
    echo "--dry-run: guards passed, would run $TODO_N of $PANEL_N pairs at --jobs $JOBS into $CORPUS_DIR"
    exit 0
fi
if [ "$TODO_N" = "0" ]; then
    echo "corpus already complete: $PANEL_N of $PANEL_N panel rows have evidence_package.json"
    exit 0
fi

# ── 3. run the composed --full-package profile for each pair still needed ───────────────────────────────
# ★ DETERMINISTIC SPINE ONLY (--no-ground/--no-risk/--no-hypothesis): the substrate chain runs AFTER the
#   fan-out, OVER the already-assembled package, so it cannot touch the claim vectors or card summaries the
#   atlas reads — and the axes it feeds (literature_context, translational_readiness) are excluded from the
#   frozen feature space anyway. VERIFIED on EGFR/LUAD 2026-09-11: grounded vs suppressed produced an
#   IDENTICAL 182-feature vector and identical sub-verdicts, at 2m20s instead of ~20min per pair (no
#   Bedrock, no PubMed, no network nondeterminism → the corpus is replayable).
export REGEN_RUN_PY="$RUN"
export REGEN_LOG_DIR="$CORPUS_DIR/logs"
mkdir -p "$REGEN_LOG_DIR"
echo "running $TODO_N pairs at --jobs $JOBS (logs under $REGEN_LOG_DIR)"
# ★ `|| true`: xargs exits 123 if any child failed, but per-pair failures are already swallowed above and
#   completeness is decided by the reconciliation below. Letting `set -e` kill the script here would turn a
#   single bad pair into a lost sweep.
awk -F'\t' 'NF==2 {printf "%s\n%s\n", $1, $2}' "$TODO" \
  | xargs -P "$JOBS" -n 2 -d '\n' -- bash -c 'exec bash "$0" --run-one "$1" "$2" "'"$CORPUS_DIR"'/$1-$2"' "$0" || true

# ── 4. reconcile. The completion line is a COUNT against the panel, not the absence of errors. ──────────
python3 - "$CORPUS_DIR" "$PANEL" <<'PY'
import os, sys

corpus, panel = sys.argv[1], sys.argv[2]
want = []
with open(panel) as fh:
    for line in fh:
        if not line.strip():
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 3:
            want.append(f"{parts[0]}-{parts[1]}")
missing = [k for k in want if not os.path.isfile(os.path.join(corpus, k, "evidence_package.json"))]
if missing:
    sys.stderr.write(
        f"INCOMPLETE: {len(want) - len(missing)} of {len(want)} panel rows have an evidence_package.json; "
        f"{len(missing)} MISSING: {missing[:20]}{' ...' if len(missing) > 20 else ''}\n"
        f"corpus_io silently skips runs with no harvestable claim vectors, so a freeze over this corpus "
        f"would quietly cover {len(want) - len(missing)} rows while the panel claims {len(want)}. "
        f"Re-run with --resume to fill the gaps, and check the per-pair logs under {corpus}/logs.\n"
    )
    raise SystemExit(3)
print(f"corpus regen COMPLETE and reconciled: {len(want)} of {len(want)} panel rows have "
      f"evidence_package.json under {corpus}")
PY
