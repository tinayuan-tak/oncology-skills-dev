# Per-axis strength + certainty model (design note)

**Status:** DRAFT — **reconciled 2026-08-18** per the certainty-layer design review (multiagent
adversarial pass). Companion to `PER_DIMENSION_EVIDENCE_REPRESENTATION.md`. This revision resolves
the four self-contradictions the review surfaced (unknown_mass definition; corroboration↔verdict
double-count; the "computed generically" over-claim; a spurious 5th field). Two items remain open
for sign-off (§4).

**Decision this note gates:** what `(strength, certainty)` *means* per axis, before we wire it into
the sub-skills (the Phase-3 change). Getting these definitions wrong bakes a bad certainty model
into production, so this is a deliberate, reviewed step — NOT a mechanical port.

**Scope / objective (locked 2026-08-18):** this layer is for **narrative fidelity + analyst
confidence calibration**, and it is **verdict-inert** — it never moves the recommendation, the
nomination gate, or the deterministically-clamped/floored `confidence` tier. It is computed in each
sub-skill's Python **alongside** the verdict, never inside the resolver. Making certainty *cap the
gate* would be a verdict-BEARING change (it would break the byte-stable-spine discipline) and is a
**separate decision, explicitly out of scope here.**

> **Phase context.** Phase 0 (already delivered in `target-profile`) routes the *composed* how-solid
> signal — the `_fragility_facet` (per-axis coverage + call-fragility + blind axes) — into the Tier-3
> synthesis prompt. This note specifies the *per-sub-skill* `(strength, certainty)` sidecar, which is
> **Phase 3**: built axis-by-axis only if the Phase-0/Phase-2 review shows the composed signal is
> insufficient. Dependency is the reference axis.

---

## 1. The model (axis-agnostic frame)

Every axis emits, alongside its categorical verdict, two orthogonal things:

- **strength** — the *signal* axis: *signed graded* magnitude. Sign from the rule-suffix / effect
  direction (`-supportive` = +, `-killer`/`-warning` = −, `-neutral` = 0); magnitude from the axis's
  own numeric provenance (already in each card's `summary`). **Ordinal** (`strong`/`moderate`/`weak`/
  `none`) mapped to a sign — not a continuous score, to avoid false precision. Strength is largely
  recoverable from the verdict word; it is the *lower-value* half and may be deferred.

- **certainty** — the *reliability* axis, **orthogonal to strength**: *how much of the evidence we
  have, and whether independent lines agree.* A structured object with exactly **four** fields:
  - **coverage** — did we measure it, and with what power? (n, data present vs `insufficient`/blind)
  - **corroboration** — do **independent** comparators/assays agree? (see the disjointness rule in §2)
  - **level** = `min(coverage, corroboration)` — **weakest-link**, ordinal `low | medium | high`.
  - **unknown_mass** — an explicit Dempster–Shafer-flavour *ignorance* term (§1.1).

> There is **no fifth `reliability` field.** The reliability axis *is* `certainty`; a separately
> proposed `reliability` scalar was rejected in review as redundant with `certainty.level`.
> (`relevance` is also not here — it lives in the objective spec, §2 of the parent doc.)

**Key rule:** certainty needs **no outcome labels** — it is a property of the evidence, computed from
provenance the methods already emit. It is validated *by construction* (a thin-n axis MUST read low
certainty), not against clinical outcomes.

### 1.1 `unknown_mass` — the one genuinely generic component

`unknown_mass` = **the fraction of the axis's decision-relevant cards that came back
`data_unavailable` / blind this run** (equivalently: fired `*-data-unavailable-*` rules + `_missing`
card flags ÷ decision-relevant cards). It is a *measured coverage-gap fraction*.

This is the corrected definition. The prior draft (and the `functional-requirement` prototype) used a
fixed lookup from `level` (`{high:0.1, medium:0.4, low:0.7}`), which **conflates measured-null with
never-measured** — a well-powered *discordant* call and a *never-measured* axis both landed at 0.7,
violating the MNAR discipline the framework otherwise keeps clean (coverage-gap ≠ measured-negative).
`unknown_mass` (ignorance) must stay **orthogonal to** `corroboration` (disagreement): the first says
*we didn't look*, the second says *we looked and the lines disagree*. Migrate `functional-requirement`
onto this definition (its `decision.json` golden regenerates — reviewed, not spine drift).

`unknown_mass` is the **only** component computable generically (from the fired-rule set + `_missing`
flags every skill already emits). `coverage` and `corroboration` are **not** generic — see §2.

---

## 2. Per-axis definitions (proposals — each is a per-axis expert call)

Drawn from the numeric provenance each card already emits. **These are proposals; each `coverage` /
`corroboration` extractor is a per-axis expert call reading card-specific fields — there is no generic
extractor for them** (the earlier "computed generically" framing was wrong and is retracted).

**The disjointness rule (load-bearing).** `corroboration` MUST be sourced **only from cards/signals
that fire NO verdict-driving rung** for that axis. Otherwise it double-counts the verdict: e.g.
`dependency`'s verdict `concordant_dependent` / `discordant` is *resolved from* the CRISPR↔RNAi
concordance signal, so reusing that same concordance as `corroboration` would count one signal as both
`strength` and `certainty`. A machine-checkable validator MUST assert, per gate,
`corroboration-rule-set ∩ verdict-precedence-rule-ids = ∅` (both are already declarative). **Where an
axis has no verdict-disjoint corroboration source, it emits `coverage` + `unknown_mass` only and does
not claim `corroboration`** (a single-comparator axis reads its corroboration as `unmeasured`, which
raises `unknown_mass` — never a fabricated `medium`).

| Axis | strength from | certainty: coverage | certainty: corroboration (**must be verdict-disjoint**) |
|---|---|---|---|
| **dependency** | fraction_strongly_dependent, median_chronos, dependency_class | n_cell_lines_evaluated (power) | **Broad↔Sanger cross-consortium replication** (the `cross-consortium-dependency` card, already verdict-inert). **NOT** CRISPR↔RNAi concordance — that resolves the verdict. |
| **genomic_alteration** | recurrence/frequency, alteration_role | cohort n; GENIE panel-intersect coverage | agreement across cohorts (MC3 + GENIE), if not already a verdict rung |
| **selectivity** | max_abs_log2fc (A/C cells) | cells_ran (# comparators) | cells_supporting / cells_ran; purity-confound (verdict-disjoint) |
| **tumor-presence / expression** | median TPM percentile, fraction_expressed | n samples | RNA↔protein concordance (`rna-protein-concordance*` — verdict-inert) |
| **safety** | LoF-constraint magnitude (LOEUF), # human-genetics legs | gnomAD data present vs indeterminate | # of independent human-genetics legs *agreeing* beyond the one that set the verdict |
| **tractability_sm** | pocket ligandability, PRISM activity | PDB/AlphaFold structure coverage | **unmeasured** — no verdict-disjoint source (PRISM↔CRISPR concordance card DRIVES the e7 verdict; ~~corrected 2026-08-24, was "PRISM↔CRISPR concordance"~~) |
| **surface_modality** | density level, topology favorability | density_evidence_level (A–E) | **protein-surface-evidence** (CSPA wet-lab surfaceome MS — independent surface-residency line, verdict-inert; ~~corrected 2026-08-24, was "topology × family agreement" which is INTERNAL to the fit_class verdict~~) |
| **mechanism** | MoA-class specificity | SIGNOR edge count | source breadth (SIGNOR/CollecTRI/Reactome agreement) |
| **differentiation** | co-mutation / ME effect (q-value) | cohort n | `pooled_eligible` (panel-intersect) |

**Worked example — dependency (the reference axis):**
- strength: `strongly_dependent` (frac_strong ≥ ~0.5) → strong+; `lineage_selective` → moderate+;
  `non_dependent` → strong−; scaled by median Chronos.
- coverage: n_cell_lines ≥ 20 → high; 5–20 → medium; < 5 → low (mirrors the existing power floor).
- corroboration: **Broad↔Sanger cross-consortium** replication `replicated` → high; single-consortium
  → medium; `discordant-across-consortia` → low. (This is verdict-disjoint; the CRISPR↔RNAi
  concordance stays where it belongs — driving the verdict.)
- level = min(coverage, corroboration); `unknown_mass` = fraction of dependency cards unavailable
  this run (§1.1), independent of the above.

---

## 3. Where it's computed + emitted (and what it must NOT touch)

Certainty is computed in **each sub-skill's Python**, verdict-inert, reading the card `summary`
provenance — the same pattern `functional-requirement` already uses for `dependency_confidence` /
`strength_certainty`. It is emitted **beside** the verdict (a sidecar keyed by sub-skill short in the
`target-profile` fan-out; **NOT** in `GateVerdict.as_dict()`, **NOT** in `nomination.json`
`sub_verdicts`, **NOT** in any shared carrier — those are byte-golden). The resolver is **not**
touched: its grammar is deliberately non-Turing-complete (no arithmetic), and certainty is arithmetic,
so it stays in Python. The grounded context/risk agent *anchors to* the verdict and *reads* certainty;
it does not compute it.

**Required validators (machine-checkable, per gate):**
1. `corroboration-rule-set ∩ verdict-precedence-rule-ids = ∅` (the §2 disjointness rule). **IMPLEMENTED
   (2026-08-20, R3):** `validators/validate_certainty_disjointness.py`, wired in `contracts-validate` CI.
   Corroboration sources are declared per gate in `vocabularies/certainty_corroboration.yaml`; the
   validator maps each gate's resolver rungs → rule_ids → `when.card_id` to get the verdict-precedence
   card-set and asserts the intersection is empty. (Follow-on: have the Python certainty extractors
   CONSUME that manifest so it is authoritative rather than parallel.)
2. Each verdict-bearing skill ships a `verdict → strength` map total over its full verdict enum.
3. `CERTAINTY_MODEL.md` exists at the path the code's `_model_ref` names (currently
   `CERTAINTY_MODEL.md#dependency`) — a dangling pointer must fail CI.

---

## 4. Open questions for sign-off

Resolved in this revision: ordinal (not continuous); `unknown_mass` definition (§1.1); the 5th-field
question (there is no 5th field); corroboration must be verdict-disjoint (§2); dependency corroboration
re-sourced to Broad↔Sanger. **Still open:**

1. **Per-axis threshold ownership.** The n / effect-size / concordance cutoffs for the **8
   non-dependency axes** (the table's right-hand columns) need per-axis calibration owners. Until
   assigned, those extractors are unvalidated placeholders and MUST NOT be wired.
2. **`unknown_mass` exposure.** Surface it in the panel as an interval/band, or only as the ordinal
   `level` + a numeric `unknown_mass`? (Recommend: ordinal `level` in the headline, numeric
   `unknown_mass` in the detail.)

---

## 5. Reference-implementation plan (Phase 3, conditional)

Gated behind the Phase-0/Phase-2 review (see the Phase context box). If built:
1. Wire `dependency` (this note's worked example) in its **sub-skill Python** → emit
   `{strength, certainty{level, coverage, corroboration, unknown_mass}, provenance}` beside the
   verdict, sidecar-keyed in the `target-profile` fan-out.
2. Validate *by construction*: a low-n or cross-consortium-discordant dependency MUST read low
   certainty; a well-powered, cross-consortium-replicated one high. (No outcome labels involved.)
3. Add the §3 validators; migrate `functional-requirement`'s `unknown_mass` onto the §1.1 definition.
4. Fan out axis-by-axis using the table, **path-A (resolver) skills only**, each as its own reviewed
   change, and only to axes whose threshold owners (§4.1) have signed off. Path-B/B′ (inline-verdict)
   and the gateless descriptive skills are deferred; the signed `strength` axis is deferred
   indefinitely (low value; recoverable from the verdict word).
