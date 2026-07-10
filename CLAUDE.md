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

## Completion

- Draft PR on first push, registry `status: pr-open`, then `status: merged`
  on merge. Entries auto-cleaned 24h post-merge.

## Machine enforcement

- `.claude/hooks/pre-commit` + `.claude/hooks/pre-push` per
  `core.hooksPath = .claude/hooks`

`--no-verify` bypass discouraged.
