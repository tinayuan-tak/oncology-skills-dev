# oncology-skills — v2 compositional framework

> **This is `main`, the trunk.** The redesigned target-evaluation platform: a
> **compositional skill framework** where each biological question is answered
> by an independent, retrieval-only skill that composes *evidence cards* over pre-computed
> derived products. Skills never recompute on invocation; heavy compute happens out-of-band
> and is published as versioned, gene-sorted artifacts.
>
> New here and want to write a skill? Start with
> **[docs/AUTHORING_A_SKILL.md](docs/AUTHORING_A_SKILL.md)**, then
> [DEVELOPMENT_GUIDELINES.md](DEVELOPMENT_GUIDELINES.md) for the branch/test/data-access
> conventions.
>
> **For the v1 plugin** — the seven `analysis-*` / `workflow-*` indication × modality skills
> (used to validate targets like SCD1, PCDH7, WEE1) — see **[v1 is archived](#v1-is-archived)**
> below. v1 was the production install path until v2 was promoted to the trunk on 2026-09-16;
> it is preserved, still installable, and no longer developed.

---

## What v2 is, and why it exists

v2 answers one question well: **"Should we pursue target X in indication Y — and what does
the evidence say, gate by gate?"** It does this by decomposing target evaluation into a set
of **focused, biology-first question-answering skills**, each owning one gate of the
nomination argument. A skill:

1. **Consumes evidence cards** — declarative contracts (defined in the sibling
   [`target-contracts`](https://github.com/oneTakeda/rnd-computational-biology-oncology-target-contracts)
   repo) that say *which measurement, at which entity grain, read from which derived product*.
2. **Invokes method modules** — analysis code lives in the sibling
   [`analysis-methods`](https://github.com/oneTakeda/rnd-computational-biology-oncology-analysis-methods)
   repo, never inline in the skill.
3. **Reads a derived product** — gene-sorted Parquet on S3, queried by predicate pushdown
   (one row per gene), never a full-matrix scan.
4. **Fires a rule subset** — deterministic, versioned rules turn the numbers into a
   rank-ordered *verdict* (e.g. presence ladder, dependency call, selectivity class).

The single most important structural invariant: **compute globally, query locally, never
recompute on call.** This is the fix for the v1 failure mode — a skill loading a multi-GB
expression matrix and chunk-scanning it for one gene, on every invocation. In v2 that is
architecturally impossible: skills are `derived_read` / `live_read` only, and the derived
products are physically sorted on the read key so a per-gene query touches one row.

The second invariant: **biology-first verdicts, modality as a post-hoc lens.** Each skill's
primary output (`selectivity_class`, `dependency_verdict`, `fit_class`, …) is
modality-independent. Whether the target is being considered as a small molecule, ADC, TCE,
or degrader is an *interpretation layer* (`--modality` flag / orchestration), not something
that changes the measured biology.

```
 pre-computed DERIVED PRODUCTS  (gene-sorted Parquet on s3://onc-compbio/…, built out-of-band)
        │  predicate-pushdown read (one gene = one row)
        ▼
 METHOD MODULES  (analysis-methods repo — the compute; skills call, never inline)
        │  numbers
        ▼
 EVIDENCE CARDS  (target-contracts repo — measurement × entity-grain contract)
        │  rule subset fires → deterministic verdict
        ▼
 SKILLS  (this repo — one biological question each; retrieval-only, Claude-invocable)
        │  compose
        ▼
 COMPOSITION  target-profile (narrative synthesis + evidence package)
```

---

## Prerequisites — this repo is not self-contained

A compute/compose skill run (`target-profile` and the question skills like
`tumor-presence`) reads `methods/` and `contracts/` **in this same tree** (they were
merged in, SK#2063 — no separate clone needed) plus data-catalog manifests and
**S3**. Installing this repo alone gets you the code; you still need:

1. **`data-catalog` cloned as a sibling** —
   [`data-catalog`](https://github.com/oneTakeda/rnd-computational-biology-oncology-data-catalog)
   (manifests + the `target_id_resolver` lib) is the one remaining external repo
   dependency.
2. **AWS access** — the `cbg` profile for S3 data reads, and `cmp-dev` for the Bedrock LLM synthesis
   (see [AWS configuration](#aws-configuration)). No amount of cloning substitutes for S3 access.

### Locating `data-catalog` (env var)

By **default** the skills expect it at
`/home/sagemaker-user/rnd-computational-biology-oncology-data-catalog` (the shared
SageMaker layout `bootstrap.sh` produces). If you clone it **anywhere else**, point
the skills at your path:

```bash
export DATA_CATALOG_ROOT=~/work/rnd-computational-biology-oncology-data-catalog
```

`TARGET_CONTRACTS_ROOT` / `ANALYSIS_METHODS_ROOT` still exist as escape-hatch
overrides (`skills/_skills_common/paths.py`) for the rare case you need to point a
skill at a `contracts/` or `methods/` tree outside this checkout — their defaults
now resolve to `./contracts` and `./methods` in this repo, not a sibling clone.

> **Lighter footprint:** the retrieval-only [`query-target-evidence`](skills/query-target-evidence/)
> skill reads a finished `evidence.json` from S3 and needs **only S3 access** — no
> `data-catalog` clone. `render-evidence-package` needs only the in-tree `contracts/`
> schemas. The full dependency set above applies to the compute/compose skills.

---

## The biology-first phase model

Skills are organized by **phase** — the gate of the nomination argument each one answers.
A full profile walks A → K; a focused question invokes a single skill.

| Phase | Question | Skill(s) |
|---|---|---|
| **A** Presence | Is the target expressed in the tumor (RNA + protein, cell-line + patient)? | [`tumor-presence`](skills/tumor-presence/) |
| **B** Selectivity | Is it tumor-selective vs normal tissue, robustly across comparators? | [`tumor-selectivity`](skills/tumor-selectivity/) |
| **C** Requirement | Is it a genetic dependency (CRISPR + RNAi + lineage), and is a null read a context-conditional false negative? | [`functional-requirement`](skills/functional-requirement/) |
| **C** Combination & vulnerability | What does it depend on / combine with — SL partners, measured dual-KO co-dependencies, combo co-targets, resistance mediators? | [`combination-and-vulnerability`](skills/combination-and-vulnerability/) *(consolidates the retired `synthetic-lethal-partners` + `combinatorial-dependency` and the archived `combo-and-resistance`)* |
| **A/E** Genomic alteration | How is it altered — SNV/indel, copy-number, fusion — and which class drives? | [`genomic-alteration-profile`](skills/genomic-alteration-profile/) |
| **D** Mechanism | What upstream/downstream signaling context and candidate MoA hooks exist? | [`mechanism-and-pharmacology`](skills/mechanism-and-pharmacology/) |
| **E** Differentiation | What co-mutation / mutual-exclusivity landscape frames patient selection? | [`differentiation-landscape`](skills/differentiation-landscape/) |
| **F** Tractability & modality | Is it small-molecule druggable? Does surface biology support ADC/TCE? | [`tractability-small-molecule`](skills/tractability-small-molecule/), [`surface-modality-fit`](skills/surface-modality-fit/) |
| **F** Immune context | Is the tumor immune-hot enough (CD8 effector population) to redirect a TCE? | [`immune-context`](skills/immune-context/) |
| **G** Safety | Is it germline-constrained (gnomAD) — what does that imply for a full-KO modality? | [`on-target-safety-liability`](skills/on-target-safety-liability/) |
| **I** Combination/resistance | On inhibition, what combinations / resistance signatures emerge? | [`combination-and-vulnerability`](skills/combination-and-vulnerability/) *(now the live home; the former `combo-and-resistance` was **archived** 2026-09-05 — its combination + resistance cards compose here)* |
| **J** Translational readiness | Models, PD assays, imaging tracers available? | [`translational-readiness`](skills/translational-readiness/) *(partial)* |
| **—** Target-intrinsic | Indication-independent molecular dossier (localization, pathways, PPIs, domains, protein class). | [`target-intrinsic`](skills/target-intrinsic/) |

Some phases are **partially wired** — the skill and its rule subset exist, but not every
card's upstream derived product is materialized yet. Placeholder skills emit a structured
`phase-not-yet-wired` response naming the specific data gaps rather than failing silently, so
coverage gaps are visible in the catalog. See the per-skill status table below.

---

## How verdicts are computed — one declarative spine

Every focused question skill resolves its verdict the same way: the skill fires its rule
subset, then calls `_skills_common/resolver.py::resolve_verdict_for_gate(fired, gate)`, which
reads the gate's declarative rung ladder from `target-contracts/resolvers/<gate>.resolver.yaml`
and returns `(verdict, driving_rule_id)`. The verdict spine is therefore deterministic and
lives in the contracts repo, not in per-skill Python. `target-profile` does **not** recompute —
it **inherits** each sub-skill's verdict and adds only the Tier-3 LLM narrative on top (stored
in distinct schema slots; the audit spine is invariant even if narrative drifts).

**Lean read path (`--verdict-only`).** `_skills_common/reachability.py::verdict_relevant_cards(gate)`
derives the subset of cards whose rules the resolver actually references — the cards that can
*move* the verdict; every other card a skill consumes is verdict-inert enrichment. `run_wired_skill`
accepts a `verdict_cards` subset and, under `--verdict-only`, reads only those cards. This is
**opt-in and safe-by-default**: a skill that declares no proven subset (or whose derivation is
incomplete) reads **all** cards, so leaning can never change the verdict. `surface-modality-fit`
is the first skill wired to the lean path.

**`target-profile` fast modes.** `--verdict-only` (umbrella; implies `--no-synthesis` +
`--no-figures`) skips the Bedrock synthesis tail *and* figure/panel rendering, emitting the
auditable `nomination.json` + a narrative-free `target_profile.md` with **no LLM call**.
`--no-synthesis` skips only the synthesis tail; `--no-figures` skips only figure/HTML rendering.
The deterministic verdict spine is **byte-identical** to a full run (guarded by
`skills/target-profile/tests/test_verdict_only.py`).

**One composition engine (Phase D — complete, 2026-08-12).** Every skill computes verdicts
through the single resolver spine above. The focused skills and `target-profile` always did;
the older iter-1 `compose-dashboard` orchestrator used to *re-implement* verdicts in
`scripts/_synthesis.py` as a per-modality `fit_level` scorer, a **second** engine that never called
`resolve_verdict_for_gate`. Phase D deleted that reconstruction (#375 pinned the cross-engine
equivalence, #377 did the swap) and routed it through the shared resolver; `compose-dashboard`
itself was then **retired entirely** (#654, 2026-08-20), its engine (live readers, figure emitters,
`envelope.assemble_evidence_package`) rehomed to `_skills_common`. Because there is one engine, a
newly added evidence facet cannot drift between two verdict paths.

Productization (Phase D / D1): standalone subskills emit the deterministic `evidence_package`
envelope via `run_wired_skill --emit-envelope` + `_skills_common/envelope.py`
(`assemble_evidence_package`); for a composed run, `target-profile --emit evidence-package` produces it.

---

## Skill inventory

### Question-answering skills (one gate each)

| Skill | Ver | Phase | Data mode | Status |
|---|---|---|---|---|
| [`tumor-presence`](skills/tumor-presence/) | 1.20.0 | A | `derived_read` | wired — 11 cards, 7 verdict-bearing + 4 display facets |
| [`tumor-selectivity`](skills/tumor-selectivity/) | 1.23.0 | B | `derived_read` | wired — 4-cell tumor-vs-normal sensitivity |
| [`functional-requirement`](skills/functional-requirement/) | 1.9.0 | C | `derived_read` | wired — CRISPR + RNAi + lineage + paralog + subtype panorama |
| [`combination-and-vulnerability`](skills/combination-and-vulnerability/) | 0.5.1 | C | `derived_read` | partial — consolidated relational annex: SL (SynLethDB v3) + measured dual-KO + combo co-targets + resistance mediators; ranked-partner-table output, gateless (verdict=None) |
| `synthetic-lethal-partners` | 1.1.0 | C | `derived_read` | **RETIRED 2026-08-20 — deleted from git (#1254).** SL cards now compose under `combination-and-vulnerability` |
| `combinatorial-dependency` | 1.1.0 | C | `derived_read` | **RETIRED 2026-08-20 — deleted from git (#1254).** Dual-KO card now composes under `combination-and-vulnerability` |
| [`genomic-alteration-profile`](skills/genomic-alteration-profile/) | 2.16.0 | A, E | `derived_read` | wired — SNV/indel + copy-number + fusion [LIVE, additive] |
| [`mechanism-and-pharmacology`](skills/mechanism-and-pharmacology/) | 1.10.0 | D | `derived_read` | wired — SIGNOR/CollecTRI/Reactome MoA network + phospho-pathway-activity (re-homed from tumor-presence 2026-08-05) |
| [`differentiation-landscape`](skills/differentiation-landscape/) | 1.10.0 | E | `derived_read` | partial — co-mutation + clinical-precedent (public-domain AACT) + competitor-landscape (OT 26.06) wired; only patent-landscape placeholder |
| [`tractability-small-molecule`](skills/tractability-small-molecule/) | 3.9.1 | F | `derived_read` | wired — PRISM + chemical-genetic concordance |
| [`surface-modality-fit`](skills/surface-modality-fit/) | 1.9.0 | F | `derived_read` | partial — surfaceome-family + topology + density readers live (+ CSPA surface-confirmation, shed-ectodomain, sc-homogeneity, therapeutic-window, pMHC, exon-window, mutation-/pathway-stratified, CD-antigen backbone as additive signal facets); structure-features (PDB/AlphaFold + ligandability) landed 2026-08-07, feeding the small-molecule ligandability leg (does not feed the biologics `fit_class` by design) |
| [`immune-context`](skills/immune-context/) | 1.6.1 | F | `derived_read` | partial — CIBERSORT LM22 CD8 infiltration (per-indication); TCE effector-arm companion to surface-modality-fit; antigen-conditioned join is v2 |
| [`on-target-safety-liability`](skills/on-target-safety-liability/) | 1.17.0 | G | `derived_read` | partial — 6 human-genetics legs live (gnomAD LoF + Open Targets 26.06: gene-burden, ClinGen dosage, mouse-KO, ClinVar, target-priority) + GTEx breadth; two axes remain incomplete |
| [`target-intrinsic`](skills/target-intrinsic/) | 1.6.0 | A,C,F,G | `live_read` | wired — 18 live cards, indication-independent dossier |
| [`translational-readiness`](skills/translational-readiness/) | 1.5.0 | J | `derived_read` | partial — target-model-availability card wired (HCMI patient-derived model coverage per indication; graduated 2026-08-14); PD-assay / imaging-tracer / internal-model legs remain unwired |
| [`cis-feature-coherence`](skills/cis-feature-coherence/) | 1.4.0 | A, C, E | `derived_read` | gateless (verdict-inert) — coherence owner for the locus → expression → dependency chain (cis-driven addiction vs. mere co-occurrence) |
| [`literature-context`](skills/literature-context/) | 1.1.0 | — | `derived_read` | gateless (verdict-inert) — cited-literature evidence: co-occurrence volume/recency + typed relation direction, from two catalogued literature products (no LLM) |

### Composition & orchestration skills

| Skill | Ver | Role |
|---|---|---|
| [`target-profile`](skills/target-profile/) | 1.2.0 | Fans out (in-process) to the 15 wired question-answering sub-skills, collects each sub-verdict, then runs Tier-3 structured LLM synthesis (Bedrock, tool-choice-forced) for `executive_summary` + `tension_analysis` + `recommendation`. Emits `target_profile.md` + `nomination.json` + provenance. Deterministic sub-verdicts and LLM narrative live in **distinct schema slots** — the audit spine is invariant even if narrative drifts. |
| `compose-dashboard` | — | **RETIRED 2026-08-20 (#654).** The iter-1 `dashboard_spec`-driven orchestrator was deleted; its engine (live readers, figure emitters, `envelope.assemble_evidence_package`) rehomed to `_skills_common`, and `target-profile --emit evidence-package` now produces the deterministic `evidence_package.json`. |
| [`render-evidence-package`](skills/render-evidence-package/) | — | Renders an `evidence_package.json` to Stage-1 static markdown (exec summary, per-card panels, governance + provenance blocks). (Formerly auto-invoked by the retired `compose-dashboard`.) |
| [`query-target-evidence`](skills/query-target-evidence/) | 2.0.0 | **Retrieval-only.** Reads a stored `evidence.json` from `core-artifacts/`, validates + checks staleness, returns. If an artifact is missing it names the batch job that produces it — it never triggers compute. |

### Developer & utility skills

| Skill | Ver | Role |
|---|---|---|
| [`catalog-query`](skills/catalog-query/) | 1.0.0 | **Read-only** explorer over the `data-catalog` YAML manifests — find which manifest covers a need, inspect one manifest (S3 URI, schema, sort key, license, lineage), trace `derived_from` / `cited_by`, audit coverage gaps. Never adds, edits, or pushes manifests. |
| [`example-gallery`](skills/example-gallery/) | 1.0.0 | Standalone developer/demo generator — builds a static-HTML gallery of full example outputs (verdict + per-card summaries + tables + figures) from the focused subskills. Not composed into `target-profile`. |

### Reasoning & meta skills (not composed into `target-profile`)

| Skill | Ver | Role |
|---|---|---|
| [`target-archetype`](skills/target-archetype/) | 0.6.0 | Verdict-inert META / reduction-stage companion — consumes the other sub-skills' composed `claim_vector`s from a full profile and positions the (target, indication) pair as a soft phenotype mixture in a frozen low-dimensional target-signature embedding. |
| [`cross-evidence-hypothesis`](skills/cross-evidence-hypothesis/) | 0.5.0 | Decision-facing synthesis layer that sits **above** `target-profile` — integrates a target-profile `evidence_package` with the indication-independent dossier to surface cross-evidence hypotheses. |
| [`literature-risk-assessment`](skills/literature-risk-assessment/) | 0.1.0 | Retrieval-grounded 6-dimension literature RISK assessment (Biological / Druggability / Translational / Clinical / Safety / Commercial), each rated LOW/MEDIUM/HIGH/not_assessed with a cited justification. |

> **Framework-health smoke harness:** `skills/_skills_common/framework_health_smoke.py` is a deterministic, offline "runs clean?" probe — it runs each wired subskill's real `run.py` on stubbed (non-live) cards and rolls the `run_health` blocks into `subskill_health.json`, which the `target-contracts` health probe reads. `python -m _skills_common.framework_health_smoke --check` fails if the committed file is stale (CI gate).

---

## Repository layout

| Path | What it is |
|---|---|
| [skills/](skills/) | The compositional skill framework (tables above). Each skill is a `SKILL.md` (frontmatter contract + description) plus `scripts/`. |
| [skills/_skills_common/](skills/_skills_common/) | Shared helpers used across skills. |
| [contracts/schemas/](contracts/schemas/) | The stored-artifact contract (`evidence.schema.json`, `target.schema.json`) + per-product `result` schemas. Consumed by `query-target-evidence`. (The root `core-artifacts-schema/` copy was a stale v1 snapshot, retired 2026-09-29.) |
| [docs/](docs/) | Design + governance docs — scope reviews, defect register, `target-profile` walkthrough, showcase design, worked examples. |
| [.claude-plugin/](.claude-plugin/) | Plugin + marketplace manifests for Claude Code installation. |

`batch/`, `configs/`, `libs/`, and `notebooks/` (the v1-era R DGE pipeline, its
per-indication config, the stale migration note, and the empty exploration
placeholder) were retired 2026-09-29 (#2138) — `batch/expression_rna_COADREAD/`'s
R scripts are superseded by `methods/methods/dge_deseq2` (which carries them
byte-identical under `r/legacy/`), and `libs/target_id_resolver` moved to
`data-catalog/libs/` on 2026-06-29.

---

## The package layout (consolidated 2026-09-29, SK#2063)

`analysis-methods` and `target-contracts` were merged into this repo as `methods/`
and `contracts/` — a card/rule/method/skill change is now ONE atomic PR, no sibling
pins or bump PRs. `data-catalog` remains a separate sibling repo (stable manifest-ID
interface).

| Package | Owns | This repo's dependency |
|---|---|---|
| `skills/` (here) | Skills — one biological question each; composition | — |
| `contracts/` (here) | Evidence **cards**, rules, dashboard specs, schemas, vocabularies | Skills' `cards_used` / `rules_scope` reference IDs here |
| `methods/` (here) | **Method modules** — the actual compute | Skills invoke method CLIs for tier-1 evidence |
| [`data-catalog`](https://github.com/oneTakeda/rnd-computational-biology-oncology-data-catalog) (sibling) | Versioned source + derived-product **manifests** (GDC release + UUID + pipeline-version pins) | Indirectly, via `methods/`; provenance flows through catalog manifest IDs |

`target-profile --emit evidence-package` writes the emitted evidence packages (the
retired `compose-dashboard` formerly wrote them into a separate `data-products` repo).

See [CLAUDE.md](CLAUDE.md) — the sole process entry point — for the cross-session
coordination ritual and branch discipline: claim your workstream in
`~/.claude/wip-registry.md` before non-trivial writes.

---

## Conventions that still hold

- **Indication = a literal AACR OncoTree code** (uppercase): `COADREAD`, `LUAD`, `LUSC`,
  `NSCLC`, `PAAD`, `STAD`, … — see https://oncotree.mskcc.org/. Direct cross-reference to
  GENIE / cBioPortal / TCGA project IDs without translation.
- **Subtype is a path axis**, default `all`. Stratified analyses produce one shard per
  stratum (`COADREAD/CMS4/…`, `COADREAD/MSS-RASmut/…`). Subtype is *molecular*
  (CMS, RAS, MSI) — Takeda-internal vocabulary, since OncoTree doesn't enumerate it.
- **Therapeutic modality is not a dimension.** It's a post-hoc lens (`--modality`) that
  decides which evidence is required and how to interpret it; the underlying measurements
  are modality-agnostic. Re-evaluating a target as a different modality = same evidence,
  new lens.
- **Derived products are gene-sorted and read by pushdown.** A per-target product is Parquet
  physically sorted on the read key + a resolver sidecar; queries read one row, not the
  monolith. Sorting on the wrong key (or scanning) silently fails at scale.
- **DGE methodology** (batch layer) = DESeq2 + ComBat-seq + lfcShrink(apeglm) on raw integer
  counts; actionability filter `padj < 0.05 AND |log2FC| ≥ 1 AND baseMean cutoff`.
- **Canonical TCGA source = GDC DR45.0**, pinned by release + manifest UUID + pipeline
  `workflow_version` (release tag alone is insufficient — ~44% of genes drift across GDC
  releases due to pipeline shifts).

---

## AWS configuration

Two AWS profiles map to two Takeda accounts (deliberate data-sovereignty separation):

| Profile | AWS account | Used by | Purpose |
|---------|---|---------|---------|
| `cbg` | `557690623046` (`tec-rnd-cbg-dev`) | All data reads — derived products, catalog, core-artifacts under `s3://onc-compbio/…` | S3 data access |
| `cmp-dev` | `888307857004` (`tec-rnd-cmp-dev`) | Bedrock SDK calls (LLM synthesis in `target-profile`) | Bedrock (Opus / Sonnet), region `us-east-1` |

On a fresh SageMaker space:

```bash
aws sso login --profile cbg
aws sso login --profile cmp-dev
export AWS_PROFILE=cbg     # default for data work
```

> **Bedrock note:** the LLM-synthesis skills invoke Bedrock via the `cmp-dev` account in
> `us-east-1` — `cbg` is data-only. If a synthesis call 400s, export *frozen* credentials
> (the Bedrock SDK client does not honor `AWS_PROFILE`) and strip any `[1m]` alias suffix
> from the model ID before invoking.

> **Ephemeral `$HOME`:** this SageMaker space is on ephemeral EBS — every restart wipes `~/`.
> Re-establish profiles, `gh` auth, clones, and pixi in one command with the recovery script
> (`personal-notes/bin/bootstrap.sh`). Run it after every restart.

---

## Local development

```bash
git clone https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills.git
cd rnd-computational-biology-oncology-claude-oncology-skills
pixi install
```

A fresh clone lands on `main`, which is the framework — no `git checkout` step.
`methods/` and `contracts/` are in-tree editable path dependencies (`./methods`,
`./contracts` in `pixi.toml`) — nothing to clone for them. `data-catalog` is the one
remaining sibling repo (its `libs/target_id_resolver` is an editable path dependency)
and must be cloned **side by side** with this one; `pixi install` resolves it from
`../rnd-computational-biology-oncology-data-catalog`.

Run a focused question skill against live S3 (example — dependency call for KRAS in CRC):

```bash
export AWS_PROFILE=cbg
pixi run python skills/functional-requirement/scripts/run.py \
    --target KRAS --indication COADREAD \
    --out ~/scratch/kras-coadread-dependency
```

Every wired skill routes through the shared `run_wired_skill` dispatcher, which writes a
timestamped **`<out>/run.log`** — a tee of the run's stdout + stderr (card resolution,
dependency-status behavior, verdict, warnings) — alongside `decision.json`. Always on; a durable
backend trace for development and provenance. Live terminal output is unchanged; each line is
stamped with a UTC timestamp + `OUT`/`ERR` tag. `target-profile` writes the same `run.log` for its
composed fan-out.

### Full composed profile — skill outputs **and** clickable HTML (one command)

`skills/target-profile/scripts/run.py` is the top-level entry point. A **full run**
(no `--verdict-only` / `--no-figures`) writes the complete skill output tree **and** the
clickable dashboard into `--out` in a single invocation:

- `target_profile.md` — narrative report
- `nomination.json` — deterministic sub-verdicts + LLM synthesis (auditable spine)
- `target_profile.html` — single-page dashboard (per-subskill sections, Plots|Evidence|Rules
  tabs, LLM exec-summary / tension / recommendation)
- `figures/` — per-card SVG + composite PNG, and provenance
- `run.log` — a timestamped tee of the run's stdout + stderr (fan-out, gate firing, Bedrock
  call, figure emission, warnings). Always written; a durable backend trace for development
  **and** provenance (listed in `provenance.yaml` artefacts). Live terminal output is
  unchanged — the log is an added copy, each line stamped with a UTC timestamp + `OUT`/`ERR` tag.

`--target`, `--indication`, and `--out` are **required**. The HTML is emitted by default;
`--no-figures` (and the umbrella `--verdict-only`) is what *suppresses* it.

```bash
export AWS_PROFILE=cbg BEDROCK_AWS_PROFILE=cmp-dev AWS_REGION=us-east-1
export ANTHROPIC_MODEL=us.anthropic.claude-opus-4-8   # strip any [1m] alias suffix
pixi run python skills/target-profile/scripts/run.py \
    --target KRAS --indication COADREAD \
    --subtypes MSI_H,MSS \
    --out ~/dev/framework-runs/KRAS-COADREAD-target-profile
```

- `AWS_PROFILE=cbg` = S3 data reads; `BEDROCK_AWS_PROFILE=cmp-dev` = the Bedrock LLM synthesis
  (see [AWS configuration](#aws-configuration)). Without Bedrock creds the run crashes at the
  synthesis tail — use `--no-synthesis` (or `--verdict-only`) to skip it.
- `--subtypes` is **negative-selection only**: a measured, floor-cleared *non-dependent* subtype
  downgrades to `hold`; if the target stays a dependency across all subtypes, `subtype_fit`
  correctly emits no verdict and the subtype figures still render.
- Write `--out` under `~/dev/…` or `~/scratch/` — `/tmp` is invisible in the SageMaker
  JupyterLab file picker and wiped on restart.
- Confirm synthesis is real (not degraded): in `nomination.json`,
  `llm_synthesis.executive_summary._source == "llm_synthesized"`.

> **Interpreter note.** The CI-tested `pixi` env ships the full data-card stack but **no
> `anthropic`**, so a synthesis run under bare `pixi` fails at the Bedrock tail. Either add
> `anthropic[bedrock]` to the pixi env, or run under an interpreter that has both the card
> stack (`openpyxl`, `lifelines`, `pyreadr`, `gseapy`) **and** `anthropic[bedrock]` — a
> mismatched env silently drops cards and can flip a sub-verdict.

#### How the figures are produced

On a full run, figures are generated in three stages, all written under `<out>/figures/`:

1. **Offline data-persist (during fan-out).** As each sub-skill resolves, its card `plot_data`
   is persisted into `figures/cards/<card_id>/`. The figure emitters later render from this
   saved data instead of doing a **second** live S3 / method read — the "offline seam."
2. **Composite "at-a-glance" panel.** `figures/target_profile_at_a_glance.png` (+ `.svg`
   companion) — the slide-drop summary artifact. It also narrates the LLM recommendation, so a
   `--verdict-only` run skips this panel specifically.
3. **Per-card distribution figures.** Each card with a registered emitter renders as **SVG +
   interactive `.plotly.json`** via the shared figure registry. Only ~34 cards have emitters;
   a card without one simply produces no figure (expected, not an error).

`target_profile.html` **inlines the composite SVG** and references the per-card figures in its
Plots tabs; `target_profile.md` embeds the composite panel by relative path.

Behaviors worth knowing:

- **Figures are verdict-inert.** They never feed `nomination.json` or the sub-verdicts — a
  separate presentation slot. So `--no-figures` (and the umbrella `--verdict-only`) yields a
  **byte-identical** verdict spine; the HTML just degrades to the tested static, no-JS layout.
- **Every figure step is best-effort.** A composite-render or HTML-render failure logs a
  `WARN` and continues (the report degrades to no-image); figure rendering never blocks
  emission of the verdict artifacts.

Re-run the same profile as a fast, deterministic verdict-only pass (no Bedrock, no figures, no HTML):

```bash
pixi run python skills/target-profile/scripts/run.py \
    --target KRAS --indication COADREAD \
    --out ~/scratch/kras-coadread-verdict-only --verdict-only
```

The repo-root `pixi.toml` is the **only** pixi manifest in the repo (SK#2145): one workspace,
one `pixi.lock`, one interpreter (python 3.14) for `skills/`, `methods/` and `contracts/` alike.
The batch pipeline it used to also cover was retired with the v1 root husks (#2165), and the
former `methods/pixi.toml` — a second env that gated the same code under python 3.12 — is gone;
`methods/pyproject.toml` remains as the package definition and is editable-installed by the root
manifest. No per-skill or per-package `pixi.toml` exists or should be added.

---

## Continuous integration

`.github/workflows/skills-validate.yml` runs on every PR (or `push: main`). Since
`methods/` and `contracts/` are in-tree, CI only checks out one sibling —
`data-catalog` (pinned by SHA, for its manifests / `target_id_resolver` editable
pixi dep) — using the `CROSS_REPO_TOKEN` repo/org secret (a PAT or GitHub App token
with `contents:read`), falling back to the default `GITHUB_TOKEN`.

The workflow's required `pytest` check is a fan-in over four jobs: the skills
`pytest-shards`, `methods-pytest`, and the two contracts jobs (`contracts-static`,
`contracts-pytest`). Locally, `scripts/preland.sh all` mirrors this fan-in (see
[CLAUDE.md](CLAUDE.md)'s Testing section for the dispatcher and the blast-radius
cases you must gate fully locally before pushing).

**Blocking, within the skills fan-in**:

- `skills/_skills_common/tests/` — the shared harness
- `skills/target-profile/tests/` — the composed nomination skill
- `skills/tests/` — the cross-skill invariant guards: Guard B (`CARDS ⊆ cards_used`),
  composition-declarations, resolver-verdict-consumers, no-reference-drift, scope,
  reviewer-driven-upgrades

**Non-blocking coverage** — the remaining per-skill suites each run in their own pytest
process (isolating each `run.py` import) and report failures as `::warning::` without gating.
Live-data tests self-skip when the `onc-compbio` S3 bucket is unreadable, so the suite is
green on a credential-less runner.

---

## Branching strategy

| Branch | Purpose |
|--------|---------|
| **`main`** | **You are here.** The trunk: the v2 compositional framework. Feature branches cut off it and PR back into it |
| `feat/*`, `fix/*`, `chore/*` | Short-lived work branches off `main` (draft PR on first push) |
| `legacy/v1` | Archived v1 plugin (`analysis-*`, `workflow-*` skills). Frozen — no development |

## v1 is archived

v2 was promoted to the trunk on **2026-09-16**. Before the promotion, `main` held v1 and the
framework lived on a long-lived `v2-architecture` branch — which meant a fresh clone landed on
v1, and GitHub registered this repo's `schedule:` workflows from a branch that did not contain
them (three crons had never fired once). Promoting v2 to `main` fixed both.

v1 is preserved two independent ways and nothing was deleted:

| Ref | What it is |
|---|---|
| tag `v1-final` | Immutable snapshot of v1's final commit |
| branch `legacy/v1` | Browsable, still-installable v1 |

It remains installable via the `oncology-skills-v1` entry in
`.claude-plugin/marketplace.json`, which pins `ref: legacy/v1`. If you need it as a standalone
checkout:

```bash
git clone https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills.git oncology-skills-v1
cd oncology-skills-v1 && git checkout legacy/v1
claude plugin marketplace add .
```

---

## Requirements

- **Python** ≥ 3.10 — skills + orchestration
- **R** ≥ 4.4 with Bioconductor 3.20+ (DESeq2, sva, apeglm, arrow) — batch DGE pipeline
- **pixi** for env management
- **AWS credentials** — `cbg` for S3, `cmp-dev` for Bedrock (see [AWS configuration](#aws-configuration))

---

## License

Internal use only — Computational Biology Oncology Team, Takeda Pharmaceuticals.

---

## Authors

- **v1 (main):** Ming-Ju Tsai (ming-ju.tsai@takeda.com)
- **v2 architecture (this branch):** Ryan Abo (ryan.abo@takeda.com), building on v1 as foundation
