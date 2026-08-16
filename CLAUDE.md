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
or branch refs. The primary checkout stays parked on `v2-architecture`.

Start a workstream:

    ~/.claude/git-hooks/new-worktree claude-oncology-skills fix/presence-ladder \
        --scope skills/tumor-presence/

This creates `/tmp/wt/<repo>__<branch>/` on a fresh branch off the
`default_base` in `.claude/config` (here: `v2-architecture`), writes
`.claude/branch-scope`, and prints a registry stub to paste into
`~/.claude/wip-registry.md`. The committed hook symlinks resolve inside the
worktree, so pre-commit/pre-push enforcement travels with it. Do all work
in that directory. Trivial in-scope edits may use the primary checkout.

## Branch & PR discipline

Feature work branches off the long-lived `v2-architecture` integration branch
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

## Long-lived branches (exception to one-workstream-per-branch)

`v2-architecture` is a long-lived architectural branch tracking the
compositional-skill design. It legitimately accumulates many commits
across many workstreams — the one-workstream-per-branch rule does not
apply here. Workstreams should cut short-lived feature branches OFF
of `v2-architecture` and PR back into it.

## Landing a PR (merge discipline)

The lifecycle does NOT end at "PR open." Land it with:

    ~/.claude/git-hooks/land-pr <pr-number>

Merge policy = **auto-merge when CI passes**. Open the PR draft-first
(`gh pr create --draft --base v2-architecture` for arch-branch work);
land-pr then marks it ready and:
  - checks pending → enables GitHub auto-merge (lands itself when green)
  - checks failing → refuses
  - no checks / all green → squash-merges now
Always `--squash --delete-branch`.

It NEVER deletes a branch/worktree until it re-reads the PR and confirms
`state == MERGED` — deleting a head branch before merge closes the PR
UNMERGED (silent work loss). After a confirmed merge it prunes the
worktree, deletes the local branch, and fast-forwards `v2-architecture`
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
