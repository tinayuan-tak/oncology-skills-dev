---
name: tractability-small-molecule
description: |
  Phase-F skill: "Given known chemical + genetic evidence, does target X in
  indication Y look druggable by a small molecule — is there a compound that
  hits it, and does the chemical signal agree with the genetic dependency?"

  SPLIT 2026-07-14 from the former `tractability-and-modality` skill. That
  skill had grown to 9 cards, but its verdict keyed entirely off the 3
  chemical-genetic cards; the 6 surface cards it merely displayed were split
  into the sibling `surface-modality-fit` skill. This skill owns the
  small-molecule / intracellular tractability call.

  Use for questions like "does PRISM show anyone hitting KRAS in COADREAD?",
  "is there a tool compound for MET, and does it agree with the CRISPR
  dependency?"

metadata:
  version: 3.1.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [F]
  cards_used:
    - prism-compound-activity
    - prism-crispr-concordance
    - dependency-predictability
    - structure-features-static      # E8: forward ligandability (pocket structure)
  # DATA_TO_SKILL_CONTRACT Rule 3 — measurement_type claims pulled. chemical_genetic_concordance is
  # the derived on-target-engagement type this gate shares with functional-requirement (flow-pattern 2:
  # one atom, two gate-views). dependency_predictability had no puller before this — now claimed here.
  measurement_types_pulled:
    - prism_compound_activity
    - chemical_genetic_concordance
    - dependency_predictability
    - structure_druggability
  rules_scope:
    - all
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  status: wired
---

# tractability-small-molecule

## What this skill does

- Fetches the 3 chemical-genetic cards (prism-compound-activity,
  prism-crispr-concordance, dependency-predictability) via the
  compose-dashboard live-reader dispatchers.
- Fires the `e7-*` / `prism-*` / `predictability-*` rules.
- Emits `decision.json` with:
  - `headline`: `druggability_snapshot` + `driving_rule_id`, plus the driving
    prism activity class, PRISM-CRISPR concordance class, and predictability
    class.
  - `fired_rules`: which chemical-genetic rules matched.

## Snapshot resolution (rank-ordered, first match wins)

Chemical-genetic evidence (RETROSPECTIVE — a compound has actually hit the target)
ranks highest; structural / forward ligandability (E8 — a druggable pocket, no
compound required) ranks below a real chemical hit but above `chemically_unhit`.

  1. `e7-triangulated-target-engaged-supportive` → `well_covered`
     (chemical hits agree with genetic dependency — highest confidence)
  2. `e7-crispr-confirmed-supportive-sm` → `chemically_confirmed_genetic`
  3. `prism-clinically-active-supportive-sm` → `chemically_active`
  4. `prism-tool-compound-only-weak-supportive-sm` → `tool_compound_only`
  5. `prism-weakly-active-weak-supportive-sm` → `weakly_active`
  6. `hotspot-in-druggable-pocket-sm-supportive-e8` → `structurally_ligandable`
     (E8: druggable pocket, forward — the KRAS-G12C switch-II archetype)
  7. `structure-pocket-adjacent-sm-supportive` → `structurally_ligandable`
  8. `e7-discordant-off-target-warning` → `discordant`
  9. `structure-low-confidence-sm-opposing` → `structurally_intractable`
     (E8: low-confidence/disordered fold — SM-opposing, NOT a killer)
  10. `prism-no-compounds-found-neutral` → `chemically_unhit`
  11. else → `insufficient`

## Degrader lens (2026-07-23, modality-specific-interpretation slice 2)

The headline ALSO carries a `degrader_snapshot` — a SECOND-PASS projection over the DEGRADER channel
of the same fired rules (this skill loads the intracellular axis, which scores small_molecule AND
degrader in parallel). Degradation ≠ inhibition: it models COMPLETE removal (KO-like), so a target
with a dependency but no druggable pocket can still be a degrader prospect. Rank: a degrader-killer →
`degrader_unviable`; a dominant degrader-supportive → `strong_degrader_rationale`; any degrader-
supportive → `degrader_rationale`; a degrader-opposing → `degrader_opposed`; else `insufficient`.
ADDITIVE + verdict-inert (the SM snapshot resolution above is unchanged). The FULL degrader question
("is the degradation MACHINERY intact?" — CRBN/VHL/proteasome) needs the E3-machinery card
(modality-specific-interpretation slice 3, not yet built); until then `degradability_machinery` reads
`not_yet_assessed`.

## What this skill does NOT do

- Does NOT assess biologics-modality fit (ADC / TCE / degrader surface
  topology, surfaceome family). That is the sibling `surface-modality-fit`
  skill. A full modality workup chains both. NB: `structure-features-static`
  is consumed by BOTH skills — this one reads it for SM pocket ligandability
  (E8, small_molecule-scoped rules); surface-modality-fit reads it for
  adc/bite_tce topology (surface-axis rules). Same card, two axis-scoped reads.
- No new dispatchers.

## How Claude invokes this skill

1. Extract `target` (HGNC symbol, uppercase) and `indication` (AACR OncoTree
   code, uppercase — e.g. COADREAD, LUAD).
2. Pick a durable `out` directory (prefer `~/dev/framework-runs/...`; avoid
   `/tmp`, which is wiped on SageMaker restart).
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/tractability-small-molecule/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
4. Read `<OUT_DIR>/decision.json`, present the `druggability_snapshot` +
   `driving_rule_id` inline.
