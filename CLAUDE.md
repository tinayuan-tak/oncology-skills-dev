# Claude Code — Working Rules for claude-oncology-skills

You are running under user `takoncoder`. Multiple parallel Claude sessions
may be active across the framework repos. Before doing ANY non-trivial
write work in this repo you MUST follow the cross-session coordination
ritual below.

## Cross-session coordination ritual

Before starting a new workstream in this repo:

1. **Read `~/.claude/wip-registry.md`.** Skills are the highest-level
   consumers in the framework — a skill change often depends on
   coordinated changes in analysis-methods and target-contracts.

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

Top-level scope roots: `skills/`, `libs/`, `notebooks/`, `tests/`.

Each branch's `.claude/branch-scope` should list the specific skill
directories the branch is allowed to modify. Cross-skill refactors
should either bundle the affected skills together (declared as multiple
prefixes in branch-scope) OR — preferably — be done in stages, one
skill per branch.

## Cross-repo dependencies

`claude-oncology-skills` depends on:
- **analysis-methods** — skills invoke method modules for tier-1 evidence
- **target-contracts** — skills' `composition.cards_used` references
  card IDs; `composition.rules_scope` references rule IDs
- **data-catalog** — indirectly, via analysis-methods

Before extending a skill's `cards_used`, check registry for active
card-refactor work in target-contracts. Before wiring a skill to a
new method, check for active method work in analysis-methods.

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

## Testing & landing invariants

- Run pytest under `pixi run` from THIS home checkout, never bare `python` (a bare
  env red-fails the resolver golden snapshots) and never from a `/tmp` worktree
  (pixi deep-copies a multi-GB env there → ENOSPC and a wedged `/tmp`). To gate code
  living in a worktree, run from the home checkout against the worktree paths
  (e.g. `pixi run pytest /tmp/wt/<branch>/skills/<skill>/tests/ -q`).
- **Two required status checks gate `main`, and `scripts/preland.sh` mirrors only
  one of them.** The required contexts are `pytest` (`.github/workflows/skills-validate.yml`)
  and `ruff` (`.github/workflows/ruff.yml`), `strict: false`, with no rulesets on the branch.
  `preland.sh` transcribes the `pytest` job's suite steps and runs **no** lint gate, so a green
  `ALL GATES PASS` does not mean the PR goes green — run the two ruff gates yourself as printed
  in that script's header. CodeQL / `Analyze (python)` also run on every PR (org-level default
  setup) but are **not** required and do not gate. Four checks run; two gate. Re-measure rather
  than trusting this line:
  `gh api 'repos/{owner}/{repo}/branches/main/protection' --jq .required_status_checks`
- Trunk is `main`. (It was `v2-architecture` until 2026-09-16; anything still saying
  "never `main`" predates the promotion and is wrong.)
- A resolver / verdict-contract change fans out into golden snapshots + synthetic
  fired-sets + stub fixtures across multiple skill dirs, so run the FULL skills suite
  (`skills/_skills_common/`, `skills/target-profile/`,
  the changed `skills/<skill>/`, and the cross-skill guards in `skills/tests/`) — a
  `-k` subset silently misses the fan-out. Regenerate the golden via
  `skills/_skills_common/tests/regenerate_resolver_golden.py` (manually append any NEW
  `rule_id` to the relevant `<gate>.rule_ids` first).
- Stale skills PR branches share no merge-base with the rewritten trunk, so reland via `gh pr diff <n> > /tmp/pr.patch` then `git apply --3way`
  (NOT a rebase), and push with `git push --force-with-lease`.
- `--synthesize` needs system python + `BEDROCK_AWS_PROFILE=cmp-dev`. (The `compose-dashboard`
  orchestrator was RETIRED 2026-08-20, #654 — its engine rehomed to `_skills_common`; disregard any
  lingering reference to it. A target-profile `--ground` / Bedrock run needs `AWS_PROFILE=cbg` for the
  onc-compbio bucket.)
- After a SageMaker restart, `gh` (`~/.local/bin/gh`) and `pixi` (`~/.pixi/bin`) fall
  off PATH — re-export both before running any gate.
