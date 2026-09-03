# Unified skill-output contract (`skill_report`)

**Status:** adopted incrementally (safety = first pilot). **Origin:** the tumor-presence signals-first
review (USP8/NSCLC), where three output layers disagreed and the least-honest one (a scalar verdict
picked from the favorable cell-line lens) won the headline. This contract makes every wired skill emit
the *same shape* of message, with the **signal + corroboration** package as the spine and the collapsed
verdict as a subordinate, signal-capped summary.

## Principle: signals lead, the verdict follows

The reader-facing truth is the **claim vector** (per-axis `signal × corroboration` atoms) plus the
**honest phrase** derived from it — not the one-word `verdict`. A skill's scalar verdict must never read
*more favorable* than its own verdict-inert projections (INV-6). tumor-presence enforces this with a
signal-derived tier cap (`reconcile_presence_verdict`, PR #928); other skills adopt the same discipline.

## The `skill_report` object

Every wired skill emits one `skill_report` with these slots (assembled by
`_skills_common/skill_report.py::build_skill_report`):

| Slot | Type | Meaning | Empty-state |
|---|---|---|---|
| `call` | enum \| `null` | the verdict class | gateless → `null` |
| `role` | `gating` \| `descriptive` \| `inert` | how the composer treats the skill | required |
| `polarity` | canonical scale (below) | one normalized direction for the call | descriptive/inert → `not_scored` |
| `honest_phrase` | str | reader-facing one-liner from the signal package | required |
| `confidence` | `{level, basis, coverage}` | weakest-link confidence | required |
| `top_tension` | `{text, source, severity}` \| `null` | the load-bearing caveat | `null` |
| `claim_chips` | list of `{key, label, signal, corroboration, conflict, cites[]}` | the A/B/C/D spine | `[]` |
| `question_table` | list of Q rows | reader Q&A | `[]` |
| `per_phase_metrics` | list of `{metric, value, sample_context, card_id}` | traceable numbers | `[]` |
| `figures` | list of `{slot, kind, path, caption}` | the skill's hero + card plots, made selectable | `[]` |
| `provenance` | `{driving_rule_id, fired_rule_ids, cards_used, cards_missing}` | audit | required |

`build_skill_report` is a thin normalizer: skills already compute `claim_vector`, `key_signals`,
`headline_block` (via `headline_core.build_headline`) and `provenance` — the helper packages them and
stamps `role` + canonical `polarity`. It does **not** recompute or move any verdict.

**Full claim→card traceability (`cites`).** Each chip's `signal`, `corroboration` and `conflict` can
draw on *different* cards — e.g. a presence abundance chip's signal comes from `tumor-rna-distribution`
while its corroboration (the RNA↔protein proxy quality) comes from the concordance card. So every chip
carries `cites`: a **role-tagged list** `[{role: signal|corroboration|conflict, card_id, fields}]`, not
a single card. A claim records a secondary source by setting an atom-level `corr_cite` / `conflict_cite`;
the primary (signal) card is always the atom's `evidence_atom.cite`. No part of a chip is untraceable.

## `role` taxonomy (the genuinely-new slot)

- **`gating`** — the skill's verdict can move the nomination recommendation (member of
  `tp_fanout._SHORT_TO_GATE`: selectivity, dependency, mechanism, genomic_alteration, differentiation,
  tractability_sm, surface_modality, safety). Feeds the deciding-axis / ordinal matrix.
- **`descriptive`** — emits a real, reader-useful read but **no** gate (tumor-presence/expression,
  translational_readiness, target_intrinsic, combination_vulnerability, literature_context). Rendered
  with its `honest_phrase` + metrics; **excluded from gate math**. Replaces today's dropped `—` row so
  a descriptive skill's content is not invisible.
- **`inert`** — emits a verdict-shaped string that is explicitly **not** a call (cis_coherence's
  `expressed_cis_coupled_inert`). Rendered as a view; never scored. Disambiguates it from a `gating`
  call that merely happens to be neutral.

## Canonical polarity vocabulary (single source of truth)

Use `_skills_common/ordinal_view.py` — the one order-preserving scale — everywhere direction is shown:

`killer (−3) · opposing (−1) · neutral (0) · supportive (+2)` + off-scale `insufficient`,
`not_applicable`; plus `not_scored` for `descriptive`/`inert` roles.

Deprecate the ad-hoc dialects: the 3-band headline polarity (`positive/neutral/negative`, which loses
the killer distinction), and question-table verb forms (`supports/opposes`). A `verdict_class →
polarity → phrase` lookup (per skill, co-located with its claims module) maps the skill-local enum to
this scale and a plain-language phrase; chips carry **polarity AND strength decoupled**
(e.g. "opposing · weak").

## Traceability invariants (testable)

From the USP8/NSCLC audit; enforced per skill (presence lands INV-1/2/3/4/6/7/8 in PR #928):

- **INV-1 polarity ceiling** — when a favorable lens (e.g. `*/cell_line`) and a measured tumor-context
  lens disagree, the emitted `call`'s tier ≤ the tumor-context lens's tier.
- **INV-2 bidirectional discordance** — flag lens disagreement in *both* directions, with a `direction`.
- **INV-3 sample-context on every number** — each `per_phase_metrics` entry names its `sample_context`
  and `card_id`; a label may not imply a context the value's card doesn't have.
- **INV-4 denominator = cited field** — a displayed `n=` equals the exact field its `cite` names.
- **INV-6 scalar ≤ projections** — the `call`'s polarity/strength ≤ the peak claim-chip signal.
- **INV-7 phrase ↔ call** — `honest_phrase` polarity agrees with `call` polarity.
- **INV-8 lens-qualified confirmation** — a corroboration state names its lens
  (e.g. `confirmed_cell_line_only` when tumor confirmation is absent).

## Three-level model: `skill_report` → `target_report` → advisory synthesis

The nomination decision is a CROSS-skill claim that no single skill owns. Model it as three layers, each
reading the one below, with authority moving DOWN (deterministic) and readability moving UP (generative):

```
skill_report[]     atomic per-skill signals (the spine)                 [deterministic]
      ↓ deterministic projections (pure functions of skill_report[])
target_report      rollups — OWNS the go/hold/kill decision              [deterministic]
      ↓ reads + narrates (advisory only; does not decide)
llm_synthesis      the story: executive_summary / tensions / arguments   [generative]
```

### `target_report` — the deterministic rollup layer

A per-target sibling to `skill_report`. Its rollups are **projections of the same `skill_report[]`
signals along orthogonal axes** — NOT new opinions. Each is a pure, reproducible function of the
per-skill `polarity`/`confidence`/`top_tension`/`claim_chips`, carries **roll-up provenance** (a rollup
cell links to the contributing skills' `claim_chips` → `cites` → cards), and inherits every invariant
(killer legible, `unmeasured ≠ clean`, scalar ≤ signals) at the rollup level.

| Rollup slot | Projection axis | Aggregates over |
|---|---|---|
| `target_call` `{call: go\|hold\|kill, confidence, basis, deciding_skill, dissent[], unmeasured_gates[]}` | by **gate/axis** | the `gating` skills' polarity/confidence/tension. **NEW** — today this is only LLM prose. |
| `modality_fit` (`modality_fit_by_channel`) | by **modality column** (SM / degrader / ADC / TCE / antibody) | per-skill per-modality signals. **Exists today.** |
| `risk_6dim` (`risk_rollup`) | by **governance category** (biological / druggability / translational / clinical / safety / commercial) | maps each skill's polarity into its category. **Exists today.** |
| `ordinal_matrix`, `deciding_axis` | by gate × modality (display) / necessity-first routing | **Exist today.** |

Most of these ALREADY exist in `nomination.json`; the unification is to (a) add the missing
deterministic `target_call`, (b) wrap them all under `target_report` with uniform slots + roll-up
provenance, and (c) make each read from the `skill_report[]` spine so they cannot drift from the honest
per-skill signals.

**Modality trap (spine-safety):** `modality_fit` must NOT be a naive column-sum of `ordinal_matrix` — a
normal-breadth liability is shared across axes and would be double-counted (the matrix itself is labeled
"NOT SPINE-SAFE"). It is a purpose-built per-channel aggregation, not a matrix reduction.

**Already implemented (migration, not invention):** `target_report.modality_fit` ≡ the existing
`tp_facets._modality_fit_by_channel` (worst-case conjunction per channel over each axis's `modality_scope`
record) + `_modality_conjunction_facet` (presence × surface × window × safety). Like
`subtype_convergence`, migration = re-point it at the `skill_report` spine (feed `modality_scope` from
`claim_chips`), not rebuild.

### Rollup coverage & wiring gaps (as-implemented; 2026-09-02 two-agent audit)

The rollups are the RIGHT shape but UNDER-FED — most gaps are wiring, not missing data. Fix before a
rollup is treated as decision-trustworthy.

`modality_fit` — only **3 of 14** skills emit `modality_scope` (tractability_sm, surface_modality,
safety):
- small_molecule ✅ rich; adc/biologics ✅ (via surface `fit_class`, collapsed).
- **bite_tce effector arm ❌ unwired** — immune-context (CD8) has no `_claim_record` and is absent from
  `_modality_conjunction_facet`; the TCE channel never sees whether the tumor is immune-hot. (top gap)
- **degrader ⚠ paralog-blind** — fed only by `degradation-feasibility` + a safety refinement;
  `paralog-buffering` (the canonical SM-vs-degrader discriminator) is not wired in.
- antibody ⚠ has no dedicated axis (inherits the biologics/surface base).
- scRNA antigen-escape reaches the conjunction facet but NOT the per-channel rollup (the two modality
  views are inconsistent because presence is modality-blind).

`risk_6dim` (`literature-risk-assessment/scripts/risk_rollup.py`) — 4 of 6 under-served, mostly WIRING:
- biological ✅, safety ✅ (richest).
- **druggability — BUG:** the bin lookup omits the strong tractability verdicts (`measured_potent_ligand`,
  `chemically_confirmed_genetic`, `structurally_ligandable`) → they silently default to MED. One-line fix.
- **clinical — unmapped:** the live public AACT `clinical-precedent` card is in the package but the
  `clinical` pseudo-axis has `cards:[]`.
- **commercial — half wiring:** the `competitor-landscape` card is LIVE (Open Targets, CC0) but unmapped;
  only market-size/IP is a genuine data gap (Cortellis/IQVIA unlicensed).
- **translational — mis-mapped:** `AXIS_TO_DIM` maps `differentiation` (not `translational_readiness`) to
  the translational dim, and translational-readiness emits verdict=None; HCMI/genotype-matched/PDXE never
  reach the bin. Larger fix (needs translational-readiness to emit an ordinal or a card-call read).

Quick wins (feed exists, just unmapped): druggability lookup, clinical←clinical-precedent,
commercial←competitor-landscape, TCE←immune-context, degrader←paralog-buffering.

### Literature & 6-dim risk integration (migration — decided 2026-09-03)

Today the 6-dim risk lives in a POST-package bolt-on (`literature-risk-assessment`, the default-on
grounded-substrate chain) that reads the package back in and produces THREE diverging surfaces
(`risk_rollup.json` deterministic, `risk_assessment.json` LLM non-citable, and `tp_render_md`'s hardcoded
table). Root cause: `risk_rollup.deterministic_bins` is a PURE projection of the deterministic spine that
merely lives inside a skill named "literature-risk." This aligns with two existing governance decisions
— `target-contracts/docs/design/RISK_ASSESSMENT_INTEGRATION.md` (literature = context-tier,
`citable_in_nominations:false`, never a gate input) and `RISK_CATEGORY_DASHBOARD_SPINE.md` Decision 3
("a category's risk level is a roll-up of its gates' statuses — computed, not authored").

Migration (each piece re-homed into the three levels):
- **MOVE** `deterministic_bins` + `AXIS_TO_DIM` + `_mod` → `target_report.risk_6dim` (spine projection,
  no network, next to `modality_fit`).
- **ANNOTATE** `ground_axis` literature grounding → an escalate-only corroboration/confidence overlay on
  `skill_report`/claim_chips.
- **ABSORB** the 6-dim LLM `risk_assessment` → advisory `llm_synthesis` (narrates the deterministic dims;
  stays non-citable).
- **DELETE** `tp_render_md._risk_by_category_from_sub_verdicts` → render `target_report.risk_6dim`
  (kills the md↔html divergence).
- **KEEP** pubmed/entity retrieval infra + the standalone `literature-risk-assessment` CLI as a lit-only
  query path.

Decisions (2026-09-03):
1. **Grounding ANNOTATES confidence only — it never moves a `risk_6dim` bin.** `risk_6dim` stays a pure
   deterministic spine projection; the "grounding catches a false-LOW" escalation moves OUT of the bin
   into the claim-chip confidence/contradiction annotation. (Removes today's `project()` escalate-of-bin
   behavior; aligns with "literature never a gate input.")
2. **`risk_6dim` IS citable_in_nominations** — it is deterministic + reproducible (distinct from the
   non-citable literature score), so it may be governance-load-bearing. (target_call remains the sole
   go/hold/kill gate; risk_6dim is a citable governance rollup.)
3. **Keep the standalone CLI** as a lit-only ad-hoc query path even after the pieces re-home.

Sequencing: land the risk-coverage wiring PR (#930) first (fuller deterministic bins → clean DELETE),
then this migration lands in the `target_report` workstream (requires `target_report` to exist).

### Subtype is a CONDITIONING dimension, NOT a peer projection

`modality_fit`/`risk_6dim` are lossless RE-GROUPINGS of the one fixed per-skill signal set. Subtype is
categorically different — it does not re-bucket existing signals, it **re-computes** them: a skill
conditioned on a stratum yields different values (CD274 is flat pooled, strong in MSI-H), so each skill's
signal becomes a VECTOR over strata. Model it in two faces, NOT as a 4th projection:

1. **Scope parameter (primary):** subtype behaves like `indication` — re-run the whole
   `skill_report[] → target_report` CONDITIONED on the subtype (the `--subtypes` path). "Is X a target in
   MSI-H NSCLC?" is a scoped run, one level above the projections: `scope = indication × subtype`.
2. **Within-pooled convergence signal (secondary):** for a pooled-indication question, each skill carries
   a `claim_chips_by_subtype` sub-vector, and `target_report.subtype_convergence` detects the stratum
   MULTIPLE axes agree on (today's `subtype_facet`/`spotlight_subtype`). This is a **cross-axis JOIN**
   (which subset does the case rest on?), deliberately distinct from the independent-bucket rollups —
   NOT a projection of one axis.

   **Already implemented (migration, not invention):** `target_report.subtype_convergence` ≡ the existing
   `subtype_facet.convergent_subtypes` (strata where ≥2 measured axes agree), which the composer already
   builds from the per-skill facets and already feeds to the LLM synthesis prompt
   (`tp_synthesis_prompt.py`). Today it rides the LEGACY synthesis-facet channel, NOT the `skill_report`
   spine — so as skills migrate onto `skill_report`, subtype float-up breaks unless the
   `claim_chips_by_subtype` slot is added. The convergence detection + LLM wiring are done; the migration
   is re-pointing them at the spine.

So: modality and risk are peers; subtype is a scope/conditioning axis whose rollup is a convergence-join.
Treating it as "just a 4th projection" would lose that it re-parameterizes signals and that its rollup is
about AGREEMENT across axes, not slicing one axis.

### `llm_synthesis` — advisory narrative, not the decision

The generative layer narrates the deterministic decision; it does not set it. Rules:
1. **Authority:** `target_call` is the recommendation of record; `llm_synthesis.recommendation` renders
   as `[advisory — does not set the call]`.
2. **Disagreement check:** if the LLM recommendation ≠ `target_call`, the deterministic call wins AND the
   mismatch is surfaced as a target-level tension (cf. presence `contradicts_deterministic`).
3. **Anchored inputs:** the LLM reads the capped verdicts, `honest_phrase`s, ranked tensions and
   `unmeasured`-vs-`clean` distinctions — never raw scalars (the presence fix, applied target-wide).
4. **Traceability:** synthesis `citations{claim → anchors}` resolve into `skill_report` `claim_chips` →
   `cites` → cards, so every sentence traces down like the deterministic layers (`_anchor_validation`
   already guards invented anchors).

Net: the LLM is the only non-deterministic layer, moved from *deciding* to *describing*; everything
decision-bearing (`skill_report` → `target_report`) is deterministic and testable.

## Rendering model (direction — renderer not yet built)

Because every skill emits the same `skill_report` shape, a **report is a declarative selection over those
objects, not bespoke code**. Decide once (the report cards), present many ways. Three independent dials:

1. **Detail level (progressive disclosure)** — each slot belongs to a depth tier; one knob per report:
   - **L0 Headline** — `call` + `honest_phrase` + `polarity` (one line per skill)
   - **L1 Summary** — + `confidence`, `top_tension`, top 2–3 `claim_chips`
   - **L2 Evidence** — + full `claim_chips`, `question_table`, `per_phase_metrics`, key `figures`
   - **L3 Trace** — + `provenance` (rules, cards), all `figures`, raw card summaries
2. **Medium (text ⇄ figure)** — each slot has a text form and, where relevant, a figure form; pick per
   slot: `claim_chips` → sentence or hero chip-strip; `per_phase_metrics` → table or plot;
   `question_table` → Q&A rows or signal bar.
3. **Scope** — which skills, and lead order (`role` distinguishes decision-driving `gating` from context
   `descriptive`; can lead with the deciding axis or the recommendation).

A **report spec** (small, declarative) drives one renderer over `skill_reports`:
```
skills: [all | gating | <list>]
level:  L0 | L1 | L2 | L3        # or per-skill overrides
medium: text | figure | both     # or per-slot
lead:   deciding_axis | recommendation | none
```

Illustration (same USP8 data, two specs):

| | **Exec brief** | **Reviewer dossier** |
|---|---|---|
| spec | `skills: all · level: L0 · medium: text · lead: recommendation` | `skills: gating · level: L2 (deciding axis L3) · medium: both` |
| presence row | "Present, not elevated vs normal (weak)" | full question_table + tumor/cell-line medians + hero figure |
| safety row | "Highly LoF-constrained — full-KO risk" | claim_chips (constraint strong·high, …) + gnomAD figure + rule trace |
| output | one page, no figures | multi-section, figures on, traceable to cards |

The renderer itself (consumes `skill_reports + spec` → md / HTML / slides / JSON) is a **follow-up
workstream** — it pays off once most skills emit `skill_report`. This section fixes the target shape.

## Adoption status

- **tumor-presence** — signal-capped verdict + INV-1/2/3/4/6/7/8 (PR #928). Emits the richest facet.
- **safety** — first `skill_report` pilot (this PR): already had `claim_vector` + `headline_block`;
  now assembled via `build_skill_report` with `role: gating`.
- **remaining skills** — migrate incrementally: wrap the existing `_synthesis_facet` in
  `build_skill_report`, stamp `role`, and add the `verdict_class → polarity → phrase` lookup.
