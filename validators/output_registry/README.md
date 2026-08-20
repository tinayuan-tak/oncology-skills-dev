# output_registry — the framework output spine

Derives **one cross-tier index of every standardized framework output**, and renders a coverage
grid so the gap between "what the framework can evaluate" and "what it has actually produced" is
visible. Derived, never hand-authored — re-run it and it re-reads ground truth (the same principle
as `validators/framework_health`).

## Two tiers

| tier | source | governance |
|---|---|---|
| **governed** | data-products repo — `<TARGET>/<IND>/ep-*/evidence_package.json` | concurrence-reviewed |
| **exploratory** | `s3://onc-compbio/skill-runs/index.json` (per-run `decision.json`) | ungoverned dev runs |

## Outputs (into `--out`, default `./registry/`)

- `catalog.json` — machine registry: normalized entries, coverage grid, summary, and a
  card-level **`card_firings`** index (see below).
- `CATALOG.md` — browsable cross-tier table (supersedes the per-target `INDEX.md`s).
- `coverage.html` — self-contained coverage grid (target × indication × {governed | skill lanes}).

## Run

```
AWS_PROFILE=cbg python3 -m validators.output_registry.build_output_registry \
    --data-products <path-to-data-products-checkout> \
    --skill-runs-index s3://onc-compbio/skill-runs/index.json \
    --generated-at <ISO-timestamp> --out ./registry
```

`--generated-at` is passed in explicitly (no wall-clock read) so the artifact is reproducible and
diffable. The `--skill-runs-index` accepts a local path or an `s3://` URI.

## The signal merge — feeding framework_health

`card_firings` carries, per card, which governed packages and which exploratory runs it fired in,
plus two convenience sets:

- `fired_card_ids_governed` — cards with a fired `validation_state` in a governed package.
  **Byte-stable mirror** of `framework_health.probe.fired_card_ids()` (same states, same field).
- `fired_card_ids_any` — the **superset** that also credits cards proven live in exploratory runs
  (harvested from each run's `decision.json → run_health.cards_fired`).

When this `catalog.json` is committed at the **data-products root**, `framework_health` reads it as
a plain local file (never a network call — the probe stays deterministic and `--self-check`-safe)
and lights up a `fires_in_any_run` liveness signal alongside the unchanged, governed-only
`fires_in_real_package`. Absent the catalog, the probe degrades gracefully to its historical glob —
no behaviour change. See `framework_health.probe.registry_card_firings` / `fired_card_ids_any`.
