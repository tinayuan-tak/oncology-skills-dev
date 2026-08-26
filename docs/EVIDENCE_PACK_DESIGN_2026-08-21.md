# Per-skill evidence pack (Layer B) — design

**Status:** DRAFT / proposal (2026-08-21). Layer A shipped; this is the next layer. No code yet —
decision points are flagged inline.

## Context

Cold-start single-shot latency for a focused subskill is dominated by **card resolution**, not
compute: a skill fans out to N cards, each doing its own S3 read, in a bounded thread pool. On
`tumor-presence` (14 cards) this was ~11s.

**Layer A** (shipped) attacked the per-card *read*: store each product as parquet, sort by the read
key, read with column/predicate pushdown, precompute constants as sidecars. Status after Layer A:
- `cellline-protein-abundance` — SHIPPED (long parquet + median-null sidecar; 3.0s→0.4s).
- `tumor-rna-distribution` — already optimal (long gene-sorted products, pyarrow S3-range pushdown,
  precomputed all-gene rank).
- `cellline-rna-distribution` — already column-projected + precomputed rank; the only residual is a
  cold-vs-warm **cache-policy tradeoff** in the shared `depmap_common.parquet` loader (stream = win
  for 1 target / cold; download-once = win for a batch of ≥~4 targets). Deliberately left as-is —
  see "Why Layer B, not more Layer A" below.

Even with every card individually optimized, a cold single-shot still pays: **N separate S3
round-trips + N pyarrow footer/range reads + the fan-out orchestration**. Layer A drives each card
toward its floor; it cannot remove the fan-out itself. That is what Layer B is for.

## Why Layer B, not more Layer A

The `cellline-rna` residual is instructive: on a loader shared by ~10 method modules, "stream vs
download" is a genuine cold-single-shot-vs-warm-batch tradeoff, not a bug. Chasing the last second
per card means per-loader policy knobs that pull in opposite directions for interactive vs batch.
A **single fan-in read per skill** sidesteps all of it: one read, one round-trip, no per-matrix
cache policy. That is the structural move.

## The idea (disciplined)

A **per-skill evidence pack** = a materialized VIEW over the Layer-A per-source products, that a
skill reads in **one fan-in** instead of resolving N cards against N products.

Three constraints make it honest:

### 1. It's a bundle of tables, not one table (grain mismatch)
`tumor-presence`'s 14 cards live at incompatible grains — cell-line RNA (`ModelID × gene`), tumor
RNA (`sample × gene × indication`), CPTAC protein (`cohort`), single-cell (`celltype × donor`),
HPA-normal (`tissue`), subtype panorama (`stratum`). There is no shared key. The pack is therefore
a small **dataset (a directory of ~4-5 tables, one per measurement grain)**, not a flat table.

### 2. Keyed by `target`, with `indication` as a PARTITION column — not a key-multiplier
Pan-cancer cards (cell-line distributions) are indication-independent; keying the pack by
`(target, indication)` would duplicate them ~40× (once per indication) and multiply refresh churn.
Instead: key by `target`; carry `indication` as a partition/filter column only on the
indication-scoped tables (tumor RNA-vs-adjacent, CPTAC). One target's pack is read with a single
`filters=[("target","=",X)]` pushdown per grain-table.

### 3. Materialize on-demand + cache — NOT full precompute
Precomputing all `target × indication` combinations (~20k genes × ~40 indications) is ~99% waste.
Instead, build a target's pack lazily on first request (fan-in over the Layer-A products, once),
persist it to `s3://.../derived/evidence-pack-<skill>-v1/<target>/`, and serve subsequent reads from
it. A warm target = one read; a cold target = the current fan-out ONCE, then cached forever (until a
source refresh invalidates it).

## What the pack stores — the key decision

Two ends of a spectrum; **recommend (a)** for the first cut:

- **(a) Raw substrate rows** the cards need (the projected columns, pre-joined by grain). The skill
  still runs its `classify`/`percentile`/`compute_summary` methods over them. Saves *I/O + fan-out*,
  not compute. **Reproducible**: a method-version bump changes the verdict on next run without
  rebuilding the pack. This is the safe default.
- **(b) Card OUTPUTS** (resolved summaries). The skill becomes a lookup — fastest (~0 compute), but
  the pack is **method-version-locked**: bump `depmap_protein_abundance` and every pack is stale.
  Offer later as an explicit `--fast` tier with a method-version stamp, eyes open.

## Read path

`_skills_common.resolve_cards` gains an evidence-pack fast path: if a pack exists for `target` (and
covers the requested `indication` partition + is not stale), read it in one fan-in and hand each
card its slice; else fall back to today's per-card fan-out AND write the pack for next time. Verdict
byte-identical either way (same substrate → same methods → same verdict). This keeps the pack
**verdict-inert** and safe to roll out behind a flag.

## Staleness / versioning

Pack digest = the set of `(input_product_id, version)` it was built from (the Layer-A manifests
already carry versions + `derived_from`). A pack is stale when any input product supersedes. Cheap
check: compare the pack's stamped input-version set against the current resolved releases before
serving; stale → rebuild. This reuses the existing release-resolution + `supersedes` graph.

## Expected win

One fan-in read (a handful of small pushdown slices) + the skill's compute, vs 14 fan-out reads.
Cold single-shot target ~**1-2s** (from ~8-11s), and — critically — **no per-loader cache-policy
tradeoff**, because the pack read is a single pass.

## Open questions (for review)

1. **Pack scope** — per-skill (simplest; some cross-skill duplication since cards are shared) vs a
   shared multi-skill pack keyed by target (less duplication, more coupling). Lean per-skill first.
2. **Build trigger** — lazy-on-first-request (proposed) vs a nightly warm-set builder for the
   ~50-target Takeda portfolio (predictable interactive latency for the common set).
3. **Grain-table boundary** — exactly which tables (bulk_rna / bulk_protein / sc_rna / normal /
   subtype), and whether the single-cell + spatial grains are worth packing or better left as
   direct pushdown (they're already small).
4. **(a) vs (b)** storage — start raw-substrate; add a `--fast` results-cache tier only if the
   interactive path needs the last 2×.

## Phasing

Pilot on `tumor-presence` (the exemplar, richest card set): build the grain-table schema + lazy
builder + the `resolve_cards` fast-path behind a flag, measure the real single-shot floor, confirm
byte-identical verdicts, then generalize the builder to the other focused skills.

## Relationship to Layer A

Layer B reads FROM the Layer-A per-source products (it's a view, not a replacement) and inherits
their refresh — so no divergent copies of source data. Layer A remains the foundation and benefits
every consumer (skills, batch, ad-hoc); Layer B is the interactive-single-shot accelerator on top.
