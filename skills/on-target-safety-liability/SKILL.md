---
name: on-target-safety-liability
description: |
  Phase-G skill — germline LoF-constraint safety signal from gnomAD +
  (iter-2) HPA normal-tissue liability + IMPC + ClinVar. Consumes the
  gnomad-lof-constraint card as its first wired evidence.

  GRADUATED 2026-07-08: placeholder → partial. gnomAD constraint card
  wired against the existing gnomad-constraint-snapshot-2026-07-02 source
  manifest (data-catalog PR #79). Remaining cards
  (normal-tissue-liability, protein-surface-evidence) stay placeholder;
  their data sources are catalogued but the dispatchers are not built.

  Question this skill answers:
  Is {target} highly constrained against loss-of-function variants in the
  gnomAD population, and what does this imply for on-target safety of a
  full-KO modality (degrader, RNA therapeutic, or full-inhibition SM)?

  Reviewer-driven graduation (2026-07-08): this closes the plan's most
  obvious G-phase gap. gnomAD data was landed; wiring is a ~1-day fix
  that moves the skill from `not_wired` → `partial` with a concrete
  germline-safety signal.

metadata:
  version: 1.2.0
  owner: ryan.abo@takeda.com
  requires_preflight: false

composition:
  data_mode: derived_read
  phase: [G]
  cards_used:
    - gnomad-lof-constraint            # Wired 2026-07-08 (Layer 6e)
    - normal-tissue-liability          # Placeholder (HPA dispatcher pending)
    - protein-surface-evidence         # Placeholder (HPA IHC dispatcher pending)
    - alteration-role                  # 2026-07-23 — mechanism CONTEXT for mutant-selective
                                       # conditioning of the WT gnomAD-constraint concern (its
                                       # activating-driver-role-safety-context rule combines with the
                                       # highly-constrained warning in the resolver → downgrade).
  # DATA_TO_SKILL_CONTRACT Rule 3 — measurement_type claims pulled. normal_tissue_protein_breadth is
  # the safety-framed normal-tissue type (distinct from selectivity's tumor_vs_normal). surface_
  # confirmation is pulled-but-data-blocked (its card needs the CSPA/HPA reader) — a visible-gap state.
  measurement_types_pulled:
    - gnomad_lof_constraint
    - normal_tissue_protein_breadth
    - surface_confirmation
    - alteration_role                  # mechanism-conditioning input (mutant-selective downgrade)
  rules_scope:
    - gnomad-lof-constraint
    - activating-driver-role-safety-context   # mutant-selective conditioning (2026-07-23)
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  status: partial
  # KNOWN GAP (2026-07-13 review): the gnomad-lof-constraint dispatcher
  # currently imports methods.gnomad_constraint, which does NOT exist — so
  # this card resolves to _missing (its source manifest landed, but the
  # reader method was never written). The skill therefore produces no real
  # constraint verdict yet. Tracked as a separate feature workstream (build
  # the gnomad_constraint method module). status stays `partial` honestly.
  # normal-tissue-liability + protein-surface-evidence are excluded from the
  # runtime card set (dispatchers pending); a prior on_dependency_status
  # block was removed because run.py never passed it.
---

# on-target-safety-liability — Phase G partial skill

## What this skill does (iter-1 partial wiring)

Given a target:
  1. Loads the gnomad-lof-constraint card summary (pLI, LOEUF, mis_z,
     constraint_class).
  2. Rules engine consumes constraint_class categorical → per-modality
     safety signals (highly_constrained → warning; tolerant → supportive).
  3. Emits a data_package output tree with the constraint-derived safety
     verdict.

## What this skill does NOT do (yet)

- **gnomAD constraint (the one "wired" card):** currently NON-FUNCTIONAL —
  the dispatcher imports `methods.gnomad_constraint`, a method module that
  has not been written yet (the gnomAD source manifest landed, but the
  reader did not). The card resolves to `_missing`; no constraint verdict is
  produced until that method is built. Tracked as a separate workstream.
- **Normal-tissue liability from HPA IHC:** the normal-tissue-liability
  card's HPA IHC-intensity dispatcher is not built; the card is not in this
  skill's runtime card set, so no section is produced for it.
- **Protein-surface evidence:** same — dispatcher pending, not in card set.
- **IMPC mouse KO phenotypes:** not catalogued; iter-2 backlog.
- **ClinVar germline outcomes:** not catalogued; iter-2 backlog.
- **Historical trial-outcome DB:** external data feed licensing pending.

## Output tree (data_package shape)

```
<out>/
├── decision.json                 # rule verdicts + fired rules
├── summary.yaml                  # card summary_fields (gnomad only in iter-1)
├── tables/
│   └── gnomad_constraint_summary.csv   # emitted only when the card resolves
└── provenance.yaml               # data_provenance (manifest IDs) + partial-status notice
```

(No `figures/` are emitted by this skill — no figure emitter is wired.)

## Invocation

```
/on-target-safety-liability KRAS
```

## Provenance discipline

- `data_provenance`: per-card data_source (derived-manifest ID) + missing
  flag/reason, emitted by the shared writer.
- `skill_status`: `partial` — surfaced in every output so consumers see the
  epistemic ceiling.
- Placeholder cards (normal-tissue-liability, protein-surface-evidence) are
  excluded from the runtime card set rather than skipped via a runtime
  mechanism.

## Iter-2 wiring roadmap

1. Build HPA IHC-intensity dispatcher for normal-tissue-liability card.
2. Add IMPC + ClinVar source manifests to data-catalog.
3. Add on-target-safety-clinical-precedent card (external trial-outcome
   feed licensing).
