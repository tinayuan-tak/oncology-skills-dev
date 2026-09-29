# Claude Code — Working Rules for claude-oncology-skills

You are running under user `takoncoder`. Multiple parallel Claude sessions
may be active across the framework repos. Before doing ANY non-trivial
write work in this repo you MUST follow the cross-session coordination
ritual below.

## Consolidated layout (SK#2063, 2026-09-29)

analysis-methods and target-contracts live IN THIS REPO as `methods/` and
`contracts/` (subtree merges, full history preserved; the old repos are
archived read-only). What this changes:

- A card/rule/method/skill change is ONE atomic PR here — no sibling pins,
  no bump PRs, no two-phase landings. The old `methods/CLAUDE.md` and
  `contracts/CLAUDE.md` still hold their packages' domain rules; their
  cross-REPO ritual sections are historical.
- data-catalog is still a SEPARATE sibling repo (stable manifest-ID
  interface); CI checks it out at ONE pinned SHA (skills-validate.yml) —
  bump that pin by hand, rarely.
- Gating is per-package via one dispatcher, `scripts/preland.sh` — see the
  Testing section below. NEVER run a whole-tree `pytest` from the repo root:
  duplicate test basenames kill collection.
- The three root symlinks `rnd-computational-biology-oncology-*` are a
  TEMPORARY geometry shim for parent-dir path resolution; do not add code
  that depends on them (package imports / `*_ROOT` env vars instead).

## Cross-session coordination ritual

Before starting a new workstream in this repo:

1. **Read `~/.claude/wip-registry.md`.** Skills are the highest-level
   consumers in the framework — a skill change often lands atomically with a
   coordinated `methods/` or `contracts/` change in the SAME PR.

2. **Reality check.** `gh pr list --author @me --state open` and
   `git branch --list`.

3. **Claim your workstream.** Registry entries for skills work typically
   list one or more skill directories, e.g.:
   ```
   paths: [skills/tractability-and-modality/, skills/target-profile/]
   ```

4. **Declare branch scope.** Write `.claude/branch-scope` before first
   commit.

**Trivial-work bypass** for single-file edits or clearly scoped edits
within an active registry entry.

## Worktree-per-workstream (DEFAULT)

Every non-trivial workstream runs in its OWN git worktree — not in this
primary checkout — so parallel sessions cannot clobber each other's files
or branch refs. The primary checkout stays parked on `main`.

Start a workstream:

    ~/.claude/git-hooks/new-worktree claude-oncology-skills fix/presence-ladder \
        --scope skills/tumor-presence/

This creates `/tmp/wt/<repo>__<branch>/` on a fresh branch off the
`default_base` in `.claude/config` (here: `main`), writes
`.claude/branch-scope`, and prints a registry stub to paste into
`~/.claude/wip-registry.md`. The committed hook symlinks resolve inside the
worktree, so pre-commit/pre-push enforcement travels with it. Do all work
in that directory. Trivial in-scope edits may use the primary checkout.

## Branch & PR discipline

Feature work branches off the trunk `main`
via a per-workstream worktree and merges back by PR (see
[DEVELOPMENT_GUIDELINES.md](DEVELOPMENT_GUIDELINES.md) for the full flow). This
composes with the coordination ritual above.

- **Approved branch prefixes**: `feat/`, `fix/`, `chore/`, `feature/`
- **Draft PR on FIRST push**
- **One workstream per branch**
- Enforced by `.claude/hooks/pre-commit`

## Directory scopes (grab-bag prevention)

Top-level scope roots: `skills/`, `methods/`, `contracts/`, `libs/`, `notebooks/`,
`tests/`, `eval/`.

Each branch's `.claude/branch-scope` should list the specific directories the
branch is allowed to modify — e.g. `skills/tumor-presence/` for a skill change,
`methods/depmap_chronos/` for a method change, `cards/adc-tce-modality-fit.card.yaml`
(relative to `contracts/`) for a card change. Cross-skill or cross-package refactors
should either bundle the affected paths together (declared as multiple prefixes in
branch-scope) OR — preferably — be done in stages, one skill/package per branch. A
card + rule + method + skill change that must land atomically (they usually do now —
see Consolidated layout above) is the deliberate exception: declare all the touched
prefixes across `skills/`, `methods/`, and `contracts/` in one `branch-scope`.

## Package dependencies

`skills/` depends on:
- **`methods/`** — skills invoke method modules for tier-1 evidence
- **`contracts/`** — skills' `composition.cards_used` references
  card IDs; `composition.rules_scope` references rule IDs
- **`data-catalog`** (sibling repo) — indirectly, via `methods/`

Extending a skill's `cards_used` or wiring it to a new method now lands in the SAME
PR as the card/method change (one atomic PR — see Consolidated layout above); check
the WIP registry for an overlapping in-flight branch before starting, same as any
other path.

## The trunk (exception to one-workstream-per-branch)

`main` is the trunk. It legitimately accumulates many commits across many
workstreams — the one-workstream-per-branch rule does not apply to it.
Workstreams cut short-lived feature branches OFF of `main` and PR back into it.

Until 2026-09-16 the trunk was a long-lived `v2-architecture` branch and `main`
held the v1 plugin; v2 was then promoted to `main` and v1 archived to the
`legacy/v1` branch + `v1-final` tag. `legacy/v1` is frozen — never branch off it
or PR into it.

## Landing a PR (merge discipline)

The lifecycle does NOT end at "PR open." Land it with:

    ~/.claude/git-hooks/land-pr <pr-number>

Merge policy = **auto-merge when CI passes**. Open the PR draft-first
(`gh pr create --draft --base main`);
land-pr then marks it ready and:
  - checks pending → enables GitHub auto-merge (lands itself when green)
  - checks failing → refuses
  - no checks / all green → squash-merges now
Always `--squash --delete-branch`.

**`main` is protected by a GitHub merge queue** (ruleset `merge-queue-main`,
squash method). A queue-protected branch REJECTS a direct merge, so land-pr
detects the queue and ENQUEUES the PR instead — it lands asynchronously after
the queue re-runs the required checks on the *prospective merged tree* (the
`merge_group` event), which is why "all green" no longer merges instantly. Re-run
`land-pr <pr>` after it lands (or pass `--now`) to prune the worktree.

It NEVER deletes a branch/worktree until it re-reads the PR and confirms
`state == MERGED` — deleting a head branch before merge closes the PR
UNMERGED (silent work loss). After a confirmed merge it prunes the
worktree, deletes the local branch, and fast-forwards `main`
in the primary checkout.

**Stacked PRs**: if other open PRs use your branch as their base, land-pr
refuses (squash-merging a parent auto-closes stacked children). Land the
children first, or pass `--retarget-children` to move them onto the base.

## Registry / completion

- State transitions: `planned` → `in-progress` → `pr-open` → `merged`.
  Set `status: merged` by hand after landing (land-pr does not edit the
  shared registry — parallel sessions share it). Entries auto-cleaned 24h
  post-merge.

## Machine enforcement

- `.claude/hooks/pre-commit` — grab-bag prevention + branch-prefix
- `.claude/hooks/pre-push` — invisible-work + parallel-collision

`--no-verify` bypass discouraged.

## Testing

**One command to memorize**: `scripts/preland.sh` (subcommands
`skills|methods|contracts|all`; `all` is the default and the right choice for a
cross-package change). It chains the three packages' prelands plus `ruff`, printing
each step's PASS/FAIL. Pass a single package name when your change is scoped to it
(`scripts/preland.sh skills`, `scripts/preland.sh methods`,
`scripts/preland.sh contracts`) to skip the other two.

**Never pipe a gate to `tail`/`head`.** The pipeline's exit code is the last
command's, not the gate's — a RED silently reads as green. Redirect to a file
(`cmd > /tmp/out 2>&1`) and read the script's own PASS/FAIL summary line, never just
the shell exit code. SKIP ≠ PASS — a module-level `importorskip` or a missing-data
guard can make a whole file silently skip; reconcile the collected-test count if in
doubt.

- Run pytest / the dispatcher under `pixi run` from THIS home checkout, never bare
  `python` (a bare env red-fails the resolver golden snapshots) and never from a
  `/tmp` worktree (pixi deep-copies a multi-GB env there → ENOSPC and a wedged
  `/tmp`). To gate code living in a worktree, run from the home checkout against the
  worktree paths (e.g. `pixi run pytest /tmp/wt/<branch>/skills/<skill>/tests/ -q`).
- **Two required status checks gate `main`**: `pytest`
  (`.github/workflows/skills-validate.yml` — fans in the skills shards, the methods
  suite, and both contracts jobs) and `ruff` (`.github/workflows/ruff.yml`),
  `strict: false`. Both also trigger on the `merge_group` event so the merge queue can
  run them on the prospective merged tree. CodeQL / `Analyze (python)` also runs on
  every PR (org-level default setup) but is **not** required and does not gate. Three
  checks run; two gate. A `merge-queue-main` ruleset requires the queue (squash) — it
  adds no status checks; the queue runs the two required contexts above. Re-measure
  rather than trusting this line:
  `gh api 'repos/{owner}/{repo}/branches/main/protection' --jq .required_status_checks`
  and `gh api 'repos/{owner}/{repo}/rules/branches/main' --jq '[.[].type]|unique'`
- **Blast-radius exception — gate fully locally before pushing, don't lean on CI**:
  any change under `cards/` | `interpretation-rules/` | `resolvers/` | `vocabularies/`
  (inside `contracts/`), or any change that spans `skills/` + `methods/` + `contracts/`
  in one PR. Run `scripts/preland.sh all` and read the summary before pushing — CI is
  still authoritative, but a schema violation here can red trunk for every open PR
  faster than CI catches it.
- Trunk is `main`. (It was `v2-architecture` until 2026-09-16; anything still saying
  "never `main`" predates the promotion and is wrong.)
- A resolver / verdict-contract change fans out into golden snapshots + synthetic
  fired-sets + stub fixtures across multiple skill dirs, so run the FULL skills suite
  (`skills/_skills_common/`, `skills/target-profile/`,
  the changed `skills/<skill>/`, and the cross-skill guards in `skills/tests/`) — a
  `-k` subset silently misses the fan-out. Regenerate the golden via
  `skills/_skills_common/tests/regenerate_resolver_golden.py` (manually append any NEW
  `rule_id` to the relevant `<gate>.rule_ids` first).
- **`methods/`**: run `methods/ tests/` together under `--import-mode=importlib`
  (several method test files share a basename); running `methods/` alone
  under-collects. Live-data tests need `AWS_PROFILE=cbg` locally.
- **`contracts/`**: bare python, no pixi (`python validators/validate_cards.py`, …) —
  `scripts/preland.sh contracts` runs the validator pool plain pytest never touches.
- Stale skills PR branches share no merge-base with the rewritten trunk, so reland via `gh pr diff <n> > /tmp/pr.patch` then `git apply --3way`
  (NOT a rebase), and push with `git push --force-with-lease`.
- `--synthesize` needs system python + `BEDROCK_AWS_PROFILE=cmp-dev`. (The `compose-dashboard`
  orchestrator was RETIRED 2026-08-20, #654 — its engine rehomed to `_skills_common`; disregard any
  lingering reference to it. A target-profile `--ground` / Bedrock run needs `AWS_PROFILE=cbg` for the
  onc-compbio bucket.)
- After a SageMaker restart, `gh` (`~/.local/bin/gh`) and `pixi` (`~/.pixi/bin`) fall
  off PATH — re-export both before running any gate.
