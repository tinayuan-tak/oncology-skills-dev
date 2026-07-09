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
  version: 1.1.0
  owner: ryan.abo@takeda.com
  requires_preflight: false

composition:
  data_mode: derived_read
  phase: [G]
  cards_used:
    - gnomad-lof-constraint            # Wired 2026-07-08 (Layer 6e)
    - normal-tissue-liability          # Placeholder (HPA dispatcher pending)
    - protein-surface-evidence         # Placeholder (HPA IHC dispatcher pending)
  rules_scope:
    - gnomad-lof-constraint
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  status: partial
  on_dependency_status:
    normal-tissue-liability: skip_section       # arch A4 discipline
    protein-surface-evidence: skip_section
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

- **Normal-tissue liability from HPA IHC:** the normal-tissue-liability
  card's HPA IHC-intensity dispatcher is not built. When invoked, this
  skill's per-tissue liability section will be SKIPPED per the
  on_dependency_status: skip_section arch A4 contract.
- **Protein-surface evidence:** same — dispatcher pending.
- **IMPC mouse KO phenotypes:** not catalogued; iter-2 backlog.
- **ClinVar germline outcomes:** not catalogued; iter-2 backlog.
- **Historical trial-outcome DB:** external data feed licensing pending.

## Output tree (data_package shape)

```
<out>/
├── decision.json                 # rule verdicts + fired rules
├── summary.yaml                  # card summary_fields (gnomad only in iter-1)
├── figures/
│   └── constraint_scores_gauge.png
├── tables/
│   └── gnomad_constraint_summary.csv
└── provenance.yaml               # gnomAD manifest md5, partial-status notice
```

## Invocation

```
/on-target-safety-liability KRAS
```

## Provenance discipline

- `gnomad_snapshot`: manifest ID pin (gnomad-constraint-snapshot-2026-07-02)
- `skill_status`: `partial` — surfaced in every output so consumers see the
  epistemic ceiling
- `skipped_sections`: enumerates which cards were skipped due to
  placeholder dependencies (per arch A4)

## Iter-2 wiring roadmap

1. Build HPA IHC-intensity dispatcher for normal-tissue-liability card.
2. Add IMPC + ClinVar source manifests to data-catalog.
3. Add on-target-safety-clinical-precedent card (external trial-outcome
   feed licensing).
