# Figure catalog — full redraft of the emitted figure set

**Status:** design deliverable (2026-08-19). Workstream A of the figure-emitter consolidation
(see [`FIGURE_EMITTER_ARCHITECTURE_2026-08-19.md`](FIGURE_EMITTER_ARCHITECTURE_2026-08-19.md)).
**Purpose:** decide, from scratch, the *target* visual set — the source of truth the Stage-5 figure
spec encodes and its validator enforces. Organizing axis is the **skill's key question**, not the
card: the skills now answer a fixed set of key questions (presence = 7, selectivity = 8; others to
follow), and a figure earns its place by *helping answer a question*. Cards remain the substrate that
supplies each figure's data. Applies the `dataviz` discipline: **form follows the data's job**
(magnitude / distribution / polarity / relationship / identity / state / survival), color assigned
last, from the shared palette.

Two figure layers:
- **Leading question table** (per skill) — a per-question *signal-meter + confidence-dots* row; the
  hero that answers "how do all the key questions resolve at a glance." Verdict-inert projection over
  `decision['headline']` + the claim_vector (already built by `presence_question_table.py` /
  `selectivity_question_table.py`).
- **Per-question detail figure** — the one chart that lets a reader inspect the evidence *for that
  question*. A question maps to its *primary* card's figure (sometimes a composed/cross-card visual);
  one card may serve several questions, and one question may compose several cards.

Inventory basis: all **35** registry entries in
`skills/compose-dashboard/scripts/_figure_emitters.py::CARD_FIGURE_EMITTERS`, the presence/selectivity
question models, and each card's `question:` in `target-contracts/cards/`. Full-redraft scope (per
user): revisit every question's visual and the composed heroes.

---

## 1. The closed `type` vocabulary (chosen by job)

The current code uses ~30 ad-hoc `type` strings for ~12 real forms (one density-histogram job is
spelled 5 ways). The value-kind (chronos/rnai/expression/cn/protein) belongs in the axis label +
`plot_data`, never in `type`.

| Job (what the reader must do) | Canonical `type` | dataviz color job |
|---|---|---|
| Magnitude — rank entities low→high | `ranked_waterfall` | sequential |
| Magnitude — labeled horizontal bars, one emphasized | `magnitude_bar` | 1 hue + gray (emphasis) |
| Magnitude grid | `heatmap` | sequential |
| Distribution — population shape (+ target marked) | `density_histogram` | sequential + status refline |
| Distribution — per-group jitter | `group_strip` | categorical (≤ token ceiling) |
| Distribution — two overlaid populations + rug | `overlay_density` | 2 categorical |
| Distribution — tumor vs normal per-sample (paired) | `paired_group_distribution` | 2 categorical (tumor/normal) |
| Polarity — per-group effect vs a baseline (+CI) | `diverging_forest` | diverging |
| Relationship — two measures | `scatter` | 1 hue (+ emphasis for highlighted points) |
| Identity / part-to-whole — composition | `stacked_bar` | categorical |
| Survival — stratified time-to-event | `survival_curve` | 2 categorical (high/low) |
| State — bounded score(s) vs a limit | `meter_panel` (gauge/meter + icon+label) | **status** (reserved) |
| State — categorical call | `state_badge` (class call + evidence, icon+label) | **status** (reserved) |

**Composed heroes** (skills-side, layout-bespoke, declared on the *skill* not a card — §4):
`context_matrix`, `claim_vector`, `card_board`, `evidence_strip`, `verdict_badge_grid`,
`question_table`.

Three new forms vs today: **`survival_curve`** (Kaplan-Meier — the honest form for
`expression-clinical-association`, currently a text card), and the former overloaded `evidence_panel`
split into **`meter_panel`** (a bounded score vs a limit — dataviz "single ratio against a limit →
meter") and **`state_badge`** (a categorical call + evidence). Both status-colored (reserved) with
icon+label, never color-alone. Retired: `text_summary_panel` (vocab prose is not a figure) and the
per-value-kind `*_card`/`*_with_kde_*` spellings.

---

## 2. Key-question → the visual that answers it

For each skill with a key-question model, every question gets: its **slot in the leading table**
(signal-meter + confidence-dots, always present) and **one detail figure** (the chart to inspect that
question's evidence). "Primary card" = the card whose `plot_data` drives the detail figure; "form" is
from §1. Where no single card answers a question, the visual is **composed** (cross-card) and lives in
the skills lane (§4).

Two deliberate exceptions to "one detail figure per question": (i) a question may render a **RNA +
protein small-multiple** of the same form (presence Q1) — one figure, two panels; (ii) a question
whose primary card does not (yet) emit a figure shows only its leading-table row until that card gains
an emitter — flagged **⚠ no-emitter** below.

### 2a. Tumor-presence — 7 questions
| Q | Question | Detail figure (form) | Primary card | Compose / note |
|---|---|---|---|---|
| Q1 | expressed at all? (abundance) | `density_histogram` (target marked in pan-cancer TPM) | cellline-rna-distribution / cellline-protein-abundance | claim A; RNA + protein small-multiple |
| Q2 | vs other cancers? (generality) | `diverging_forest` per-indication (breadth) | tumor-elevation-breadth | claim D |
| Q3 | vs normals? | `paired_group_distribution` (tumor vs GTEx/adjacent) | tumor-rna-distribution / tumor-rna-vs-adjacent | claim B; HPA normal-atlas as support inset |
| Q4 | subtype variation? | `paired_group_distribution` small-multiples by subtype | tumor-rna-distribution-by-subtype | — |
| Q5 | absolute vs all genes? | **composed** `magnitude_bar` — all-gene percentile position (a "where does the target rank among all genes" strip), aggregated across cards | *(cross-card)* | level-vs-effect; a new composed hero, not a card figure |
| Q6 | RNA↔protein? | `scatter` (RNA vs protein + r) | cellline-rna-protein-concordance / rna-protein-concordance-tumor | — |
| Q7 | malignant-intrinsic? | `magnitude_bar` (per-compartment detection, malignant emphasized) | tumor-scrna-celltype-expression | claim C; purity-confound `scatter` as caveat inset |

### 2b. Tumor-selectivity — 8 questions
| Q | Question | Detail figure (form) | Primary card | Compose / note |
|---|---|---|---|---|
| Q1 | over-expressed vs origin? (window) | `diverging_forest` (tumor vs origin-normal, log2FC + CI) | tumor-vs-normal-selectivity | claim WIN; RNA→protein concordance support |
| Q2 | comparator-robust? | `diverging_forest` (3 comparators as a forest) | tumor-vs-normal-selectivity | same card, 2nd question — the multi-comparator view |
| Q3 | per-sample separation? | `paired_group_distribution` (+ overlap shading) | tumor-rna-distribution / tumor-vs-normal-percentile-crossing | claim DIST |
| Q4 | absolute vs all genes? | **composed** `magnitude_bar` — all-gene percentile position | *(cross-card)* | shared with presence Q5 (one composed hero, reused) |
| Q5 | window vs worst normal? | `magnitude_bar` (per-tissue normal, worst organ emphasized) | normal-tissue-liability-gtex | claim SAFE; named critical organ |
| Q6 | malignant-intrinsic? | `scatter` (expression × purity) + spatial | expression-purity-confound | claim INT; spatial-coloc support |
| Q7 | absolute surface density? | `meter_panel` (copies/cell vs density floor, meter+grade) | *(surface-density card — ⚠ no-emitter)* | tiered-evidence A–E, not a single number; card lives in surface-modality-fit |
| Q8 | spatial bystander? | `paired_group_distribution` (tumor vs normal-epithelium adjacency) | *(spatial coloc card — ⚠ no-emitter)* | confirm emitter coverage before promising a detail figure |

### 2c. Other skills (no question model yet)
functional-requirement (dependency analog — planned), genomic-alteration-profile,
mechanism-and-pharmacology, tractability, safety: their cards get the §3 form treatment now; when each
adopts a key-question model, add a `2x` block here mapping its questions to detail figures. The §3
substrate is question-model-independent, so no rework is wasted.

**Shared composed hero (new):** the **all-gene percentile position** figure (presence Q5 = selectivity
Q4) — a single `magnitude_bar`/strip showing where the target sits among all ~20k genes, absolutizing
the relative ladder. Built once in the skills lane, reused by both leading tables. **Data source (confirmed):** the
`allgene_percentile` / `allgene_percentile_class` fields already on the presence cards + the
`selectivity_allgene_percentile(_class)` headline fields, backed by the materialized
`allgene-depmap-rank-26q1-v1` product (`methods/allgene_percentile_precompute`). No new product needed.

---

## 3. Card substrate — the figure each card supplies (form + data source)

The mechanical layer beneath §2: which canonical form each card's `plot_data`/`summary` renders as.
A question in §2 draws its detail figure from one (or more) of these.

**Decision** legend: `keep` (form already right; canonicalize `type`) · `reframe` (form must change to
match the question) · `upgrade` (text/panel → real chart) · `dedup` (redundant with a sibling) ·
`add` (missing twin/parity mark). **Src:** `plot_data` · `summary` · `hybrid`.

### 3a. Distribution family → ONE parametrized renderer (5 cards, highest-ROI dedup)
`methods/_distribution_figures.py::render_distribution(plot_data, summary, spec)`; each card = a spec.

| card_id | Question (job) | Target figure set (primary first) | Decision | Src |
|---|---|---|---|---|
| pan-cancer-crispr-dependency-distribution | shape of CRISPR dependency (distribution) | `density_histogram` (target marked, Chronos −0.5/−1 reflines) → `ranked_waterfall` → `group_strip` | **reframe** primary waterfall→density (question asks *shape*); add group_strip | plot_data |
| pan-cancer-rnai-dependency-distribution | shape of RNAi dependency | same triad | reframe + add group_strip | plot_data |
| cellline-rna-distribution | pan-cancer TPM distribution | `density_histogram` → `group_strip` → `ranked_waterfall` | keep (Stage-2 proof card) | plot_data |
| copy-number-distribution | amplified / deleted / neutral (distribution w/ polarity) | `density_histogram` (diverging shade around neutral) → `group_strip` | keep + **add plotly twin** | plot_data |
| cellline-protein-abundance | protein-abundance distribution, lineage-stratified | `density_histogram` → `group_strip` | keep | plot_data |

### 3b. Tumor-vs-normal / presence tier — one canonical normal reference, form per question
Resolves the "GTEx rendered three ways" redundancy: each card renders its *own* question.

| card_id | Question (job) | Target figure | Decision | Src |
|---|---|---|---|---|
| tumor-rna-distribution | per-sample tumor vs GTEx normal (distribution) | `paired_group_distribution` | **reframe** (this is THE canonical presence distribution) | hybrid→plot_data |
| tumor-rna-vs-adjacent | up in tumor vs matched adjacent? (paired distribution) | `paired_group_distribution` (paired violin + significance) | **reframe/rename** off `box_forest_sensitivity_panel` (selectivity form leaking onto a presence card) | plot_data |
| tumor-vs-normal-selectivity | selectivity robust across 3 comparators (polarity) | `diverging_forest` (3 comparators, log2FC + CI) | keep (forest belongs here) | plot_data |
| tumor-vs-normal-percentile-crossing | which subtypes separate from normal (polarity, faceted) | `diverging_forest` small-multiples by subtype | **reframe** (was a duplicate of the presence distribution) | hybrid→plot_data |
| tumor-rna-distribution-by-subtype | per-subtype distribution panel | `paired_group_distribution` small-multiples | keep | hybrid→plot_data |
| tumor-elevation-breadth | across how many indications elevated (magnitude/breadth) | `diverging_forest` per-indication (tumor−normal Δ, K elevated emphasized) | **reframe** (was pan-tissue distribution; question is per-indication breadth) | plot_data |
| tumor-protein-abundance-cptac | protein present tumor vs normal per cohort | `paired_group_distribution` per cohort | keep | plot_data |
| tumor-scrna-celltype-expression | detection per compartment; malignant vs micro | `magnitude_bar` (per-compartment detection %, malignant emphasized) | keep | summary |
| normal-tissue-liability-gtex | where expressed across normal tissues; critical organ high? | `magnitude_bar` (per-tissue median, critical organs emphasized) | keep | hybrid |
| normal-tissue-liability | *identical question* | — | **dedup** into `normal-tissue-liability-gtex` (two cards, one form); if both must exist, both = `magnitude_bar`, not one heatmap + one bar | summary |

### 3c. Dependency / genomic
| card_id | Question (job) | Target figure | Decision | Src |
|---|---|---|---|---|
| dependency-lineage-selectivity | which lineages enriched for dependence (polarity) | `diverging_forest` (lineage mean vs pan, CI) → `group_strip` | keep (rename `lineage_forest_plot`→`diverging_forest`) | plot_data |
| crispr-rnai-dependency-concordance | do CRISPR & RNAi agree (relationship) | `scatter` (quadrants) → `overlay_density` → `stacked_bar` (partition) | **reframe** primary overlay→scatter (concordance is a 2-var relationship) | plot_data |
| expression-dependency-correlation | does expression predict dependency (relationship) | `scatter` (+regression) → `scatter` (lineage-stratified) | keep + **add plotly twin** | plot_data |
| mutation-stratified-dependency | dependency stratified by mutation status | `group_strip` (mut vs wt) → `group_strip` (per-hotspot) | keep; **fix descriptor ordering** (plotly currently prepended) | plot_data |
| dependency-predictability | which feature class dominates | `magnitude_bar` (top features) → `magnitude_bar` (lineage predictability) | keep; **add `_has_live_read_error` guard** | summary |
| organoid-crispr-dependency | dependency across organoid models, how broad | `magnitude_bar` (per-lineage) | keep (pillar-1 seed) | summary |
| mutation-type-counts | missense / LOF / mixed (composition) | `stacked_bar` (variant class) → `stacked_bar` (per-lineage) | keep + **add plotly twin** | plot_data |
| genomic-event-model-match | which matched models are dependent | `scatter` (matched models: correspondence × Chronos, dependent emphasized) | **upgrade** from text `*_card` | summary |

### 3d. Tractability
| card_id | Question (job) | Target figure | Decision | Src |
|---|---|---|---|---|
| prism-compound-activity | how many compounds, potency, lineage-selective | `magnitude_bar` (top compounds by AUC) → `magnitude_bar` (per-lineage) | keep; **drop** `text_summary_panel` (→ prose) | summary |
| prism-crispr-concordance | does compound-kill track CRISPR/RNAi; which lines dual-validated | `scatter` (AUC × Chronos, dual-responders emphasized) → `magnitude_bar` (dual responders) | keep; **drop** `text_summary_panel` | summary |

### 3e. Relationship & abundance biomarker cards
| card_id | Question (job) | Target figure | Decision | Src |
|---|---|---|---|---|
| cellline-rna-protein-concordance | does RNA predict protein (relationship) | `scatter` (+trend, r) | keep | summary |
| rna-protein-concordance-tumor | RNA→protein in tumors (relationship) | `scatter` | keep | summary |
| recommended-models | expression-matched models + screen roles | `scatter` (TPM × Chronos, roles colored, patient IQR band) | keep | summary |
| abundance-dependency | does protein abundance predict dependency | `scatter` (abundance × Chronos, r) | **upgrade** from text `*_card` | summary |
| expression-purity-confound | expression tumor-intrinsic or stromal-driven | `scatter` (expression × purity, r) | **upgrade** from text `*_card` | summary |
| phospho-pathway-activity | phosphorylated beyond total abundance | `scatter` (phospho × total abundance) | **upgrade** from text `*_card` | summary |

### 3f. Clinical / safety / state
| card_id | Question (job) | Target figure | Decision | Src |
|---|---|---|---|---|
| expression-clinical-association | does expression stratify **survival** | `survival_curve` (KM, high vs low expression, logrank p) | **upgrade** from text `*_card`. **RESOLVED:** `read.py` already builds the per-patient `df {case, log2_tpm, os, os_time}` + median-splits into arms for the log-rank, then discards it. Persist as `plot_data` `{arm∈{high,low}, os_time_days, os_event}`; renderer computes the KM step fn + annotates `logrank_p` from summary. Same data the log-rank consumes — no new source; a clean Stage-1 add for this method | **plot_data** (new) |
| gnomad-lof-constraint | how constrained vs LoF (score vs limit) | `meter_panel` (pLI / LOEUF / mis-z meters + icon+label) | keep (meter is the dataviz-correct form) | summary |
| functional-gene-state | biallelic vs monoallelic, by mechanism, patient vs model (composition) | `stacked_bar` (state composition, patient vs model arms) | keep | summary |
| alteration-role | GoF / LoF / biomarker / passenger (state) | `state_badge` (role call + evidence, status icon+label) | keep (genuine categorical state; no distribution to plot) | summary |

---

## 4. Composed-heroes redraft (skills lane)

These are the dashboard's *hero / KPI / status* lane — dataviz stat-tile/emphasis/status discipline,
not chart marks. All must draw status from the shared `takeda_palette` (Stage-4), never local hex.

| hero (module) | Role | Redraft |
|---|---|---|
| `context_matrix` (`presence_matrix.py`) | presence × context ordinal grid | keep; **ordinal ramp** (order≠magnitude) for tiers, **reserved status** only for measured-gap cells; texture for the coverage-gap cell (CVD/print) |
| `claim_vector` (`presence_claims_figure.py`, `presence_subtype_figure.py`) | signal × reliability per claim | recast as a `scatter`-quadrant (signal x, reliability y) so position is honest, not color-only; one module (drop the subtype fork — it's the same figure faceted) |
| `card_board` (`presence_cardboard_figure.py`) | per-card ternary signal / none / not-measured | keep as a status grid; **icon+label per cell** (never color-alone), texture for not-measured |
| `evidence_strip` (`selectivity_hero.py`) | selectivity leading graphic | keep; unify status palette; ensure the ordinal severity uses the ramp, veto uses reserved critical status |
| `verdict_badge_grid` (`composite_panel.py`) | 3×2 verdict badges | keep; replace local `VERDICT_COLORS` with shared status palette + icons |
| `question_table` (presence/selectivity) | per-question signal/confidence | keep as a **table** (dataviz: >7 meaningful classes ⇒ table, not more colors) |

Consolidation: `presence_claims_figure` + `presence_subtype_figure` are one figure (faceted) — merge.
The six heroes move to `skills/_skills_common/figures/` and share one status source.

---

## 5. Cross-cutting normalizations (enforced by the Stage-5 validator)

1. **Closed `type` enum (§1):** reject any `type` outside the vocabulary; assert emitted descriptor
   `type` == card-declared `type` (framing-drift guard — this is what stops a presence card emitting a
   `..._selectivity_...` figure).
2. **Declare-what-you-emit:** every card with a registry emitter MUST declare `outputs.figures[]`
   (several currently emit but declare nothing — the inverse of `FIGURE_DECLARED_NOT_EMITTED`). Add
   `FIGURE_EMITTED_NOT_DECLARED` to the validator.
3. **Plotly-twin parity:** every chart-mark figure emits a `.plotly.json` twin from the *same*
   `plot_data`. Backfill the 3 gaps (`copy-number-distribution`, `mutation-type-counts`,
   `expression-dependency-correlation`). Evidence panels / survival curves / heatmaps: twin optional.
4. **Guard consistency:** all data-touching emitters early-return `[]` on `_has_live_read_error`;
   the 2 deliberate exceptions (`tumor-elevation-breadth` target-only; thin-lookup placeholder cards)
   become annotated waivers.
5. **One canonical normal reference:** GTEx normal shown once per question; `normal-tissue-liability`
   ⋂ `normal-tissue-liability-gtex` deduped.
6. **`text_summary_panel` is not a figure:** vocab panels → card prose.

## 6. Two lanes, one palette

- **Method chart-marks** (§3): matplotlib SVG + Plotly twin, rendered from `plot_data`/`summary`,
  styled by `takeda_oncology.mplstyle` + `takeda_palette.py`.
- **Composed heroes** (§4): hand-rolled SVG, layout-bespoke, importing shared
  `STATUS_COLORS`/`STATUS_INK`/`STATUS_GLYPH` (Stage-4 addition to `takeda_palette`) — replacing ~68
  local hex literals across 6 modules.

Invariant: **one data source per figure (plot_data or summary), rendered ≤3 ways, colored from one
palette module, its form chosen by the card's question.**
