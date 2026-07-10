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

## Branch & PR discipline

This repo has an existing branching convention in
[DEVELOPMENT_GUIDELINES.md](DEVELOPMENT_GUIDELINES.md):
`main → dev → feature/*` on this repo, `main → feature/*` on the
sibling `ai-sci-claude-skills` repo. That guideline STILL APPLIES and
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

## Completion

- Draft PR on first push (`gh pr create --draft --base v2-architecture`
  if branching off the architecture branch, else `--base dev`).
- Registry state transitions: `planned` → `in-progress` → `pr-open` →
  `merged`. Entries auto-cleaned 24h post-merge.

## Machine enforcement

- `.claude/hooks/pre-commit` — grab-bag prevention + branch-prefix
- `.claude/hooks/pre-push` — invisible-work + parallel-collision

`--no-verify` bypass discouraged.
