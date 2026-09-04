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
  version: 3.8.0   # +--literature lane + verdict-INERT surfacing (directness_caveat DGIdb/ChEMBL inflation flag, chemical_genetic_agreement arm, TRACTABILITY_SM thesis+polarity_note); +tuned signals-first sub-group reader; +question_table emitted into headline; +known-drug (#272) +degradation (#266) +T1/T3.1
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
    - structure-features-static      # E8: forward ligandability (pocket structure + LIVE hotspot-adjacency)
    - known-drug-tractability        # E-known-drug: PHARMACOLOGY leg (DGIdb known-drug + druggable-category)
    - measured-potency-tractability  # E-measured-potency (T3.1): ChEMBL/BindingDB MEASURED binding potency
    - degradation-feasibility        # E3 slice 3: DEGRADER-lens degradability (fires degrader-channel rules)
    - gdsc-drug-activity             # 2nd drug-response platform (Sanger GDSC1/2), ORTHOGONAL corroboration of
                                     # PRISM. DISPLAY-ONLY / verdict-INERT — fires no rule, NOT in rules_scope;
                                     # a 2nd provider of the prism_compound_activity claim (the ProCan->Gygi analog)
  # DATA_TO_SKILL_CONTRACT Rule 3 — measurement_type claims pulled. chemical_genetic_concordance is
  # the derived on-target-engagement type this gate shares with functional-requirement (flow-pattern 2:
  # one atom, two gate-views). dependency_predictability had no puller before this — now claimed here.
  measurement_types_pulled:
    - prism_compound_activity
    - chemical_genetic_concordance
    - dependency_predictability
    - structure_druggability
    - known_drug_tractability        # E-known-drug: DGIdb pharmacology leg (approved-drug -> chemically_active; druggable-category -> structurally_ligandable)
    - measured_potency_tractability  # E-measured-potency (T3.1): ChEMBL/BindingDB (potent series -> measured_potent_ligand)
    - degradation_feasibility        # E3 slice 3: target degradability (degrader-lens only; SM verdict byte-stable)
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

- Fetches the 7 tractability cards via the compose-dashboard live-reader dispatchers:
  the 3 chemical-genetic (prism-compound-activity, prism-crispr-concordance,
  dependency-predictability), the structure leg (structure-features-static: forward
  ligandability + LIVE hotspot-adjacency), the DGIdb pharmacology leg (known-drug-
  tractability), the MEASURED-potency leg (measured-potency-tractability: ChEMBL/BindingDB),
  and the degrader-lens leg (degradation-feasibility).
- Fires the `e7-*` / `prism-*` / `predictability-*` / `ligandability-*` / `known-drug-*` /
  `measured-*` rules.
- Emits `decision.json` with:
  - `headline`: `druggability_snapshot` + `driving_rule_id`, plus the driving
    prism activity class, PRISM-CRISPR concordance class, and predictability
    class.
  - `fired_rules`: which chemical-genetic rules matched.

## Snapshot resolution (rank-ordered, first match wins)

Source of truth: `target-contracts/resolvers/tractability_small_molecule.resolver.yaml` (v1.3.0).
Precedence: ON-TARGET chemical-genetic (concordance-confirmed) > opposing OFF-TARGET > retrospective
chemical ACTIVITY > MEASURED potency > structural forward-ligandability > unhit.

  1. `e7-triangulated-target-engaged-supportive` → `well_covered`
     (chemical hit agrees with the genetic dependency — highest confidence; on-target)
  2. `e7-crispr-confirmed-supportive-sm` → `chemically_confirmed_genetic` (on-target)
  3. `e7-discordant-off-target-warning` → `discordant`
     (T1.1: an OFF-target compound demotes a would-be chemical hit; MUST precede the activity rungs.
      Stays below the on-target rungs above — a proven-on-mechanism target is not overridden.)
  4. `prism-clinically-active-supportive-sm` → `chemically_active` (measured cell-panel activity)
  5. `known-drug-approved-antineoplastic-sm-supportive` → `chemically_active` (DGIdb approved drug)
  6. `prism-clinical-precedent-only-weak-supportive-sm` → `clinical_precedent_only`
     (T1.2: a phase-1+ compound ANNOTATED but NO measured activity — weaker than a measured hit)
  7. `prism-tool-compound-only-weak-supportive-sm` → `tool_compound_only`
  8. `prism-weakly-active-weak-supportive-sm` → `weakly_active`
  9. `measured-potent-ligand-sm-supportive` → `measured_potent_ligand`
     (T3.1: a potent ≤1 µM MEASURED chemotype series from ChEMBL/BindingDB — a real chemical start point)
  10. `ligandability-experimental-sm-supportive` → `structurally_ligandable` (real co-crystal, strongest handle)
  11. `hotspot-in-druggable-pocket-sm-supportive-e8` → `structurally_ligandable` (LIVE hotspot-in-pocket, KRAS-G12C archetype)
  12. `structure-pocket-adjacent-sm-supportive` → `structurally_ligandable`
  13. `ligandability-predicted-sm-supportive` → `structurally_ligandable` (predicted pocket / VS-hit / cryptic)
  14. `known-drug-druggable-category-sm-supportive` → `structurally_ligandable` (DGIdb druggable-class prior)
  15. `measured-weak-ligand-sm-supportive` → `structurally_ligandable` (T3.1: weak measured activity — a starting-point handle)
  16. `structure-low-confidence-sm-opposing` → `structurally_intractable` (E8: low-confidence fold)
  17. `ligandability-disordered-sm-opposing` → `structurally_intractable` (measured IDP disorder — SM-opposing, not a killer)
  18. `prism-no-compounds-found-neutral` → `chemically_unhit`
  19. else → `insufficient`

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
