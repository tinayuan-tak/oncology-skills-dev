# oncology-skills — v2 compositional framework (`v2-architecture` branch)

> **You are on the `v2-architecture` branch.** This is the redesigned target-evaluation
> platform: a **compositional skill framework** where each biological question is answered
> by an independent, retrieval-only skill that composes *evidence cards* over pre-computed
> derived products. Skills never recompute on invocation; heavy compute happens out-of-band
> and is published as versioned, gene-sorted artifacts.
>
> **For the v1 plugin** — the seven `analysis-*` / `workflow-*` indication × modality skills
> currently installable via Claude Code's marketplace (validating targets like SCD1, PCDH7,
> WEE1 in day-to-day work) — see the [`main` branch README](https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills/blob/main/README.md).
> v1 remains the production install path until v2 reaches feature parity.

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
 COMPOSITION  target-profile (narrative synthesis) · compose-dashboard (evidence package)
```

---

## Prerequisites — these skills are not self-contained

A compute/compose skill run (`compose-dashboard`, `target-profile`, and the question skills like
`tumor-presence`) reaches into the **three sibling repos on the filesystem** and reads data from
**S3**. Installing this repo alone is not enough. To run them you need:

1. **All four repos cloned** — this repo plus
   [`target-contracts`](https://github.com/oneTakeda/rnd-computational-biology-oncology-target-contracts)
   (cards/rules/schemas), [`analysis-methods`](https://github.com/oneTakeda/rnd-computational-biology-oncology-analysis-methods)
   (the `methods.*` modules skills import), and
   [`data-catalog`](https://github.com/oneTakeda/rnd-computational-biology-oncology-data-catalog)
   (manifests + the `target_id_resolver` lib).
2. **AWS access** — the `cbg` profile for S3 data reads, and `cmp-dev` for the Bedrock LLM synthesis
   (see [AWS configuration](#aws-configuration)). No amount of cloning substitutes for S3 access.
3. **Repo locations known to the skills** — see below.

### Locating the sibling repos (env vars)

By **default** the skills expect the sibling repos at `/home/sagemaker-user/rnd-computational-biology-oncology-*`
(the shared SageMaker layout that `bootstrap.sh` produces). If you clone them **anywhere else**, point
the skills at your paths with these environment variables — each falls back to the default when unset,
so an on-the-standard-layout setup needs nothing:

| Env var | Repo it locates | Default |
|---|---|---|
| `TARGET_CONTRACTS_ROOT` | target-contracts | `/home/sagemaker-user/…-target-contracts` |
| `ANALYSIS_METHODS_ROOT` | analysis-methods | `/home/sagemaker-user/…-analysis-methods` |
| `DATA_CATALOG_ROOT` | data-catalog | `/home/sagemaker-user/…-data-catalog` |
| `CLAUDE_ONCOLOGY_SKILLS_ROOT` | this repo (used by target-contracts' validators) | `/home/sagemaker-user/…-claude-oncology-skills` |

```bash
# Example: repos cloned under ~/work instead of the default location
export TARGET_CONTRACTS_ROOT=~/work/rnd-computational-biology-oncology-target-contracts
export ANALYSIS_METHODS_ROOT=~/work/rnd-computational-biology-oncology-analysis-methods
export DATA_CATALOG_ROOT=~/work/rnd-computational-biology-oncology-data-catalog
```

> **Lighter footprint:** the retrieval-only [`query-target-evidence`](skills/query-target-evidence/)
> skill reads a finished `evidence.json` from S3 and needs **only S3 access** — no sibling repos.
> `render-evidence-package` needs only `target-contracts` (for schemas). The full dependency set
> above applies to the compute/compose skills.

---

## The biology-first phase model

Skills are organized by **phase** — the gate of the nomination argument each one answers.
A full profile walks A → K; a focused question invokes a single skill.

| Phase | Question | Skill(s) |
|---|---|---|
| **A** Presence | Is the target expressed in the tumor (RNA + protein, cell-line + patient)? | [`tumor-presence`](skills/tumor-presence/) |
| **B** Selectivity | Is it tumor-selective vs normal tissue, robustly across comparators? | [`tumor-selectivity`](skills/tumor-selectivity/) |
| **C** Requirement | Is it a genetic dependency (CRISPR + RNAi + lineage), and is a null read a context-conditional false negative? | [`functional-requirement`](skills/functional-requirement/), [`synthetic-lethal-partners`](skills/synthetic-lethal-partners/) |
| **C** Combinatorial dependency | Is it a measured paralog dual-KO (synthetic-lethal / buffering) co-dependency? | [`combinatorial-dependency`](skills/combinatorial-dependency/) |
| **A/E** Genomic alteration | How is it altered — SNV/indel, copy-number, fusion — and which class drives? | [`genomic-alteration-profile`](skills/genomic-alteration-profile/) |
| **D** Mechanism | What upstream/downstream signaling context and candidate MoA hooks exist? | [`mechanism-and-pharmacology`](skills/mechanism-and-pharmacology/) |
| **E** Differentiation | What co-mutation / mutual-exclusivity landscape frames patient selection? | [`differentiation-landscape`](skills/differentiation-landscape/) |
| **F** Tractability & modality | Is it small-molecule druggable? Does surface biology support ADC/TCE? Whole-surfaceome scan; logic-gated antigen-pair scan. | [`tractability-small-molecule`](skills/tractability-small-molecule/), [`surface-modality-fit`](skills/surface-modality-fit/), [`surfaceome-cohort-ranking`](skills/surfaceome-cohort-ranking/), [`bispecific-pair-scan`](skills/bispecific-pair-scan/) |
| **F** Immune context | Is the tumor immune-hot enough (CD8 effector population) to redirect a TCE? | [`immune-context`](skills/immune-context/) |
| **G** Safety | Is it germline-constrained (gnomAD) — what does that imply for a full-KO modality? | [`on-target-safety-liability`](skills/on-target-safety-liability/) |
| **I** Combination/resistance | On inhibition, what combinations / resistance signatures emerge? | [`combo-and-resistance`](skills/combo-and-resistance/) *(partial)* |
| **J** Translational readiness | Models, PD assays, imaging tracers available? | [`translational-readiness`](skills/translational-readiness/) *(placeholder)* |
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

**One composition engine (Phase D — complete, 2026-08-12).** Every skill now computes verdicts
through the single resolver spine above. The focused skills and `target-profile` always did;
`compose-dashboard` — the older iter-1 orchestrator — used to *re-implement* verdicts in
`scripts/_synthesis.py` as a per-modality `fit_level` scorer, a **second** engine that never called
`resolve_verdict_for_gate`. Phase D deleted that reconstruction (#375 pinned the cross-engine
equivalence, #377 did the swap): `compose-dashboard`'s Phase-3 synthesis now calls the shared
resolver and emits `primary_gate_verdict` + `additional_gate_verdicts`, with the per-modality
`fit_level` demoted to an optional presentation lens. Because there is one engine, a newly added
evidence facet can no longer drift between two verdict paths.

Productization (Phase D / D1): standalone subskills can emit the same `evidence_package` envelope
`compose-dashboard` produces, via `run_wired_skill --emit-envelope` + `_skills_common/envelope.py`
(`assemble_evidence_package`) — the AgenticBoost "subskills-first" path.

---

## Skill inventory

### Question-answering skills (one gate each)

| Skill | Ver | Phase | Data mode | Status |
|---|---|---|---|---|
| [`tumor-presence`](skills/tumor-presence/) | 1.2.0 | A | `derived_read` | wired — 11 cards, 7 verdict-bearing + 4 display facets |
| [`tumor-selectivity`](skills/tumor-selectivity/) | 1.2.0 | B | `derived_read` | wired — 4-cell tumor-vs-normal sensitivity |
| [`functional-requirement`](skills/functional-requirement/) | 1.3.0 | C | `derived_read` | wired — CRISPR + RNAi + lineage + paralog + subtype panorama |
| [`synthetic-lethal-partners`](skills/synthetic-lethal-partners/) | — | C | `derived_read` | wired — SynLethDB v3 veto-suppressor (annotation, not measurement) |
| [`combinatorial-dependency`](skills/combinatorial-dependency/) | 1.0.0 | C | `derived_read` | wired — measured paralog dual-KO co-dependency (DepMap ParalogV2 26Q1); self-contained verdict |
| [`genomic-alteration-profile`](skills/genomic-alteration-profile/) | 2.0.0 | A, E | `derived_read` | wired — SNV/indel + copy-number + fusion [LIVE, additive] |
| [`mechanism-and-pharmacology`](skills/mechanism-and-pharmacology/) | 1.2.0 | D | `derived_read` | wired — SIGNOR/OmniPath MoA network + phospho-pathway-activity (re-homed from tumor-presence 2026-08-05) |
| [`differentiation-landscape`](skills/differentiation-landscape/) | 1.2.0 | E | `derived_read` | partial — co-mutation wired; clinical-precedent / patent placeholder |
| [`tractability-small-molecule`](skills/tractability-small-molecule/) | 3.1.0 | F | `derived_read` | wired — PRISM + chemical-genetic concordance |
| [`surface-modality-fit`](skills/surface-modality-fit/) | 1.0.0 | F | `derived_read` | partial — surfaceome-family + topology + density readers live (+ CSPA surface-confirmation, shed-ectodomain, sc-homogeneity, therapeutic-window, pMHC, exon-window, mutation-/pathway-stratified, CD-antigen backbone as additive signal facets); structure-features product still pending |
| [`immune-context`](skills/immune-context/) | 1.0.0 | F | `derived_read` | partial — CIBERSORT LM22 CD8 infiltration (per-indication); TCE effector-arm companion to surface-modality-fit; antigen-conditioned join is v2 |
| [`on-target-safety-liability`](skills/on-target-safety-liability/) | 1.7.0 | G | `derived_read` | partial — 6 human-genetics legs live (gnomAD LoF + Open Targets 26.06: gene-burden, ClinGen dosage, mouse-KO, ClinVar, target-priority) + GTEx breadth; two axes remain incomplete |
| [`surfaceome-cohort-ranking`](skills/surfaceome-cohort-ranking/) | 1.1.0 | F | `batch_compute` | target-scan hook — per-indication whole-surfaceome ranking |
| [`bispecific-pair-scan`](skills/bispecific-pair-scan/) | 1.0.0 | F | `batch_compute` | partial — logic-gated (AND/OR/NOT) antigen-pair tumor-vs-normal selectivity scan; background candidate-generation hook, not interactive |
| [`target-intrinsic`](skills/target-intrinsic/) | 1.0.0 | A,C,F,G | `live_read` | wired — 18 live cards, indication-independent dossier |
| [`combo-and-resistance`](skills/combo-and-resistance/) | 2.0.0 | I | `derived_read` | partial — combination half wired (combo-crispr-screen → DepMap 26Q1 drug-anchor); resistance-emergence half deferred |
| [`translational-readiness`](skills/translational-readiness/) | 1.0.0 | J | `derived_read` | **placeholder** — cards not yet wired (`not_wired`) |

### Composition & orchestration skills

| Skill | Ver | Role |
|---|---|---|
| [`target-profile`](skills/target-profile/) | 1.0.0 | Fans out (in-process) to the 9 wired question skills, collects each sub-verdict, then runs Tier-3 structured LLM synthesis (Bedrock, tool-choice-forced) for `executive_summary` + `tension_analysis` + `recommendation`. Emits `target_profile.md` + `nomination.json` + provenance. Deterministic sub-verdicts and LLM narrative live in **distinct schema slots** — the audit spine is invariant even if narrative drifts. |
| [`compose-dashboard`](skills/compose-dashboard/) | — | Consumes a `dashboard_spec` (from `target-contracts`) + invocation context (target, indication, subgroup, data_mode, release_pin) and produces `evidence_package.json` (+ `run_plan.yaml`, `dashboard.md`, `INDEX.md`) in the `data-products` repo; the validation summary is embedded in `evidence_package.governance` (there is no separate `lockfile.yaml` / `validation_report.json`). All three phases (compose → execute → synthesize) are implemented. |
| [`render-evidence-package`](skills/render-evidence-package/) | — | Renders an `evidence_package.json` to Stage-1 static markdown (exec summary, per-card panels, governance + provenance blocks). Invoked automatically by `compose-dashboard`. |
| [`query-target-evidence`](skills/query-target-evidence/) | 2.0.0 | **Retrieval-only.** Reads a stored `evidence.json` from `core-artifacts/`, validates + checks staleness, returns. If an artifact is missing it names the batch job that produces it — it never triggers compute. |

### Developer & utility skills

| Skill | Ver | Role |
|---|---|---|
| [`catalog-query`](skills/catalog-query/) | 1.0.0 | **Read-only** explorer over the `data-catalog` YAML manifests — find which manifest covers a need, inspect one manifest (S3 URI, schema, sort key, license, lineage), trace `derived_from` / `cited_by`, audit coverage gaps. Never adds, edits, or pushes manifests. |
| [`example-gallery`](skills/example-gallery/) | 1.0.0 | Standalone developer/demo generator — builds a static-HTML gallery of full example outputs (verdict + per-card summaries + tables + figures) from the focused subskills. Not composed into `target-profile`. |

> **Framework-health smoke harness:** `skills/_skills_common/framework_health_smoke.py` is a deterministic, offline "runs clean?" probe — it runs each wired subskill's real `run.py` on stubbed (non-live) cards and rolls the `run_health` blocks into `subskill_health.json`, which the `target-contracts` health probe reads. `python -m _skills_common.framework_health_smoke --check` fails if the committed file is stale (CI gate).

---

## Repository layout

| Path | What it is |
|---|---|
| [skills/](skills/) | The compositional skill framework (tables above). Each skill is a `SKILL.md` (frontmatter contract + description) plus `scripts/`. |
| [skills/_skills_common/](skills/_skills_common/) | Shared helpers used across skills. |
| [libs/target_id_resolver/](libs/target_id_resolver/) | Target-ID resolver consumed by ingestion + skills so raw-ID joins don't silently drop. |
| [core-artifacts-schema/](core-artifacts-schema/) | The stored-artifact contract (`evidence.schema.json`, `target.schema.json`) + per-product `result` schemas. Consumed by `query-target-evidence`. |
| [batch/](batch/) | Out-of-band compute. `batch/expression_rna_COADREAD/` is the reference R/Bioconductor DGE pipeline (DESeq2 + ComBat-seq + lfcShrink(apeglm)); `batch/loaders/` defines the source-loader `Protocol`. Batch jobs write artifacts; they are **never invoked by Claude**. |
| [configs/](configs/) | Per-indication parameters (`COADREAD.yaml`: cohorts, subtypes, FDR tiers, reference). |
| [docs/](docs/) | Design + governance docs — scope reviews, defect register, `target-profile` walkthrough, showcase design, worked examples. |
| [notebooks/](notebooks/) | Exploration before code hardens into `batch/` or a method module. |
| [.claude-plugin/](.claude-plugin/) | Plugin + marketplace manifests for Claude Code installation. |

---

## The four-repo ecosystem

`claude-oncology-skills` is the top-level consumer. A skill change often needs coordinated
changes downstream:

| Repo | Owns | This repo's dependency |
|---|---|---|
| **claude-oncology-skills** (here) | Skills — one biological question each; composition | — |
| [`target-contracts`](https://github.com/oneTakeda/rnd-computational-biology-oncology-target-contracts) | Evidence **cards**, rules, dashboard specs, schemas, vocabularies | Skills' `cards_used` / `rules_scope` reference IDs here |
| [`analysis-methods`](https://github.com/oneTakeda/rnd-computational-biology-oncology-analysis-methods) | **Method modules** — the actual compute | Skills invoke method CLIs for tier-1 evidence |
| [`data-catalog`](https://github.com/oneTakeda/rnd-computational-biology-oncology-data-catalog) | Versioned source + derived-product **manifests** (GDC release + UUID + pipeline-version pins) | Indirectly, via `analysis-methods`; provenance flows through catalog manifest IDs |

`compose-dashboard` also writes into a `data-products` repo (the emitted evidence packages).

See [CLAUDE.md](CLAUDE.md) for the cross-session coordination ritual and branch discipline —
because multiple parallel sessions edit these repos, claim your workstream in
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
| `cmp-dev` | `888307857004` (`tec-rnd-cmp-dev`) | Bedrock SDK calls (LLM synthesis in `target-profile`, `compose-dashboard`) | Bedrock (Opus / Sonnet), region `us-east-1` |

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
git checkout v2-architecture
pixi install
```

Run a focused question skill against live S3 (example — dependency call for KRAS in CRC):

```bash
export AWS_PROFILE=cbg
pixi run python skills/functional-requirement/scripts/run.py \
    --gene KRAS --indication COADREAD
```

Run a full composed profile with LLM synthesis:

```bash
export AWS_PROFILE=cbg AWS_REGION=us-east-1   # Bedrock for synthesis
pixi run python skills/target-profile/scripts/run.py \
    --gene MET --indication NSCLC
```

Re-run the same profile as a fast, deterministic verdict-only pass (no Bedrock, no figures):

```bash
pixi run python skills/target-profile/scripts/run.py \
    --gene MET --indication NSCLC --verdict-only
```

The repo-root `pixi.toml` carries the env for the v2 skills + batch pipeline. The retained
v1 `analysis-*` / `workflow-*` skills carry their own isolated `pixi.toml`.

---

## Continuous integration

`.github/workflows/skills-validate.yml` runs on every PR touching `skills/**` (or the pixi
env / the workflow file itself). Because this repo editable-depends on three siblings, CI
checks them out adjacent under the workspace — using the `CROSS_REPO_TOKEN` repo/org secret
(a PAT or GitHub App token with `contents:read` on the siblings), falling back to the default
`GITHUB_TOKEN` — so `pixi install --locked` resolves the `../` paths.

**Blocking gate** — four suites must pass:

- `skills/compose-dashboard/tests/` — the v2 orchestration spine
- `skills/_skills_common/tests/` — the shared harness
- `skills/target-profile/tests/` — the composed nomination skill
- `skills/tests/` — the cross-skill invariant guards: Guard B (`CARDS ⊆ cards_used`),
  composition-declarations, resolver-verdict-consumers, no-reference-drift, scope,
  reviewer-driven-upgrades (this top-level dir is *not* matched by the per-skill
  `skills/*/tests` glob, so these guards previously never ran in CI).

**Non-blocking coverage** — the remaining per-skill suites each run in their own pytest
process (isolating each `run.py` import) and report failures as `::warning::` without gating.
Live-data tests self-skip when the `onc-compbio` S3 bucket is unreadable, so the suite is
green on a credential-less runner.

---

## Branching strategy

| Branch | Purpose |
|--------|---------|
| `main` | v1 — plugin-installable production system (`analysis-*`, `workflow-*` skills) |
| **`v2-architecture`** | **You are here.** Long-lived architectural branch for the compositional framework; feature branches cut off it and PR back into it |
| `feat/*`, `fix/*`, `chore/*` | Short-lived work branches off `v2-architecture` (draft PR on first push) |

When v2 reaches parity with v1's analytical capabilities it merges to `main`; v1 becomes a
documented legacy install path.

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
