# framework_dashboard

**One self-contained HTML that consolidates the framework's _health_ and its _architecture_.**

Companion to (and consumer of) [`validators/framework_health`](../framework_health). Where
`framework_health` answers *"is it live / healthy?"*, this product also answers *"what is
wired to what?"* — and puts both in a single page with an executive landing.

```
Overview  →  Explorer            Health            Cards        Datasets
(hero +      (Miller-columns      (skill matrix:    (per-card    (catalog resolution:
 tiles +      skill → cards →       verdict, drift,   inputs,      manifest / non-manifest /
 fix-next +   datasets · methods·   runs-clean,       outputs,     uncataloged; indication
 coverage)    outputs · rules →     risk category)    verdict,     families)
              verdict)                                health)
```

## Why it's one product
The consolidation is **data-level, not just tabs**: a single build produces one graph in
which the architecture wiring (fresh-extracted) is *overlaid on a freshly-computed health
report*. So every node carries both "what it is" (wiring) and "is it live" (health) — the
Overview's Fix-next comes from the health drift index; its Coverage-frontier comes from the
architecture's dataset resolution.

## Run
```bash
# from the target-contracts repo root
python -m validators.framework_dashboard.build
# → writes health/framework_dashboard.html (+ .json) and health/health_current.json
```
Options: `--tc/--sk/--dc` override sibling-repo roots (default via `framework_health.probe`),
`--out/--json` set output paths, `--no-compute-health` loads an existing health JSON instead
of recomputing it in-process.

## Data sources (read fresh at build time)
| layer | source |
|---|---|
| skills → cards | `claude-oncology-skills/skills/*/SKILL.md` (`composition.cards_used`) |
| cards → inputs/methods/outputs | `target-contracts/cards/*.card.yaml` |
| cards → rules → verdict | `target-contracts/interpretation-rules/*.rules.yaml` + `resolvers/*.resolver.yaml` |
| datasets | `data-catalog/manifests/**.yaml` + `subgroup-catalogs/` + `resolver-releases/` |
| health overlay | `framework_health.generate()` (imported, **not** modified) |

## Modules
- `extract.py` — pure extraction of the architecture graph (skills, cards, datasets,
  resolvers, rule→verdict wiring, catalog resolution incl. non-manifest resources +
  indication-family detection).
- `render_arch.py` — the Miller-columns Explorer renderer (CSS + vanilla JS, no CDN).
- `render_unified.py` — assembles the one-page product (Overview/Health/Cards/Datasets +
  the imported Explorer).
- `build.py` — CLI: compute health → build graph → merge → render.

## Design note / dependency
`framework_health` is a **code** dependency (health is computed via `generate()`); skills and
data-catalog are **data** dependencies (read from disk, same as `framework_health` does). This
is why the package lives beside `framework_health` rather than in a separate repo — the two
evolve together. The `merge()` step reads health-report keys defensively (`.get`) so a change
in the health report shape degrades gracefully rather than crashing.

## Tests
`tests/test_extract.py` unit-tests the extraction against the **in-repo** cards/rules/resolvers
only (no sibling checkouts required), so it runs under the checkout-only `contracts-validate`
CI — mirroring `framework_health`'s `--self-check` philosophy. A full end-to-end build requires
the sibling `claude-oncology-skills` + `data-catalog` checkouts.
