# Product Overview — the oncology target-evaluation framework

**A layered product front-door.** The top half is written for **ODDU / BD /
leadership**: what the framework is, what it can do today, and why its two
signature behaviours — *verdict-inert optionality* and *abstention* — are
selling points rather than caveats. The bottom half is written for the
**end-user comp-bio scientist**: how a single datum becomes an auditable
verdict, walked end to end on one skill (`tumor-presence`) and one worked
target (KRAS in COADREAD).

Every number in this document is pulled from a **shipped, committed
artifact** — the Framework Atlas feed (`health/framework_atlas.json`), the
coverage ledgers (`coverage/`), and the per-skill product pages the Atlas now
renders. Where a capability is *registered but not yet live*, this document
says so. There are no forward-looking capability claims. Provenance for every
count is in the [Appendix](#appendix--provenance).

> **Reuse, don't re-derive.** This is a wrapper over prose that already exists.
> Each section cites its source design doc; read those for the full argument.

---

# Part I — Executive front-door

## The model in one sentence

Raw oncology data is refined through **four repositories**, each a distinct
layer with a distinct contract, so that a scientist's question — *"is KRAS a
good target for MSS colorectal cancer?"* — is answered by **composing** small,
auditable, independently-testable evidence units, not one monolithic analysis.

*(Source: [`FRAMEWORK_OVERVIEW.md`](../design/FRAMEWORK_OVERVIEW.md) — "The model in one sentence".)*

## The four-repo spine

```
data-catalog        →   analysis-methods    →   target-contracts    →   claude-oncology-skills
(what data exists)      (how to compute)        (what to claim)         (how to answer)
```

| Repo | Owns | Analogy |
|------|------|---------|
| **data-catalog** | Manifests pointing at S3 bytes (sources + derived products), each with pinned MD5 + version + license | The card catalog — *where* everything is |
| **analysis-methods** | Deterministic Python readers/computers (`read_*`, `build_*`) | The lab instruments — *how* you measure |
| **target-contracts** | Cards (what evidence), rules (what signals), controlled verdict vocabularies, schemas + validators | Lab protocols + the review board — *what* claims are legitimate |
| **claude-oncology-skills** | Skills that compose cards → resolver ladders → the nomination gate → synthesis; renderers | The scientist writing the report — *how* it's answered |

**The dependency arrow never reverses.** A skill never touches raw data
directly — it goes through a card → a method → a pinned manifest. That chain is
what makes any single claim auditable back to a specific data file.

*(Source: [`FRAMEWORK_OVERVIEW.md`](../design/FRAMEWORK_OVERVIEW.md) — "The four repos".)*

## What is shipped today

These are the counts in the committed Atlas feed
(`health/framework_atlas.json`, `framework_atlas_version` 1.0.0, generated
2026-09-23; see [Appendix](#appendix--provenance)):

| Measure | Count | Source field |
|---|---:|---|
| Skills in the roster | **22** | `summary.n_skills` |
| Skills **wired** (live readers, firing in real packages) | **11** | `summary.n_wired_skills` |
| Evidence **cards** | **148** | `summary.n_cards` |
| **Verdict-bearing** cards | **44** | `summary.n_verdict_bearing_cards` |
| Datasets referenced by cards | **235** | `summary.n_datasets` |
| …of which resolve to a catalog manifest | **229** | `summary.n_datasets_in_catalog` |
| Broken dataset references (surfaced, not hidden) | **6** | `summary.n_broken_refs` |
| Resolver ladders (gate-bearing skills) | **9** | `summary.n_resolvers` |
| Distinct verdict tokens across the vocabulary | **94** | `summary.n_verdicts` |

The evidence corpus behind the observed-value statistics in Part II is the
**`target-archetype-corpus-20260920`** — **504** emitted packages
(`coverage/emission_ledger.yaml`: `n_packages`), across **136** cards that
declare a controlled vocabulary (`counts.cards_declaring_vocabulary`).

For the **data footprint** at the source layer, the ODDU-facing catalog
overview (2026-07-09 snapshot) records **85** source-release manifests spanning
**45,430** files on S3, plus tracked derived-product manifests, each carrying a
verbatim license block.
*(Source: [`catalog-overview-for-oddu-2026-07-09.md`](https://github.com/oneTakeda/rnd-computational-biology-oncology-data-catalog/blob/main/docs/catalog-overview-for-oddu-2026-07-09.md).)*

## Two differentiators

**1. Verdict-inert optionality.** The deterministic spine — data → method →
card → rule → verdict — is byte-stable. Around it sit *optional lanes* a user
can toggle: an LLM narrative (`--synthesize`), a literature lane
(`--literature`), figures (`--figures`), emit modes, data-mode / release pins,
a modality lens, a subtype panorama. **Every one of these is verdict-inert** —
turning it on adds a sibling output key but never changes a verdict token. The
Atlas Product tab labels each lane and asserts this invariant in test
(`test_product_page_roster.py`). You get full optionality *without* putting the
audit spine at the mercy of a prompt.

**2. Abstention as a feature.** The framework's best-measured property is that
it returns an honest `insufficient_evidence` on the axis it cannot see, rather
than fabricating a level. The nomination verdict is rule-gated on **both**
sides: a fired veto/hold rule forces a negative recommendation, *and* on
abstention (no rule fires) an LLM-authored `veto`/`hold` collapses to
`insufficient_evidence` — so a negative recommendation always has a rule (or the
honest abstention floor) behind it.
*(Source: [`KNOWN_TARGET_FRAMEWORK_REFRAMES.md`](../design/KNOWN_TARGET_FRAMEWORK_REFRAMES.md) — "Abstention is the framework's best property"; the lower-bound clamp is documented in [`FRAMEWORK_OVERVIEW.md`](../design/FRAMEWORK_OVERVIEW.md).)*

## Skill inventory — the biology-first phase model

Skills are organised by **phase** — the gate of the nomination argument each
one answers. The 11 wired skills carry live verdicts; the remainder are
registered breadth (see [Known limitations](#known-limitations-read-this)).

| Phase | Question | Skill(s) |
|---|---|---|
| **A** Presence | Is the target expressed in the tumour (RNA + protein, cell-line + patient)? | `tumor-presence` |
| **B** Selectivity | Is it tumour-selective vs normal tissue, robustly across comparators? | `tumor-selectivity` |
| **C** Requirement | Is it a genetic dependency (CRISPR + RNAi + lineage)? | `functional-requirement`, `combination-and-vulnerability` |
| **A/E** Genomic alteration | How is it altered — SNV/indel, copy-number, fusion — and which class drives? | `genomic-alteration-profile` |
| **D** Mechanism | What signalling context and candidate MoA hooks exist? | `mechanism-and-pharmacology` |
| **E** Differentiation | What co-mutation / mutual-exclusivity landscape frames patient selection? | `differentiation-landscape` |
| **F** Tractability & modality | Is it small-molecule druggable? Does surface biology support ADC/TCE? | `tractability-small-molecule`, `surface-modality-fit` |
| **F** Immune context | Is the tumour immune-hot enough to redirect a TCE? | `immune-context` |
| **G** Safety | Is it germline-constrained (gnomAD)? | `on-target-safety-liability` |
| **J** Translational readiness | Models, PD assays, imaging tracers available? | `translational-readiness` *(partial)* |

*(Source: [`README.md`](https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills/blob/main/README.md) — "The biology-first phase model".)*

## Where to look

- **The live Framework Atlas** — the single dashboard (Overview / Flow / Gaps /
  Concepts / Explorer / Axes / Health / Cards / Datasets / Coverage / **Product**
  / Docs). The committed feed is [`health/framework_atlas.html`](../../health/framework_atlas.html),
  regenerated with `make atlas`; dated bundles are published to the
  [GitHub Releases page](https://github.com/oneTakeda/rnd-computational-biology-oncology-target-contracts/releases)
  (tagged `atlas-<date>`).
- **The Product tab** — the per-subskill "product page" (five panels; a skill
  `<select>` defaulting to `tumor-presence`), added by the product-showcase
  work. Standalone per-skill exports render to `health/product/<skill>.html`
  via `make atlas-product` (a regenerable view, gitignored).
- **The worked example** — the KRAS/COADREAD target profile
  ([`target_profile.md`](https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills/blob/main/docs/examples/target-profile-kras-coadread/target_profile.md)),
  and the [example-gallery](https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills/tree/main/skills/example-gallery)
  that renders per-card real data + figures + a Data→Verdict widget.

## Known limitations (read this)

The framework is deliberately honest about what is *not* done. Two items in
particular must not be read as polish:

1. **Registry ↔ code risk-category drift (tracked as issue #856 — surfaced, not
   fixed).** The risk-category a skill maps into is assigned in two places that
   currently disagree for **5 axes**: the registry
   (`vocabularies/target_profiling_axes.yaml`) and the runtime code
   (`risk_projection.py` `AXIS_TO_DIM` + `ir.py` `_CONTEXT_DIM`). Runtime
   `risk_6dim` bins come from the **code**, so the code is authoritative and the
   registry is the stale side. The Atlas emits the diff as **data**
   (`product_page.risk_drift`), not as a silent paper-over:

   | Axis (`short`) | Registry category | Code dim | Code source | Kind |
   |---|---|---|---|---|
   | `cis_coherence` | biology | biological | `_CONTEXT_DIM` | category_mismatch |
   | `combination_vulnerability` | biomarker | biological | `_CONTEXT_DIM` | category_mismatch |
   | `differentiation` | commercial | translational | `AXIS_TO_DIM` | category_mismatch |
   | `selectivity` | biological | safety | `AXIS_TO_DIM` | category_mismatch |
   | `translational` | translational | *(unmapped)* | — | unmapped_in_code |

   Reconciliation is a governed-vocabulary change and is deferred to its own PR
   (#856). Until then, **trust the code's `risk_6dim` bin**, and read the drift
   block as the open ledger of the disagreement.

2. **12 of 22 skills carry no verdict source — by design, not a gap.** The
   product-page roster classifies every skill into three verdict-source shapes
   (`product_page.skills`):

   | Shape | Count | Skills |
   |---|---:|---|
   | `python_ladder` | **1** | `tumor-presence` |
   | `resolver_yaml` (gate-bearing) | **9** | `cis-feature-coherence`, `differentiation-landscape`, `functional-requirement`, `genomic-alteration-profile`, `mechanism-and-pharmacology`, `on-target-safety-liability`, `surface-modality-fit`, `tractability-small-molecule`, `tumor-selectivity` |
   | no verdict source | **12** | `catalog-query`, `combination-and-vulnerability`, `cross-evidence-hypothesis`, `example-gallery`, `immune-context`, `literature-context`, `literature-risk-assessment`, `query-target-evidence`, `render-evidence-package`, `target-intrinsic`, `target-profile`, `translational-readiness` |

   The 12 are descriptive / support / orchestration / gateless skills
   (composition engines like `target-profile`, retrieval like `catalog-query`,
   context lanes like `literature-context`). They **legitimately** have no gate
   ladder; the product page renders them with an honest empty-spine "no ladder"
   block rather than fabricating a green verdict, and the assembler cross-checks
   that a *genuinely gating* axis missing its ladder still errors.

3. **Registered breadth ≠ live breadth.** "22 skills" is *registered* breadth;
   only **11** are wired. Some `products.yaml` dimensions are `data-blocked` and
   some skills are PARTIAL (e.g. `translational-readiness`). The maturity ladder
   — honest wired-vs-deferred — is itself the selling point, not something to
   hide.
   *(Source: [`README.md`](https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills/blob/main/README.md) — "The biology-first phase model", partial-wiring note.)*

---

# Part II — Scientist deep-dive

## A card's journey to a verdict

A **card** is a unit of evidence: it names a `measurement_type`, the
method(s) that compute it, the source dataset(s) it reads, and a controlled
**summary field** with a declared vocabulary. A **rule** maps an observed field
value to a **verdict token** (and per-modality signals). A skill collapses its
cards' verdicts through an ordered **ladder** into one skill verdict. Only the
final *synthesis narrative* is LLM-generated; everything up to and including
rule-firing is deterministic and reproducible.
*(Source: [`FRAMEWORK_OVERVIEW.md`](../design/FRAMEWORK_OVERVIEW.md) — "The core unit: a card's journey to a verdict"; the full per-dimension wiring is in [`DATA_CARD_RULE_VERDICT_MAP.md`](../design/DATA_CARD_RULE_VERDICT_MAP.md).)*

## The five panels of a product page

The Atlas **Product tab** presents each subskill as five linked panels. This is
the backbone of the whole showcase; below, each panel is walked on the exemplar
**`tumor-presence`** (short axis `expression`, phase A, status **wired**, 17
cards, verdict source `python_ladder`). The Product tab is the *target-invariant*
view (the schematic); the [example-gallery](https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills/tree/main/skills/example-gallery)
is its *worked-example* companion (the rendered data for a real target). Read
them as a pair.

### Panel 1 — Spine (anatomy)

`data source → method → card → summary field (+ type, observed values) → rule
(gating/display) → verdict token → collapsed skill verdict → output shape`.

For `tumor-presence` the spine resolves **7 verdict-bearing cards** onto one
collapsed field, `tumor_presence_verdict`, drawn from a 34-token verdict enum.
Worked on the lead card, `cellline-rna-distribution`:

- **Source** → `depmap-consortium-26q1` (+ two derived rank/isoform products),
  all resolving to catalog manifests, each carrying its DepMap Consortium DUA
  license text.
- **Method** → `depmap-expression-distribution`.
- **Summary field** → `expression_class` (categorical), declared vocabulary
  `{broadly_high, broadly_moderate, lineage_restricted, broadly_low,
  data_unavailable}`.
- **Rule** → e.g. `expression-broadly-low-degrader-killer` is a **killer** for
  the degrader modality; `expression-broadly-high-supportive` is a display rule
  emitting `broadly_high_expression`.

### Panel 2 — Card drill-down

Per card: real fields + **observed value ranges from the corpus**, source
datasets (with catalog resolution + license), and a live/dark overlay. The
observed distributions are *measured*, not declared — for
`cellline-rna-distribution`'s `expression_class` over the 504-package corpus:

| Value | Packages observed |
|---|---:|
| `broadly_high` | 235 |
| `broadly_moderate` | 153 |
| `lineage_restricted` | 90 |
| `broadly_low` | 26 |

(`out_of_vocab` is empty — the emitted values are a strict subset of the
declared vocabulary; saturation ≈ 0.47.) Each drill-down row deep-links to the
example-gallery render of that card's real data + figures.

### Panel 3 — Optionality lanes

The deterministic spine (`cards → rules → ladder → presence_verdict`,
byte-stable) plus the optional lanes, **each labelled verdict-inert**:

| Flag | Lane | Adds |
|---|---|---|
| `--synthesize` | LLM narration | `decision['llm_synthesis']` (prose, sibling key) |
| `--literature` | literature | `decision['literature_synthesis']` |
| `--figures` | figures | `figures/*` |
| `--emit-envelope` | envelope emit mode | `evidence_package.json` beside `decision.json` |
| `--data-mode` / `--release-pin` | data-mode / pin | governance block in the emitted envelope |
| `--modality` | modality lens | `presence_verdict_by_modality` projection |
| `--subtypes` | subtype panorama | `subtype_presence_panorama` (descriptive) |

The LLM/literature seam is one boxed call, `synthesize_structured()`
(`_skills_common/llm.py`) — forced tool-use, enum-constrained, `prompt_hash`
stamped. `literature-context` is reproducible / card-backed / no-LLM;
`literature-risk-assessment` is live-LLM, retrieval-grounded, context-tier, and
**never a gate input**.

### Panel 4 — Roll-up to nomination

How the subskill verdict flows into the broader target-profile nomination:
`sub_verdicts[short]` → gate block → `risk_6dim` bin → `claim_vectors`. For
`tumor-presence` the roll-up records `gateless: true`, `band: necessity`,
`risk_dim: biological` (source `AXIS_TO_DIM`), with two foreign consumers — i.e.
presence is a **necessity** signal, not a gate that can veto on its own. (For
gate-bearing skills, e.g. `functional-requirement` fires a veto and
`on-target-safety-liability` a hold; see
[`DATA_CARD_RULE_VERDICT_MAP.md`](../design/DATA_CARD_RULE_VERDICT_MAP.md).)
Where a skill's registry risk-category disagrees with the code dim, the
roll-up's `drift` field points at the [risk-drift ledger](#known-limitations-read-this).

### Panel 5 — Cards → questions

The question hierarchy the subskill answers, from
`vocabularies/target_profiling_axes.yaml` (`question_hierarchies`). For
`tumor-presence` (axis `expression`):

- **`abundance`** (claim axis A) → *how_much_present* over
  `tumor_expression_distribution`, `cell_line_rna_expression`,
  `tumor_protein_abundance`, `tumor_protein_ihc_presence`,
  `cell_line_protein_abundance`; *rna_protein_proxy* (corroboration).
- **`malignant_intrinsic`** (claim axis C) → *in_cancer_cells* over
  `sc_tumor_celltype_expression`.
- **`generality`** (claim axis D) → *broad_across_cancers* over
  `tumor_elevation_breadth`.

Plus *other lenses* (e.g. `tumor_vs_adjacent_expression` routed to the
`tumor-selectivity` lens) — the hierarchy makes explicit which questions a
measurement answers *here* vs. where it is re-used.

## Worked example — KRAS in COADREAD

The five-panel product page is the invariant schematic; the KRAS/COADREAD
profile is the same machinery run on a real target. In that profile KRAS
presents as a *biomarker-stratified, lineage-selective dependency* — hotspot
mutants (G12D/G12V/G13D/G12C/A146T) account for ~42% of COADREAD samples with a
large dependency delta vs. wildtype — recommendation `nominate` / confidence
`high`. Critically, the deterministic **risk-by-category reshape** returns
`insufficient_evidence` for druggability, translational, clinical, safety, and
commercial (the axes whose data is not wired) rather than fabricating levels —
abstention in action.
*(Source: [KRAS/COADREAD worked example](https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills/blob/main/docs/examples/target-profile-kras-coadread/target_profile.md); the composed-skill design + demo framing is in the [target-profile walkthrough](https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills/blob/main/docs/TARGET_PROFILE_WALKTHROUGH.md).)*

## Reference map & how to reproduce

- **End-to-end wiring of every dimension:**
  [`DATA_CARD_RULE_VERDICT_MAP.md`](../design/DATA_CARD_RULE_VERDICT_MAP.md) —
  data source → card → class field → gate? → risk-table?, every row grounded in
  the actual sub-skill `_verdict`, guarded against rename drift by
  [`test_no_reference_drift.py`](https://github.com/oneTakeda/rnd-computational-biology-oncology-claude-oncology-skills/blob/main/skills/tests/test_no_reference_drift.py).
- **Regenerate the Atlas feed:** `make atlas` (needs the sibling checkouts) →
  `health/framework_atlas.{json,html}`.
- **Regenerate the standalone product pages:** `make atlas-product` →
  `health/product/<skill>.html` for all 22 skills.

---

## Appendix — provenance

| Source | Field / stamp | Value |
|---|---|---|
| `health/framework_atlas.json` | `framework_atlas_version` | 1.0.0 |
| `health/framework_atlas.json` | `generated_at` | 2026-09-23T17:09:16 |
| `health/framework_atlas.json` | `root_shas.target_contracts` | `bc7f52a` |
| `health/framework_atlas.json` | `root_shas.skills` | `248ca094` |
| `health/framework_atlas.json` | `root_shas.data_catalog` | `63777b3` |
| `coverage/emission_ledger.yaml` | `corpus_vintage` | `target-archetype-corpus-20260920` |
| `coverage/emission_ledger.yaml` | `n_packages` | 504 |

All capability counts in Part I are the `summary.*` fields of that feed; the
observed-value distributions in Part II are from `coverage/emission_ledger.yaml`
and the `product_page` block of the same feed. Regenerate with `make atlas`
before quoting counts elsewhere — the committed feed is a point-in-time
snapshot.
