# Claude Code — Domain Rules for contracts/

> **Process (worktrees, branch/PR discipline, landing, the WIP registry) lives in one
> place: root [CLAUDE.md](../CLAUDE.md).** Read that first. This file holds only the
> rules specific to the `contracts/` package (the former `target-contracts` repo, now
> in-tree — SK#2063): cards, interpretation rules, resolvers, schemas, vocabularies.

## Domain rules to remember

- **Bare python — no pixi in this package.** Gates run as plain
  `python` / `python -m pytest`, not `pixi run`.
- **Card schema caps**: `caveats` ≤ 500 chars; vocabulary lists are string-only
  (no `null` entries).
- **Never rename or delete a card/rule ID in place** — downstream skills reference
  IDs by string. Use `vocabularies/card_id_aliases.yaml` for forward renames.
- **Cards and rules live on separate branches** where practical — a card addition is
  a data-contract change, a rule addition is a signal-mapping change, and they
  should be reviewable independently unless the rule cannot exist without the card.
- **Gate with `scripts/preland.sh contracts`** (or root `scripts/preland.sh all` for
  a cross-package change) before landing any `cards/` | `interpretation-rules/` |
  `resolvers/` | `vocabularies/` change — see root CLAUDE.md's Testing section. Plain
  `pytest` does **not** run `validators/validate_*.py`, and `contracts-validate`
  feeds the required CI fan-in but is not itself a required check by name — a schema
  violation can green pytest yet red trunk for every open PR.
