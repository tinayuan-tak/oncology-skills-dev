---
name: combo-and-resistance
description: |
  PLACEHOLDER SKILL — Phase-I question is declared in the framework but
  the underlying evidence cards are NOT yet wired. Invoking this skill emits
  a structured "phase-not-yet-wired" response naming the specific data gaps.

  Question this skill would answer once wired:
  When target X is inhibited, what emerges — combination opportunities, resistance signatures?

  Visible in the skill catalog for transparency: the framework's coverage
  gaps are exposed rather than hidden. See gaps + backlog in
  ~/.claude/plans/deep-foraging-thompson.md.

metadata:
  version: 1.0.0
  owner: ryan.abo@takeda.com
  requires_preflight: false

composition:
  data_mode: derived_read
  phase: [I]
  cards_used:
    - combo-crispr-screen
    - resistance-emergence-signature
  rules_scope:
    - none
  synthesis:
    - none
  output_shape:
    - data_package
  steps_covered: [1, 2]
  status: not_wired
---

# combo-and-resistance — placeholder

## Status: not wired

This skill exists to make the framework's Phase-I coverage gap explicit
and inspectable. When invoked, it emits `decision.json` with:

- `status: "not_wired"`
- `verdict: "phase_not_yet_wired"`
- `unwired_cards`: `combo-crispr-screen`, `resistance-emergence-signature`
- `data_gaps`: specific pointers to what would need to be wired

## What would this skill do once wired?

When target X is inhibited, what emerges — combination opportunities, resistance signatures?

## Wiring backlog

- Combo CRISPR screens (some exist in DepMap; method not written)
- Resistance-emergence-signature source (paired pre/post-tx expression / mutation) not catalogued

## How Claude invokes this skill

When called as `/combo-and-resistance`, Claude should:

1. Run the skill (it accepts `--target` and `--indication` like any other
   compositional skill).
2. Read the decision.json — the `data_gaps` field enumerates the blockers.
3. Optionally point the user at ~/.claude/plans/deep-foraging-thompson.md
   §"Gaps + backlog" for the wiring roadmap.
