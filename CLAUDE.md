# Claude Code — Working Rules for analysis-methods

You are running under user `takoncoder`. Multiple parallel Claude sessions
may be active across the framework repos. Before doing ANY non-trivial
write work in this repo you MUST follow the cross-session coordination
ritual below.

## Cross-session coordination ritual

Before starting a new workstream in this repo:

1. **Read `~/.claude/wip-registry.md`.** If any entry lists `analysis-methods`
   with paths overlapping what you plan to change, STOP and surface the
   collision to the user. Options:
   - **Coordinate** — extend the existing branch instead of cutting a new one
   - **Disjoint scope** — cut a new branch touching different paths
   - **Override** — user explicitly authorizes the parallel work

2. **Reality check.** Run `gh pr list --author @me --state open` and
   `git branch --list` — any local branches / open PRs NOT in the
   registry should be reconciled first.

3. **Claim your workstream.** Append an entry to `~/.claude/wip-registry.md`
   following the schema at the top of that file. Use ISO-8601 UTC
   timestamps.

4. **Declare branch scope.** Before your first commit on a new branch,
   write `.claude/branch-scope` (one path prefix per line) listing the
   top-level paths this branch is allowed to touch. This is gitignored
   per-worktree — never committed.

**Trivial-work bypass**: single-file typo fixes, doc-only edits, or edits
clearly within an active registry entry's scope skip steps 1-3 (still
write branch-scope for step 4).

## Worktree-per-workstream (DEFAULT)

Every non-trivial workstream runs in its OWN git worktree — not in this
primary checkout — so parallel sessions cannot clobber each other's files
or branch refs. The primary checkout stays parked on `main`.

Start a workstream:

    ~/.claude/git-hooks/new-worktree analysis-methods feat/paralog-aggregator \
        --scope methods/depmap_paralog_aggregator/ tests/methods/depmap_paralog_aggregator/

This creates `/tmp/wt/<repo>__<branch>/` on a fresh branch off the
`default_base` in `.claude/config` (here: `main`), writes
`.claude/branch-scope`, and prints a registry stub to paste into
`~/.claude/wip-registry.md`. The committed hook symlinks resolve inside the
worktree, so pre-commit/pre-push enforcement travels with it. Do all work
in that directory. Trivial in-scope edits may use the primary checkout.

## Branch & PR discipline

- **Approved branch prefixes**: `add-` (dominant historical convention),
  `feat/`, `fix/`, `chore/`
- **Draft PR on FIRST push** — never accumulate pushed-but-PR-less branches
- **One workstream per branch** — if scope drifts, stop and cut a new branch
- Enforced by `.claude/hooks/pre-commit` (via `core.hooksPath`)

## Directory scopes (grab-bag prevention)

Top-level scope roots for this repo: `methods/`, `libs/`, `tests/`.

Each branch's `.claude/branch-scope` should list the specific sub-paths
under these roots that the branch is allowed to modify. Example for a
new method:

```
methods/depmap_paralog_aggregator/
tests/methods/depmap_paralog_aggregator/
```

The pre-commit hook rejects commits that touch files outside the
declared prefixes.

## Cross-repo dependencies

`analysis-methods` depends on:
- **data-catalog** — reads source + derived manifests from
  `s3://onc-compbio/data-catalog/`; manifest IDs must be pinned
- **target-contracts** — implements the method APIs declared in
  card + rule contracts

Before extending a method that reads a specific manifest, check the
registry for active work in data-catalog on that manifest. Before
adding a new method that satisfies a card's `methods:` list, check
target-contracts for active card-refactor work.

## Landing a PR (merge discipline)

The lifecycle does NOT end at "PR open." Land it with:

    ~/.claude/git-hooks/land-pr <pr-number>

Merge policy = **auto-merge when CI passes**. Open the PR draft-first;
land-pr marks it ready, then:
  - checks pending → enables GitHub auto-merge (lands itself when green)
  - checks failing → refuses
  - no checks / all green → squash-merges now
Always `--squash --delete-branch`. Auto-merge waits for any required checks
(e.g. CodeQL) before landing.

It NEVER deletes a branch/worktree until it re-reads the PR and confirms
`state == MERGED` — deleting a head branch before merge closes the PR
UNMERGED (silent work loss). After a confirmed merge it prunes the
worktree, deletes the local branch, and fast-forwards `main`.

**Stacked PRs**: if other open PRs use your branch as their base, land-pr
refuses (squash-merging a parent auto-closes stacked children). Land the
children first, or pass `--retarget-children`.

## Registry / completion

- State transitions: `planned` → `in-progress` → `pr-open` → `merged`.
  Set `status: merged` by hand after landing (land-pr does not edit the
  shared registry). Any session may remove `status: merged` entries older
  than 24h during its startup ritual.

## Machine enforcement

- `.claude/hooks/pre-commit` — refuses commits mixing declared
  scopes (grab-bag prevention) and enforces branch-prefix
- `.claude/hooks/pre-push` — warns on branches without an open PR
  (invisible-work) and detects registry-declared scope collisions
  (parallel-collision)

Bypass with `git commit --no-verify` / `git push --no-verify` is
technically possible but explicitly discouraged (memory documented:
the user's standing rule is never to use `--no-verify`).

See also: [DEVELOPMENT_GUIDELINES.md](DEVELOPMENT_GUIDELINES.md) for
what belongs in a method module (deterministic CLIs, per-method
output schemas, catalog manifest ID pinning). This CLAUDE.md
governs the coordination + branch discipline layer above.
