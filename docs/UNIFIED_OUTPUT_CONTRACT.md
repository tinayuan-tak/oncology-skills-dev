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

## Typed surface authority — which surface is authoritative FOR WHICH TYPE

The section above names one authoritative scale for **polarity**. Necessary, but not sufficient: a
composed nomination emits the same axis's "how did it go" judgement on **six** surfaces, and those
surfaces carry **four different types**. Until 2026-09-13 nothing declared which surface owned which
type, so a reader comparing two of them was sometimes checking agreement and sometimes committing a
category error — and the two are indistinguishable in a diff. "These two surfaces differ" is a bug
report only *after* you establish the two are the same type.

| # | Surface | Type | Vocabulary (live) | Authority |
|---|---|---|---|---|
| 1 | `sub_verdicts.<axis>.verdict` | verdict token | **open**, per-resolver (55 live / 66 declared) | **authoritative** |
| 2 | `…skill_reports.<axis>.evidence_graph.verdict.id` | verdict token | same as (1) | derived — must be identical |
| 3 | `target_call.gate_scorecard[].verdict` | verdict token | same as (1) | derived |
| 4 | `skill_reports.<axis>.polarity` | polarity | **closed, 5**: `killer` `opposing` `neutral` `supportive` `not_scored` | **authoritative** |
| 5 | `…evidence_graph.verdict.polarity` | polarity | **closed, 4**: `killer` `opposing` `neutral` `supportive` (+ off-scale `not_applicable`) | derived — lossy only in the off-axis direction |
| 6 | `target_call.gate_scorecard[].status` | polarity | closed, 4: `opposing` `neutral` `supportive` `coverage_gap` | derived — different vocabulary |
| 7 | `target_call.gate.hard_gates[].status` | gate **lifecycle** | closed, 6: `fired` `latent` `suppressed` `reconciled` `excluded` `opposing` | **authoritative** |
| 8 | `target_call.gate.hard_gates[].disposition` | contracts **disposition** | `gated` `excluded_modality_scoped` `contradiction` `uncorroborated` | **target-contracts** owns it (`policy_source: vocab`) |

All figures below are measured over `skills/target-profile/tests/fixtures/polarity_surface_projection.json`
— 37 target×indication pairs (latest-per-pair), 629 axis rows, from live runs under
`~/dev/framework-runs/examples`. Rebuild with `tests/build_polarity_surface_projection.py`.

### Type 1 — verdict token: (1) is authoritative; (2) and (3) MUST be identical

Same type, so equality is meaningful and required. Measured: **337 / 372** rows where both are present
are identical. All **35** violations are on a single axis, `surface_modality` (35 of its 37 rows).

### Type 2 — polarity: (4) and (5) answer DIFFERENT questions about the same axis

The two are not a value and a lossy copy of it. **(4) is the axis's gate contribution** — `not_scored`
when the role is `descriptive`/`inert`. **(5) is the axis's read direction** — always on the measurement
scale, role-blind on purpose, because a descriptive axis still points somewhere and the renderer shows
that. So they are *expected* to differ on off-axis roles, and forcing them equal would blank the
direction badge on hundreds of rows. Where the axis is **`gating`**, both are answering the same
question and must be **identical** — measured 151/151 (per-skill) and 261/261 (composed), with no
exception list.

On the tokens the two vocabularies share, they agree **perfectly — 236 / 236 identical, 0 differ**.
That figure is measured on the frozen projection corpus, whose (5) values **predate** the veto join
below, so it is restricted to the three tokens that corpus observed — not to the four (5) declares. The
distinction is the whole subject of the retired violation below: read it before reusing the number.
Every apparent disagreement is one *named* collapse — plus, formerly, one plumbing gap that had been
documented as a second collapse:

- ~~**refinement loss** — `killer → opposing`, 25 rows.~~ **FIXED. This entry was wrong about its own
  cause, and the wrongness is the lesson.** It read "not wrong, just weaker — a reader that needs the
  killer distinction must read (4), never (5)", justified by (5) having only 3 tokens. Both halves
  were false. `evidence_graph._CANON_POLARITY` has always mapped onto `{supportive, neutral, opposing,
  killer}`; the "3 tokens" figure was what the corpus *contained*, recorded as what the field *admits*.
  And no renderer reads (4) — `report_render` reads (5) for every `_skill_graph_header` — so the
  prescribed mitigation was unavailable to the only consumer there is.

  The actual mechanism: `headline_block.verdict.polarity` is the 3-band `positive/neutral/negative`
  field, and `skill_report._HEADLINE_TO_CANONICAL` floors every negative at `opposing` deliberately,
  because severity needs the driving rule. A skill that knows its call is a veto declares it with
  `build_skill_report(canonical_polarity_override="killer")` — which lands on (4), one key away in the
  same emitted object, and (5) never read it. So a surface-axis **KILL rendered as merely negative**.
  `evidence_graph._verdict_polarity` now performs that sibling join, **escalate-only**: `killer` is the
  least favourable token on the scale, so honouring a declared one can only ever make the surface read
  worse, never better, and it can never blank a badge. Measured on two independent corpora — 2 of 278
  per-skill rows and 25 of 483 composed rows move, every other row byte-identical, and afterwards
  **every gating row agrees exactly across (4) and (5)** (151/151 and 261/261). Guarded live in
  `skills/_skills_common/tests/test_evidence_graph_verdict_polarity.py`; the frozen projection fixture
  cannot observe a producer change, so the population pin stays in the projection test while the
  behaviour is asserted against current code.
- **off-axis collapse** — `not_scored → neutral` (181 rows) and `not_scored → supportive` (**41 rows**:
  `expression` 35, `cis_coherence` 4, `immune_context` 2). `not_scored` is **off-axis** (roles
  `descriptive`/`inert` — see the `role` taxonomy above); the evidence graph has no off-axis value, so
  it places the axis *on* the measurement scale. The 41 `supportive` rows are the harmful direction:
  an axis that was never scored renders as the favourable measured class. Same failure family as
  scoring an unmeasured tier as a low measured one.

  **Deliberately NOT "fixed" alongside the veto join above, and the asymmetry between the two decisions
  is the point.** `killer → opposing` dropped information the producer had already computed, in the
  favourable direction, on the surface the renderer reads — strictly a defect. Writing `not_scored`
  onto (5) would instead put an **off-scale token on the display scale** and blank the direction on
  ~125 of 278 per-skill rows, discarding a real read to make two fields that answer different questions
  look alike. So the 41 harmful rows stay **pinned by count** (they must not grow) while the direction
  itself is retained, and the asymmetry is asserted rather than left to inference — see
  `test_off_axis_roles_keep_their_read_direction_on_the_graph`. The clean fix for the harmful subset is
  a separate `scored` / `gate_bearing` field on the verdict node, which needs a target-contracts schema
  PR first (`$defs.verdict` is `additionalProperties: false`); the value change here needed none,
  because `verdict.polarity` declares no `enum`.

### Type 3 — gate lifecycle: (7) is authoritative and is NOT a polarity

`fired`/`latent`/`suppressed`/`reconciled`/`excluded` describe **where a declared kill-capable row sits
in the gate's lifecycle**, not a direction of evidence. It shares exactly **one** token with the
polarity scale — `opposing` — and that token means different things on the two surfaces: on (7) "this
gate row is the one opposing", on (4)/(6) "this axis's evidence opposes". Do not join on it.

**This vocabulary is CLOSED, and growing it is a fail-open — not a nicety.** `hard_gates[].status` is
the only field of the block that the cross-evidence integrator's fail-closed ceiling switches on
(`cross-evidence-hypothesis/scripts/hypothesis_core.py::_gate_ceiling`), and that switch handles
exactly `{fired, blind, opposing, excluded}` — every other token falls through it with **no signal**,
silently dropping the `advanceable_with_caveat` clamp. So a status token is not a label you may add to
describe a row better; it is a key in a switch whose default case is "no constraint". Any new lifecycle
token lands **in the same PR as the integrator that reads it**, never before.

### Type 4 — disposition: owned by target-contracts, mirrored here

`hard_gates[].disposition` carries `policy_source: vocab`: it is a mirror of
`nomination_verdict_gate.yaml`'s `kill_capable_verdicts[].disposition`. **This repo may not redefine
it**; a new disposition lands in contracts first (skills CI reads contracts `main`). Live distribution:
`latent/contradiction` 301, `latent/excluded_modality_scoped` 233, `latent/gated` 167,
`excluded/gated` 37, `suppressed/gated` 34, `opposing/contradiction` 28, `excluded/excluded_modality_scoped` 26,
`fired/gated` 21, `reconciled/contradiction` 4.

`uncorroborated` joins this vocabulary in `nomination_verdict_gate` **v1.20.0**, for verdicts where the
axis's own arms disagree — `dependency/discordant` (CRISPR vs RNAi) and
`selectivity/discordant_across_comparators` (two comparator arms). Because a disposition is vocab-owned
but a skills-side reader must work on both contracts versions, `tp_gates._load_positive_uncorroborated`
reads the block when present and falls back to a hardcoded **mirror** when it is not. The empty set is
the wrong default: it would silently unblock `strong`, so the fallback is fail-CLOSED and the mirror is
asserted equal to the declaration on every run.

### Incommensurable pairs — declared as such, not as "disagreeing"

Measured token-set intersections:

- `sub_verdict` × `gate_scorecard[].status` = **∅** (55 open tokens vs 4 polarity tokens)
- `sub_verdict` × `skill_report.polarity` = **∅**

A test asserting these agree can only ever fail; a report calling their difference a "disagreement" is
reporting a **type error as a data error**. This is `gap ≠ absent` one level up: "the surfaces are
incommensurable" ≠ "the surfaces disagree".

### Partially-overlapping pairs — where the real bugs hide

Worse than disjoint, because a naive equality check is right most of the time:

- `gate_scorecard[].status` ∩ `skill_report.polarity` = `{neutral, supportive, opposing}`; the
  remainders are disjoint — `{coverage_gap}` vs `{killer, not_scored}`. 3 of 5 tokens shared.
- `hard_gates[].status` ∩ `gate_scorecard[].status` = `{opposing}` — exactly one token, two meanings
  (see Type 3).

### Known violations — ratcheted, not waived

**Retired, and worth reading before adding to this list: `killer → opposing` on (5), 25 rows.** It sat
here as a *benign* refinement loss for the life of the file, and the reason it survived was not that
anyone waived it — it was that its stated cause was wrong (see Type 2). Three habits let that happen,
each of which this list now guards against:

- an **observation about the corpus** (surface (5) held 3 tokens) was written down as a **property of
  the field** — so the entry read as structural. `test_the_graph_polarity_vocabulary_matches_THE_CODE_not_this_corpus`
  now asserts each surface's declared vocabulary against its **producer**, letting the corpus be a
  strict subset;
- the entry prescribed a mitigation — "read (4), never (5)" — **without checking that any reader could
  follow it.** None could: nothing renders (4). Name the actual consumer when you write a mitigation;
- the pin was named for the **outcome** (`KILLER_TO_OPPOSING_ROWS`), so it kept asserting the behaviour
  was intended. It is now `KILLER_SPINE_ROWS` — a population, not a verdict on that population.

A count pinned "both ways" still cannot see a **producer** change if the count is taken over a frozen
snapshot. Pin the population in the projection test; assert the behaviour against live code.

1. **`surface_modality` puts a card field in `verdict.id`** (35 of 37 rows). Its
   `evidence_graph.verdict.id` carries the `adc-tce-modality-fit` card's `summary.fit_class`
   (`both_viable` / `TCE_preferred` / `neither_viable` / `data_unavailable`, produced in
   `_skills_common/_live_readers.py:1722-1759`), while `sub_verdicts.surface_modality.verdict` carries
   the resolver token (`adc_preferred_tce_unsafe` / `tce_unsafe_normal_liability` /
   `pmhc_tce_supported` / `insufficient`). The two vocabularies overlap only on `modality_ambiguous`.
   Note the null tokens differ too — `insufficient` vs `data_unavailable` — so the one row that looks
   like a null-handling disagreement (MUC17/STAD) is really two vocabularies' nulls being compared.
   Either (2) is wrong on this axis or the field is mistyped; **pinned at exactly 1 axis / 35 rows** so
   it cannot spread, and it may not be "fixed" by relaxing the pin.
2. **`not_scored → supportive`, 41 rows** (see Type 2). Pinned at 41 so it cannot grow. Not a plumbing
   gap — the two surfaces answer different questions here — so it is pinned, not joined.
3. **The authoritative polarity has not caught up with the `uncorroborated` relabelling, 6 rows.** On
   `dependency/discordant` the derived scorecard now reads `coverage_gap` while (4) — the
   **authoritative** surface — still reads `opposing`. The derived surface is the more accurate of the
   two here, which inverts the declared authority on exactly those rows. Two facts make this a declared
   residual rather than a half-measure: the authority is **already inconsistent with itself** on the
   identical situation (the same "the arms disagree" verdict reads `opposing` on `dependency` and
   `neutral` on `selectivity` — 6 rows vs 1), and the correct value is `neutral`, an **existing**
   polarity token, so unlike a new lifecycle token no reader can fail open on it. Net accounting for the
   relabelling: it **removes** one pre-existing anomaly (KRAS/COADREAD selectivity, `opposing` scorecard
   against a `neutral` authority) and **adds** these 6. Pinned at `{dependency: opposing ×6,
   selectivity: neutral ×1}`; a fix must update this declaration in the same PR.

   **Where the fix goes — traced, because the obvious answer is wrong.** Not
   `_skills_common/skill_report.py::canonical_polarity`: that helper is correct as written, it floors a
   3-band `negative` to `opposing` and honours an explicit override for any gating role. The asymmetry
   between the two axes is in each skill's **own** 3-band reading, and the two axes reach their answers
   by different routes:
   * `tumor-selectivity` is already right **by fall-through** — `discordant_across_comparators` is in
     neither its positive nor its negative token set, so `_headline_polarity` returns its `neutral`
     default (`skills/tumor-selectivity/scripts/run.py`). Nothing there declares the intent, so a later
     token sweep could sort it into the negative set and silently move the authority.
   * `functional-requirement` is wrong **by declaration** — `discordant` is a member of
     `_DEP_NEG` (`skills/functional-requirement/scripts/run.py:491`), and
     `_dependency_verdict_polarity` (`:1079`, wired at `:1137`) maps that set to `negative`.
   `_DEP_NEG` has **three readers with three different meanings**: `_dependency_strength` (`:518`) reads
   it as a signed **magnitude**, `:648` reads it as an **evidence state** (`measured_negative` — whose
   own comment conflates the two: "measured non-dependence / discordant"), and
   `_dependency_verdict_polarity` reads it as a **polarity**. So the fix is *not* to remove the token
   from the set — that would move all three at once. Only the polarity reader may move; `discordant`
   must return `neutral` there while the set keeps its other two meanings. The set's docstring
   currently justifies the sharing ("so the polarity can't drift from the strength helper"), which is
   exactly the conflation: for a verdict that says *the arms disagree*, magnitude is unknown and
   polarity is neutral — different questions with different answers. Whether `measured_negative` at
   `:648` is also wrong is a **separate** call and must be measured, not assumed. Same family as the
   one-token-two-meanings `display` finding, and the same LABEL-not-DROP discipline as the rest of this
   change, one surface further out.

1 and 2 are pinned by `skills/target-profile/tests/test_surface_authority.py`, 3 by
`test_uncorroborated_not_contradiction.py`. All fail if a violation count **grows** — and equally if it
silently shrinks without the pin being updated, so the corpus can't quietly stop covering it.

### Relabelling a verdict across surfaces: LABEL, never DROP — and the merge order is measured

`uncorroborated` (Type 4, v1.20.0) is the worked example, and the general rule it establishes is that a
verdict whose *classification* moves must keep its *gate effect*. Removing a row from
`positive_contradictions` **relaxes** the `strong` gate — the same fail-open shape as dropping an organ
from a safety denominator. So the strong-block is preserved as `contradictions ∪ uncorroborated` and only
the label moves, **independently per surface, each moving exactly as far as its own readers allow**:

| surface | moves? | why |
|---|---|---|
| tier (`_positive_tier`) | no | blocked on a separate flag with identical effect; the union is unchanged |
| `gate_scorecard[].status` | **yes** → `coverage_gap` | we DID look; the arms disagreed. No corroborated measurement, and no opposing one either |
| `hard_gates[].disposition` | **yes** → `uncorroborated` | vocab-owned, mirrored here |
| `hard_gates[].status` | **no**, holds at `opposing` | closed vocabulary, fail-open switch downstream (see Type 3) |
| `skill_reports[].polarity` | not yet | out of scope; declared as known violation 3 above |

**Merge order — reversed from what it looks like, and measured.** The instinct is "contracts first,
because skills CI reads contracts `main`". For this change that is exactly backwards. Replaying a live
37-pair corpus through the 2×2 of {code before, code after} × {contracts pre-1.20.0, v1.20.0}, three
cells are byte-stable and the fourth is not:

- `before/OLD`, `after/OLD`, `after/NEW` — **0 tier movements**;
- `before/NEW` — contracts v1.20.0 **without** this reader promotes **KRAS/COADREAD `moderate → strong`**
  and turns the 7 affected scorecard rows `neutral`, i.e. a measured negative becomes no signal at all.

The asymmetry is the fallback mirror: it makes the skills side correct on **both** contracts versions,
while the contracts side alone has no reader for the block it just declared. So **skills lands first, or
both together — never contracts first.** Note also that the 2×2 is the point: comparing only along the
contracts axis finds 0 differences *by design* (that is what the mirror is for) and proves nothing.

**Ordered follow-up, not a TODO.** Splitting the `hard_gates[].status` lifecycle token (so an
uncorroborated row is distinguishable from a contradiction on that surface too) lands **with** the
`hypothesis_core._gate_ceiling` change that would read it, in one PR. Until then the guard that holds the
token at `opposing` (`test_hard_gate_lifecycle_holds_at_opposing`) is **dormant on contracts `main`** —
pre-v1.20.0 the disposition still reads `contradiction`, so the branch it protects is unreachable and a
mutation of it reds nothing. It begins biting the moment the contracts change lands. A guard that
protects a future state is worth having; claiming it protects the present one would not be.

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
