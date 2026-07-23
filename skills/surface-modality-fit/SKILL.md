---
name: surface-modality-fit
description: |
  Phase-F skill: "For target X in indication Y, does the surface biology
  (topology, surfaceome family, structure pockets, abundance) support a
  biologics modality — ADC-favorable, TCE-favorable, both, or neither?"

  SPLIT 2026-07-14 from the former `tractability-and-modality` skill, which
  merely DISPLAYED these 6 surface cards without letting them change its
  (chemical-genetic) verdict. This skill makes the surface-modality call,
  resolving from the composed `adc-tce-modality-fit` card's `fit_class`.

  status: partial — most surface derived products (structure-features,
  surfaceome-family, cohort-ranking) are not yet on S3, so the verdict is an
  honest `insufficient` until they land. The sibling small-molecule
  tractability call is `tractability-small-molecule`.

  Use for questions like "does EGFR look ADC-favorable in COADREAD?", "is this
  target TCE-viable topologically?"

metadata:
  version: 1.0.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg
  method_version_pins:
    isoform_selective_targets: '1.0.0'

composition:
  data_mode: derived_read
  phase: [F]
  cards_used:
    - surface-topology-and-ptm
    - surfaceome-family-classification
    - structure-features-static
    - surface-abundance-density
    - adc-tce-modality-fit
    - normal-tissue-liability          # HPA IHC off-tumor safety (in run.py CARDS; was doc-stale)
    - copy-number-distribution         # P4 (2026-07-23): genomic amplification → surface antigen-density
                                       # signal (adc/bite_tce/antibody). Same card reads SM/degrader at
                                       # genomic-alteration-profile — Example B. Render/signal facet.
  # DATA_TO_SKILL_CONTRACT.md Rule 3 — the PULL half: this gate-view declares the
  # measurement_type CLAIMS it needs to answer "is this target biologics-viable", independent of
  # which datasets provide them. Keys resolve against target-contracts/vocabularies/
  # measurement_types.yaml. During migration cards_used (above) is the live wiring; this list is
  # the machine-checkable pull-intent a resolver will match on (migration step 5 — resolver matches
  # on type, falling back to card_id/product_id). surface_confirmation is pulled but not yet in
  # cards_used because its card (protein-surface-evidence) is data-blocked until the CSPA/HPA reader
  # lands — the pull makes that gap explicit (a registered type with a puller but no live provider),
  # exactly the first-class visible state Rule 3 describes.
  measurement_types_pulled:
    - surface_confirmation
    - surface_topology
    - surfaceome_family
    - surface_density
    - adc_tce_modality_fit
    - normal_tissue_protein_breadth    # HPA IHC off-tumor safety (normal-tissue-liability)
    - copy_number_alteration           # P4 (2026-07-23): genomic amplification → surface antigen-density lens
  rules_scope:
    - all
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  optional_lenses:
    - modality
  status: partial
---

# surface-modality-fit

## What this skill does

- Fetches the 5 surface/structure cards via the compose-dashboard live-reader
  dispatchers.
- Fires the `surface_intrinsic` rule subset.
- Resolves a `surface_modality_verdict` from the composed `adc-tce-modality-fit`
  `fit_class` — the card that fuses topology / family / structure / density
  into a modality call.
- Emits `decision.json` with the verdict + `driving_rule_id`, the `fit_class`,
  and the contributing surface categoricals.

## Verdict resolution (rank-ordered, first match wins)

  1. `adc-preferred-supportive` → `adc_preferred`
  2. `tce-preferred-supportive` → `tce_preferred`
  3. `both-viable-supportive` → `both_viable`
  4. `neither-viable-killer` → `neither_viable`
  5. `isoform-dependent-modality-suppression` → `isoform_dependent_undefined`
  6. else → `insufficient` (honest — surface inputs data_unavailable)

## Status: partial

Most surface derived products are not yet on S3:
- `structure-features-static` (PDB/AlphaFold manifests not re-landed)
- `surfaceome-family-classification` (derived product pending)
- `surface-abundance-density`, cohort-ranking (pending)

Until they land, `fit_class` is typically `data_unavailable` and the verdict is
`insufficient`. This is honest, not a bug — the skill does not fabricate a
modality call from missing surface data.

## Known design gap (flagged, not owned by this skill)

`fit_class == modality_ambiguous` has NO rule in `surface-intrinsic.rules.yaml`,
so a target landing there fires nothing → `insufficient`. Adding that rule is a
target-contracts change (rule-coverage-holes), tracked separately.

## How Claude invokes this skill

1. Extract `target` (HGNC symbol) + `indication` (OncoTree code).
2. Pick a durable `out` directory (avoid `/tmp`).
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/surface-modality-fit/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
4. Read `<OUT_DIR>/decision.json`; present `surface_modality_verdict` +
   `driving_rule_id`. If `insufficient` due to `data_unavailable`, say so
   plainly (surface data not yet landed).
