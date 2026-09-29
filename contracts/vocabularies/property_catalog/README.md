# property_catalog/ — the governed register of biological properties

Epic #1507's thesis is that measurements resolve **shared biological properties**, not
per-card classifiers. Until now that thesis lived in prose (`docs/EVIDENCE_PROPERTY_ENVELOPE_v0.md`)
and in code (`skills/_skills_common/presence_claims.py::_SOURCE_PROPERTY_RECIPES`), so there was
no single place to answer the two questions the architecture stands on:

1. **Which property does this measurement estimate?** — and therefore which *other* measurements
   are estimating the same thing and may corroborate it.
2. **What numbers decide its value, and why those numbers?**

This directory is that place. It is a **register, not an engine**: nothing here executes, and no
skill reads these files at runtime. The teeth are `../../validators/validate_property_catalog.py`
(run by `scripts/preland.sh contracts`) plus `../../tests/validators/test_property_catalog.py`.

## Files

| file | `kind` | what |
|---|---|---|
| `expression.yaml` | `l2a_property` | the shared expression properties (the `expression_property.enum.yaml` v1.0.0 family), resolved today from the cell-line RNA panel |
| `tumor_presence.yaml` | `l2a_property` | the six per-source properties the tumour-presence vertical resolves — the reference L2a implementation |
| `integrated_families.yaml` | `l2b_family` | the 13 landed L2b concordance families: which arms each integrates, and on what comparability basis |

Wave 1 of arc #2210 adds one `l2a_property` file per remaining domain (safety, dependency,
genomic, selectivity, surface). **Add files; do not grow these three.**

## The identifiability test — the admission criterion for `role: estimator`

Two observables are estimators of **one** property only if *perfect* measurements of both would
agree up to noise.

- CRISPR essentiality × RNAi essentiality → **one** property. A perfect knockout screen and a
  perfect knockdown screen would agree; the disagreements we see are measurement error and
  incomplete knockdown. Two `estimator`s.
- Tumour RNA abundance × tumour protein abundance → **two** properties. Perfect measurements of
  both would *still* disagree, because translation and degradation intervene. That disagreement is
  biology, not noise. So they are two properties with a declared coupling — never two arms of one.

An observable that measures a genuinely different property but is retained on an entry to record
the coupling carries `role: coupled` and **must** name what it actually estimates via
`estimates_property:`. A `coupled` observable is not independent corroboration, and a consumer that
counts it as such is wrong.

This is why `role:` is mandatory and why the validator requires every property to carry at least
one `estimator`. A property with only `coupled` observables is not resolvable — it is a placeholder
that has not admitted the thing that measures it.

## `dependence_group` — the anti-double-counting field

Mandatory on every observable and every family arm. Two observables sharing a `dependence_group`
share a supply chain (same assay modality, same source dataset, same cohort) and must **never** be
counted as independent arms. The motivating case is #1667: CPTAC and TPHP are both mass-spectrometry
tumour proteomics, so `protein_ms` covers both and a "two-arm agreement" across them is one arm
measured twice.

For an `l2b_family`, the validator requires either **≥2 distinct `dependence_group`s among the
arms** or an explicit `independence_waiver:` saying out loud why a single-group family earns its
keep. A family that integrates siblings without saying so is asserting independence it does not have.

## Entry shape

```yaml
catalog_id: <must equal the filename stem>
kind: l2a_property | l2b_family
version: <semver>
description: |
  ...
governance:
  role: |          # what this file is authoritative for
  versioning: |    # what a bump means here
  ownership: |     # who changes it and via what coordination
  change_discipline: |
properties:        # `families:` for kind: l2b_family
  <snake_case_id>:
    definition: |
      One sentence naming the latent quantity — NOT the classifier, NOT the card.
    grain:
      measurement_type: <governed measurement_types.yaml key or a free token where none exists>
      sample_context: <patient_tumor | cell_line_panel | normal_tissue | ...>
      entity_grain: <gene | transcript | protein | ...>
    observables:                           # l2a_property only
      - card_id: <must exist in cards/>
        field: <must be in that card's outputs.summary_fields>
        role: estimator | coupled
        dependence_group: <token>
        estimates_property: <property_id>  # REQUIRED iff role: coupled
        lift: card_summary | headline       # optional; `headline` = read off the headline, see below
        note: |                             # optional
    arms:                                  # l2b_family only; >= 2
      - card_id: ...
        field: ...
        dependence_group: ...
        property_id: ...                    # optional — set once the arm's property is catalogued
    determinants:                          # may be empty; every entry needs a rationale
      - name: <constant name as it appears in code>
        value: <number | string>
        unit: <what the number is in — see the units caution below>
        source: <repo-relative path[:line] — the PATH must exist>
        rationale: |
          Why THIS number. The literal `UNKNOWN` is permitted and honest, but then
          `calibration.adjudication` is REQUIRED so the hole is tracked rather than permanent.
        calibration:
          controls: <ref | null>
          flip_matrix: <ref | null>
          adjudication: <issue ref | null>
    integration:                           # l2b_family only; REQUIRED there, FORBIDDEN on l2a
      island_key: <the emitted concordance-island key>
      builder: <repo-relative path to the fold-builder module>
      builder_function: <_x_concordance_claim>
      comparability: |
        What must hold for these arms to be commensurable at all.
      relations: [corroborates, contradicts, qualifies]   # subset of dependence_edges.py
      independence_waiver: |               # only when all arms share one dependence_group
    consumers:                             # may be empty
      - skill: <must be a real skills/<name>/ directory>
        axis_key: <the HeadlineSpec axis that reads it>   # or `surface:` for a non-axis consumer
```

### `lift: headline`

Two landed families (`recurrence`, `selectivity`) read their arms off the **headline** rather than
off card summaries — the builder receives `h.get("genie_driver_recurrence_class")`, not a card dict.
The catalog still records the underlying `{card_id, field}`, because the reconstructability contract
is about where the number *came from*, not which dict the builder happened to read. `lift: headline`
records the indirection so nobody mistakes the entry for a direct card read.

### The units caution

`unit:` is mandatory and load-bearing. Reconciling two thresholds that turn out to be in different
units produces a confident, wrong answer: a *fraction of a panel* and a *median expression level*
are both "0.3" and are not comparable. Arc #2210's Wave-3 adjudications exist partly because this
was not recorded anywhere.

## Governance

- **Additive only.** Removing a property, or changing an existing property's `grain`, is a breaking
  change; `validate_property_catalog.py --additive-against <ref>` enforces this against a git ref
  and `preland.sh` runs it against the merge base when one is resolvable.
- Adding a property or an observable is a **minor** bump. Correcting a rationale or a `source:` line
  is a **patch** bump.
- `property_id`s are referenced by ID from outside this directory (the arc's forthcoming
  `claim_axis.enum.yaml` `resolves:` field, #2228). Treat an ID as a published name: **add → consume
  → remove**, never a bare rename.

## What this catalog deliberately does NOT do

- It does not gate a verdict, and no consumer may make it one. Per SK#2091, verdict movement is not
  a metric here in either direction.
- It does not check itself against skills' `HeadlineSpec`s. The dependency direction is
  `skills/` → `contracts/`, never the reverse, so the contracts-side validator may only check the
  `consumers:` block's *shape*; comparing it against real axis declarations belongs to a skills-side
  test (#2228).
- It does not define new concordance families. The 13 in `integrated_families.yaml` are the landed
  population; new families belong to peer epics #1730 / #1755 / #1779 / #1812.
