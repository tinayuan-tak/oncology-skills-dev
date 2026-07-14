# Target-Profile Skill — End-to-End Wiring Walkthrough

**Status:** DRAFT for team review · **Owner:** Ryan Abo · **Last updated:** 2026-07-14
**Audience:** ODDU + oncology comp-bio colleagues
**Supersedes:** `docs/SHOWCASE_DESIGN.md` (its five design decisions are folded into §8 below)

> **How to comment:** add your name + date inline under any 🗳️ **OPEN** marker. Nothing in §8
> is final until we converge as a team.

---

## 1. Purpose

We want to put the **`target-profile` composed skill** in front of ODDU and hardening its design
choices with comp-bio feedback. To review it credibly, this doc surfaces the **full wiring** — from
raw dataset to final recommendation — with real file paths and a real worked example (KRAS ×
COADREAD). The goal is that a reviewer can trace *any* claim in the output back to the dataset row,
the code that summarized it, and the rule that interpreted it.

The single most important thing to take away:

> **The verdicts are deterministic and reproducible (verified byte-identical across runs); the prose
> is LLM-written, labeled, and traceable.** Sub-verdicts, fired-rule IDs, and the risk-by-category
> table are pure rule-fired logic. Only the narrative + the enum-constrained recommendation come from
> the LLM, and every LLM-written field is stamped with its model ID and a hash of the exact prompt
> that produced it. (One caveat on the hash's stability is tracked in §9 Known issues; it does not
> affect the scientific spine's reproducibility.)

---

## 2. The composed skill at a glance

`target-profile` answers: *"Give me the full biology + tractability + mutation + prevalence picture
of target X in indication Y, with a narrative synthesis and a nomination recommendation."*

It **fans out in-process to 10 sub-skills**, collects each one's deterministic sub-verdict, then
runs a single **Tier-3 structured-LLM synthesis** over those verdicts.

```
                         target-profile/scripts/run.py
                                     │
        ┌────────────────────────────┼────────────────────────────┐
        │  1. FAN OUT (in-process via importlib, sequential)        │
        │                                                           │
        │   tumor-presence          → expression   verdict         │
        │   tumor-selectivity       → selectivity  verdict         │
        │   functional-requirement  → dependency   verdict         │
        │   mechanism-and-pharmacology → mechanism  verdict         │
        │   mutation-profile        → mutation      verdict         │
        │   differentiation-landscape → differentiation verdict     │
        │   tractability-and-modality → tractability verdict        │
        │   on-target-safety-liability → safety     verdict         │
        │   patient-population-and-access → population (no verdict)  │
        │   surfaceome-cohort-ranking → cohort_rank (no verdict)     │
        │                                                           │
        │   each sub-skill: resolve_cards() → fired_rules()         │
        │                   → _verdict(fired) = (verdict, rule_id)  │
        └────────────────────────────┬────────────────────────────┘
                                     │  DETERMINISTIC spine (byte-reproducible)
                                     ▼
        ┌───────────────────────────────────────────────────────────┐
        │  2. TIER-3 SYNTHESIS  (_skills_common/llm.py)              │
        │  Bedrock, tool_choice-forced, 6-field schema              │
        │  executive_summary · tension_analysis · args_for/against  │
        │  overall_recommendation ∈ {nominate,hold,veto,insuff.}    │
        │  confidence ∈ {high,medium,low,insufficient}              │
        │  every field stamped _source / _model_id / _prompt_hash   │
        └────────────────────────────┬──────────────────────────────┘
                                     ▼
        ┌───────────────────────────────────────────────────────────┐
        │  3. OUTPUT (durable dir)                                   │
        │   target_profile.md   — narrative, LLM sections tagged     │
        │   nomination.json     — sub_verdicts slot ⟂ llm_synthesis  │
        │   provenance.yaml     — prompt_hash + model_id + artefacts  │
        │   figures/target_profile_at_a_glance.{png,svg}            │
        └───────────────────────────────────────────────────────────┘
```

**Relationship to `compose-dashboard` (the sibling path).** `target-profile` is a *projection* over
the same evidence registry that the `compose-dashboard` skill uses. Both read cards through the
**same dispatcher** — `skills/compose-dashboard/scripts/_live_readers.py` (`CARD_READERS`, the
`card_id → method-reader` table). They differ only in their *output shape*:

| | `target-profile` (this doc) | `compose-dashboard` |
|---|---|---|
| Output | `nomination.json` + `target_profile.md` | `evidence_package.json` + `dashboard.md` |
| Framing | biologist "should we nominate?" | full 18-card evidence package |
| Synthesis | 6-field nomination schema | per-section headline + modality-fit |
| Committed demos | *first run staged in §6* | KRAS/COADREAD, EGFR/LUAD, BRAF/SKCM |

Feature note: the fan-out loop is **sequential in-process** (not threaded), despite historical
"parallel" language in older docstrings.

---

## 3. The five-layer repo stack

All repos live under `/home/sagemaker-user/`, org `oneTakeda`, prefix
`rnd-computational-biology-oncology-`:

| Layer | Repo | Role in the chain |
|---|---|---|
| **Datasets** | `-data-catalog` | source + derived **manifests** — the dataset origin (S3 + md5 + schema) |
| **Methods** | `-analysis-methods` | deterministic method CLIs/readers that turn a manifest into a summary + plots |
| **Contracts** | `-target-contracts` | 34 **cards** + 110 **rules** + dashboards + schemas + vocabularies |
| **Orchestration** | `-claude-oncology-skills` | the **skills** (`target-profile`, its 10 sub-skills, `compose-dashboard`, `render-evidence-package`) |
| **Outputs** | `-data-products` | committed evidence packages per (target × indication) |

The chain is:
**data-catalog manifest → analysis-methods reader → card_spec → interpretation rule → sub-verdict →
Tier-3 synthesis → nomination.json / target_profile.md**

---

## 4. The full wiring, walked on one card (KRAS × COADREAD)

We trace a single evidence card, `expression-distribution`, all the way through. Every other card
follows the identical pattern; this is the representative slice.

### 4.1 Dataset — where the numbers come from

The card declares its dataset dependency by **manifest ID**, not by file path:

```yaml
# target-contracts/cards/expression-distribution.card.yaml
required_inputs:
  - product_id: depmap-consortium-26q1        # ← a data-catalog manifest
    release_pin: "{release_pin}"
```

`depmap-consortium-26q1` resolves (in `data-catalog/manifests/sources/`) to the DepMap 26Q1 release
on S3, e.g. `s3://onc-compbio/data-catalog/sources/depmap-consortium/dmc-26q1/
OmicsExpressionTPMLogp1HumanProteinCodingGenes.csv` — pinned with md5 + schema. **Nothing in the
framework reads a bare S3 path; every read is manifest-mediated**, so provenance and release-pinning
are automatic.

### 4.2 Card — the pure-data contract

`cards/expression-distribution.card.yaml` (Card E3a) is a **pure-data contract**: it says *what to
compute and how to classify it*, but carries no therapeutic judgment. Its load-bearing fields:

- `applies_when:` — a CEL-subset predicate gating whether the card runs at all:
  `"context.data_sources.depmap_expression_available == true"`.
- `methods:` — the method to call, with templated args:
  `call: depmap-expression-distribution` (args: `target`, `release_pin`, `expressed_threshold`).
- `outputs.summary_fields:` — the scalars the method must emit (percentiles, `fraction_expressed`,
  `per_lineage_stats`, …).
- `outputs.summary_fields_vocabulary:` — **the categorical that drives rules**:
  `expression_class ∈ {broadly_high, broadly_moderate, lineage_restricted, broadly_low,
  data_unavailable}`.
- `outputs.figures:` — three declared figures (density+KDE, per-lineage strip, ranked waterfall),
  each with `preferred_surfaces` (markdown / ppt / decision_memo).
- `thresholds:` — named numeric cutoffs (e.g. `expressed_threshold_log2tpm: 1.0`), referenced from
  predicates as `THRESHOLD.<name>`.
- `warning_predicates:` — e.g. `n_cell_lines_evaluated < 500 → low_panel_expression_coverage`
  (fires → `passed_with_warnings`).
- `caveats:` — governance caveats carried verbatim into the evidence package (e.g. "cell-line
  expression ≠ tumor expression").

> **Design point for reviewers:** the card is deliberately *descriptive only*. One of its own
> caveats says it: *"Expression class is descriptive — therapeutic interpretation lives in
> target-contracts/interpretation-rules/."* This separation is what makes the interpretation layer
> auditable independently of the data layer.

### 4.3 Method — dataset → summary + plots

The card's `methods.call` resolves to `analysis-methods/methods/depmap_expression_distribution/`:

- `cli.py:load_expression_files()` reads the DepMap parquet/CSV (Tier-2 parquet fast-path →
  legacy CSV fallback), filtered to default model entries.
- `compute_summary_stats()` computes the `summary_fields` scalars and `_classify_expression()`
  assigns the `expression_class` categorical using the card's thresholds.
- `emit_density_plot / emit_lineage_strip / emit_waterfall_plot` render the three SVGs in the shared
  Takeda style (`target-contracts/plot_styles/takeda_oncology.mplstyle`); `emit_plot_data()` writes
  `plot_data_expression.parquet`; `emit_manifest()` records inputs + provenance.
- `read.py:read_expression_distribution()` is the thin library entry the orchestrator calls in live
  mode; it returns the summary dict matching the card's `summary_fields`.

**This is the only layer that touches raw data.** Everything downstream operates on the categorical
+ scalars, not the parquet.

### 4.4 Rule — categorical → per-modality signal

Interpretation lives in `target-contracts/interpretation-rules/intracellular-intrinsic.rules.yaml`
(1,442 lines) — separate from the card. A rule fires when a card emits a specific categorical and
maps it to **per-modality signals**. The KRAS-defining example (a *different* card — the mutation
one — but the clearest illustration):

```yaml
# interpretation-rules/intracellular-intrinsic.rules.yaml  (line ~315)
- rule_id: mutant-strongly-dependent-supportive
  when:
    card_id: mutation-stratified-dependency
    field: mutation_stratification_class
    equals: mutant_strongly_dependent
  signals:
    small_molecule: supportive
    degrader: supportive
  dominant: true
  rationale: |
    Mutant cells significantly + strongly more dependent than WT (BH-corrected q < α,
    |delta| >= 0.5). Oncogene-addiction biomarker ... Canonical examples:
    BRAF-V600E + vemurafenib, KRAS-G12C + sotorasib, EGFR-L858R + erlotinib.
```

Signal vocabulary is `killer` / `supportive` / `neutral` / `insufficient`, **per modality**.
`dominant: true` marks a rule strong enough to anchor a verdict on its own.

> **Design point:** this is *where scientific judgment is encoded* — in a version-controlled YAML
> rule with a human-readable `rationale` citing drug precedents. Not in the method (which only
> computes the categorical), and not in the LLM (which only narrates). This is exactly the surface
> the "nomination bar" open question (§8, Decision 5) is about.

### 4.5 Sub-verdict — the deterministic spine

Each sub-skill exposes a `_verdict(fired) → (verdict_str, driving_rule_id)` that does rank-ordered
resolution over the fired rules (e.g. `functional-requirement`: `pan_essential_killer` →
`concordant_dependent` → `lineage_selective` → … → `insufficient`). `target-profile`'s
`_run_sub_skills()` calls each in turn (`skills/target-profile/scripts/run.py:123`). These verdicts
are **pure rule logic — no LLM** — and are the invariant audit spine.

**Live KRAS × COADREAD sub-verdicts (from the run in §6):**

| Sub-skill (short) | Sub-verdict | Nature |
|---|---|---|
| expression | `broadly_moderate_expression` | rule-fired |
| selectivity | *(no verdict fn)* | raw metrics only |
| dependency | `lineage_selective` | rule-fired |
| mechanism | `well_characterized` | rule-fired |
| mutation | `biomarker_stratified_dependency` | rule-fired |
| differentiation | `insufficient` | rule-fired |
| tractability | `well_covered` | rule-fired |
| safety | `insufficient` | rule-fired |
| population | *(no verdict fn)* | raw metrics only |
| cohort_rank | *(no verdict fn)* | raw metrics only |

### 4.6 Synthesis — the only LLM step

`_build_synthesis_tool()` (`run.py:173`) defines a `tool_choice`-forced Bedrock schema. The model
**must** emit exactly this object (it cannot free-form a verdict):

| Field | Type | Constraint |
|---|---|---|
| `executive_summary` | string | 3–5 sentences |
| `tension_analysis` | string | where sub-verdicts disagree + why |
| `top_arguments_for` | string[] | max 5 |
| `top_arguments_against` | string[] | max 5 |
| `overall_recommendation` | **enum** | `nominate` / `hold` / `veto` / `insufficient_evidence` |
| `confidence` | **enum** | `high` / `medium` / `low` / `insufficient` |

The two enums are the audit-critical fields. Provenance is stamped in `_skills_common/llm.py`:
`_prompt_hash()` is a SHA-256 over `(system + user + tool-schema + model-id)`, computed *before* the
API call; `_stamp_llm_provenance()` attaches `_source: llm_synthesized`, `_model_id`, `_prompt_hash`
to every returned field. The hash is a **fingerprint of the exact prompt sent**, stamped for audit —
so a reviewer can prove which prompt produced a given narrative, and detect prompt drift. The Bedrock
call runs under a temporary profile swap to `BEDROCK_AWS_PROFILE` (default `cmp-dev`) because the
data-read profile `cbg` lacks Bedrock marketplace permission.

> **Reproducibility:** back-to-back KRAS runs produced a **byte-identical deterministic spine**
> (every `sub_verdicts` entry + `driving_rule_id`, and `nominate` both times). The `_prompt_hash`
> stability has one open caveat — see §9 Known issues.

### 4.7 Output — where the spine and the narrative live separately

`main()` writes to the durable `--out` dir:

- **`nomination.json`** — the deterministic spine (`sub_verdicts`: per-dimension `verdict`,
  `driving_rule_id`, `fired_rule_ids`, `cards_missing`) sits in a slot **distinct** from
  `llm_synthesis` (the full stamped LLM object). This is the structural expression of the
  determinism-separation claim.
- **`target_profile.md`** — LLM sections explicitly tagged *(LLM-synthesized)*; the deterministic
  **risk-by-category** table, sub-verdict table, and per-phase evidence tables are not LLM.
- **`provenance.yaml`** — `sub_skills_ran`, `llm_prompt_hash`, `llm_model_id`, and the artefact list.
- **`figures/target_profile_at_a_glance.{png,svg}`** — the composite panel (300 DPI; render is
  wrapped so a figure failure never blocks artefact emission).

---

## 5. Deterministic risk-by-category (non-LLM reshape)

`_risk_by_category_from_sub_verdicts()` (`run.py:371`) maps the sub-verdicts onto the familiar
6-category risk framing **deterministically** — and honestly returns `insufficient_evidence` for
phases that aren't wired yet, rather than fabricating. For the KRAS run:

| Category | Level | Driver |
|---|---|---|
| biological | **LOW** | strong support across A/B/C/mut (`biomarker_stratified_dependency`) |
| druggability | **LOW** | tractability `well_covered` (PRISM-CRISPR triangulated) |
| translational | insufficient_evidence | Phase-J placeholder — data not wired |
| clinical | insufficient_evidence | Phase-E clinical-precedent feed not wired |
| safety | insufficient_evidence | HPA + gnomAD normal-tissue cards not wired |
| commercial | insufficient_evidence | Cortellis/IQVIA not licensed |

---

## 6. Worked artifact (first-ever `target-profile` run)

Generated 2026-07-14, `KRAS × COADREAD`, via the composed skill (exact invocation in the Appendix):

```
export AWS_PROFILE=cbg && python3 skills/target-profile/scripts/run.py \
  --target KRAS --indication COADREAD --out <durable-dir>
```

Staged for review at **`docs/examples/target-profile-kras-coadread/`**:
`nomination.json`, `target_profile.md`, `provenance.yaml`, `figures/`.

**LLM synthesis result** (model `us.anthropic.claude-opus-4-7`, prompt_hash `b481f040…`):
`overall_recommendation = nominate`, `confidence = high`.

> *Executive summary (LLM-synthesized, verbatim):* "KRAS in COADREAD presents as a well-validated,
> biomarker-stratified oncology target with strong functional and pharmacological evidence. CRISPR
> and RNAi both show bimodal, lineage-selective dependency enriched in Bowel (54% strongly
> dependent) and Pancreas, and hotspot-mutant lines are dramatically more dependent than WT (delta
> Chronos -1.32, q~1e-102). … Expression is broadly moderate/non-selective and safety/surface data
> are uninformative — expected for an intracellular GTPase — so the target profile is intracellular
> small-molecule/tri-complex, not surface/ADC."

Note how the synthesis **respects the per-axis signals rather than overclaiming**: expression fired
a *neutral* rule (`expression-broadly-moderate-neutral`), and the LLM explicitly says selectivity
"must come entirely from mutant-state pharmacology, not expression differential" — the nomination
rests on the mutation + dependency axes, exactly as the deterministic spine indicates. It also flags
real risks the spine surfaces (NRAS paralog buffering; empty safety card).

The composite figure:

![Target profile at a glance](examples/target-profile-kras-coadread/figures/target_profile_at_a_glance.png)

**Trace to verify:** the mutation card emits `mutation_stratification_class = mutant_strongly_dependent`
(KRAS G12X addiction, mut-strat Δ≈-1.32, q≈1e-102) → fires `mutant-strongly-dependent-supportive`
(`small_molecule: supportive`, `degrader: supportive`, `dominant: true`) → mutation sub-verdict
`biomarker_stratified_dependency` → feeds biological-risk **LOW** and the LLM's arguments-for.

### Breadth — the sibling `compose-dashboard` demos (committed)

Three fully-materialized evidence packages already exist in `data-products/` (the `compose-dashboard`
path — 12–14 cards + ~29 figures each):

- `data-products/KRAS/COADREAD/ep-kras-coadread-unpinned-latest_approved-001/dashboard.md`
- `data-products/EGFR/LUAD/ep-egfr-luad-unpinned-latest_approved-001/dashboard.md`
- `data-products/BRAF/SKCM/ep-braf-skcm-unpinned-latest_approved-001/dashboard.md`

Three shells (`MDM2/SKCM`, `MCL1/LUAD`, `HRAS/PDAC`) carry `.invalid` suffixes — honest markers that
they failed validation / aren't materialized.

---

## 7. Coverage honesty — what's real vs placeholder

The **spine is structurally complete** (34 cards, 110 rules, full compositional test suite). What's
uneven is the *data richness* underneath. Current status (per
`~/.claude/plans/skills-roadmap-assessment-2026-07-10.md`):

| Phase | Skill | Status |
|---|---|---|
| A presence | tumor-presence | wired (protein/CPTAC layer partial) |
| B selectivity | tumor-selectivity | wired |
| C requirement | functional-requirement | wired |
| D mechanism | mechanism-and-pharmacology | wired (cold path slow) |
| A/E mutation | mutation-profile | wired |
| E differentiation | differentiation-landscape | **partial** (co-mutation data pending) |
| F tractability | tractability-and-modality | **partial** (3/9 cards; 6 blocked) |
| F surface scan | surfaceome-cohort-ranking | wired (parquet not yet on S3) |
| G safety | on-target-safety-liability | **partial** (gnomAD only) |
| H population | patient-population-and-access | **partial** (hotspot only) |
| I combo/resistance | combo-and-resistance | **PLACEHOLDER** (cards not designed) |
| J translational | translational-readiness | **PLACEHOLDER** (cards not designed) |
| K composer | target-profile | wired |

**8 wired / 3 partial / 2 transparent placeholders.** Root cause of the partials: five Layer-3
derived parquets were reverted in data-catalog PR #113 (2026-07-09) because their manifests carried
`TBD_ON_INGEST` md5/size placeholders. Re-landing the 3 unblocked ones (cooccurrence, CPTAC,
surfaceome-family) moves the framework 6/12 → 9/12 real.

> **Not every `insufficient` in the §6 KRAS run is a genuine data gap** — some are decision-layer
> bugs being fixed in a parallel workstream. See §9 Known issues before trusting an `insufficient`
> verdict.

---

## 8. Open design questions (folded in from SHOWCASE_DESIGN.md)

🗳️ **OPEN — Decision 1 · Targets.** Ryan's lean: KRAS/COADREAD hero + EGFR/LUAD + BRAF/SKCM (the 3
materialized). Should we materialize a non-textbook ODDU-relevant target (MDM2/MCL1/HRAS)? Should we
include a deliberately negative/ambiguous target to show `hold` / `insufficient_evidence`?

🗳️ **OPEN — Decision 2 · Data.** No new data needed for the 3-target showcase (DepMap+TCGA+PRISM
backbone). Do we disclose "RNA-only presence" or land CPTAC before showing ODDU (they care about
protein-level presence for modality)? Tractability has 6/9 surface cards unavailable — disclose or
downscope?

🗳️ **OPEN — Decision 3 · Cards.** Show the full composed profile, spotlight 3 hero cards
(mutation-stratified-dependency, dependency-lineage-selectivity, prism-crispr-concordance). Which
cards "wow" ODDU specifically? Any card weak enough to hide rather than disclose?

🗳️ **OPEN — Decision 4 · Plots.** Figure quality bar for slide-drop (300 DPI). Adopt
`takeda_oncology.mplstyle` uniformly? Want a single profile-at-a-glance headline visual (the
composite panel)?

🗳️ **OPEN — Decision 5 · Synthesis / the nomination bar (highest stakes).** What evidence justifies
`nominate` vs `hold` vs `veto` vs `insufficient_evidence`? Today the LLM decides within prompt
guidance. Should we encode explicit **gates** (e.g. "veto if pan-essential") as rules at the
synthesis level — mirroring how §4.4 rules encode judgment at the card level? Demo with a modality
lens or hypothesis-neutral? Executive-summary tone/length; include "what would change your mind"
kill-experiments?

---

## 9. Known issues & follow-ups

Engineering caveats surfaced while producing this walkthrough. None affect the deterministic spine's
reproducibility; all are tracked for fix.

**9.1 — LLM `_prompt_hash` is not byte-stable across process launches.** The two real KRAS runs
stamped different hashes (`b481f040…` vs `dadfbc27…`), even though the deterministic spine was
byte-identical and the recommendation was `nominate` both times. In a controlled test the user prompt
reconstructs byte-for-byte identically both within one process and across two separate processes — so
the cross-run hash difference is **currently unexplained** (a `PYTHONHASHSEED`-driven ordering effect
in some part of the hashed string is the leading hypothesis, not a confirmed cause). *Impact:* the
hash works as an audit fingerprint of a single run, but cannot yet be used as a cross-run
drift alarm. *Follow-up:* pin `PYTHONHASHSEED` (and/or sort keys in the summary serialization),
re-test, and confirm hash-equality before advertising it as a reproducibility guarantee.

**9.2 — Some `insufficient` sub-verdicts are decision-layer bugs, not data gaps.** A parallel
hardening workstream (`fix/skills-rule-firing-hardening`, PR #60) identified bugs in
`skills/_skills_common/` that suppress rules even when data is present — notably a bool-vs-string
match bug (rules encode `equals: 'true'` while readers emit Python `True`), which kills the
boolean-keyed rules behind **differentiation-landscape** (co-mutation *is* present for KRAS —
APC/SMAD4 co-occurrence, BRAF/EGFR exclusivity — but the sub-verdict reads `insufficient`) and
**mechanism**'s PD-marker rule. *Follow-up:* after that PR merges, **re-generate** the §6 KRAS run so
`differentiation` fires a real verdict. By contrast, `safety → insufficient` *is* a genuine data gap
(the gnomAD LoF card returned empty here).

**9.3 — Runtime environment has two easy-to-trip prerequisites** (see Appendix): the Python must have
both the data stack and `anthropic[bedrock]`; and `ANTHROPIC_MODEL` must be a raw Bedrock-invokable id
(the harness's `…opus-4-8[1m]` alias returns HTTP 400). Both are documented in the skill's `SKILL.md`.

**9.4 — Phase-letter labels are inconsistent.** The §5 risk-by-category drivers and the §7 status
table use different phase letters for the same skills (e.g. safety appears as "Phase-G" in §5 but the
status table calls differentiation "Phase E"). These strings originate in the code; harmonizing the
phase taxonomy is a low-priority cleanup.

---

## Appendix — reproduce this yourself

The runtime Python must have **both** the scientific stack (pandas/pyarrow/boto3, for the sub-skill
card readers) **and** `anthropic[bedrock]` (for the synthesis). The base SageMaker `python3` (3.12)
has the data stack; add the synthesis client once with `pip install --user "anthropic[bedrock]"`.
(Note: the `workflow-target-evaluation-onc` pixi env has `anthropic` but **not** the data stack, so
it produces an all-`insufficient` run — don't use it here.)

```
export AWS_PROFILE=cbg && export AWS_REGION=us-east-1
# ANTHROPIC_MODEL must be a raw Bedrock-invokable id. The Claude Code harness sets
# ...opus-4-8[1m]; that [1m] alias is NOT Bedrock-invokable (HTTP 400) — override it:
export ANTHROPIC_MODEL=us.anthropic.claude-opus-4-7
python3 skills/target-profile/scripts/run.py \
  --target KRAS --indication COADREAD \
  --out ~/dev/framework-runs/target-profile-kras-coadread-2026-07-14
```

Optional lenses: `--modality small_molecule`, `--therapeutic-hypothesis "<text>"` (both reshape LLM
narrative only; sub-verdicts unchanged).

**Reproducibility check:** re-run and confirm the `sub_verdicts` are byte-identical across runs (this
is verified — the deterministic spine is stable). The `_prompt_hash` is **not yet** guaranteed stable
across process launches (see §9). The LLM narrative itself is expected to vary run-to-run — that's why
the tagging + hash exist.
