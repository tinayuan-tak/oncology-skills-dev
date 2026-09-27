# Evidence-property architecture — L1→L4 (governing schematic)

**Status:** the governing architecture for the evidence-property layering effort (#1507) — the target the
build works toward. It is the concrete, refined (2026-09-27) **subskill-as-evidence-domain** model; keep
it in front of the team and do not re-derive it.

**Directive (non-negotiable):** the layers produce **framings/perspectives and a traceable synthesis**,
NOT a flat verdict token. The flat verdict is the misguided, too-broad abstraction and must dictate
nothing about how the layers are built. **Verdict impact is NOT a decision input for this effort** — do
not scope, prioritize, gate, or accept/reject any layer, property, resolver, or view by whether it moves
a verdict, and do not run "does this change the verdict?" as a decision probe. "verdict-inert" is not a
limitation here — it is the point; a layer matters by the perspective it opens and by whether its data
is accurate and fully used, never by verdict movement.
Companion contracts: `docs/EVIDENCE_PROPERTY_ENVELOPE_v0.md` (L2b envelope, #1629),
`docs/PROPERTY_MAPPING_COVERAGE_INVENTORY_2026-09-25.md` (property islands / the F inventory),
the #1630 promotion taxonomy.

---

## Organizing principle: the subskill is the evidence-domain boundary; the card is the source/readout unit

The subskill is the **natural evidence-domain boundary**. The cards inside it are the **source/readout
units** that generate L1. The subskill is then allowed to resolve those card outputs **upward** into
L2a and selected L2b property claims **within its biological domain**.

> Cards primarily generate L1. The subskill resolves card outputs upward into L2a and selected L2b
> property claims within its biological domain.

```text
TARGET PROFILE
│
├── SUBSKILL: tumor-presence
│    ├── Card 01: TCGA tumor RNA      ├── Card 05: scRNA tumor cells
│    ├── Card 02: adjacent normal RNA ├── Card 06: scRNA normal cells
│    ├── Card 03: GTEx RNA            ├── Card 07: CPTAC protein
│    ├── Card 04: DepMap RNA          ├── Card 08: HPA IHC   └── …17 cards
├── SUBSKILL: dependency
├── SUBSKILL: alterations
├── SUBSKILL: safety
├── SUBSKILL: tractability
└── …
```

## Inside a subskill (worked example: tumor-presence)

```text
                    TUMOR-PRESENCE SUBSKILL

        CARD A          CARD B          CARD C          CARD D
       TCGA RNA        DepMap RNA       scRNA          CPTAC
          │               │              │               │
          ▼               ▼              ▼               ▼
   ───────────────────── L1 ───────────────────────────────
          measurements / emitted card fields
     median TPM      frac high       malignant frac    protein abundance
     prevalence      frac off        cell coverage     tumor:normal FC
     distribution    bimodality      heterogeneity     etc.
          │               │              │               │
          ▼               ▼              ▼               ▼
   ───────────────────── L2a ──────────────────────────────
           source-level observational properties
     patient tumor     model expr.      malignant-cell    tumor protein
     abundance         structure        coverage          abundance
     patient prev.     subset-high      heterogeneity     protein support
          │               │              │               │
          └───────────────┼──────────────┼───────────────┘
                          ▼
   ───────────────────── L2b ──────────────────────────────
       purpose-built integrated properties / "islands"
                 tumor_abundance_concordance
                 tumor_coverage_concordance
                 tumor_presence_concordance
                 tumor_normal_selectivity
                 protein_support / etc.
```

## The card is NOT the unit that must be architecturally "clean" — cards emit ingredients

A correction to earlier language. A card legitimately emits **many L1 fields** (median, mean, percentile,
fraction_high, fraction_off, distribution_pattern, sample_count, power flag, …). You do **not** turn every
one into a property. Most emitted fields **were never supposed to be properties** — they are ingredients.

```text
many L1 card fields
        ↓
small number of biologically meaningful L2a properties
        ↓
even smaller number of L2b integrated properties
```

Compression pyramid (illustrative numbers; **the shape is what matters**):

```text
17 cards  →  ~100+ L1 measurements/readouts  →  ~10–20 L2a source properties  →  ~3–6 L2b integrated claims
```

This directly explains the F result: only ~20% of emitted fields cleanly looked like shared properties
because most emitted fields were never meant to be properties in the first place. Fields are the wrong
fleet-wide unit; **property islands + the small common envelope** is the forward architecture.

## Card field disposition: retention ≠ exposure ≠ recovery (the new card contract)

The old `field_disposition` roles (`signal / context / display`) conflated two independent questions and
tied a field's survival to whether it moved the verdict. Rework the **role of these gates, don't remove
them**. Under the new architecture:

> **`signal` no longer means "allowed to influence the verdict." It means "carries biological information
> that may participate in interpretation."** But do **not** pass all L1 fields forward indiscriminately
> (that undoes the compression), and do **not** let the old `signal/context/display` label decide what
> survives.

**Separate the two questions the old role conflated:**

1. **What IS this field?** (semantic role) — `measurement · derived_measurement · quality · provenance ·
   context · identifier · presentation`
2. **Where may it FLOW?** (interpretation reach) — `property_input · qualifier · recoverable_only ·
   presentation_only`

A field carries **both** axes, e.g. for EPCAM:

| Field | Semantic role | Reach |
|---|---|---|
| `fraction_high=.435` | measurement | property_input |
| `fraction_off=.37` | measurement | property_input |
| `distribution_pattern=bimodal` | derived_measurement | property_input |
| `median_tpm=2.51` | measurement | property_input |
| `n_models=46` | quality | qualifier |
| `dataset=DepMap` | provenance | qualifier |
| `expression_class=broadly_moderate` | local_composite | recoverable_only / legacy |
| `"43.5% high"` | presentation | presentation_only |

### The critical rule: retention broad · exposure narrow · recovery broad
Do **not confuse retention with exposure.**
- **Retention (broad):** keep essentially all scientifically meaningful L1 outputs. `median_tpm` does not
  disappear just because the resolver primarily consumes `fraction_high / fraction_off / distribution_pattern`.
- **Default downstream exposure (narrow):** L2 resolvers consume **explicitly declared** fields; L3
  receives **L2 claims + their relevant retained quantitative attributes**, NOT the whole L1 payload.
- **Drill-down / recovery (broad):** L3/L4 or a scientist can always trace back to the complete L1 evidence.

```text
             ALL MEANINGFUL L1  ── retained / traceable ──┐
                     │                                    │
        ┌────────────┴────────────┐                       │
   declared resolver inputs   other L1 fields             │
        │                                                 │
        ▼                                                 │
       L2  ───────────────── recoverability ──────────────┘
```

### The one class NOT propagated: pure presentation / serialization artifacts
`display_order · formatted_string · chart_title · CSS class · tooltip_text`, and **duplicate
representations** (`fraction_high_display="43.5%"` when `fraction_high=0.435` exists — only the canonical
numeric flows). Distinguish **"scientifically meaningful but currently unused → retain"** from **"pure
presentation/serialization artifact → don't propagate into evidence."** This is safer than old
`display` vs `signal`, because some old `display` fields carry real biology (EPCAM's `distribution_pattern`).

### The new card contract
```text
CARD OUTPUT
├── EVIDENCE PAYLOAD    measurements · derived measurements · quality/power · context/grain · provenance
├── LOCAL INTERPRETATION local composites (where useful)
└── PRESENTATION        formatting / display only
        +
DECLARED CONSUMPTION    "L2 resolver X reads: measurement A, measurement B, derived C, qualifier D"
```

### Two invariants (both, or you get one of two failure modes)
> **Recoverability guarantee:** no scientifically meaningful L1 field may become inaccessible merely
> because it is not currently consumed by an L2 resolver. *(prevents: rich data silently deleted)*
>
> **Reach guarantee:** every L1 field consumed by an L2 resolver must have an explicit declared
> consumption edge. *(prevents: hidden classifier dependency)*

### The old roles become migration metadata (do not delete yet)
Keep the old label as `legacy_role` and add the new axes + `consumed_by`; then run a migration audit over
four cases:

| Old role | New status | Meaning |
|---|---|---|
| signal | L2 input | expected / healthy |
| **display** | **L2 input** | **⚠️ old architecture was UNDER-consuming evidence** (EPCAM `distribution_pattern`) |
| **signal** | **not used by L2** | **⚠️ new resolver missing evidence, or old classifier used it unnecessarily** |
| display | not used by L2 | probably fine; remains recoverable |

### Retire `signal` as a label eventually — the consumption graph defines it
`signal` is overloaded (measurement→L2 property signal; L2 claim→L3d domain signal; L2 claim→ADC-frame
signal; L3→L4 synthesis signal). Move toward explicit relationships and let **the graph of consumption
be the definition of signal** (consistent with the existing reach concept):

```yaml
field:
  id: fraction_high
  type: measurement
  consumed_by: [{resolver: expression_population_structure_v1}]
  qualifies: [{property: tumor_coverage}]
  retained: true
```

**Net rule:** do NOT pass all old `signal` fields automatically, nor restrict downstream evidence to old
`signal` fields. Reclassify card output semantically, retain all meaningful scientific L1 evidence, and
let explicit resolver-consumption edges determine what is promoted into L2. *(This means the Track-A
`field_disposition.yaml` ledgers being authored now become the `legacy_role` migration baseline — not
wasted, but not the survival determinant.)*

## Layer semantics (crisp definitions — keep these stable)

> **L1** = what a card measured/computed: reproducible, source-specific readouts (the ingredients).
>
> **L2a** = a property resolved from **one** evidence source / analysis grain (deterministic resolver;
> raw quantitative anchors retained; provenance + quality + dependence metadata).
>
> **L2b** = a reproducible integrated property resolved from **multiple** evidence sources
> (deterministic integration, concordance + corroboration + uncertainty, no LLM authorship, conforms to
> `EVIDENCE_PROPERTY_ENVELOPE_v0`).
>
> **L3d** (domain interpretation) = the coherent biological story **within one evidence domain**, packaging
> its L2 properties into something human- and LLM-usable. Stays inside the subskill's semantic scope;
> traceable back to L2 claim IDs. Answers: *what is the coherent biological story within this domain?*
>
> **L3f** (decision frame) = a cross-subskill, explicit, versioned lens (ADC / TCE / 5R / biomarker /
> nomination). Answers: *what does that story imply for a specific development decision?*

**Two kinds of L3, kept distinct (do not overload "L3").** `L3d` is domain interpretation and lives
**inside** the subskill; `L3f` is decision framing and lives **across** subskills. Governance rule:

> **A subskill's L3 (L3d) may interpret its own domain; it may NOT make conclusions that require evidence
> owned by other domains.** That reserves cross-domain implication for `L3f` and prevents cross-skill
> leakage while still capturing the value of local synthesis.

**L3d is a useful domain synthesis, NOT a lossy gateway.** Do not force `L3d → L3f` as the only path — it
over-compresses. **L3f reads the canonical L2 claims directly** (e.g. the ADC frame consumes
`tumor_coverage` itself, not whatever the L3d prose chose to emphasize) **AND** uses L3d as an additional
domain interpretation. Frames consume **L2 + L3d**; that protects fidelity.

**L2b means cross-SOURCE integration, not necessarily cross-SUBSKILL.** Whether the integrated sources
happen to live in one subskill (tumor-presence already spans TCGA / GTEx / DepMap / single-cell / CPTAC /
HPA) or several is an implementation detail. So `tumor_abundance_concordance` is L2b even though it is
produced entirely inside one subskill. This keeps the layer model stable.

**Local composites** stay inside the subskill (e.g. `mutation_landscape_class`,
`combination_opportunity_class`, `surface_confirmation_state`). They do not have to become L2 properties
or disappear — they are carried with their epistemic type declared.

## The subskill as a bounded biological evidence package

A subskill answers a bounded biological evidence question — e.g. *"What evidence supports tumor presence
and expression of this target in this indication?"* Its responsibilities:

```text
CARDS      collect & calculate evidence          → L1
RESOLVERS  translate measurements into bounded    → L2a
           biological properties
INTEGRATORS reconcile properties across sources    → L2b
```

It emits an **evidence package**, not a pile of card outputs — retaining all card-level detail while
giving downstream reasoning a small, biologically organized interface:

```yaml
tumor_presence:
  cards:
    …17 card outputs…               # L1, retained in full
  source_properties:                 # L2a
    patient_tumor_abundance: …
    model_expression_structure: …
    malignant_cell_coverage: …
    tumor_protein_abundance: …
    tumor_normal_selectivity: …
  integrated_properties:             # L2b — the property islands
    tumor_abundance_concordance: …
    tumor_coverage_concordance: …
    tumor_presence_concordance: …
  local_composites:                  # carried, epistemic type declared
    …
```

## The subskill boundary — where L3 begins

A subskill may conclude domain-scoped biological facts:

- "Tumor expression is strongly supported across patient RNA and protein data."
- "Expression is heterogeneous / subset-high across relevant sources."
- "Patient and model expression are discordant."

It should generally **not** conclude "this is a strong ADC target" — that crosses out of the
tumor-presence evidence domain. ADC fit requires other subskills (surface biology, normal safety,
internalization, antigen density, functional biology, …). **That cross-domain interpretation is where
L3 begins.**

Property islands are therefore most naturally **subskill-level outputs** — each domain earns a handful:

```text
tumor-presence : tumor abundance · tumor coverage · heterogeneity · tumor-normal selectivity · protein support
dependency     : essentiality · dependency prevalence · dependency selectivity · context specificity
safety         : normal-tissue liability · critical-cell liability · genetic tolerance
alterations    : mutation recurrence · CNA recurrence · biallelic loss · functional alteration direction
```

No global ontology is required for every card field — each subskill develops well-earned islands within
its domain.

## Across subskills — the full stack

```text
                              TARGET × INDICATION
         ┌────────────────────────────┼─────────────────────────────┐
         ▼                            ▼                             ▼
  TUMOR-PRESENCE                 DEPENDENCY                    SAFETY
     SUBSKILL                     SUBSKILL                    SUBSKILL
   ┌─────┴─────┐                ┌─────┴─────┐                 ┌─────┴─────┐
   │ 17 cards  │                │ N cards   │                 │ N cards   │
   └─────┬─────┘                └─────┬─────┘                 └─────┬─────┘
         ▼                            ▼                             ▼
       L1  measurements            L1                            L1
         ▼                            ▼                             ▼
       L2a source properties       L2a                           L2a
         ▼                            ▼                             ▼
       L2b tumor-presence          L2b dependency                L2b safety-liability
           property islands            properties                    properties
         ▼                            ▼                             ▼
       L3d domain interpretation   L3d "dependency story"        L3d "safety story"
           "expression biology story"
         └────────────────────────────┼─────────────────────────────┘
                          EXPORTED EVIDENCE PACKAGE (L2 + L3d)
                                      ▼
                          TYPED EVIDENCE INTERFACE
             ┌────────────────────────┼────────────────────────┐
             ▼                        ▼                        ▼
       L2 PROJECTIONS            L3f DECISION FRAMES    other consumers
       (verdict-inert views)     (cross-subskill lenses)
       dashboard                 ADC fit · TCE fit
       evidence graph            5R / Right-{Target,Tissue,Safety,Patient,Drug}
       question views            biomarker / translational readiness
       property × source         target nomination · evidence sufficiency
                                      │
                                      ▼
                                 L4 SYNTHESIS
                            target thesis · opportunity drivers · liabilities &
                            contradictions · modality implications · critical
                            unknowns · next evidence · decision state (tip only)
```

`L3` frames are **explicit, versioned lenses** (perspectives), not verdict engines. `L4` is where the
framework stops being "organized evidence" and becomes directly useful to a decision — as a **structured,
traceable synthesis**, never a black-box "good/bad" token.

## L4 — integrated synthesis (the decision-facing layer)

> **L4 is not another evidence layer. It is the decision-facing synthesis layer that integrates domain
> interpretations (L3d) and decision frames (L3f) into a coherent target/program story.**

Where L3 asks "what does this evidence mean within tumor presence / for ADC fit / for Right Safety?",
L4 asks: *taken together, what should a scientist understand about this target in this indication, what
are the major opportunities and liabilities, what remains unresolved, and what evidence would most
change the decision?* It consumes **multiple L3 outputs plus selected L2 claims where necessary**:

```text
tumor-presence L3d ─┐
dependency L3d ─────┤
safety L3d ─────────┤
alterations L3d ────┼──► L4 TARGET SYNTHESIS
ADC frame (L3f) ────┤
TCE frame (L3f) ────┤
5R frames (L3f) ────┤
biomarker frame ────┘
```

### The six core L4 products

1. **Core target thesis** — the most defensible biological rationale, *integrated across domains* (not a
   tumor-presence summary): e.g. "EPCAM is a strongly supported epithelial surface antigen in CRC … the
   opportunity is defined by antigen targeting rather than tumor-cell dependency."
2. **Opportunity drivers** — the claims that make the target interesting; each **cites** its L2/L3 claim.
3. **Liabilities AND contradictions** — keep **contradictions distinct from weaknesses**: "TCGA says
   broad-high / DepMap says subset-high" is an *evidence relationship worth understanding*, not a low score.
4. **Modality-specific implications** — capture **why different modalities see the same biology differently**
   (per modality: opportunity · liability · critical unknown), not a scalar `ADC fit = moderate`.
5. **Critical unknowns** — a **first-class product**, not an appendix. Distinguish
   `KNOWN | UNKNOWN | CONTRADICTED | NOT_ASSESSED`, and **decision-critical** unknowns from low-priority
   gaps (`question · affects[frames] · decision_importance · current_status`).
6. **Next evidence / value-of-information** — what additional evidence would most change or resolve the
   assessment (this is where L4 becomes more than reporting).

### Not a single target score
`Right Target 3/5 · Right Safety 2/5 · ADC 3/5 · Overall 2.7/5` throws away the value built. Two targets
with identical averages can be different propositions ("strong driver biology / weak tractability" vs
"weak driver biology / excellent surface opportunity"). L4 preserves that by naming the **dominant
interpretation** and a **target archetype** (driver-dependent · lineage-marker · surface-antigen
opportunity · synthetic-lethal · biomarker-defined · pathway-node · immune-context) — *what kind of
opportunity is this*, not merely *how good*. A `decision_state` may exist but is the **tip of the
iceberg, not the main output**.

### Organize by decision tension
Beyond +/− lists, L4 surfaces the major **tensions** (strong abundance VS normal expression · high-
expression subset VS negative population · strong presence VS weak dependency · many datasets VS
patient/model disagreement). The tensions often carry more insight than any verdict — they show where
the biology gets interesting.

### L4a / L4b — synthesis vs decision state by stage
- **L4a — scientific synthesis:** what does all the biology say? (stage-independent)
- **L4b — decision state:** given the current **decision stage**, what is the state of the program? The
  same science supports different calls by stage (early discovery → "proceed to characterize"; candidate
  nomination → "insufficient evidence"). Decision stage should be explicit.

### L4 object (shape)

```yaml
target_synthesis:
  target: EPCAM
  indication: CRC
  archetype: surface-antigen-opportunity
  thesis:                              # L4a
    state: supported_with_caveats
    narrative: >
      Credible CRC surface-targeting opportunity driven by strong tumor antigen presence rather than
      tumor dependency; key constraints are heterogeneous coverage and normal epithelial expression.
    supported_by: [tumor_abundance_concordance, tumor_coverage_concordance, normal_liability_concordance]
  opportunity_drivers:
    - {claim: patient_tumor_abundance, note: strong patient tumor abundance}
    - {claim: protein_support, note: orthogonal protein-level corroboration}
  liabilities:
    - {claim: normal_liability_concordance, note: normal epithelial expression}
  contradictions:
    - {between: [tcga_broad_high, depmap_subset_high], note: patient vs model expression structure}
  modality_implications:
    adc: {opportunity: surface abundance in a tumor subset, liability: incomplete coverage + normal expr,
          critical_unknown: quantitative density / internalization}
    tce: {opportunity: surface target present, liability: normal expression more consequential,
          critical_unknown: tumor-normal density separation}
    small_molecule: {opportunity: little from expression alone, critical_evidence: functional dependency / tractability}
  critical_unknowns:
    - {question: Does EPCAM achieve adequate surface density in CRC tumors?, affects: [adc_fit, tce_fit],
       decision_importance: high, current_status: unresolved}
  next_evidence:
    - {evidence: quantitative patient-level surface density, resolves: [adc_fit, tce_fit]}
    - {evidence: single-cell malignant-cell coverage, resolves: [escape_risk]}
    - {evidence: normal GI epithelial density, resolves: [therapeutic_window]}
  decision_dimensions:                 # 5R as FACETS of the one synthesis (not a separate system)
    right_target: strong antigen biology; weak dependency not central to mechanism
    right_tissue: strong CRC presence but heterogeneous tumor coverage
    right_safety: normal epithelial expression is a major unresolved liability
    right_patient: EPCAM-high population may provide a selection strategy
    right_drug: surface-directed modalities plausible; density/internalization remain critical
  readiness: not_ready_for_modality_nomination
  decision_state:                      # L4b — tip of the iceberg only
    stage: candidate_nomination
    status: evidence_incomplete
    rationale: quantitative density and therapeutic-window evidence unresolved
```

L4 is best represented internally as **facets** (thesis · opportunity_drivers · liabilities ·
contradictions · critical_unknowns · next_evidence · modality_implications · decision_dimensions[5R] ·
readiness), **not hard-coded around either 5R or modality** — so the presentation layer can render many
decision views over one synthesis object.

### What L4 must NOT do
Invent new measurements · silently resolve contradictory evidence · treat missing evidence as negative
evidence · launder L3 judgment into an L2 "fact" · hide critical unknowns behind a positive narrative ·
produce unsupported causal explanations · collapse everything into one universal score.

### L4 must always be reconstructable downward
Every L4 statement drills back to its basis:

```text
"Normal-tissue liability is the dominant ADC risk"
   ↓ ADC frame (L3f)
   ↓ normal_liability L2b claim
   ↓ GTEx + scRNA + IHC evidence (L2a)
   ↓ L1 measurements
```

**The philosophical line:** *L3 interprets evidence through bounded lenses; L4 reconciles those lenses
into a coherent, decision-facing scientific argument* — the transition from **data → evidence → insight
→ actionability**.

## Where the views sit — two families

**Evidence views — INERT** (answer: *what evidence do we have?*)
```text
property × source matrix · evidence graph · question table · per-target dashboard ·
cross-target atlas · claim/provenance drill-down
```

**Decision views — INTERPRETIVE** (expose L3/L4; answer: *what does the evidence mean for this decision?*)
```text
target × modality · target × 5R/risk dimension · opportunity/liability summary ·
critical-unknowns view · next-evidence view · target nomination summary · program readiness view
```

Keep this distinction both **visually and architecturally**.

### Frame on the way in, view on the way out (the dual role of 5R / modality)

5R and modality play **two roles, and that is not a contradiction**:

> **At L3f they are FRAMES** — reasoning operations that *create* contextual interpretation ("what does
> the evidence imply for ADC?"; antigen density means something different to ADC vs TCE, so the lens must
> operate at L3). **At L4 they are VIEWS** — presentation/organization of the *already-synthesized*
> target story ("show me the synthesis from the ADC perspective"). **Frame on the way in, view on the way out.**

```text
                  L2 EVIDENCE (+ L3d)
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
       ADC L3f       TCE L3f       5R L3f          ← frames CREATE interpretation
        frame         frame        frames
          └─────────────┼─────────────┘
                        ▼
                   L4 SYNTHESIS                     ← one facet-based synthesis object
                        │
          ┌─────────────┼─────────────┐
          ▼             ▼             ▼
       5R view    Modality view   Risk view         ← views REORGANIZE the same synthesis
```

Because L4 is facet-based, **one synthesis object renders many decision views** — no three independent
synthesis systems:

```text
L4 TARGET SYNTHESIS  →  Executive target profile · 5R view · Modality view · Biological-risk view ·
                        Evidence-gap view · Target-nomination view · Portfolio-comparison view
```

**Same evidence, same integrated understanding, different decision-facing organization.** For EPCAM × CRC:

*5R view* — Right Target: strong antigen biology, weak dependency not central · Right Tissue: strong CRC
presence but heterogeneous coverage · Right Safety: normal epithelial expression a major unresolved
liability · Right Patient: EPCAM-high population as a selection strategy · Right Drug: surface-directed
modalities plausible, density/internalization critical.

*Modality view* — ADC: {opp strong surface subset · liab heterogeneity + normal expr · unknown density +
internalization} · TCE: {opp antigen-positive population · liab normal expr more consequential · unknown
tumor-normal density separation} · SM: {opp limited from expression · unknown functional/tractability}.

## The per-subskill design rule (apply to every subskill)

1. **What did the cards measure?** → L1.
2. **What small number of biological properties can be reproducibly resolved from those measurements?**
   → L2a (one source/grain) and L2b (integrated across sources).
3. **What conclusions require evidence from outside this subskill or a drug-development context?**
   → leave them for L3.

For tumor-presence: the 17 cards are the **evidence-acquisition layer**; the subskill as a whole becomes
the **tumor-expression evidence package** that downstream frames consume.

## The layers, as a question ladder (with scope)

| Layer | Scope | Core question |
|---|---|---|
| **L1** | card / source | What did we measure? |
| **L2a** | card / source | What biological property does this source support? |
| **L2b** | usually subskill / domain | What do multiple sources jointly support? |
| **L3d** | **within subskill** | What is the biological story for this domain? |
| **L3f** | **across subskills** | What does the evidence mean for this decision lens? |
| **L4** | **whole target / program** | What is the integrated target story, and what matters next? |

### The simplest mental model
> **L3d tells the story of a subskill. L3f asks a question across subskills. L4 tells the story of the target.**

```text
CARDS → SUBSKILL → TARGET DECISION → TARGET STORY
 L1/L2     L3d          L3f              L4
```

## Center of gravity

> **L1/L2 establish what is supported.**
> **Projections expose it.**
> **L3d tells the biological story inside each domain; L3f applies explicit decision lenses across domains.**
> **L4 reconciles those lenses into the coherent target/program story and identifies what would change the decision.**

This is where the system transitions from **data → evidence → insight → actionability**.
