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
#   --mem-floor G  SOFT floor, default 35. Below it the sweep DRAINS: it stops launching new pairs and lets
#                  the in-flight ones finish. Costs wall clock, never a pair.
#   --mem-hard G   HARD floor, default 15. Below it the largest in-flight worker is SACRIFICED (SIGKILL) so
#                  the HOST survives. Costs exactly one pair, which reconciliation names and --resume refills.
#   --mem-drain-timeout S  default 900. If the soft floor stays breached this long, stop feeding altogether
#                  and let the sweep end INCOMPLETE (exit 3) rather than wait forever. --resume continues it.
#   --mem-max-sacrifice N  default 10. Past N sacrifices the watchdog stops killing and halts the feed
#                  instead: repeated sacrifice means --jobs is wrong, and shredding pair after pair would
#                  trade a recoverable stall for a corpus full of holes.
#   --mem-poll S   default 10. Sampling interval for both floors.
#   --no-mem-guard disable both floors. For a machine where /proc/meminfo headroom is not the binding
#                  constraint, or to reproduce the pre-guard behaviour in a test.
#
#   Timing, from the 504 per-pair durations the n=504 build actually LOGGED (corpus-20260914/logs/driver*.log),
#   not derived from package mtimes: a wall-clock-per-package figure off a PARALLEL run is not a per-pair cost,
#   and reading 36.3 s/package off those mtimes understated the true pair by 3.5x.
#     per pair: min 83s  median 123s  mean 127s  p90 165s  max 222s   ⇒  SERIAL ~17.8 h
#     ideal:    --jobs 2 ~8.9 h    --jobs 3 ~5.9 h    --jobs 4 ~4.5 h
#   ★ --jobs 4 is the CAP, not a safe setting. The reference n=504 build ran 4-wide for 2h37m, hit its 25 G
#     memory floor at 276/504, and had to finish 3-wide (2h27m; 5.09 h total). Budget for that: the recovery
#     loop here is `reconciliation exits 3 and NAMES the gaps` -> re-run with --resume.
#
# ── MEMORY: WHY THE GUARD IS AGGREGATE AND NOT PER-WORKER ────────────────────────────────────────────────
# The obvious hardening is a per-worker RSS cap. It is the wrong shape for this failure mode, and both
# mechanisms for imposing one are unavailable here anyway. Measured, not assumed:
#
#   1. THE FAILURE IS A COINCIDENCE OF ORDINARY PAIRS, NOT ONE MONSTER. The 95 G peak on the n=504
#      reference build was four pairs at the 83rd-90th DURATION percentiles running at once, ~24 G each,
#      and ALL FOUR COMPLETED SUCCESSFULLY. So a per-worker ceiling high enough to admit a legitimate pair
#      cannot fire on a collision of legitimate pairs, and one low enough to fire would have killed four
#      good runs. Package SIZE does not predict the spike either (all four sat near the 2461 KB median).
#      The scarce resource is an aggregate, so the guard reads and acts on the aggregate.
#   2. cgroup `memory.max` IS NOT AVAILABLE to this uid. The memory controller is listed in
#      cgroup.controllers -- which is what makes it look available -- but cgroup.subtree_control is EMPTY,
#      mkdir of a child cgroup is EACCES, and CapEff is 0. `systemd-run --scope -p MemoryMax` cannot work
#      either: the binary is on PATH but /run/systemd/system does not exist, so no systemd is running.
#      A PRESENT CONTROLLER IS NOT A DELEGATED ONE.
#   3. `ulimit -v` (RLIMIT_AS) CANNOT EXPRESS AN RSS BUDGET. Live workers here run VSZ/RSS of 3.3-3.8x
#      (22.6 G of address space against 6.9 G resident) from per-thread malloc arenas and BLAS
#      reservations across 32 cores. Admitting a legitimate pair needs -v near 23 G, and RLIMIT_AS bounds
#      ADDRESS SPACE, not resident pages -- so that same worker can then fault in ~20 G without tripping
#      it. The cap that admits legitimate work permits an RSS 3x what it was meant to bound.
#      `ulimit -m` (RLIMIT_RSS) is worse still: Linux has ignored it since 2.4.
#
# So: two aggregate floors off /proc/meminfo MemAvailable. The soft floor DRAINS (the mechanism that
# carried the hand-rolled step5 driver through that 95 G spike) and the hard floor SACRIFICES the largest
# in-flight worker. Note that NO single floor can be both non-firing and worst-case-proof: at --jobs 3
# three in-flight median pairs (~5.75 G) can each grow to ~24 G, so the worst case is ~55 G of new demand
# after the drain begins, which is more headroom than a 3-wide run ever actually has. That gap is exactly
# why the hard floor exists -- the soft floor can be crossed faster than in-flight pairs can finish.
#
# ★ THE SACRIFICE IS ONLY SAFE BECAUSE A FAILED PAIR NOW LEAVES NO PACKAGE BEHIND. tp_evidence_package
#   persists with `out_path.write_text(json.dumps(...))` -- a truncate-then-write, not an atomic rename --
#   so a worker killed mid-write leaves a TRUNCATED evidence_package.json, and the reconciliation below
#   used to test `isfile` alone. That combination would have turned "sacrifice one pair" into a silently
#   CORRUPT corpus, which is strictly worse than the reboot it prevents. Two changes close it: --run-one
#   deletes an UNPARSEABLE package after a failed run (and only an unparseable one -- run.py does more work
#   after the write, so a late failure can still leave a GOOD package that must be kept), and the
#   reconciliation now requires every package to PARSE, not merely exist. The second half also catches
#   partial writes this driver did not cause: a reboot, a host OOM-kill, or a full disk.
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
#   3  INCOMPLETE — runs happened but the corpus does not cover the panel (named pairs are missing).
#      Also the deliberate landing place for BOTH memory outcomes: a pair sacrificed at the hard floor, and
#      a drain that timed out. Neither is a special exit code, because the recovery is identical and
#      already built: the reconciliation NAMES the gaps and --resume refills them.
#
set -euo pipefail

# ── --run-one re-entry: MUST be first, and it deliberately bypasses the pre-flight guards ───────────────
# This is how --jobs parallelises: the dispatch loop re-enters this same script once per pair. The guards
# already ran
# in the parent, and re-running them per pair would not just be 504× redundant — it would REFUSE, because the
# parent's own completed packages make the dir look dirty to every child after the first.
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
        # ★ Swallow the per-pair failure on purpose so the sweep keeps going: RECONCILIATION is the authority
        #   on completeness, never a per-pair exit code. A 5 h sweep must not die on pair 300 — and a
        #   sweep that dies at 60% with exit 0 is precisely the silent success this driver exists to stop.
        echo "  FAILED: $_t / $_i (log: $_log)" >&2
        # ★ REMOVE A TRUNCATED PACKAGE, AND ONLY A TRUNCATED ONE. The writer is
        #   `out_path.write_text(json.dumps(...))` — a truncate-then-write, not an atomic rename — so a
        #   worker that dies mid-write (the hard floor below, a host OOM-kill, a reboot, a full disk) leaves
        #   a file that EXISTS and does not parse. The reconciliation keys on presence, so that file would
        #   be counted as a finished pair and frozen into the atlas. Deleting unconditionally on failure
        #   would be wrong in the OTHER direction: run.py keeps working after the write (the --full-package
        #   review bundle), so a LATE failure can leave a perfectly good package that must survive.
        _pkg="$_o/evidence_package.json"
        if [ -f "$_pkg" ] && ! python3 -c 'import json,sys; json.load(open(sys.argv[1]))' "$_pkg" 2>/dev/null
        then
            rm -f "$_pkg"
            echo "  PURGED: $_t / $_i left an UNPARSEABLE evidence_package.json (removed so the" >&2
            echo "          reconciliation reports it missing instead of complete; --resume refills it)" >&2
        fi
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
# ★ TEST SEAMS FOR THE MEMORY GUARD, in the same spirit as REGEN_RUN_PY. Without them the drain and the
#   sacrifice are only reachable by actually exhausting a 124 G box, so they would ship ungated — and this
#   driver has NO shell linting in CI, which makes its test file the only gate it has. REGEN_MEMINFO points
#   the floors at a writable meminfo-shaped file, so a stub run.py can simulate pressure ARRIVING and
#   LIFTING mid-sweep; REGEN_MEM_MIN_KILL_KB lowers the GiB-scale sacrifice threshold so a cheap stub worker
#   can stand in for a 24 G one. Neither is referenced by the real invocation path.
MEMINFO="${REGEN_MEMINFO:-/proc/meminfo}"
MEM_MIN_KILL_KB="${REGEN_MEM_MIN_KILL_KB:-1048576}"

# ── memory-guard defaults, derived from the 913-sample monitor log of the n=504 reference build ──────────
#   3-wide measured: min MemAvailable 60 G, peak workers_rss 56 G.  4-wide: min 20 G, peak 95 G.  Box 124 G.
#   35 sits below anything a 3-wide run reached, so the soft floor does not fire on healthy work, and leaves
#   room for roughly one more p90 pair (~24 G) to grow before the hard floor. 15 is the sacrifice point: the
#   cgroup high-water mark for this box is 118 G of 124 G, so the observed worst case came within ~6 G.
#   The floors are ABSOLUTE and calibrated to the WORKLOAD, not scaled to the box: what has to fit is one
#   more p90 pair (~24 G), and that size is a property of run.py, not of MemTotal. A percentage-of-MemTotal
#   default would look portable and mean nothing. Where the box is too small for the default floor to be
#   workable the guard says so LOUDLY and disables (see below) rather than refusing every run.
MEM_FLOOR_G=35; MEM_HARD_G=15; MEM_DRAIN_TIMEOUT=900; MEM_POLL=10; MEM_GUARD=1; MEM_MAX_SACRIFICE=10
MEM_FLOOR_EXPLICIT=0
MEM_P90_PAIR_G=24        # measured p90 worker RSS; the headroom the soft floor is meant to preserve

CORPUS_DIR=""; PANEL=""; JOBS=1; RESUME=0; DRY_RUN=0
while [ $# -gt 0 ]; do
    case "$1" in
        --panel)   PANEL="${2:?--panel needs a path}"; shift 2 ;;
        --jobs)    JOBS="${2:?--jobs needs an integer}"; shift 2 ;;
        --resume)  RESUME=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        --mem-floor) MEM_FLOOR_G="${2:?--mem-floor needs an integer (GiB)}"; MEM_FLOOR_EXPLICIT=1; shift 2 ;;
        --mem-hard)  MEM_HARD_G="${2:?--mem-hard needs an integer (GiB)}"; shift 2 ;;
        --mem-drain-timeout) MEM_DRAIN_TIMEOUT="${2:?--mem-drain-timeout needs an integer (seconds)}"; shift 2 ;;
        --mem-max-sacrifice) MEM_MAX_SACRIFICE="${2:?--mem-max-sacrifice needs an integer}"; shift 2 ;;
        --mem-poll) MEM_POLL="${2:?--mem-poll needs an integer (seconds)}"; shift 2 ;;
        --no-mem-guard) MEM_GUARD=0; shift ;;
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

# ── memory-guard validation ─────────────────────────────────────────────────────────────────────────────
_mem_avail_g() { awk '/^MemAvailable:/ { printf "%d", $2 / 1048576 }' "$MEMINFO"; }
_mem_total_g() { awk '/^MemTotal:/ { printf "%d", $2 / 1048576 }' "$MEMINFO"; }

# ★ AUTO-DISABLE ON A BOX TOO SMALL FOR THE DEFAULT FLOOR, LOUDLY. The floor only makes sense if the box
#   can hold it PLUS a p90 pair; below that every run would trip the already-below-floor refusal and the
#   guard would be a blanket "no", which is not protection, it is breakage. This is deliberately noisy
#   rather than silent — a safety guard that switches itself off quietly is the fail-open shape this driver
#   exists to eliminate. It applies ONLY to the default: an explicit --mem-floor is always honoured, so an
#   operator on a small box can still opt into a floor that suits it.
if [ "$MEM_GUARD" = "1" ] && [ "$MEM_FLOOR_EXPLICIT" = "0" ] && [ -r "$MEMINFO" ]; then
    _total="$(_mem_total_g)"
    if [ "${_total:-0}" -lt "$((MEM_FLOOR_G + MEM_P90_PAIR_G))" ]; then
        echo "★ MEMORY GUARD AUTO-DISABLED: MemTotal is ${_total} G, below the default floor ${MEM_FLOOR_G} G" >&2
        echo "  plus one p90 pair (${MEM_P90_PAIR_G} G). These floors are calibrated for the ~124 G host this" >&2
        echo "  driver was written for; on this box they would refuse every run instead of protecting it." >&2
        echo "  If you mean to run a real sweep here, use --jobs 1 and pass an explicit --mem-floor, which is" >&2
        echo "  always honoured." >&2
        MEM_GUARD=0
    fi
fi

if [ "$MEM_GUARD" = "1" ]; then
    for _v in MEM_FLOOR_G MEM_HARD_G MEM_DRAIN_TIMEOUT MEM_MAX_SACRIFICE MEM_POLL; do
        eval "_val=\$$_v"
        case "$_val" in
            ''|*[!0-9]*) echo "usage error: $_v must be a non-negative integer, got '$_val'" >&2; exit 2 ;;
        esac
    done
    [ "$MEM_POLL" -ge 1 ] || { echo "usage error: --mem-poll must be >= 1, got $MEM_POLL" >&2; exit 2; }
    if [ "$MEM_HARD_G" -ge "$MEM_FLOOR_G" ]; then
        echo "usage error: --mem-hard $MEM_HARD_G must be BELOW --mem-floor $MEM_FLOOR_G. The floors are" >&2
        echo "  ordered on purpose: the soft floor buys time by draining, and the hard floor spends a pair" >&2
        echo "  only once draining has failed. Inverted, the sweep would sacrifice pairs it never tried to" >&2
        echo "  save." >&2
        exit 2
    fi
    if [ ! -r "$MEMINFO" ]; then
        echo "REGEN REFUSED: --mem-floor was requested but $MEMINFO is unreadable, so the guard would" >&2
        echo "  silently never fire. Pass --no-mem-guard to run unguarded, deliberately." >&2
        exit 1
    fi
    _avail_now="$(_mem_avail_g)"
    # ★ REFUSE A FLOOR THAT IS ALREADY BREACHED. Otherwise the feed gate blocks on pair 1 and the sweep
    #   drains for --mem-drain-timeout before ending INCOMPLETE having run NOTHING: a guard that presents as
    #   protection while producing the same empty corpus this driver exists to prevent. Same family as the
    #   skip-all refusal — the failure mode is a confident no-op, so it is caught before any work.
    if [ "$_avail_now" -lt "$MEM_FLOOR_G" ]; then
        echo "REGEN REFUSED: MemAvailable is ${_avail_now} G, already below --mem-floor ${MEM_FLOOR_G} G, so" >&2
        echo "  the sweep would drain from pair 1 and finish INCOMPLETE having run nothing. Either wait for" >&2
        echo "  the box (check for peer sessions: ps -eo rss,args --sort=-rss | head), lower --mem-floor" >&2
        echo "  deliberately, or pass --no-mem-guard." >&2
        exit 1
    fi
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
import json, os, sys

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
present = {d for d in os.listdir(corpus) if os.path.isfile(os.path.join(corpus, d, "evidence_package.json"))}

# ★ PRESENT AND USABLE ARE DIFFERENT SETS, and conflating them makes --resume unable to heal. The package
#   is written by a truncate-then-write, so a death mid-write leaves a file that EXISTS and is truncated.
#   Keyed on presence, skip-if-exists would skip that pair on EVERY subsequent --resume and freeze the
#   truncated package in permanently. So `usable` (parses) drives what to run, while `present` drives the
#   membership check below -- a stray corrupt package still has to be explained by the panel.
unusable = {}
for d in sorted(present):
    p = os.path.join(corpus, d, "evidence_package.json")
    try:
        with open(p) as fh:
            json.load(fh)
    except Exception as exc:
        unusable[d] = f"{type(exc).__name__}: {exc}"[:100]
have = present - set(unusable)
if unusable:
    sys.stderr.write(
        f"note: {len(unusable)} existing package(s) do not parse and will be RE-RUN rather than skipped "
        f"(truncated write -- a mid-write kill, host reboot or full disk): "
        f"{sorted(unusable)[:5]}{' ...' if len(unusable) > 5 else ''}\n"
    )

# ★ THE 297-OVER-504 CATCH. If the corpus holds packages the panel does not name, the panel is not
#   describing this corpus -- regen would cover one membership and the re-freeze another.
uncovered = sorted(present - set(want))
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

print(
    f"pre-flight OK: panel {len(want)} rows | present {len(present)} | usable {len(have)} | "
    f"to run {len(todo)}"
)
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
MEM_LOG="$REGEN_LOG_DIR/memory-guard.log"
MEM_HALT="$REGEN_LOG_DIR/.mem-halt"
rm -f "$MEM_HALT"

_mem_ts() { date -u +%Y-%m-%dT%H:%M:%SZ; }

# ── the worker census the guard acts on ─────────────────────────────────────────────────────────────────
# Print "<rss_kb> <pid>" for every DESCENDANT of $1, largest first.
# ★ DESCENDANTS OF OUR OWN PID, NEVER A PATTERN MATCH ON argv. `pkill -f run.py` and `pgrep -f run.py`
#   would both match a PEER SESSION's workers on this shared box — and `pkill -f` additionally matches its
#   own command line, so it kills the shell that invoked it. Killing a peer's multi-hour run is the one
#   outcome strictly worse than rebooting our own sweep, so the census is structural (a ppid walk) rather
#   than textual. It follows that this guard is safe to run while other sessions are working.
_regen_workers_by_rss() {
    awk -v root="$1" '
      FNR == 1 {
        # /proc/<pid>/stat is "PID (comm) STATE PPID ...". comm can contain spaces AND parentheses, so
        # anchor on the LAST ") " instead of splitting on whitespace, which is the classic parse bug here.
        if (match($0, /^[0-9]+ \(.*\) /) == 0) next
        pid  = substr($0, 1, index($0, " ") - 1)
        rest = substr($0, RSTART + RLENGTH)
        if (split(rest, f, " ") < 22) next
        ppid[pid] = f[2]
        rss[pid]  = f[22] * 4                       # field 22 is RSS in PAGES; 4 KiB pages -> KiB
        pids[++np] = pid
      }
      END {
        for (i = 1; i <= np; i++) {
          p = pids[i]
          if (p == root) continue                   # the driver itself is not a candidate
          q = p; d = 0
          while (q != "" && q != "0" && d++ < 64) { # bounded: a ppid cycle must not hang the guard
            if (q == root) { print rss[p] " " p; break }
            q = ppid[q]
          }
        }
      }
    ' /proc/[0-9]*/stat 2>/dev/null | sort -rn
}

# ── the HARD floor: sacrifice the largest in-flight worker so the HOST survives ─────────────────────────
_mem_watchdog() {
    local root="$1" sacrificed=0
    while :; do
        sleep "$MEM_POLL"
        kill -0 "$root" 2>/dev/null || return 0            # dispatch finished; nothing left to guard
        local avail; avail="$(_mem_avail_g)"
        [ "${avail:-999}" -lt "$MEM_HARD_G" ] || continue
        local line rss pid
        line="$(_regen_workers_by_rss "$root" | head -1 || true)"
        rss="${line%% *}"; pid="${line##* }"
        # ★ Require a GiB-scale target. Below that the largest descendant is bookkeeping (a bash re-entry,
        #   this watchdog's own awk) and killing it would spend a pair's slot while freeing nothing.
        if [ -z "$pid" ] || [ -z "$rss" ] || [ "$rss" -lt "$MEM_MIN_KILL_KB" ]; then
            echo "$(_mem_ts) HARD floor breached at ${avail}G but no GiB-scale worker to sacrifice" >> "$MEM_LOG"
            continue
        fi
        if [ "$sacrificed" -ge "$MEM_MAX_SACRIFICE" ]; then
            # ★ REPEATED SACRIFICE MEANS THE WIDTH IS WRONG, NOT THE PAIRS. Past the cap, stop killing and
            #   halt the feed instead: shredding pair after pair would trade a recoverable stall for a
            #   corpus full of holes, and --jobs is the lever that actually fixes it.
            echo "$(_mem_ts) HARD floor at ${avail}G but $sacrificed sacrifices already made (cap $MEM_MAX_SACRIFICE)" >> "$MEM_LOG"
            echo "$(_mem_ts) HALTING THE FEED instead -- re-run with --resume at a lower --jobs" >> "$MEM_LOG"
            : > "$MEM_HALT"
            return 0
        fi
        local outdir; outdir="$(tr '\0' '\n' < "/proc/$pid/cmdline" 2>/dev/null | grep -A1 -x -- '--out' | tail -1 || true)"
        sacrificed=$((sacrificed + 1))
        # ★ MiB, not GiB: integer division by 1048576 printed a 200 MiB target as "0G", which reads as
        #   "killed something that was using nothing" — the opposite of the justification for killing it.
        #   A real worker prints ~7000 MiB, which is just as legible and never rounds away the evidence.
        echo "$(_mem_ts) !! HARD floor: MemAvailable ${avail}G < ${MEM_HARD_G}G -- SACRIFICING pid $pid ($((rss / 1024)) MiB RSS) out=${outdir:-unknown}" >> "$MEM_LOG"
        echo "  SACRIFICE: MemAvailable ${avail}G below hard floor ${MEM_HARD_G}G; killing pid $pid ($((rss / 1024)) MiB RSS)" >&2
        kill -9 "$pid" 2>/dev/null || true
        sleep "$MEM_POLL"                                   # let the pages actually come back before re-testing
    done
}

# ── the SOFT floor: drain by not launching the next pair ────────────────────────────────────────────────
# ★★ THE GATE MUST BE EVALUATED WHEN A SLOT FREES — AND THAT IS WHY THIS DRIVER NO LONGER USES `xargs -P`.
#   The first version of this guard piped a gated feed into `xargs -P "$JOBS" -n 2`, on the premise that
#   xargs pulls its next pair from stdin only as a slot frees, so a feeder that withholds a line IS a drain.
#   ★ MEASURED FALSE. xargs does one buffered read() and parses batches out of its OWN buffer, so a 504-pair
#   feed (~6 KB, well inside a 64 KB pipe) is consumed entirely in the first few milliseconds — every gate
#   check happening before any worker has allocated anything. The guard was INERT: a check that can only run
#   before the memory is used can never see pressure. The probe that settles it: a feeder timestamping each
#   line into `xargs -P 1 -n 2` with a 2 s child wrote all six lines at t=0 while the children ran 2 s apart.
#   So the driver now does its own slot accounting. `wait -n` returns as each worker retires — the one moment
#   when MemAvailable reflects what the next pair will actually face — and the gate runs immediately after,
#   in the PARENT, where the drain counter, the timeout and the log already live. This also drops a process
#   layer (no `xargs`, no `bash -c` wrapper), so the watchdog's ppid walk gets shallower.
MEM_DRAINS=0
MEM_DRAINING=0                  # 1 while below the floor, so a drain that spans pairs counts ONCE
_mem_gate() {
    [ "$MEM_GUARD" = "1" ] || return 0
    local t="$1" i="$2" avail waited=0
    while :; do
        if [ -f "$MEM_HALT" ]; then
            echo "$(_mem_ts) feed HALTED by the watchdog after $MEM_DRAINS drain(s)" >> "$MEM_LOG"
            echo "  HALT: feed stopped; in-flight pairs will finish and the sweep ends INCOMPLETE" >&2
            return 1
        fi
        avail="$(_mem_avail_g)"
        if [ "${avail:-999}" -ge "$MEM_FLOOR_G" ]; then
            if [ "$MEM_DRAINING" = "1" ]; then
                echo "$(_mem_ts) drain #$MEM_DRAINS lifted at ${avail}G after ${waited}s -- resuming with $t/$i" >> "$MEM_LOG"
                echo "  RESUME: MemAvailable ${avail}G >= floor ${MEM_FLOOR_G}G after ${waited}s" >&2
                MEM_DRAINING=0
            fi
            return 0
        fi
        if [ "$MEM_DRAINING" = "0" ]; then
            MEM_DRAINS=$((MEM_DRAINS + 1)); MEM_DRAINING=1
            echo "$(_mem_ts) DRAIN #$MEM_DRAINS: MemAvailable ${avail}G < floor ${MEM_FLOOR_G}G -- holding $t/$i" >> "$MEM_LOG"
            echo "  DRAIN: MemAvailable ${avail}G below floor ${MEM_FLOOR_G}G; holding $t / $i" >&2
        fi
        if [ "$waited" -ge "$MEM_DRAIN_TIMEOUT" ]; then
            # ★ A drain that never lifts becomes a CLEAN INCOMPLETE, not an infinite wait and not a forced
            #   launch. That reuses the recovery loop this driver already has instead of inventing a second
            #   one: reconciliation exits 3 and names the gaps, --resume refills. The timeout is TERMINAL —
            #   returning 1 stops the dispatch loop outright, so a stuck box costs one timeout, not one per
            #   remaining pair (which at 900 s × 490 pairs would be a 40 h "guard").
            echo "$(_mem_ts) DRAIN TIMEOUT after ${waited}s at ${avail}G -- feed stopped, sweep will end INCOMPLETE" >> "$MEM_LOG"
            echo "  DRAIN TIMEOUT: ${waited}s below floor; stopping the feed. Sweep ends INCOMPLETE;" >&2
            echo "                 re-run with --resume (and consider a lower --jobs)." >&2
            return 1
        fi
        sleep "$MEM_POLL"
        waited=$((waited + MEM_POLL))
    done
}

# ── dispatch: at most $JOBS workers, gated at each slot handover ─────────────────────────────────────────
# ★★ NEVER `wait` AND NEVER BARE `wait -n` HERE: THE WATCHDOG IS A BACKGROUND CHILD OF THIS SAME SHELL.
#   Bare `wait` waits for EVERY child, and the watchdog only exits when the driver does -- a circular wait
#   that hung a finished sweep indefinitely (all 3 pairs written, then nothing). Bare `wait -n` is subtler
#   but still wrong: it can return for the watchdog (which DOES exit on its own, at the sacrifice cap),
#   miscounting a slot and letting the reconciliation read a package still being written. So reap by name:
#   `wait -n -p` reports WHICH pid was collected, and a watchdog collection is not a freed slot.
_reap_worker() {
    local reaped
    while :; do
        reaped=""
        # ★ `|| true`: a worker SIGKILLed at the hard floor exits 137, and `set -e` would turn the sacrifice
        #   this guard makes ON PURPOSE into a dead sweep with no reconciliation at all.
        wait -n -p reaped 2>/dev/null || true
        [ -n "$reaped" ] || return 0                        # no children left to collect
        [ "$reaped" = "${WATCHDOG_PID:-}" ] || return 0     # a real worker retired: the slot is free
        WATCHDOG_PID=""                                     # the watchdog halted itself; keep waiting
    done
}

_dispatch() {
    local t i running=0
    while IFS=$'\t' read -r t i; do
        [ -n "$t" ] && [ -n "$i" ] || continue
        if [ "$running" -ge "$JOBS" ]; then
            _reap_worker                                    # blocks until a pair retires and frees its RSS
            running=$((running - 1))
        fi
        # ★ Gated HERE -- immediately after a slot frees -- so MemAvailable is read at the one moment that
        #   describes what the next pair will actually face.
        _mem_gate "$t" "$i" || break
        bash "$0" --run-one "$t" "$i" "$CORPUS_DIR/$t-$i" &
        running=$((running + 1))
    done
    while [ "$running" -gt 0 ]; do                          # let the in-flight pairs finish, untouched
        _reap_worker
        running=$((running - 1))
    done
}

echo "running $TODO_N pairs at --jobs $JOBS (logs under $REGEN_LOG_DIR)"
if [ "$MEM_GUARD" = "1" ]; then
    echo "memory guard ON: drain below ${MEM_FLOOR_G}G, sacrifice below ${MEM_HARD_G}G (max $MEM_MAX_SACRIFICE), MemAvailable now $(_mem_avail_g)G -> $MEM_LOG"
    echo "$(_mem_ts) sweep start: $TODO_N pairs, --jobs $JOBS, floor ${MEM_FLOOR_G}G, hard ${MEM_HARD_G}G, MemAvailable $(_mem_avail_g)G, MemTotal $(_mem_total_g)G" >> "$MEM_LOG"
    _mem_watchdog "$$" &
    WATCHDOG_PID=$!
    # ★ Extend the existing EXIT trap so an abnormal exit (interrupt, a `set -e` death in the
    #   reconciliation) cannot leave an orphan watchdog polling this box forever. Kill by PID, never pattern.
    # ★★ EVERY COMMAND IN THIS TRAP MUST SUCCEED. `set -e` applies INSIDE an EXIT trap, and a trap that dies
    #   part-way exits with THAT status — which is how the first version turned a fully reconciled sweep into
    #   exit 1: the explicit reap below had already collected the watchdog, so the trap's `kill` failed with
    #   "no such process" and `set -e` exited 1. Exit 1 is the REFUSAL code, so a perfect 5 h regen would
    #   have reported itself as a pre-flight guard firing. Hence `|| true` on the kill, not just a trailing
    #   `true`, and hence unsetting WATCHDOG_PID after the reap so the trap has nothing left to try.
    #   ⚠ EITHER ONE ALONE SUFFICES, so they are redundant on purpose and the test only reds when BOTH are
    #   reverted (measured). Do not "simplify" by dropping one on the strength of a green suite.
    trap 'rm -f "$TODO" 2>/dev/null || true
          if [ -n "${WATCHDOG_PID:-}" ]; then kill "$WATCHDOG_PID" 2>/dev/null || true; fi
          true' EXIT
else
    echo "memory guard OFF (--no-mem-guard): a tail collision can reboot this host"
fi

# ★ NOT a pipeline. _dispatch must run in THIS shell, not a subshell, or MEM_DRAINS and MEM_DRAINING would
#   be lost at the end of it and the drain summary would always read zero.
_dispatch < "$TODO"

# ★ Stop the watchdog by PID -- never by pattern. It is a subshell of this script, so it shares an argv with
#   the driver itself and any `pkill -f regenerate_corpus` here would kill the parent mid-reconciliation.
if [ -n "${WATCHDOG_PID:-}" ]; then
    kill "$WATCHDOG_PID" 2>/dev/null || true
    wait "$WATCHDOG_PID" 2>/dev/null || true
    unset WATCHDOG_PID                              # ★ so the EXIT trap has nothing left to fail on
fi
if [ "$MEM_GUARD" = "1" ]; then
    # ★ The drain count is the PARENT'S OWN counter, not a grep of the log: _dispatch ran in this shell on
    #   purpose, so the number is authoritative and carries no dependence on log wording. The sacrifice count
    #   has to come from the log because the watchdog is a subshell and cannot hand a variable back.
    _n_sac=$(grep -c 'SACRIFICING pid' "$MEM_LOG" 2>/dev/null || true)
    echo "memory guard: $MEM_DRAINS drain(s), ${_n_sac:-0} sacrifice(s) -- detail in $MEM_LOG"
fi

# ── 4. reconcile. The completion line is a COUNT against the panel, not the absence of errors. ──────────
python3 - "$CORPUS_DIR" "$PANEL" <<'PY'
import json, os, sys

corpus, panel = sys.argv[1], sys.argv[2]
want = []
with open(panel) as fh:
    for line in fh:
        if not line.strip():
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) == 3:
            want.append(f"{parts[0]}-{parts[1]}")

# ★ COMPLETENESS MEANS PARSEABLE, NOT PRESENT. tp_evidence_package persists the package with
#   `out_path.write_text(json.dumps(...))` — a truncate-then-write with no atomic rename — and these files
#   run 1.5-6.7 MB, so any death mid-write (the hard floor above, a host OOM-kill, the reboots this corpus
#   has actually suffered, a full disk) leaves a file that EXISTS and is TRUNCATED. An isfile() check calls
#   that a finished pair, and the freeze then encodes it. So parse every package: it is the only check that
#   distinguishes "the pair ran" from "a file appeared", it costs seconds against a multi-hour sweep, and
#   unlike the --run-one purge it catches partial writes this driver never caused.
missing, corrupt = [], []
for k in want:
    p = os.path.join(corpus, k, "evidence_package.json")
    if not os.path.isfile(p):
        missing.append(k)
        continue
    try:
        with open(p) as fh:
            json.load(fh)
    except Exception as exc:
        corrupt.append((k, f"{type(exc).__name__}: {exc}"[:120]))

if missing or corrupt:
    n_ok = len(want) - len(missing) - len(corrupt)
    sys.stderr.write(
        f"INCOMPLETE: {n_ok} of {len(want)} panel rows have a PARSEABLE evidence_package.json "
        f"({len(missing)} missing, {len(corrupt)} unparseable)\n"
    )
    if missing:
        sys.stderr.write(f"  MISSING ({len(missing)}): {missing[:20]}{' ...' if len(missing) > 20 else ''}\n")
    if corrupt:
        sys.stderr.write(f"  UNPARSEABLE ({len(corrupt)}) -- a truncated write, NOT a missing run:\n")
        for k, why in corrupt[:10]:
            sys.stderr.write(f"    {k}: {why}\n")
        sys.stderr.write(
            "  --resume RE-RUNS these: the pre-flight keys the gap-fill on whether a package PARSES, not on "
            "whether the file exists, so a truncated package is not skipped. No manual deletion needed.\n"
        )
    sys.stderr.write(
        f"corpus_io silently skips runs with no harvestable claim vectors, so a freeze over this corpus "
        f"would quietly cover {n_ok} rows while the panel claims {len(want)}. "
        f"Re-run with --resume to fill the gaps, and check the per-pair logs under {corpus}/logs.\n"
    )
    raise SystemExit(3)
print(f"corpus regen COMPLETE and reconciled: {len(want)} of {len(want)} panel rows have a PARSEABLE "
      f"evidence_package.json under {corpus}")
PY
