# Card Architecture Decision — Two Layers, Question-Routed

**Status:** Decided (principle) 2026-07-17. Foundational organizing principle for the
evidence-card layer. Implementation (card reorg) is future, staged work — this record
fixes the *principle* so new data-wiring follows it and the atomic-vs-fused debate is
not re-litigated. Companion to `FRAMEWORK_OVERVIEW.md`, `DATA_CARD_RULE_VERDICT_MAP.md`,
`RISK_ASSESSMENT_INTEGRATION.md`.

Portable GFM (no Mermaid/HTML) per README format rules.

---

## What prompted this

While iterating on the expression/presence cards it became hard to organize the card
set: fused cards felt fragile to revise, new data types ("where does cell-line
proteomics go?") had no obvious home, and it was unclear whether the *right questions*
were being asked. A design panel (biology-first-principles taxonomy, framework-
architecture, subtype/data-completeness) + a git-history archaeology of the one place
the framework already faced "atomize vs fuse" (the 4-cell selectivity card vs the
CRISPR/RNAi split) converged on a single diagnosis and a two-layer principle.

**Diagnosis:** the struggle came from cards trying to do **two jobs at once** — be a
*measurement atom* AND be a *question answer*. Those two jobs want **opposite
organizations**: measurements organize data-source-up (one source → one card);
question-answers organize question-down (one gate → routed evidence). The 37 current
cards are a blurred mix (some clean atoms, some question-answers, some straddling both).

## The decision: two layers, two organizations

**Layer 1 — Evidence (measurement atoms), organized data-source-up.**
A card at this layer answers "what does THIS measurement say about the target." One
data source → one card. It **carries continuous/rich evidence** (log2FC, percentile,
n, effect size, distribution) — NOT only a pre-thresholded category. A category may be
emitted as a convenience, but nothing is *dropped* before the next layer; the value
travels with it. This is where new data scales trivially: a new assay is a new atom,
routed upward — never a reorganization.

**Layer 1b — Derived-comparison cards (a thin, principled exception).**
When *the comparison itself is the scientific question* — "do two orthogonal
measurements agree?" (CRISPR vs RNAi concordance), "how robust is the signal across
comparators?" (the 4-cell selectivity `cells_supporting`) — the comparison cannot be
reconstructed downstream because it requires joint computation on one substrate. These
are `derived_from` composed cards. They are question-defined cards that take atoms as
input. This is the framework's existing, validated pattern (`adc-tce-modality-fit`,
`crispr-rnai-dependency-concordance`).

**Layer 2 — Question (the 8 gates), a consumer-side routing + interpretation.**
Evidence atoms **route many-to-many** to canonical question-gates. One measurement can
feed several gates (population-normal expression feeds BOTH selectivity-window AND
safety-liability — same numbers, different interpretation per gate). Interpretation /
thresholding happens HERE, in the consumer that knows the target-specific question —
NOT baked into the atom. This is where the "don't hard-threshold evidence into
something masked by a target-specific question" requirement is honored.

### The atomize-vs-fuse rule (settled, from both first-principles + git history)
- **Atomize** (one-source-one-card + route to the question layer) when measurements are
  *independent evidence for one question*. The framework did this for CRISPR vs RNAi
  (commit `51ae781`: split into two atomic cards + a derived concordance card).
- **Fuse** (one composed card owns the computation) ONLY when *the cross-comparison is
  itself the deliverable* and requires joint fitting on one substrate. The framework
  did this for the 4-cell selectivity card (commit `ddb6cdc`).
- Test for a straddle to SPLIT: the card emits **multiple independent class fields that
  consumers use separately** — not merely a `question:` sentence containing "and."

## The 8 canonical question-gates (Layer 2 skeleton)

Nomination = a **conjunction of separable necessary conditions**, partially ordered by
presupposition. Track *which* gate fails, not just a score. (Full derivation: design-
panel record; this is the durable scaffold.)

| Gate | Question | Presupposes |
|---|---|---|
| A | **Present** — RNA transcribed / protein made / genomically altered? | — |
| B | **Selective** — window vs normal (adjacent=efficacy; population=safety feed) | A |
| C | **Required** — functional dependency / driver, in which context? | A (+A3) |
| D | **Mechanism** — network position, MoA hook, PD marker | C |
| E | **Druggable** — small-molecule (E1) / surface-biologics (E2), by modality | A2 + D |
| F | **Safe** — germline constraint, normal-tissue liability, scaled by modality | A2/B2 |
| G | **Differentiated** — precedent, co-mutation, biomarker definability | C + E |
| H | **Translational** — models, PD/imaging assays, combination/resistance | A–G |

**Scaffold ≠ scoring.** The gate structure ORGANIZES evidence; it does NOT impose hard
AND-thresholds on the verdict. Real nomination is partly compensatory (a thinner window
tolerated for a stronger dependency), and the deterministic gate stays kill-only +
one-directional (existing design). Conflating "organize by gates" with "score by hard
gates" is the exact hard-thresholding trap this decision avoids: **organize early
(stable), decide late (per-question consumer).**

## Subtype is the finest rung of the SCOPE-OF-COHORT axis (DECIDED 2026-07-17)

Both analyses independently concluded: molecular subtype (MSI/MSS, driver-mutant, etc.)
is an **orthogonal conditioning variable that modifies EVERY gate**, not an 8th gate.
Dependency and selectivity especially must be evaluated *within* strata (pooling hides a
subtype-restricted signal). Which subtype axis is relevant is itself discovered from the
A3/C3/G2 evidence.

**The sharpened structure (after an adversarial pressure-test):** subtype is not a
free-floating axis — it is the **bottom rung of a three-rung scope-of-cohort ladder** the
framework already has, encoded in the existing `tier` field (`card.schema.json`):

| Rung | `tier` | Sample universe | Shipped card |
|---|---|---|---|
| pan-cancer | `target` | all DepMap lineages / all TCGA cohorts | `dependency-lineage-selectivity` (DECOUPLED FROM INDICATION) |
| indication | `indication` | one indication's cohort | `mutation-hotspot-frequency` (whole-cohort) |
| subtype | `subtype` | one stratum within an indication | `subgroup-stratified-*` panorama |

**Ruling — subtype stays a distinct card tier; it is NOT a parameter on an atom.**
A pressure-test rejected the tempting "one atom + a `subgroup_spec` parameter, pooled =
the marginal over strata" reframe on four grounds:
1. **"Pooled = marginal" is false in the shipped code.** The rungs read *different sample
   universes and different substrates*: pooled dependency is **pan-cancer, all-lineage**
   (`read_lineage_selectivity`), while the stratified panorama recomputes **within one
   indication's lineage** — not the same population, and medians do not compose into a
   stratum-weighted mean anyway. Pooled mutation frequency is a *pre-baked aggregate
   parquet* (`read_hotspot_summary`), not the average of per-stratum recomputations. A
   parameterized "pooled mode" would silently disagree with the standalone pooled card
   every non-subtype consumer already reads. (Note the word "pooled" was itself ambiguous:
   the pooled dependency card is *pan-cancer*, the pooled mutation card is *indication-
   level* — two different rungs, not one "pooled" state.)
2. **Card-invariance forbids a shape-toggling parameter.** `same card_id + inputs →
   byte-identical output` is enforced at four independent points (`card.schema.json`, the
   grain-validator, the `card_id`-keyed dispatcher registry, `SUB_SKILL_CARDS`/guard-tests).
   A `subgroup_spec` that toggles scalar↔records output violates it everywhere.
3. **Re-pointing the gate breaks the one-directional safety property.** The shipped subtype
   gate is negative-only, floor-gated, `hold`-not-`veto` by construction. Entangling it with
   the pooled dependency verdict — which *does* `veto` — risks a subtype-restricted negative
   escalating to a blanket veto.
4. **Zero new capability.** The panorama readers already recompute per-stratum and are
   already exposed through cards; the migration would discard the contract/validator/gate/
   registry wrapped around them and rebuild equivalent guarantees at runtime.

**Consequence — the axis lives at Layer 2 (consumer routing), not on the card.** Each rung
stays its own card at its own `tier` (distinct output shapes, distinct dispatchers, static
grain-check intact — no migration of merged code). The consumer that knows the query's
`subgroup_spec` routes **the whole scope ladder** (pan-cancer card + indication card +
subtype panorama) into the relevant gate and foregrounds the queried rung while carrying
the rungs above as context. This is exactly the **context-stacking** synthesis already
locked in the iDAS plan (broader-scope evidence becomes context for the narrower finding;
synthesis reads *up the stack*) — subtype is its bottom rung, not a bolt-on. It is also the
literal "organize early/stable (cards), decide late/per-question (consumer)" principle of
this document.

## How this resolves the three original worries
- **Fused-card fragility on revision** → fusion is now rule-bounded (only when the
  comparison is the deliverable); everything else is atoms + late interpretation, so a
  data revision touches one atom, not a bundle.
- **Data that won't fit** → a new dataset is a measurement atom routed to an existing
  gate; no reorganization. (cell-line proteomics → Present gate, beside RNA distribution.)
- **Right questions / right cards** → the 8-gate skeleton is the stable target; the
  current-card overlay (below) names where today's cards diverge.

## Current-state overlay (where the 37 cards diverge from the skeleton)
From the card→question map (all 37 cards inventoried). Messiest clusters, all
data-source-up artifacts to be re-routed (not urgent; guides the staged reorg):
- **Presence (7 cards, messy):** 3 cards ask different questions of ONE
  `dge-tumor-vs-adjacent` product (fine — routing); presence/selectivity boundary blurred.
- **Safety (3, messy):** `lineage-restriction-evidence` + `normal-tissue-liability` are
  near-duplicate questions on the SAME HPA product → collapse/route.
- **Alteration (6, messy):** co-occurrence signal computed in BOTH
  `mutation-hotspot-frequency` and `co-mutation-and-mutual-exclusivity` → de-dup.
- **8 straddle cards** emit multiple independent class fields (worst:
  `prism-compound-activity` = 3 questions) → candidates to split.
- **Cleanest cluster:** surface/biologics (3 atoms → 2 `derived_from` composed) — the
  reference pattern for the two-layer model done right.
- 4 true `derived_from` cards total; 33 leaf. Only 6 carry `measurement:`, 12 carry `tier:`.

## Open / next threads (NOT decided here)
1. ~~**Subtyping axis**~~ — **DECIDED 2026-07-17** (see "Subtype is the finest rung…"
   above). Subtype stays a distinct `tier: subtype` card, NOT a `subgroup_spec` parameter;
   the scope ladder is assembled by the Layer-2 consumer. The "pooled = marginal" reframe
   was pressure-tested and rejected. No migration of the shipped `subgroup-stratified-*`
   cards / panorama readers / grain-validator.
2. **How far continuous-evidence goes** — light (carry the number, keep categories) vs
   deep (drop the `_verdict` single-string collapse). Deferred.
3. **Staged card reorg** — split real straddles, collapse duplicates, clarify A/B
   boundary. Sequenced after the principle is agreed + subtype axis settled.

## Cross-references
- `FRAMEWORK_OVERVIEW.md` — the four repos, two engines, guard rails, signal grammar.
- `DATA_CARD_RULE_VERDICT_MAP.md` — the current wired data→card→rule→verdict map.
- `RISK_ASSESSMENT_INTEGRATION.md` — literature-in-synthesis-not-gate (same "decide late" spirit).
- `MODALITY_TAXONOMY.md` — the `measurement:` enum (a Layer-1 atom attribute).
