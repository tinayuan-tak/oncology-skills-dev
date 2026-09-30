# Figure-emitter architecture — current state, target, migration

**Status:** design note (2026-08-19). Anchors the figure half of the broader cards/skills reframe.
**Scope:** how per-card figures are produced across the framework (skills + analysis-methods).
**Why now:** the tumor-presence "plot redraft" (Track B of the presence-coherence work) surfaced that
the redraft is fighting the *structure*, not the individual plots. This documents the structure, the
problems, a target, and an incremental migration — so the redraft becomes cheap and testable instead
of live-data-bound and fixture-fragile.

---

## 1. Current state (as-built)

**One monolith owns every skill's figures.** `skills/compose-dashboard/scripts/_figure_emitters.py`
(~1300 lines) contains a per-card matplotlib emitter function for *every* skill's cards (presence,
dependency, genomic, protein, safety, tractability, …) plus the central `CARD_FIGURE_EMITTERS`
registry (`card_id → emitter_fn`) and the `emit_figures_for_card(card_id, summary, out_root, target,
indication)` entry point. It is imported cross-skill: by `compose-dashboard` (the heavy orchestration)
and by `example-gallery` (`_load_emit_figures_for_card`).

**Emitters RE-EXECUTE the analysis against live data.** Each emitter does
`from methods.<x> import cli/read/emit` and calls the method's `read_*` + `emit_plot_data` — i.e. it
re-runs the card's method (live S3 / `cbg`) to regenerate the plot inputs, rather than rendering the
already-computed result. (37 live-read/method imports in the file; e.g.
`_emit_expression_tumor_vs_adjacent → methods.dge_deseq2.read/emit`,
`_emit_expression_distribution → methods.depmap_expression_distribution.cli.emit_plot_data`.)
The `plot_data_*.parquet` files in the output tree are *written by the emitter during this re-run*, not
read as a cached source of truth.

**Two competing homes are emerging.** The monolith (skills) vs. in-flight PR #387
(`feat/sc-presence-figures`) which puts NEW single-cell figure code in
`analysis-methods/onc_methods/sc_tumor_expression_celltype/` + `sc_normal_expression/`, with "skills-side
`_figure_emitters` wiring [as] a separate skills PR." So figure logic is starting to live in two
places with no single convention.

**Framing/naming drift.** e.g. `tumor-rna-vs-adjacent` (a presence card) emits
`figure_tumor_vs_normal_selectivity_4panel.svg` and renders GTEx three different ways across
`_emit_expression_tumor_vs_adjacent`, `_emit_tumor_expression_distribution`, and
`_emit_tumor_elevation_breadth` — a symptom of no per-card/per-question figure spec.

---

## 2. Consequences (why the redraft is painful)

| Property | Consequence of "emitter re-executes the analysis" |
|---|---|
| **Not offline-testable** | A figure change can only be verified with live `cbg` data — no deterministic unit render. |
| **Fixture / drift-guard fragility** | Every figure edit regenerates SVGs → trips figure fixtures + the offline-replay drift-guard. |
| **Compute duplication** | The method runs once for the verdict (dispatcher) and again for the plot. |
| **Figure ↔ verdict divergence risk** | Two reads at two moments: the plotted data can differ from the card's own `summary`/verdict. |
| **Merge contention** | A ~1300-line cross-skill god-module is a collision magnet for parallel sessions (the exact hazard the repo's worktree discipline exists to avoid). |
| **Ownership diffusion** | No skill/method "owns" its figures; two competing homes (monolith vs per-method). |

These are structural, not per-plot. Redrafting a plot in place pays all of these costs and is
low-durability (it would be redone in the restructure).

---

## 3. Target architecture

Three pillars, each addressing a row above.

### 3.1 Decouple plot from compute (the big lever)
The method persists its `plot_data` **once**, as an artifact of card resolution (part of the
data-package the dispatcher already writes). The emitter renders **from that persisted `plot_data` +
the card `summary`** — never a fresh live read.
- Figures become **deterministic + offline-renderable + unit-testable** (feed a fixture `plot_data`).
- Figures **cannot diverge** from the verdict — same data object.
- No `cbg` dependence for a figure edit; fixtures become stable golden inputs, not live re-renders.
- Compute is not duplicated.

The `plot_data_*.parquet` artifacts already exist in the output tree — this pillar makes them the
**source of truth** for rendering rather than a side-effect of re-execution.

### 3.2 Co-locate + modularize (one home, per-owner)
Figure code lives **with the method that produces its data** — `methods/<x>/figures.py` in
analysis-methods (or a per-skill `figures/` package for skill-composed figures) — owning the render for
that method's `plot_data`. A thin skills-side registry keeps only `card_id → render_fn` wiring. This:
- kills the ~1300-line monolith and its merge-contention,
- gives per-method/per-skill ownership,
- resolves the two-homes split by making analysis-methods the home for method-data figures (the
  direction #387 already leans), with skills owning only composed/cross-card figures.

### 3.3 Per-question figure spec (dataviz discipline)
Each card declares, in its contract, the figure(s) that support its question — the chart *form* (the
job: magnitude / distribution / polarity / attribution) and what it must show. This:
- prevents framing drift (a "selectivity" figure can't live on a presence card if the presence card's
  figure spec says "per-sample distribution vs its normal anchor"),
- gives the renderer a declarative target (validated, like `summary_fields`),
- is the figure analogue of the `measurement_type` / summary-field discipline the cards already have.

---

## 4. Migration path (incremental, non-breaking)

Each stage is independently landable; the live-re-read path keeps working until a card is migrated.

1. **Persist plot_data as a first-class card artifact.** Have the dispatcher/method write `plot_data`
   during card resolution (it largely already does via `emit_plot_data`); define its location/schema as
   the contract. No behavior change yet.
2. **Add an offline render path.** A `render_from_plot_data(card_id, plot_data, summary) → svg` seam
   that plots WITHOUT a live read. Prove it on ONE card (candidate: `cellline-rna-distribution` or
   `tumor-rna-distribution` — self-contained bulk distributions) with a fixture-`plot_data` unit test.
3. **Migrate emitters card-by-card** to the offline render path; each migration adds a deterministic
   test and removes a live-read. Bulk presence cards first (deconflicted from #387's sc work).
4. **Split the monolith per-skill / co-locate per-method** as cards migrate; shrink
   `_figure_emitters.py` to the `card_id → render_fn` registry.
5. **Introduce per-card figure specs** in the card contracts; add a validator (mirrors the
   summary-field / concept-discipline ratchets) so new cards declare their figure intent.
6. **Deprecate the live-re-read emitters** once all cards are migrated; the offline-replay drift-guard
   then covers figures deterministically.

The presence plot redraft (rename the `selectivity_4panel`, one canonical GTEx normal reference, the
per-question figures) rides on stage 2–3 for the presence cards — cheap and testable *after* the
decoupling, painful *before*.

---

## 5. Open decisions (for the reframe)

1. **Home for method-data figures:** analysis-methods `methods/<x>/figures.py` (co-located, #387's
   direction) vs a skills `figures/` package. Recommendation: analysis-methods for method-data figures;
   skills only for composed/cross-card figures (e.g. the presence question-table, the presence-matrix
   hero).
2. **plot_data contract:** location (data-package `figures/cards/<id>/plot_data_*.parquet` today),
   schema, and whether it is the persisted card artifact or a separate emission.
3. **Relationship to #387:** #387 is actively enriching the sc figures under the *current* structure.
   Either land #387 first and migrate it in stage 3, or align #387 onto the new seam. Deconflict before
   touching `sc_tumor_expression_celltype` / `sc_normal_expression` figures.
4. **Figure-spec granularity:** per-card single figure vs a small declared set; how it interacts with
   the per-question presence model (one figure per question row vs per card).

---

## 6. Non-goals / risks
- NOT a verdict change — figures are and remain verdict-inert; this is purely the *rendering* pipeline.
- Risk: the migration touches a cross-skill file every skill depends on — stage it card-by-card behind
  the registry so no skill's figures break mid-migration.
- Risk: #387 collision — coordinate before migrating sc figures.

**Related:** presence-coherence work (PRs #549/#553/#555/#407/#418/#420; #424 held), the deferred
cards/skills reframe, and the dataviz skill's form/color discipline.
