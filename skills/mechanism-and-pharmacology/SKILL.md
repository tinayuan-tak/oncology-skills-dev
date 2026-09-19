---
name: mechanism-and-pharmacology
description: |
  Phase-D skill — signaling-network mechanism + candidate MoA hooks + PD-
  marker suggestions for a target. Consumes the signaling-network-mechanism
  evidence card — a directed signaling network composed from curated sources
  (SIGNOR + CollecTRI + Reactome) and classified into a 31-class MoA ontology.

  The network is composed on-read (methods/mechanism_composed) from the SIGNOR
  Jul2026 source release plus the CollecTRI curated edge set; the `network_class`
  edge COUNT is SIGNOR + CollecTRI only — Reactome is layered as pathway CONTEXT
  (membership/MoA), NOT counted in the edge total. Lower-weighted kinome-atlas
  prediction and DepMap co-essentiality lanes are carried alongside (never merged
  into network_class). It does NOT read OmniPath.

  Question this skill answers:
  For {target} in {indication}, what upstream regulators + downstream
  effectors are catalogued in the composed network, and which MoA classes are
  candidate hooks for small-molecule / degrader / molecular-glue programs?

metadata:
  version: 1.11.0
  owner: ryan.abo@takeda.com
  requires_preflight: false
  method_version_pins:
    signor_mechanism_network: '0.1.0'
    moa_ontology: '1.0.0'
    tahoe_drug_perturbation: '0.1.0'
    depmap_predictability: '0.2.0'

composition:
  data_mode: derived_read
  phase: [D]
  cards_used:
    - signaling-network-mechanism
    - tahoe-drug-perturbation           # ADDED 2026-08-10: Tahoe-100M single-cell drug-perturbation
                                        # MoA facet (which drugs move the target's expression). DISPLAY-ONLY
                                        # facet — feeds NO resolver (mechanism_verdict byte-stable).
                                        # engagement != dependency (a MoA lens).
    - phospho-pathway-activity          # RE-HOMED 2026-08-05 (was tumor-presence): phosphorylation is an
    - pathway-activity-context             # Track PROGENy (2026-08-10): per-indication PROGENy pathway-activity context; verdict-inert (upgrades Mechanism topology→quantitative activity)
                                        # ACTIVITY / signaling-state readout (CPTAC phosphoproteomics),
                                        # a mechanism signal not a presence one. DISPLAY-ONLY facet —
                                        # feeds NO resolver (mechanism_verdict byte-stable).
    - dependency-predictability         # ADDED 2026-08-18: DepMap predictability FEATURE-ATTRIBUTION facet —
                                        # the genome-wide omics features that best predict the target's Chronos
                                        # dependency, filtered to mechanistically-plausible partner-gene classes
                                        # and cross-referenced against SIGNOR partners. DISPLAY-ONLY facet —
                                        # feeds NO resolver (mechanism_verdict byte-stable); NOT in rules_scope.
  # DATA_TO_SKILL_CONTRACT Rule 3 — the measurement_type claims pulled, ONE per card in cards_used.
  # 2026-08-14 review: added pathway_activity_context — the pathway-activity-context card (PROGENy,
  # added 2026-08-10) was in cards_used but its type was omitted here. test_mechanism_measurement_types.py
  # now enforces every used card's type is declared so this cannot silently re-drift.
  measurement_types_pulled:
    - signaling_network_mechanism            # signaling-network-mechanism
    - tahoe_drug_perturbation                # tahoe-drug-perturbation
    - phospho_pathway_activity               # phospho-pathway-activity
    - pathway_activity_context               # pathway-activity-context (PROGENy)
    - dependency_predictability              # dependency-predictability (feature-attribution facet)
  rules_scope:
    - all
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  optional_lenses:
    - modality
  status: wired
---

# mechanism-and-pharmacology — Phase D wired skill

## What this skill does

Given a target + indication:
  1. Loads the target's composed signaling network (SIGNOR + CollecTRI +
     Reactome) on-read via methods/mechanism_composed, keyed on the target's
     UniProt-AC.
  2. Classifies each edge under the 31-class MoA ontology
     (methods/signor_mechanism_network/moa_ontology.py v1.0.0).
  3. Emits a MoA opportunities table (upstream regulators, per-edge
     mechanism, MoA class, modality relevance) + a PD-marker opportunities
     table (downstream effectors, per-edge mechanism, PD-marker relevance).
  4. Rule engine consumes categorical `network_class` +
     `has_actionable_moa` + `has_pd_marker` fields; emits per-modality
     signals (small_molecule + degrader).

## Output tree (data_package shape)

```
<out>/
├── decision.json                 # rule verdicts + fired rules
├── summary.yaml                  # card summary_fields
├── tables/
│   ├── moa_opportunities.csv     # upstream regulators, per-row MoA class
│   └── pd_marker_opportunities.csv
└── provenance.yaml               # data_provenance (manifest IDs) + MoA ontology version

(No `figures/` are emitted — no figure emitter is wired for this skill.)
```

## Invocation

```
/mechanism-and-pharmacology KRAS in COADREAD
```

## Provenance discipline

Every emitted decision.json + summary.yaml stamps:
  - `data_provenance`: the composed sources' manifest pins (the SIGNOR Jul2026
    source release + the CollecTRI / Reactome edge sets)
  - `moa_ontology_version`: from methods/signor_mechanism_network/moa_ontology.py
  - `moa_ontology_unmapped_fraction`: fraction of curated edges that fell
    to 'unmapped' class (target <5%; CI test enforces)
  - `method_version`: the composing method version

## Data gaps (iter-2 upgrade path)

- **Pathway centrality (betweenness):** the composed network gives edge-level
  MoA classification and Reactome pathway membership, but not pathway-topological
  centrality (betweenness). Computing centrality over the composed graph is a
  future extension.
- **Downstream PD-signature datasets:** the MoA ontology names PD markers
  by mechanism (e.g. "monitor KRAS-RAF1 association") but does not link
  to published PD signature datasets. Consumers of this skill's output
  must cross-reference literature for actual signature-based readouts.
- **Phenotype-of-dependency screens:** differentiation / migration /
  apoptosis phenotype-following-inhibition data (Genentech iDEP, etc.)
  not yet catalogued.
