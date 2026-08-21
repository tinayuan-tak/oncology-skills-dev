# Claude Code — Working Rules for target-contracts

You are running under user `takoncoder`. Multiple parallel Claude sessions
may be active across the framework repos. Before doing ANY non-trivial
write work in this repo you MUST follow the cross-session coordination
ritual below.

## Cross-session coordination ritual

Before starting a new workstream in this repo:

1. **Read `~/.claude/wip-registry.md`.** Card + rule changes are especially
   collision-prone because a single card is often the focus of parallel
   sessions (one adding a data field, another wiring rules against it).

2. **Reality check.** Run `gh pr list --author @me --state open` and
   `git branch --list`.

3. **Claim your workstream.** Registry entries for target-contracts
   typically list card/rule paths, e.g.:
   ```
   paths: [cards/adc-tce-modality-fit.card.yaml, interpretation-rules/surface-intrinsic.rules.yaml]
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

    ~/.claude/git-hooks/new-worktree target-contracts fix/adc-card-provenance \
        --scope cards/adc-tce-modality-fit.card.yaml

This creates `/tmp/wt/<repo>__<branch>/` on a fresh branch off the
`default_base` in `.claude/config` (here: `main`), writes
`.claude/branch-scope`, and prints a registry stub to paste into
`~/.claude/wip-registry.md`. The committed hook symlinks resolve inside the
worktree, so pre-commit/pre-push enforcement travels with it. Do all work
in that directory. Trivial in-scope edits may use the primary checkout.

## Branch & PR discipline

- **Approved branch prefixes**: `feat/`, `fix/`, `chore/`
- **Draft PR on FIRST push**
- **One workstream per branch**
- Enforced by `.claude/hooks/pre-commit`

## Directory scopes (grab-bag prevention)

Top-level scope roots: `cards/`, `interpretation-rules/`, `schemas/`,
`vocabularies/`, `tests/`.

Cards and rules should generally live on separate branches — a card
addition is a data-contract change, a rule addition is a signal-mapping
change, and they should be reviewable independently unless the rule
literally cannot exist without the card.

## Cross-repo dependencies

`target-contracts` depends on:
- **data-catalog** — cards reference source + derived manifest IDs
- **analysis-methods** — cards' `methods:` list references specific
  method module paths

Downstream:
- **claude-oncology-skills** — skills' `cards_used:` composition references
  card IDs from this repo. Card renames or deletions require coordination.

Before renaming a card or rule ID, check registry for active work in
`claude-oncology-skills` that might reference it.

## Landing a PR (merge discipline)

The lifecycle does NOT end at "PR open." Land it with:

    ~/.claude/git-hooks/land-pr <pr-number>

Merge policy = **auto-merge when CI passes**. Open the PR draft-first;
land-pr marks it ready, then:
  - checks pending → enables GitHub auto-merge (lands itself when green)
  - checks failing → refuses
  - no checks / all green → squash-merges now
Always `--squash --delete-branch`. This repo HAS CI (`contracts-validate`,
`framework-health`), so auto-merge normally waits for green.

It NEVER deletes a branch/worktree until it re-reads the PR and confirms
`state == MERGED` — deleting a head branch before merge closes the PR
UNMERGED (silent work loss). After a confirmed merge it prunes the
worktree, deletes the local branch, and fast-forwards `main`.

**Stacked PRs**: if other open PRs use your branch as their base, land-pr
refuses (squash-merging a parent auto-closes stacked children). Land the
children first, or pass `--retarget-children` to move them onto `main`.

## Registry / completion

- State transitions: `planned` → `in-progress` → `pr-open` → `merged`.
  Set `status: merged` by hand after landing (land-pr does not edit the
  shared registry). Entries auto-cleaned 24h post-merge.

## Machine enforcement

- `.claude/hooks/pre-commit` + `.claude/hooks/pre-push` per
  `core.hooksPath = .claude/hooks`

`--no-verify` bypass discouraged.

## Landing invariants

- This repo is **bare python** — there is NO pixi. Gates run as plain
  `python` / `python -m pytest`.
- Before landing a `cards/` | `interpretation-rules/` | `resolvers/` |
  `vocabularies/` change, run `scripts/preland.sh`. It mirrors, in order,
  every gate in `.github/workflows/contracts-validate.yml`. Plain `pytest`
  does NOT run `validators/validate_*.py`, and `contracts-validate` is not a
  branch-protection-required check — so a schema violation can green-light
  pytest yet turn trunk RED for every open PR.
- Card schema caps to remember: `caveats` ≤ 500 chars; vocabulary lists are
  string-only (no `null` entries).
