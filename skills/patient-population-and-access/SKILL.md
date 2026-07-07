---
name: patient-population-and-access
description: |
  Focused question skill: "How prevalent is target X's mutation footprint
  in indication Y's patient population, and what are the top recurrent
  hotspots?" Consumes the mutation-hotspot-frequency card (TCGA MC3
  tumor MAF) and emits a data-package output tree with the population-
  level mutation frequency, top hotspots, and mutually-exclusive/
  co-occurring gene neighborhoods.

  Use for questions like "how common is KRAS mutation in COADREAD?",
  "what's the top TP53 hotspot in colorectal tumors?", "how many CRC
  patients carry an APC mutation?"

  This is a NARROWLY-SCOPED version of Phase-H access questions. Two other
  Phase-H subquestions (subgroup-stratified expression + RWD-stratified
  prevalence) require cards that are declared but NOT yet wired — see
  caveats section below. When those cards come online, this skill's scope
  should broaden.

  CDx feasibility + standard-of-care whitespace remain out of scope
  entirely (require commercial data feeds).

  Biology-first output. Modality is a POST-HOC lens exposed via optional
  --modality flag.

metadata:
  version: 1.0.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [H]
  cards_used:
    - mutation-hotspot-frequency
  rules_scope:
    - mutation-hotspot-frequency
  synthesis:
    - none
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 6]
  optional_lenses:
    - modality
  status: partial
---

# patient-population-and-access

## What this skill does

- Fetches the `mutation-hotspot-frequency` card via the compose-dashboard
  live-reader dispatcher (streams TCGA MC3 MAF from S3).
- Surfaces raw metrics directly to the headline (no rules fire on this
  card_id in the current intracellular-intrinsic.rules.yaml — see
  §"Coverage gaps" below).
- Emits a data-package output tree with:
  - `decision.json` — headline metrics + empty fired_rules
  - `summary.yaml` — full hotspot-frequency card summary
  - `tables/{card}_hotspot_frequencies.csv` — top hotspots (protein_change,
    n_samples, frequency)
  - `provenance.yaml` — audit anchor

## Headline metrics

- `overall_mutation_frequency`: fraction of indication tumors with any
  target mutation
- `n_samples_in_indication`, `n_samples_mutated`: cohort counts
- `top_hotspot_residue` + `top_hotspot_frequency`: highest-recurrence
  hotspot in the indication cohort
- `top_cooccurring_genes` (if present) + `top_mutually_exclusive_genes`

## Coverage gaps (why status is `partial`)

Phase-H target-ID/profiling questions this skill does NOT answer:

- **Subgroup-stratified prevalence**: `subgroup-stratified-expression`
  dispatcher is declared as placeholder in
  `_live_readers.CARD_DISPATCHERS` but not wired. Needs
  methods/subgroup_assigner_*/read.py implementations.
- **RWD-stratified prevalence** (Tempus, Flatiron, etc.):
  `rwd-stratified-expression` dispatcher is placeholder-only. Blocked on
  `methods/tempus_rwd_aggregator/` carveout.
- **CDx (companion diagnostic) reachability**: requires
  commercial-database access (Cortellis / FDA CDx list) — not in current
  data-catalog scope.
- **Standard-of-care whitespace by line of therapy**: same commercial
  data-feed dependency.

These are named explicitly here so a user of this skill knows the
limitation — the `data_package` output is defensible for the wired
subset but does NOT constitute a full population-and-access analysis.

## How Claude invokes this skill

When called as `/patient-population-and-access`, Claude should:

1. Extract `target` + `indication`.
2. Pick an `out` directory (default `/tmp/patient-population-and-access/{target}-{indication}`).
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/patient-population-and-access/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
4. Present headline metrics + top-3 hotspots inline; note the coverage
   gaps if the user asked about subgroup / RWD / CDx dimensions.
