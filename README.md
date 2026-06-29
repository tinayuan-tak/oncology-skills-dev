# rnd-computational-biology-oncology-analysis-methods

Deterministic analytical methods for the Takeda v2 oncology target-evaluation framework.

## What this repo provides

Reusable, language-agnostic analytical code — packaged as CLIs (some R-driven, some Python, some containers). Methods are **skill-runtime-agnostic** — runnable from a Jupyter notebook, a SageMaker batch job, a Claude skill via subprocess, or directly from the command line.

This repo is the third of the v2 framework's five repos. Sits between [target-contracts](https://github.com/oneTakeda/rnd-computational-biology-oncology-target-contracts) (governance) and [claude-oncology-skills](https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills) (orchestration) in the dependency graph. Skills *call* methods; methods don't know about skills.

## Iter-1 methods (carve-out from `claude-oncology-skills/batch/` + `libs/`)

| Method | Carve-out source | CLI entrypoint | Notes |
|---|---|---|---|
| `dge_deseq2` | `claude-oncology-skills/batch/expression_rna_COADREAD/` | `dge-deseq2 --indication COADREAD --contrast tumor_vs_adjacent ...` | Parameterized indication; preserves 00-05 R step structure |
| `target_id_resolver` | `claude-oncology-skills/libs/target_id_resolver/` | `target-id-resolve --symbol KRAS ...` | Lives at `claude-oncology-skills/libs/target_id_resolver/` (co-located with resolver-releases YAMLs). A deprecated copy under `.DEPRECATED_target_id_resolver_*` was retained on disk for reversibility. |
| `depmap_chronos` | NEW iter-1 | `depmap-chronos --target KRAS --indication COADREAD ...` | Card 2: lineage-selective dependency. Consumes `depmap-consortium-26q1`. |
| `depmap_chronos_distribution` | NEW iter-2 | `depmap-chronos-distribution --target KRAS ...` | Card 1: pan-cancer dependency distribution. Consumes `depmap-consortium-26q1`. |
| `gdc_somatic_hotspot` | NEW iter-1 | `gdc-somatic-hotspot --target KRAS --indication COADREAD ...` | Consumes `gdc-pancohort-somatic-dr45-0` |
| `tempus_rwd_aggregator` | NEW iter-1 | `tempus-rwd-aggregator --target KRAS --indication COADREAD ...` | Consumes pre-aggregated `tempus-crc-2026-03-17` |

## Layout

```
methods/
├── dge_deseq2/
│   ├── steps/                # 00_load_counts.R, 01_build_design.R, …, 05_provenance.R
│   ├── cli.py                # dge-deseq2 CLI entrypoint
│   └── tests/
├── depmap_chronos/
│   ├── cli.py                # CLI + figure helpers (emit_forest_plot, emit_lineage_strip, …)
│   ├── read.py               # library entry called by compose-dashboard dispatcher
│   └── tests/
├── depmap_chronos_distribution/
│   ├── cli.py                # CLI + figure helpers (emit_waterfall_plot, emit_histogram_kde_plot, …)
│   ├── read.py               # library entry
│   └── tests/
├── gdc_somatic_hotspot/
│   ├── cli.py
│   ├── read.py
│   └── tests/
├── tempus_rwd_aggregator/
│   ├── cli.py
│   └── tests/
├── subgroup_assigner_directly_tagged/
│   └── ...
├── subgroup_assigner_maf_filter/
│   └── ...
└── io/
    └── loaders/              # shared loader utilities (carved from batch/loaders/)
tests/
└── integration/              # cross-method integration smoke tests
pixi.toml                     # heavier env: R + DESeq2 + sklearn + bioconductor + pyarrow
DEVELOPMENT_GUIDELINES.md
README.md
```

## API convention: public vs private helpers

Method modules separate **library entry** (`read.py`) from **CLI + figure emission** (`cli.py`). The library entry returns a summary dict consumed by the compose-dashboard skill's dispatcher; figure emission helpers in `cli.py` are called BOTH by the CLI's Click entrypoint AND by the skill's figure-emitter registry.

To make this dual-caller pattern explicit, the following helpers are **public (no underscore prefix)**:

- `load_depmap_files`, `compute_summary_stats`, `compute_lineage_summary`
- `emit_waterfall_plot`, `emit_histogram_kde_plot`, `emit_forest_plot`, `emit_lineage_strip`, `emit_plot_data`, `emit_manifest`

Internal-only helpers (used inside one method only) keep the `_` prefix.

## Method-output contracts

Every iter-1 method has a corresponding output schema in `target-contracts/schemas/products/`:

- `expression-rna-tumor-vs-adjacent.result.schema.json`
- `dependency-depmap-chronos.result.schema.json`
- (gdc-somatic-hotspot, tempus-rwd-aggregator schemas land as those methods ship)

A method's output validates against its schema before `compose-dashboard` curates it into a card emission. Output schema drift is caught at compose-time, not silently in the rendered evidence package.

## Status

**Iter-2, last refactored 2026-06-29.** Cards 1 + 2 (`depmap_chronos_distribution`, `depmap_chronos`) are fully implemented with synthetic-data tests + figure emitters + dispatcher wiring. `dge_deseq2` and `gdc_somatic_hotspot` have working live readers. `tempus_rwd_aggregator` and the subgroup assigners are scaffolded but not yet wired into compose-dashboard dispatchers.

See the v2 framework's [master plan](https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills) for the full roadmap.
