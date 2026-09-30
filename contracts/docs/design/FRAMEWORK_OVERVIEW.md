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
| **claude-oncology-skills** | Skills that compose cards → resolver ladders → the nomination gate → synthesis; renderers | The scientist writing the report — *how* it's answered |

**The dependency arrow never reverses.** methods read from catalog; contracts
reference methods + catalog; skills reference contracts. A skill never touches
raw data directly — it goes through a card → a method → a pinned manifest. That
chain is what makes any single claim auditable back to a specific data file.

**Determinism vs. judgment is split by layer.** Everything up to and including
rule-firing is deterministic and reproducible. Only the *final synthesis
narrative* is LLM-generated. The nomination verdict is rule-gated on **both** sides:
a fired veto/hold rule forces the recommendation, and — as of the 2026-09-11
lower-bound fix — on **abstention** (no rule fires) an LLM-authored `veto`/`hold`
collapses to `insufficient_evidence`, so a negative recommendation always has a rule
(or the honest abstention floor) behind it. The only value the LLM still owns
outright is a `nominate` on abstention, which stays bounded *above* by the kill gate.
The audit spine is invariant even when prose drifts run-to-run.

> **✅ Resolved defect (found + fixed 2026-09-11).** The clamp (`run.py`, gate branch)
> used to be one-*sided*: it forced the recommendation only when a veto/hold rule
> fired; the abstention branch touched only `confidence`, leaving
> `overall_recommendation` = the LLM's value with **no lower bound**. So on the ~half
> of runs where the gate abstained, the LLM could author a `veto`/`hold` with no rule
> behind it and nothing in the audit spine to attribute it to (measured: 41 of 120
> run artifacts published a recommendation the gate did not produce; 5 LLM-authored
> vetoes landed on approved drugs). It bounded optimism (a `nominate` requires a
> positive tier) but not pessimism — the side of the framework's measured failure
> mode. **Fix (landed):** the missing lower half — an abstention `veto`/`hold` with no
> fired rule collapses to `insufficient_evidence` (`tp_gates.abstention_lower_bound_clamp`,
> recorded as `gate.lower_bound_clamp`). Replayed over the corpus it moved 14 of 43
> runs (9 hold + 5 veto, incl. 4 approved-drug vetoes) to `insufficient_evidence`. A
> recommendation is now rule-authoritative whenever it is a negative; where
> `target_call.gate.fired == false` and the value is `insufficient_evidence`,
> `deciding_axis.basis` will read
> `abstention_coverage_gaps`.

---

## The core unit: a card's journey to a verdict

A **card** answers one evidence question. Its journey through the layers:

```
1. CATALOG    data-catalog/subgroup-catalogs/COADREAD/2026-Q2.yaml
                 declares strata (MSI_H, MSS, right/left_sided, ...)
                    |
2. METHOD     analysis-methods/onc_methods/depmap_chronos/read.py
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

**Two verdict backstops** (both intrinsic to the single spine — the per-skill
resolver ladder + the nomination gate; see the next section):
- **Killer short-circuit** — any `killer` signal short-circuits its axis to
  `not_viable`/veto, uniformly whether from a Tier-2 rule or a modality
  `killer_condition`. This is not a property of any one aggregator; it is how the
  signal grammar itself is defined (the `killer` row above), so it holds in every
  resolver and in the nomination gate's max-severity reduction alike.
- **Insufficient-evidence floor / refuse-to-answer** — when a skill's in-scope
  evidence is empty or too thin, its resolver returns an honest negative rather
  than a fabricated call: the composed `adc-tce-modality-fit.fit_class`, for
  instance, emits `neither_viable` (or degrades to `insufficient`) when upstream
  is thin, and the nomination gate maps a run with no admissible positive to
  `insufficient` rather than inventing one. This is the collective answer to "what
  if the data is null": enough nulls and the framework **declines to answer**
  rather than fabricate a call.

**Tie-back to the nomination gate.** The same discipline is why the
verdict-affecting subtype rule fires only on `subgroup_n_floor_met: true`: an
underpowered subtype is `insufficient` / inadmissible, never `opposing` — a thin
subtype cohort can never manufacture a subtype-specific no-go.

---

## One aggregation engine (the nomination gate)

There is **one** aggregation into a decision: the target-profile fan-out →
per-skill resolver ladders → the nomination gate. Knowing that this gate is the
sole place a verdict is composed is the single most important fact for future
work.

```
target-profile fans out to 15 sub-skills (in parallel, in-process)
        |  each skill resolves its cards through a declarative ladder
        |  (_skills_common/resolver.py :: resolve_verdict) -> a sub-verdict tuple
        v
  nomination gate  (target-profile/scripts/tp_gates.py :: _gate_recommendation,
                    policy in vocabularies/nomination_verdict_gate.yaml)
        |  max-severity reduction over the ~8 verdict-bearing sub-verdicts
        v
  the nomination verdict  (nominate / hold / veto / insufficient)
```

Key properties of the gate:
- **One-directional** — it can only force a verdict *more* conservative
  (`veto` > `hold`), never force `nominate`. A killer/negative signal ratchets
  down; nothing ratchets up. Policy lives in
  `vocabularies/nomination_verdict_gate.yaml`, conservative hardcoded fallback
  on load failure (never permissive).
- **This is what makes the subtype layer safe** — a subtype signal can never
  subordinate a pan-cancer safety killer, because the gate takes max-severity
  across all fired sub-verdicts.

**Modality-fit is not a second engine.** It once was: a separate
`compose-dashboard` aggregator scored a per-modality `fit_level` in its own
`_synthesis.py`, duplicating the killer-gating pattern over a different input.
That engine was **retired 2026-08-20 (#654)** — the skills `CLAUDE.md` instructs
"disregard any lingering reference to it." Its work now flows through the single
spine like every other card: modality substrate is the **composed
`adc-tce-modality-fit` card** (its `fit_class` fused at compose time from
surfaceome-family + topology + structure), resolved inside the
`surface-modality-fit` sub-skill of the fan-out above. There is no longer a
"two-engine unification" to do; there is one engine, and modality-fit is one of
its inputs.

---

## The LLM synthesis layer (where judgment enters — and where it doesn't)

The framework is deterministic up to the very end. There is **exactly one LLM
call** in the whole target-profile pipeline, and it is tightly boxed: it writes
the narrative, proposes a recommendation from a fixed enum, and is then
overridden by the deterministic gate below it. Everything feeding it — including
the modality `fit_class` — is rule-scored, not LLM-scored.

```
fan-out sub-skills fire rules -> sub_results (deterministic verdict tuples)
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

**The recommendation is advisory within a gated band that is now bounded on BOTH
sides.** The LLM proposes a recommendation from the enum, and `_gate_recommendation`
runs *after*: a fired killer / subtype-non-dependence sub-verdict forces `veto`/`hold`
regardless of the LLM's choice (override recorded, LLM value preserved for audit), and
no positive tier can force `nominate`. So the LLM can never override a safety/efficacy
killer and can never manufacture a GO. **And when NO rule fires (the gate abstains —
roughly half of runs), an LLM-authored `veto`/`hold` is clamped to
`insufficient_evidence`** (`tp_gates.abstention_lower_bound_clamp`, recorded as
`gate.lower_bound_clamp`; the 2026-09-11 lower-bound fix), so a negative recommendation
always has a fired rule — or the honest abstention floor — behind it. The only value the
LLM still owns outright is a `nominate` on abstention, bounded above by the kill gate.
With both sides bounded, "discard every LLM word and the verdict remains" holds for every
verdict except an abstention `nominate`. Sub-verdicts (deterministic, rule-fired) always
live in separate schema slots from the LLM narrative, so the *sub-verdict* spine is
invariant regardless.

**Provenance + reproducibility** (`_skills_common/llm.py`):
- `_prompt_hash` — SHA-256 over `(system + user + tool_schema + model_id)`, tool
  serialized `sort_keys` so field-order doesn't perturb it. Same inputs -> same
  hash; a differing hash explains any output drift.
- `_stamp_llm_provenance` — every top-level LLM field is wrapped
  `{value, _source: llm_synthesized, _model_id, _prompt_hash}`, so `nomination.json`
  is field-by-field auditable (machine-reasoned vs. rule-derived).
- Model: Bedrock `ModelConfig.from_env().synthesis_model` — **Opus by default**
  (`FRAMEWORK_SYNTHESIS_MODEL = us.anthropic.claude-opus-4-8` in
  `_skills_common/bedrock_client.py`), env-overridable via `ANTHROPIC_MODEL`.

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
**catalog → card admission (`cards_used` / `SUB_SKILL_CARDS`) → dispatch →
per-sample builder → evidence_state render** for 2 live cards
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
- **Biggest architectural debt** → the gate does not implement the ontology's
  necessity model. `vocabularies/target_profiling_axes.yaml` declares necessity
  as **ANY-OF** (an antigen-driven target carries no recurrent somatic
  alteration, so an unfired `genomic_alteration` must not read as failing
  necessity), but `nomination_verdict_gate.yaml` operates as
  **dependency-AND-safety** — 2 vetoes, both on `dependency`, plus safety holds,
  with a growing lookup table of per-(archetype × axis × modality) exceptions
  papering over the gap. The consequence is measured, not hypothetical: 0/14
  surface antigens in the reference panel are adjudicated on surface biology, and
  the composed panel emits 0 nominate. The remediation is a **thesis-routed
  gate** — type the target's thesis, then let *that thesis's* admissible axis
  decide (co-conditioned on a favorable *measured* verdict, so routing can never
  invent a GO). See the 2026-09-11 architecture assessment
  (`~/dev/framework-runs/2026-09-11-framework-architecture-review/ASSESSMENT.md`).
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
| Deferred by design | Thesis-routed gate (the biggest debt above); modality-fit subtype parity; F3/F5 emitter fields (driver-alignment, noise-floor); F6 nomination immutability manifest; F7 nominate/browse mode; raised floors; tumor-cohort (non-cell-line) subgroup dependency |

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
