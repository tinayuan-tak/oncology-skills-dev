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

## Completion

- **On first push**: pre-push hook prompts you to open a draft PR
  (`gh pr create --draft --fill`). Do so. Then update the registry
  entry with `pr: <N>`, `status: pr-open`.
- **On merge**: update the registry entry to `status: merged`.
- **Cleanup**: any session may remove entries with `status: merged`
  older than 24h during its startup ritual.

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
