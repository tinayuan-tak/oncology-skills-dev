---
name: on-target-safety-liability
description: |
  PLACEHOLDER SKILL — Phase-G question is declared in the framework but
  the underlying evidence cards are NOT yet wired. Invoking this skill emits
  a structured "phase-not-yet-wired" response naming the specific data gaps.

  Question this skill would answer once wired:
  What are target X's on-target safety liabilities — normal-tissue expression, LoF tolerance, critical-cell essentiality, historical clinical failures?

  Visible in the skill catalog for transparency: the framework's coverage
  gaps are exposed rather than hidden. See gaps + backlog in
  ~/.claude/plans/deep-foraging-thompson.md.

metadata:
  version: 1.0.0
  owner: ryan.abo@takeda.com
  requires_preflight: false

composition:
  data_mode: derived_read
  phase: [G]
  cards_used:
    - normal-tissue-liability
    - protein-surface-evidence
  rules_scope:
    - none
  synthesis:
    - none
  output_shape:
    - data_package
  steps_covered: [1, 2]
  status: not_wired
---

# on-target-safety-liability — placeholder

## Status: not wired

This skill exists to make the framework's Phase-G coverage gap explicit
and inspectable. When invoked, it emits `decision.json` with:

- `status: "not_wired"`
- `verdict: "phase_not_yet_wired"`
- `unwired_cards`: `normal-tissue-liability`, `protein-surface-evidence`
- `data_gaps`: specific pointers to what would need to be wired

## What would this skill do once wired?

What are target X's on-target safety liabilities — normal-tissue expression, LoF tolerance, critical-cell essentiality, historical clinical failures?

## Wiring backlog

- normal-tissue-liability dispatcher not wired (HPA card pending)
- protein-surface-evidence dispatcher not wired
- gnomAD LoF constraint card not yet added (data-catalog PR #79 landed source manifest; needs a card)
- clinical-precedent (historical trial-outcome DB) has no data feed

## How Claude invokes this skill

When called as `/on-target-safety-liability`, Claude should:

1. Run the skill (it accepts `--target` and `--indication` like any other
   compositional skill).
2. Read the decision.json — the `data_gaps` field enumerates the blockers.
3. Optionally point the user at ~/.claude/plans/deep-foraging-thompson.md
   §"Gaps + backlog" for the wiring roadmap.
