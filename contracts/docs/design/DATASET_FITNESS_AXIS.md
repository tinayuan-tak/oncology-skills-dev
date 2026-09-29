# Dataset fitness axis — `(product_id) → fitness_class`

**Status:** design + vocabulary slice (this PR introduces the `fitness_class` enum only;
the axis registry, the resolver, and the analysis-methods metric are later one-thing-per-branch
PRs). **Audience:** target-contracts framework maintainers.

## What this is

An **orthogonal, product-grain reporting axis**. Where the per-target framework answers
`(target × indication) → verdict` (is *this gene* a good target *here*?), the fitness axis
answers a question about the **evidence itself**:

> Given a data product `P`, how fit is `P` to serve as evidence for the claim it is meant to
> support?  →  `fitness_class(P)`

It is keyed by `product_id` (the id registered in `vocabularies/products.yaml` /
data-catalog manifests), **not** by a target × indication. It is a **90° rotation** of the
primary axis onto the *dataset* grain.

## Why it lives OUTSIDE the per-target grammar

Three framework facts force this to be a standalone axis rather than a new measurement_type
or card:

1. **`measurement_types.yaml` excludes it by its own scope.** That registry states its identity
   rule — "a card's IDENTITY is (measurement_type × entity_grain)" — and explicitly keeps out
   *"population-relative claims ... a different product class ... kept out of the per-target
   skills."* A fitness claim is a property of the **product**, not a per-target claim, so it is
   exactly the class the registry declines to hold.

2. **There is no product/dataset grain, and adding one would be wrong.** Every grain in
   `entity_grain_vocabulary` is target-anchored (`target`, `target_indication`,
   `target_subtype`, …). A product-keyed axis does not select *within* a target's grain
   ceiling; it is orthogonal to it. Minting a `product` grain to force fitness into the
   identity system would overload a vocabulary whose governance (the concordance test) is about
   per-target claims.

3. **A `card` is the wrong vehicle.** Cards template on `{target.symbol}` / `{indication}` and
   their `tier` enum is `target | indication | panel | subtype`. A product-keyed fitness verdict
   has no target to template on. Modelling it as a card would require a `card.schema.json` tier
   change and would misrepresent a dataset property as a target measurement.

## Dimension, not gate

Fitness **reports; it never vetoes.** It is deliberately **not** wired into
`nomination_verdict_gate.yaml`: no `fitness_class` value forces an `overall_recommendation`.
A product that is `unfit` for a claim is *flagged*, not silenced — the decision of whether the
evidence still contributes is left to the consumer, exactly as an unmeasured signal reads as
NULL rather than as "bad."

This invariant is made machine-visible on the enum itself (`axis_role: dimension`,
`never_gates: true`) so a future validator can assert that no `fitness_class` token ever appears
in the nomination gate.

## What it reads

The fitness classes are derived from the **general, cross-omics** measured-quality signals that
the data-catalog profile producer emits under `quality.measured` on each dataset profile
sidecar (data-catalog PR #637), governed by `schema/dataset-profile.schema.json` (#636):

| signal | meaning |
|---|---|
| `primary_value_missingness` | pooled NaN fraction of the primary value column(s) |
| `dynamic_range` | spread of the primary value (e.g. median \|log2FC\|) |
| `significant_fraction` | fraction of rows passing the product's significance criterion |
| `rows_measured` | number of value rows actually profiled |
| `sampling` | `full` \| `bounded_sample` \| `skipped_too_large` \| `""` |

These are intentionally **not** DGE-specific. The DGE family is the first roster to be scored,
but the class boundaries are defined on the general signals so the axis extends to any profiled
product; class thresholds will be validated against the **whole** first roster (not just the
one motivating dataset) when the resolver lands.

## The verdict vocabulary

`vocabularies/dataset_fitness_class.enum.yaml` declares the allowed `fitness_class` values.
Following framework convention, the enum carries **value semantics only** — the numeric
thresholds that map measured signals to a class live in the (later) resolver, never in the
vocabulary. The default/abstention value is `not_measured`.

| value | one-line meaning |
|---|---|
| `fit` | measured; quality signals healthy — usable without a data-quality caveat |
| `fit_with_caveats` | measured; usable, but a signal is degraded enough to surface a caveat |
| `partially_fit` | measured; a signal is degraded enough that the product supports only a **narrower** read than its name implies (the "silent degradation" case) |
| `unfit` | measured; the product cannot support its intended claim from its own values |
| `not_measured` | quality.measured absent / not profiled — the NULL abstention (default); reports "unknown," never "bad" |

## Planned sequence (one thing per branch)

1. **done** — design doc + `fitness_class` vocabulary.
2. **axis registry** (this PR) — `vocabularies/dataset_profiling_axes.yaml`: the `dataset_fitness`
   axis descriptor naming the signals it reads and their roles, parallel to
   `target_profiling_axes.yaml` but product-grain.
3. **resolution** — `vocabularies/dataset_fitness_resolution.yaml`: signals → `fitness_class` with
   declared thresholds, `default: not_measured`, validated against the full first roster.
4. **metric** — a reusable analysis-methods method that computes the signals (house rule:
   skill-readable ⇒ method), so the resolution reads a method output rather than re-deriving.

**Step 3 is NOT a `resolvers/*.resolver.yaml`** (corrected 2026-09-19; this section previously
named `resolvers/dataset_fitness.resolver.yaml`). `validators/validate_resolvers.py` globs that
directory and requires every `when_fired` token to be a `rule_id` declared in
`interpretation-rules/`, which match on `card_id`, which requires a per-target `measurement_type` —
so the only way a product-grain resolver could pass validation there is by first committing the
category error this design exists to avoid. Keeping the resolution outside `resolvers/` is what
upgrades `never_gates: true` from a convention to a **reachability** guarantee: the
rule → resolver → `nomination_verdict_gate` chain has no path to a fitness class at all.

## Non-goals (explicit)

- Does **not** add a grain to `measurement_types.yaml`.
- Does **not** add a `fitness` card or change `card.schema.json`.
- Does **not** enter `nomination_verdict_gate.yaml` (never gates a recommendation).
- Does **not** introduce a new axis token into the closed `interpretation_rules.schema.json`
  `axis` enum — the fitness resolver reads measured signals directly, not fired per-target
  `rule_id`s.
