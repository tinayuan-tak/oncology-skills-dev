# Framework Overview — data → skills, end to end

**Start-here orientation doc.** How the iDAS target-evaluation framework is
structured across four repos, what each layer owns, and how a scientist's
question becomes an auditable answer. Read this first; then drop into
`IDAS_SUBTYPE_PIPELINE.md` (subtype layer), `SUBGROUP_PANORAMA_PLAYBOOK.md`
(per-indication recipe), or the per-card docs under `cards/`.

Portable GFM (compact tables + fenced ASCII; no Mermaid/HTML) per the
`README.md` format rules.

---

## The model in one sentence

Raw oncology data is refined through **four repos**, each a distinct layer with
a distinct contract, so a scientist's question ("is KRAS a good target for MSS
colorectal cancer?") is answered by **composing** small, auditable,
independently-testable evidence units — not one monolithic analysis.

## The four repos (the spine)

```
data-catalog        →   analysis-methods    →   target-contracts    →   claude-oncology-skills
(what data exists)      (how to compute)        (what to claim)         (how to answer)
```

| Repo | Owns | Analogy |
|------|------|---------|
| **data-catalog** | Manifests pointing at S3 data (sources + derived products); subgroup catalogs | The card catalog — *where* everything is |
| **analysis-methods** | Deterministic Python readers/computers (`read_*`, `build_*`) | The lab instruments — *how* you measure |
| **target-contracts** | Cards (what evidence), rules (what signals), vocabularies (controlled verdicts), schemas + validators | Lab protocols + the peer-review board — *what* claims are legitimate |
| **claude-oncology-skills** | Skills that compose cards → synthesis; two engines; renderers | The scientist writing the report — *how* it's answered |

**The dependency arrow never reverses.** methods read from catalog; contracts
reference methods + catalog; skills reference contracts. A skill never touches
raw data directly — it goes through a card → a method → a pinned manifest. That
chain is what makes any single claim auditable back to a specific data file.

**Determinism vs. judgment is split by layer.** Everything up to and including
rule-firing is deterministic and reproducible. Only the *final synthesis
narrative* is LLM-generated — and even the nomination *verdict* is rule-gated,
not LLM-chosen. The audit spine is invariant even when prose drifts run-to-run.

---

## The core unit: a card's journey to a verdict

A **card** answers one evidence question. Its journey through the layers:

```
1. CATALOG    data-catalog/subgroup-catalogs/COADREAD/2026-Q2.yaml
                 declares strata (MSI_H, MSS, right/left_sided, ...)
                    |
2. METHOD     analysis-methods/methods/depmap_chronos/read.py
                 build_dependency_panorama() reads per-ModelID Chronos,
                 groups by stratum member-set
                    |  emits per_subgroup_metrics:
                    |    [{stratum, class, evidence_state, subgroup_n,
                    |      subgroup_n_floor_met, source_cohort, ...}]
3. CARD       target-contracts/cards/subgroup-stratified-dependency.card.yaml
                 declares: methods:, summary_fields_record_schemas:, tier:,
                 subgroup_stratification:
                    |
4. RULE       target-contracts/interpretation-rules/*.rules.yaml
                 when: {card_id, field, in_record:{class: not_dependent,
                        evidence_state: measured, subgroup_n_floor_met: true}}
                 -> signals: {subtype_fit_genomic: opposing}
                    |
5. SKILL      claude-oncology-skills/skills/target-profile/scripts/run.py
                 fires rules -> sub-verdict tuple -> nomination gate -> LLM synthesis
                    |
6. RENDER     skills/render-evidence-package/scripts/render_markdown.py
                 dashboard.md with the evidence_state trichotomy tables
```

## The two "shapes" that carry everything

**Shape 1 — "one shape, four layers"** (the subgroup panorama). A tall row
`(sample, stratum, is_member)` propagates upward *unchanged in shape*:
sample-assignment parquet → method `{stratum: record}` dict → card
`per_subgroup_metrics` list → rule `in_record` match. Adding a new subgroup axis
needs no new plumbing at each layer — the shape already flows.

**Shape 2 — the sub-verdict tuple `(verdict_str, driving_rule_id)`.** Every
evidence dimension collapses to this. The nomination gate consumes a dict of
them keyed by sub-skill short name. This is the seam where determinism meets the
gate.

---

## Signal grammar — how every data surface exits to the output

A card's finding does not "always lead to a verdict." Every finding takes ONE of
three exit paths, and the path is decided by which of six signals a rule maps it
to. Getting this split right is the framework's most important honesty property.

**The six-signal vocabulary** (`schemas/interpretation_rules.schema.json`,
`$defs.signal_vocabulary`) — every rule maps a card's categorical finding to one:

| Signal | Meaning | Verdict effect |
|--------|---------|----------------|
| `supportive` | evidence consistent with the target | builds toward a positive fit |
| `opposing` | real evidence AGAINST the target | pushes toward negative |
| `killer` | hard gate | short-circuits to `not_viable` / veto |
| `neutral` | informational | none (surfaced only) |
| `insufficient` | in-scope but weak/MISSING data (coverage gap) | none (surfaced, not scored) |
| `not_applicable` | out-of-scope for this rule's tier | none (e.g. a subtype signal when no subtype was queried) |

**Measured-negative vs. null — the distinction that drives everything.** The
user-intuitive case ("expression shows no tumor expression") is really two cases
the framework deliberately keeps apart:

| Case | What it means | Signal | Fires a rule? | Affects verdict? |
|------|---------------|--------|---------------|------------------|
| **Measured negative** | We looked, with enough samples (n≥floor=30); the target is genuinely absent | `opposing` / `killer` | Yes | **Yes** |
| **Null / absent data** | We couldn't look — target missing from the panel, or cohort too small | `insufficient` | Yes (a *different* rule) | **No** — coverage gap |

A trusted negative is **as actionable as a positive** (it drives a no-go/hold);
"we have no data" is **not** evidence against the target — scoring it as `opposing`
would manufacture false no-gos. The n≥30 floor is what decides which side an
"absent" reading falls on: below the floor an absent reading is *unknown*
(`insufficient`), not a negative. Real exemplar:
`interpretation-rules/intracellular-intrinsic.rules.yaml ::
rnai-data-unavailable-insufficient`, whose own comment reads *"Coverage gap; not
used as opposing evidence."*

**The three exit paths for any card finding:**

```
CARD emits a finding
      |
      +-> matches a rule -> supportive / opposing / killer ---> AFFECTS VERDICT
      |                                                          (scored, or short-circuits)
      |
      +-> matches a rule -> insufficient / neutral / not_applicable ---> SURFACED, NOT SCORED
      |                                                          (coverage_summary / context prose)
      |
      +-> matches NO rule at all ---------------------------> SILENT (render-only, informational)
```

So the accurate statement is: **every card produces an output, but not every
output fires a verdict-affecting rule** — and a null dataset specifically fires an
`insufficient` rule that is reported as a coverage gap, never as a negative.

**Two verdict backstops** (`skills/compose-dashboard/scripts/_synthesis.py`):
- **Killer short-circuit** — any `killer` signal forces `fit_level = "not_viable"`
  (~L219), uniformly whether from a Tier-2 rule or a modality `killer_condition`.
- **Insufficient-evidence floor / refuse-to-answer** — `primary_total_in_scope ==
  0` → `insufficient_evidence` (~L227); and at the headline level,
  `n_not_informative_or_excluded >= 3` → *"Insufficient evidence for evaluation…"*
  (~L374-382). This is the collective answer to "what if the data is null": enough
  nulls and the framework **declines to answer** rather than fabricate a call.
  (`MIN_IN_SCOPE_FOR_STRONG = 2`: a single in-scope card caps the fit at
  "moderate" — honesty about sparsity.)

**Tie-back to the nomination gate (Engine B).** The same discipline is why the
verdict-affecting subtype rule fires only on `subgroup_n_floor_met: true`: an
underpowered subtype is `insufficient` / inadmissible, never `opposing` — a thin
subtype cohort can never manufacture a subtype-specific no-go.

---

## The two synthesis engines (know which does what)

There are **two** aggregation engines. Knowing which produces the nomination
verdict is the single most important fact for future work.

| Engine | File | Produces | Gating |
|--------|------|----------|--------|
| **A — compose-dashboard** | `skills/compose-dashboard/scripts/_synthesis.py :: synthesize()` | per-**modality** `fit_level` (ADC-viable? small-molecule-viable?) | rule-gated: killer short-circuit + dominant-plus-confirmation |
| **B — target-profile** | `skills/target-profile/scripts/run.py :: _gate_recommendation()` | the **nomination verdict** (`nominate`/`hold`/`veto`/`insufficient`) | LLM synthesis + a deterministic clamp gate |

Key properties of Engine B's gate (the nomination gate):
- **One-directional** — it can only force a verdict *more* conservative
  (`veto` > `hold`), never force `nominate`. A killer/negative signal ratchets
  down; nothing ratchets up. Policy lives in
  `vocabularies/nomination_verdict_gate.yaml`, conservative hardcoded fallback
  on load failure (never permissive).
- **This is what made the subtype layer safe on one engine** — a subtype signal
  can never subordinate a pan-cancer safety killer, because the gate takes
  max-severity across all fired sub-verdicts.

**The engines are NOT unified.** They duplicate the killer-gating pattern with
different inputs (card `interpretation_call`s vs. skill verdict tuples).
Unifying them is a known, deferred refactor. Any future work touching *both*
modality-fit and nomination should weigh doing it.

---

## The LLM synthesis layer (where judgment enters — and where it doesn't)

The framework is deterministic up to the very end. There is **exactly one LLM
call** in the whole target-profile pipeline (Engine B), and it is tightly boxed:
it writes the narrative, proposes a recommendation from a fixed enum, and is then
overridden by the deterministic gate below it. Engine A (compose-dashboard) is
**fully deterministic** — no LLM in its `fit_level` scoring (it has synthesis
prompt hooks in the dashboard_spec, but the modality-fit call is rule-scored).

```
9 sub-skills fire rules -> sub_results (deterministic verdict tuples)
        |
        v
  _build_user_prompt()            packages evidence as TEXT (no data/tool access)
        |
        v
  synthesize_structured()         THE single Bedrock call (_skills_common/llm.py)
    tool_choice = FORCED          model MUST call the tool; cannot free-form
        |
        v
  llm_output {executive_summary, tension_analysis, top_arguments_for/against,
              overall_recommendation (enum), confidence (enum)}
        |
        v
  _gate_recommendation()          DETERMINISTIC clamp OVERRIDES the LLM rec
        |                           (killer / subtype-non-dependence -> hold/veto wins)
        v
  nomination.json + target_profile.md   every LLM field tagged with provenance
```

**What the LLM is GIVEN** (`target-profile/scripts/run.py :: _build_user_prompt`):
pure text assembled from the deterministic layer — target + indication, the
**sub-verdicts** (each as `` `verdict_str` (driving rule: id)``), and the **card
summaries** (raw per-card evidence). The model has **no raw-data access and no
tools to fetch more** — it reasons only over what the deterministic layer already
surfaced. "Do NOT invent biology" is instructed AND structurally enforced by the
absence of any data reach.

**What the LLM MUST produce** (`_build_synthesis_tool`, forced via
`tool_choice={"type":"tool",...}`): a structured tool call with six fields —
`executive_summary`, `tension_analysis`, `top_arguments_for`/`_against` (≤5 each),
`overall_recommendation` (**enum** `nominate|hold|veto|insufficient_evidence`),
`confidence` (**enum** `high|medium|low|insufficient`). It cannot return free-form
prose; if it fails to call the tool, `synthesize_structured` raises (no silent
prose fallback).

**The recommendation is advisory within a gated band.** The LLM proposes a
recommendation from the enum, but `_gate_recommendation` runs *after* and clamps
it: a fired killer / subtype-non-dependence sub-verdict forces `veto`/`hold`
regardless of the LLM's choice, and the override is recorded (LLM value preserved
for audit). So the LLM can pick among non-vetoed options but can never override a
safety/efficacy killer. **The audit spine is invariant**: sub-verdicts
(deterministic, rule-fired) live in separate schema slots from the LLM narrative —
discard every LLM word and the verdict + driving rules remain.

**Provenance + reproducibility** (`_skills_common/llm.py`):
- `_prompt_hash` — SHA-256 over `(system + user + tool_schema + model_id)`, tool
  serialized `sort_keys` so field-order doesn't perturb it. Same inputs -> same
  hash; a differing hash explains any output drift.
- `_stamp_llm_provenance` — every top-level LLM field is wrapped
  `{value, _source: llm_synthesized, _model_id, _prompt_hash}`, so `nomination.json`
  is field-by-field auditable (machine-reasoned vs. rule-derived).
- Model: Bedrock `ModelConfig.from_env().synthesis_model` — **Opus by default**
  (`us.anthropic.claude-opus-4-7`), env-overridable.

**Known limitation (deferred hardening).** The prompt-*hash* is stable across runs
for identical inputs, but the LLM *prose* can still drift run-to-run (see
`feedback_target_profile_prompt_hash_nondeterminism`). Committees should cite the
deterministic extract (sub-verdicts + gated recommendation), not the narrative
wording. The design record's F6 "nomination immutability manifest" (bundle all
cell pins + model/prompt/response hashes + rendered-doc hash) is the deferred fix;
until it lands, treat the prose as a skin over the invariant spine.

---

## What is wired today (two milestones, both merged)

**Milestone 1 — Descriptive subgroup panorama.** The full seam
**catalog → dashboard-spec admission → dispatch → per-sample builder →
evidence_state render** for 2 live cards
(`subgroup-stratified-mutation-frequency`, `subgroup-stratified-dependency`).
Plus a **grain/tier validator** (`validators/validate_cards.py ::
_grain_and_tier_check`) that makes the "claims-stratification-it-can't-honestly-
do" trap structurally impossible. Descriptive only — enumerates subgroups,
changes no verdict.

**Milestone 2 — Verdict-affecting subtype layer.** A subtype finding can now
change the nomination: a **measured, floor-cleared, non-dependent** subtype
fires `subtype-non-dependence-opposing` → `subtype_fit_genomic: opposing` →
nomination gate `hold`, one-directionally. The `in_record` rule predicate, the
`subtype_fit_genomic` channel, and the `subgroup_n_floor_met: true` admissibility
guard (underpowered = inadmissible at rule-fire time) all landed here.

---

## The guard rails (mechanically enforced, not by convention)

A future developer must respect these invariants — each is checked by a
validator or a code path, not left to reviewer diligence:

1. **Grain-check** — a card claiming per-subgroup output (`per_subgroup_metrics`
   or `status: live`) MUST bind a per-sample reader, never an emit-time
   aggregate. (`validate_cards.py`)
2. **Tier-check** — `tier: target` cards (identity, structure, LoF-constraint,
   surfaceome-family) never stratify: they are gene/protein properties,
   invariant across patient subpopulations.
3. **Admissibility (n≥30 floor)** — underpowered strata appear in render
   *tagged* `underpowered`, but cannot fire a verdict-affecting rule
   (`in_record` pins `subgroup_n_floor_met: true`). "Below floor = excluded,
   not just flagged" — enforced at rule-fire time.
4. **One-directional gate** — subtype/killer signals can only make a nomination
   more conservative; a positive subtype finding stays descriptive (cannot
   inflate a nomination).
5. **Descriptive vs. verdict-affecting split** — a *card* emits data and no
   signal (its caveat stays honest); a *rule* reads the data and emits the
   signal. Data and judgment never conflate in the same artifact.

---

## The "intrinsic" naming caution

Two unrelated concepts both used the word "intrinsic"; the framework keeps them
separate:
- **biology axis** (`vocabularies/biology_axis.enum.yaml`):
  `intracellular_intrinsic | surface_intrinsic | extrinsic | mixed` — *where the
  drug acts* (gates modality compatibility).
- **scope-invariance** (`card.tier: target`): the card's answer is a property of
  the gene/protein, identical across patient subgroups — *whether it may
  stratify at all*.

Use `tier: target` for the second; never say "target-intrinsic."

---

## How to think about future development

- **Add a new evidence type** → new method reader + new card + (optionally) new
  rules. The card is the contract; keep it thin.
- **Add a new subgroup axis** → extend the subgroup catalog + emit assignment
  shards; the "one shape" plumbing already carries it upward.
- **Make something verdict-affecting** → author a rule that fires a channel, add
  a `(sub_skill, verdict) → action` row to `nomination_verdict_gate.yaml`. Stay
  one-directional unless you deliberately design otherwise.
- **Biggest latent debt** → the two-engine unification. Any feature needing
  subtype-awareness in *modality-fit* (Engine A) forces it.
- **Current frontier** → the verdict-affecting subtype layer is *latent on real
  data*: today's subgroup dependency cohorts are underpowered (e.g. COADREAD
  MSI-H dependency is n=17 < 30, so the floor guard correctly blocks it). The
  highest-leverage next data investment is emitting **well-powered subgroup
  assignment products** (a Phase-2b data job) so the machinery actually fires.
  Everything downstream is built and waiting.

## Maturity ladder (honest)

| State | What |
|-------|------|
| Wired + firing on real data | Descriptive panorama (mutation-freq + dependency across MSI/MSS, COADREAD) |
| Wired, latent on real data | Verdict-affecting subtype gate (needs a well-powered subtype negative to fire) |
| Deferred by design | Engine A subtype parity; two-engine unification; F3/F5 emitter fields (driver-alignment, noise-floor); F6 nomination immutability manifest; F7 nominate/browse mode; raised floors; tumor-cohort (non-cell-line) subgroup dependency |

## Cross-references

- `IDAS_SUBTYPE_PIPELINE.md` — the subtype-pipeline master design (4-layer detail,
  scope contract, signal channels, resolver product).
- `SUBGROUP_PANORAMA_PLAYBOOK.md` — per-indication recipe + the two-filter
  card-selection rule + admissibility.
- `SAMPLE_ANNOTATION_PLAN.md` — how each stratum is assigned (directly-tagged /
  MAF-filter / classifier).
- `MODALITY_TAXONOMY.md` — the measurement-modality axis on expression cards.
- `README.md` + `cards/` + `skills/` — per-card and per-skill reference docs.
- `vocabularies/nomination_verdict_gate.yaml` — the auditable veto/hold policy.
