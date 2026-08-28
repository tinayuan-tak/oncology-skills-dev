# architecture_dashboard — the framework's wiring + health

> **Consolidated (2026-08-28):** the single canonical published dashboard is now the
> **Framework Atlas** in [`living/`](living/), which SUPERSETS this one —
> it renders the same Overview/Explorer/Health/Cards/Datasets/Coverage tabs PLUS Flow /
> Gaps / Concepts / Docs and the glossary legibility layer. `make dashboard` publishes the
> living document. `build_unified_dashboard` here remains the composition **engine** (the
> living builder imports its `compute_or_load_health` / `merge` / `load_coverage`) and stays
> runnable standalone for debugging the wiring/health layer in isolation.

A self-contained HTML dashboard that consolidates **what's *wired*** (architecture) with
**what's *live*** (health) into a single click-through product:

```
Overview  →  Explorer (Miller columns)  ·  Health matrix  ·  Cards  ·  Datasets
```

- **Overview** — executive tally, clickable tiles, Fix-next (actionable drift), and the
  coverage frontier (categorized uncataloged gaps).
- **Explorer** — Miller-columns drill-down `skill → cards → datasets · methods · outputs
  (fields/vocab/figures) · rules → resolver verdict`, plus a dataset-first coverage mode.
- **Health** — the skill health matrix (verdict / runs-clean / drift), grouped by risk category.
- **Cards / Datasets** — full inventories (card health + verdict-bearing; dataset catalog
  resolution + indication-family + gap category).

It is a COMPANION to `validators/framework_health`, not a replacement: framework_health
answers "is it live/healthy?"; this adds "what is wired to what?" and folds both into one
navigable product.

## Relationship to framework_health (important)

This package **composes** `framework_health` — it does not modify it. `build_unified_dashboard`
computes fresh health in-process via `validators.framework_health.build_framework_health.generate()`
and overlays it onto a freshly-extracted architecture graph. When framework_health's probe
changes, this product's health simply reflects the new numbers on the next build.

## Usage

Reads three sibling repos fresh (target-contracts, claude-oncology-skills, data-catalog) and,
for the Health tab, computes framework_health in-process.

```bash
# the consolidated product (Overview + Explorer + Health + Cards + Datasets)
python3 validators/architecture_dashboard/build_unified_dashboard.py \
    [--tc <target-contracts>] [--sk <skills>] [--dc <data-catalog>] \
    [--out framework_dashboard.html] [--json framework_dashboard.json]

# architecture explorer only (no health compute — faster)
python3 validators/architecture_dashboard/build_architecture_explorer.py

# CI/pre-commit drift-guard: recompute and fail (exit 1) if the committed JSON's WIRING is stale
python3 validators/architecture_dashboard/build_unified_dashboard.py --check
```

Defaults write curated output to `~/dev/framework-runs/architecture-explorer/`.

### `--check` drift-guard

`--check` recomputes and compares a **volatile-stripped projection** (drops timestamps, git
SHAs, and the time-varying `health` block) against the committed `--json`. It guards the
**wiring** (skills → cards → datasets → rules → verdicts); health freshness is guarded
separately by `framework_health --check`.

**CI note:** a full run needs the sibling repos (skills + data-catalog) checked out, which the
standard target-contracts CI does not provide (framework_health's CI uses `--self-check` for the
same reason). So `--check` is a **local / pre-commit** guard today; wiring it into CI requires a
workflow that checks out the sibling repos.

## Layout

| file | role |
|---|---|
| `build_unified_dashboard.py` | the consolidated product builder (+ `--check`) |
| `render_unified.py` | Overview / Health / Cards / Datasets renderer (reuses the Miller UI) |
| `build_architecture_explorer.py` | architecture-graph extractor (skills/cards/rules/resolvers/manifests) |
| `render_arch.py` | Miller-columns explorer renderer (CSS + JS reused by render_unified) |

## Provenance

Built 2026-08-18 for the comp-bio skills presentation; upstreamed from `~/dev/architecture-explorer`.
New package (does not touch framework_health), so it does not collide with the in-flight probe
rework (PR #409). The natural next step is a CI workflow that checks out the sibling repos so
`--check` can gate drift automatically.
