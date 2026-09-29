# Gate Scaffold — 8 Questions × Modality Axis × Subtype Axis

**Status:** Decided (model) 2026-07-17. Refines the 8-gate scaffold in
`CARD_ARCHITECTURE_DECISION.md` after a modality pressure-test (SM / biologics /
structure lenses) and a 16-target backtest against clinically approved cancer drugs.
The pressure-test found the scaffold sound as a *set of questions* but its
**interpretation was single-modality** — it silently encoded a small-molecule,
pan-cancer-dependency worldview. This record fixes the model: the 8 questions are
invariant; **modality and subtype are two orthogonal axes that condition how each
gate is read** (which evidence is load-bearing, which gate may veto). Companion to
`CARD_ARCHITECTURE_DECISION.md`, `MODALITY_TAXONOMY.md`, `FRAMEWORK_OVERVIEW.md`.

Portable GFM (no Mermaid/HTML) per README format rules.

---

## The model: 8 gates, conditioned by two orthogonal axes

Nomination is a conjunction of 8 separable necessary-condition **questions** (A–H).
The questions do not change with modality or subtype. What changes is the *reading*:

- **Modality axis** ({small_molecule, degrader} vs {adc, bite_tce, antibody}) conditions,
  per gate: (a) *which evidence is load-bearing*, and (b) *whether the gate may veto*.
- **Subtype axis** (MSI/MSS, driver-mutant, …) conditions *within which stratum* a gate
  is evaluated (see `CARD_ARCHITECTURE_DECISION.md`, "Subtype is the finest rung…").

Both axes are **orthogonal conditioners, not new gates and not branches.** This is the
same shape already ruled for subtype, now extended to modality. It is also the native
shape one layer down: the rules layer already emits *per-modality* signals
(`small_molecule: killer, adc: neutral, …`). Only the nomination gate (Engine B)
flattened modality into a modality-blind veto — that flattening is the core defect.

| Gate | Question (modality-invariant) | Modality conditions… | Subtype conditions… |
|---|---|---|---|
| A | **Present** — addressably present? | load-bearing evidence: *abundance* (SM) vs *surface-accessible epitope* (biologics) | in which stratum present |
| B | **Selective** — window vs normal? | *adjacent-window* (SM efficacy) vs *population-normal-surface* (biologics safety) | per-stratum window |
| C | **Required** — does the drug need the target? | **veto-power**: vetoes SM/degrader; **informative-only** for TCE/ADC/antibody | context-restricted dependency |
| D | **Mechanism** — actionable MoA? | MoA hook (SM) vs mostly N/A (biologics kill via payload/synapse) | — |
| E | **Druggable** — can THIS modality engage it? | E1 ligandability (SM) vs E2 density/internalization/topology (biologics) | — |
| F | **Safe** — on-target liability? | **dominant axis**: germline full-KO (SM) vs normal-tissue-surface (biologics) | tissue/stratum-specific |
| G | **Differentiated** — precedent, biomarker, whitespace? | modality-specific precedent + companion-dx | per-stratum biomarker |
| H | **Translational** — models, PD, combo/resistance? | modality-specific assays | per-stratum models |

**On the count.** An earlier draft proposed ~11 gates (splitting A1/A2, B1/B2, E1/E2) plus
a modality-router meta-gate. That was rejected: A2/B2/E2 are not separate *questions* —
they are gates A/B/E **read through the biologics modality lens**. The honest count is
**8 questions × 2 axes**, not 11 gates. E1/E2 remain two sub-skills at the implementation
layer, but they answer the one question E ("can this modality engage it?") for two
modalities. A router would force a single modality lane; the orthogonal-axis model
lets one target be read for ADC *and* naked-Ab *and* TCE simultaneously.

**Presupposition, modality-conditioned.** The linear DAG in the parent doc
(D presupposes C; G presupposes C) encodes the SM worldview. Corrected:

```
                          A (Present)
                             |
              +--------------+--------------+
   intracellular (SM/degrader)        surface (ADC/TCE/antibody)
   A[abundance] -> B[adjacent]        A[surface-access] -> B[pop-normal-surface]
     -> C[dependency, VETOES]           -> E[density/internalization]
     -> D[MoA] -> E1[ligandability]      -> F[normal-tissue-surface, VETOES]
     -> G[C+E1] -> F[constraint] -> H     -> G -> H
                                        [ C is INFORMATIVE context here; never gates G, never vetoes ]
```

## The evidence: 16 approved-target backtest

Every approved target was mapped onto the gates and run against the *shipped* wiring to
see whether the framework would nominate or veto it. The result is decisive: **10 clean
false-negatives, 4 ambiguous/fragile, 2 pass (one only by sampling luck).** Only HER2
passes on merit — and it is the one target that is genuinely a genetic dependency, i.e.
the control. Every failure is **gate C** (or, for biologics, gate C firing where it
should be modality-scoped out).

| Target | Modality | Dependency mode | Shipped verdict | gate-C mechanism |
|---|---|---|---|---|
| HER2 | ADC/Ab | selective (amp) | ✅ TRUE POS | passes — the control |
| KRAS G12C | SM | oncogene-addiction | ✅ pass (lucky sampling) | clears 5% floor |
| BRAF V600E | SM | oncogene-addiction | ⚠️ fragile | near 5% floor |
| AR | SM | lineage-addiction | ⚠️ ambiguous | lineage-rescue fragile (AR-null lines) |
| MDM2 | SM | PPI, p53-WT context | ⚠️ ambiguous | non_dependent risk + E1 stranded |
| CDK4/6 | SM | paralog-buffered | ⚠️ ambiguous | single-gene buffering |
| EGFR | SM | mutation-addiction | 🔴 FALSE NEG | mutant lines < 5% floor |
| PARP | SM | synthetic-lethal | 🔴 FALSE NEG | definitionally non-essential |
| BCL2 | SM | addiction (MCL1-buffered) | 🔴 FALSE NEG | non_dependent |
| IDH1 | SM | neomorphic GOF | 🔴 FALSE NEG | rare mutant; mut-strat self-vetoes <5 lines |
| BTK | SM | sub-lineage addiction | 🔴 FALSE NEG | discriminator finer than OncotreeLineage |
| FLT3 | SM | genotype-addiction | 🔴 FALSE NEG (sharpest) | rescue orthogonal to lineage; right card severed |
| PSMB5 | SM | pan-essential + cell-state | 🔴 FALSE NEG (other arm) | common_essential → veto |
| CD19 | TCE | non-dependency-required | 🔴 FALSE NEG | modality-flat veto |
| TROP2 | ADC | non-dependency-required | 🔴 FALSE NEG | modality-flat veto |
| DLL3 | TCE | non-dependency-required | 🔴 FALSE NEG | modality-flat veto |

**Headline:** the dependency veto, as wired, would have killed osimertinib, olaparib,
venetoclax, ivosidenib, bortezomib, blinatumomab, sacituzumab govitecan, and tarlatamab.

## Gate C is the defect — a narrow band-pass filter, failing at both ends

The dependency verdict is computed from **one pooled scalar** —
`fraction_strongly_dependent` = fraction of ~1500 pan-cancer DepMap lines with
Chronos ≤ −1.0 (`depmap_chronos_distribution/cli.py`) — binned by two hard thresholds,
**both of which veto** (`nomination_verdict_gate.yaml`):

- `≥ 0.85` → `common_essential` → `pan-essential-killer` → **VETO** (too essential — PSMB5)
- `< 0.05` → `non_dependent` → `non-dependent-killer` → **VETO** (not essential enough)
- only the `0.05–0.60` bimodal band passes — exactly the KRAS/BRAF oncogene-addiction
  shape the scaffold was implicitly tuned on.

So gate C does not ask "does the target matter"; it asks "does the target sit in a narrow
slice of *pan-cancer* essentiality." Both veto arms are the same structural flaw — a
single context-free scalar — firing at opposite thresholds.

### Gate C conflates SIX biologically distinct dependency modes

The pooled scalar collapses six kinds of "required," each of which validated a different
drug through a different mechanism. **Only mode 2 is wired.**

| # | Mode | Exemplar(s) | What "required" means | Signal substrate needed |
|---|---|---|---|---|
| 1 | pan-essential + cell-state window | PSMB5 | required everywhere; window = tumor cell-state (proteotoxic stress) | tumor-line vs normal-line differential essentiality |
| 2 | selective / oncogene-addiction | KRAS, BRAF, HER2 | required in a mutant/amplified subset | **the one mode wired today** |
| 3 | lineage-addiction | AR, BTK | required in a lineage | lineage-scoped dependency |
| 4 | synthetic-lethal / context | PARP (BRCA/HRD) | required *given a partner alteration* | SL-partner co-dependency |
| 5 | neomorphic gain-of-function | IDH1 | mutant acquires a new essential activity | mutant-specific functional readout |
| 6 | non-dependency-required | CD19, TROP2, DLL3 | modality does not need dependency at all | modality axis (this doc) |

### A partial rescue already exists — and its failure pattern IS the taxonomy

`functional-requirement/run.py` checks `lineage-selective-supportive` **before** the
`non-dependent-killer` branch, so a lineage-scoped rescue exists inside gate C. It fires
only when the drug's discriminating variable matches `OncotreeLineage` granularity:

- **AR** (discriminator = lineage, Prostate) → rescue *available but fragile* (AR-null
  prostate lines dilute the delta below the −0.3 threshold) → ambiguous.
- **BTK** (discriminator = *sub-lineage*, BCR-dependent B-cell, finer than `Lymphoid`) →
  rescue diluted out → false negative.
- **FLT3** (discriminator = *genotype*, orthogonal to lineage) → lineage rescue
  structurally cannot fire.

**FLT3 is the cheapest-fix case.** The framework *already computes* the correct signal:
`mutation-stratified-dependency` contrasts FLT3-mutant vs FLT3-WT directly and fires
`mutant_strongly_dependent` (marked `dominant`). But that verdict is emitted under the
`genomic_alteration` sub-skill, which appears in **neither** `gates` **nor**
`positive_signals` in `nomination_verdict_gate.yaml` — so the right answer is computed
and then discarded. Wiring `genomic_alteration: biomarker_stratified_dependency` into the
gate vocab reconnects **EGFR + IDH1 + FLT3** at once.

## The two bucket corrections (evidence filed by skill, not by question)

The root cause across all defects: evidence was organized by *which skill holds the card*,
not *which question the measurement answers*. Two corrections follow immediately.

**PRISM belongs in gate C (dependency), not E1 (druggability).**

| Card | Filed today | Answers | Correct gate |
|---|---|---|---|
| `prism-compound-activity` | E1 druggable | is the target required (chemical perturbation) | **C** (+ compound-existence spillover to E1) |
| `prism-crispr-concordance` | E1 druggable | chemical+genetic corroboration of "required" | **C** |
| `dependency-predictability` | E1 druggable | accuracy = dependency confidence; SHAP = biomarker | **C-confidence + G-biomarker** |
| `structure-features-static` | stranded in *surface* rule file | pocket / ligandability | **E1** (the actual "can we drug it") |

Consequence: E1 today = "has it *already* been drugged" (retrospective PRISM). After the
correction E1 = "*can* it be drugged" (forward ligandability), and C gains its chemical arm.
The KRAS-G12C switch-II covalent pocket — the thing that *made* the drug — is invisible to
E1 today because the pocket card is stranded on the biologics axis.

**Safety is 6 axes; germline is one, and not the dominant one.**

| Safety axis | Question | Status | Weight |
|---|---|---|---|
| Germline LoF (gnomAD) | full-KO tolerability | ✅ wired | moderate (full-KO proxy) |
| Normal-tissue surface breadth (HPA) | on-target-off-tumor tox | 🔴 data-blocked, not gate-hooked | **dominant for ADC/TCE** |
| Essential-tissue expression | no-go-tissue liability | 🔴 subset of above | gating |
| Cell-type specificity (scRNA) | is normal expression in a dispensable compartment | absent | high |
| Clinical/class precedent | has this target/pathway caused tox | lit-in-synthesis | high |
| Modality scaling | partial-inhibition vs full-KO vs surface-kill | partial | cross-cutting |

TROP2's dose-limiting tox (normal-epithelial surface) and HER2's (cardiomyocyte-surface,
cardiotoxicity) both live in the data-blocked `normal-tissue-liability` card; the wired
germline axis is irrelevant to both.

**Where single-cell / spatial data wires in.** One substrate → four gates (a proof of the
question-first model): cell-type-resolved normal expression → **F**; tumor % positive /
antigen uniformity → **E2** (fills the `method_pending` antigen-homogeneity gap); spatial
tumor-vs-stroma localization → **B + F**; TME composition → **extrinsic biology axis**.

## Corrected evidence → gate map, with rewire-cost flags

🟢 doc-relabel · 🟡 card re-tag + rules · 🔴 new data/reader/code

| Change | Cost | Notes |
|---|---|---|
| Re-issue the model as 8 gates × modality × subtype (retire the ~11 framing) | 🟢 | this doc |
| A2/B2/E2 = biologics *reading* of A/B/E, not separate gates | 🟢 | reframe only |
| PRISM → gate C; `structure-features-static` → E1 | 🟡 | move card_ids between SUB_SKILL_CARDS; re-home structure rule to intracellular axis; no method rewrites |
| `dependency-predictability` → C-confidence + G-biomarker | 🟡 | card already emits accuracy + SHAP; add rules |
| Gate C veto modality-conditional (informative-only for biologics) | 🟡 | `excluded_modality_scoped` machinery already exists (the KRAS golden) |
| Wire `genomic_alteration: biomarker_stratified_dependency` into gate vocab | 🟡 | reconnects EGFR/IDH1/FLT3; needs a guard test |
| DepMap-power admissibility guard (below-power lineage/genotype = insufficient, not non_dependent) | 🟡 | reuse measured-vs-null discipline / subgroup_n_floor |
| Lineage/context-scoped dependency as gate-C input | 🔴 | reuse `build_dependency_panorama` (already shipped for subtype work) |
| Partner-conditioned dependency reader (generalize beyond target's-own-mutation) | 🔴 | rescues PARP/BCL2 |
| Tumor-line vs normal-line differential essentiality | 🔴 | rescues the pan-essential end (PSMB5) |
| Engine B consults the modality-router | 🔴 | Engine B has no router; this IS the two-engine unification debt |
| Normal-tissue surface + normal scRNA safety | 🔴 | HPA mirror + card + gate hook |
| Covalent-handle (CysDB) + PPI-pocket (fpocket) druggability | 🔴 | KRAS-G12C/EGFR/BTK are covalent; MDM2 is PPI |

## The deepest learning: dependency verdict must become a typed record

A single categorical (`non_dependent`/`common_essential`/`strongly_selective`) cannot
carry six modes. The fix is to emit the dependency verdict as
`{mode, context, magnitude, confidence}` — at which point the veto becomes mode-aware for
free, the power-guard has a `confidence` field to write, and the SL/lineage/neomorphic
readers each populate `context`. **This is the continuous-evidence principle from
`CARD_ARCHITECTURE_DECISION.md` applied to the one gate that most needs it** — the
backtest independently re-derived the framework's own stated principle from the opposite
direction.

## Diagnosis: convergence, not redesign

The framework already *contains* the correct design, applied inconsistently:
- the modality-router exists (Engine A / `compose-dashboard/_resolution.py`) but is absent
  from Engine B (the nomination gate);
- the modality-scoped-veto-exclusion exists (`excluded_modality_scoped`, the KRAS golden);
- the modality-tiered safety thresholds exist (`normal-tissue-liability` strict/moderate/pathway);
- the correct surface DAG exists (the surface base dashboard has *no* dependency cards);
- the lineage-scoped and mutation-stratified readers exist (just severed from the gate).

Every fix is "apply a pattern the framework already has to gates C and F, and make Engine B
consult the router Engine A already uses." The two-engine unification (flagged as the top
interpretation-layer refactor) is the load-bearing follow-up.

## Open / next threads (NOT decided here)
1. **Implementation sequencing** — a cheap "green + yellow" PR (re-issue the model,
   PRISM→C, structure→E1, modality-conditional veto scope, the `genomic_alteration` wire,
   the power-guard) vs the deeper 🔴 readers. Sequencing decided after this doc is reviewed.
2. **Dependency typed-record schema** — the `{mode, context, magnitude, confidence}` shape
   above; a card/vocab change deferred until the model is agreed.
3. **Engine B ↔ Engine A unification** — the load-bearing follow-up; see
   `FRAMEWORK_OVERVIEW.md` (two synthesis engines).

## Expanded universe: what discriminates winners from losers (~32 targets)

The 16-target gate-C backtest was extended with **8 winner-archetypes** not previously
covered (BCR-ABL/ALK/NTRK fusions, EZH2 & menin-MLL epigenetic, ATR/WEE1 DDR, VEGF
angiogenic, XPO1 nuclear-export, CYP17A1 hormone-synthesis, RET/MET) and an **8-target
negative-control set of high-profile clinical FAILURES** (IDO1, FAK, MEK-monotherapy,
RAS-FTIs, HDAC-in-solid, SMO-broad, mTOR-broad, CD44v6-ADC). The failure set is what
turns this from a survivorship-biased list into a *discrimination* study.

### Two constitutional limits explain every miss

The DepMap/TCGA/gnomAD substrate is **(1) cell-autonomous** and **(2) single-perturbation,
complete-knockout.** Every miss — winner or failure — is downstream of one of these:

- **Cell-autonomous** → the framework *inverts* on non-cell-intrinsic targets: VEGF
  (stromal/vascular), CYP17A1 (endocrine/indirect), IDO1 (immune), SMO-paracrine,
  FAK-stroma all read `non_dependent` → a **wrong-verdict veto of a validated target**,
  which is more dangerous than a data gap.
- **Single-perturbation + full-KO** → it cannot express conditional synthetic lethality's
  second genotype (ATR given CCNE1-amp), a **partial-inhibition therapeutic window** (XPO1,
  proteasome — a full KO cannot model a therapeutic index), or **adaptive feedback**
  (MEK/mTOR — needs the perturbed time-course, not a static snapshot).

### The dependency-mode taxonomy, completed: 10 modes, gate C wires 1

The winner-archetypes add four modes to the six from the first backtest:
**fusion-created** (BCR-ABL/ALK/NTRK/RET — dependency manufactured by a translocation
present in neither parent gene), **conditional-SL-2-genotype** (ATR), **microenvironment**
(VEGF), **indirect/ligand-supply** (CYP17A1). XPO1 repeats the pan-essential+window mode
(validates consistency). New **gate A** learning: for fusion drivers "present" is a
*structural-rearrangement event* (fusion junction), and for MET a *splice event* (exon-14
skipping) — an alteration class between SNV and CNV that the expression-centric gate A
misses. The `fusion-rearrangement-landscape` card is a declared placeholder (candidate
sources: GENIE `data_sv.txt` / Mitelman / ChimerDB).

### The failure set splits ~50/50 — the core discrimination result

**Framework-VISIBLE failures** fall on axes the (corrected) gates score — validating real
discriminative power: FAK (paralog-buffered non-dependency, gate C — already right), HDAC
(pan-essential, no window, B+C+F), RAS-undruggability (no pocket, E), mTOR (low
selectivity, C).

**Framework-INVISIBLE failures** — the *modal* failure of strong-rationale targets — live
in data modalities the static substrate lacks: MEK (adaptive RTK feedback), IDO1
(immune/TME context), SMO (paracrine + on-treatment resistance), and the pervasive
**monotherapy-vs-combination logic** (MEK/mTOR/FAK/IDO1 all "work in combination, fail
alone" — the framework scores every target in isolation).

**CD44v6-ADC** (discontinued for fatal skin toxicity) is a third category: biology the
framework's *modality* could see (normal skin surface expression) but the *wired* gate F
points at gnomAD germline — so **on-target-off-tumor toxicity, the dominant biologics
failure axis, passes the current safety gate.** Same finding as TROP2, now with a death.

**Tier-1 vs Tier-2 (the honest ceiling).** Tier-1 = the framework's real lane:
*biological-hypothesis quality* (dependency selectivity, pan-essentiality, normal
expression, tractability). It genuinely discriminates FAK/HDAC/undruggable-RAS. Tier-2 =
the frontier: *clinical success* is decided in dynamic/contextual/longitudinal/combinatorial
data the framework is structurally blind to. A static-omics verdict should carry an explicit
confidence discount in the Tier-2 regime.

### Target-class router (new — both mining agents reached it independently)

Because gate C (dependency) is the only hard veto and its substrate is cell-autonomous
CRISPR, the framework mishandles an entire target *class*. A target has a **class**
(cell-intrinsic / microenvironment / indirect / immune) that must condition **which
substrate gate C reads** — the same orthogonal-axis shape as modality and subtype. Without
it, the cell-autonomous veto inverts validated microenvironment/indirect targets.

### Ranked data modalities to add (success-predicting), by targets rescued

🟢 doc · 🟡 card/data exists, wire it · 🔴 new evidence spine

| Rank | Modality | Rescues | Gate | Cost |
|---|---|---|---|---|
| 1 | **Dynamic / perturbation response** (post-inhibition pathway rebound) | MEK, mTOR, feedback class | D (has topology, lacks dynamics) | 🔴 |
| 1= | **Combination-dependency** (needs-a-partner-for-window) | MEK, mTOR, FAK, IDO1 | new axis | 🔴 |
| 2 | **Conditional / 2-perturbation SL** (partner-genotype dependency) | PARP, ATR, BCL2 | C | 🔴 (generalize mut-strat card) |
| 3 | **Structural-variant / fusion detection** | BCR-ABL, ALK, NTRK, RET | A + C | 🟡 card is placeholder, sources named |
| 4 | **Normal-tissue protein/surface atlas** (HPA/GTEx) | TROP2, HER2, CD44v6, DLL3, CD19 | F (fix substrate) | 🟡 data-blocked card exists |
| 5 | **Immune / TME context** | IDO1, FAK-stroma, SMO | extrinsic axis + C-router | 🔴 |
| 6 | **Partial-inhibition window** (tumor-line vs normal-line differential essentiality) | PSMB5, XPO1 | C (pan-essential rescue) | 🔴 |
| 7 | Covalent-handle (CysDB) + PPI-pocket (fpocket) ligandability | KRAS-G12C, EGFR, BTK, MDM2 | E | 🔴 |

**Rank-1 (dynamic-perturbation) and rank-1= (combination-dependency) are the two additions
that most separate "successful target" from "good biological hypothesis"** — and are the
two the framework has zero representation for. Naming this ceiling is itself a deliverable:
it says where the verdict must defer to experimental/human judgment.

## Cross-references
- `CARD_ARCHITECTURE_DECISION.md` — the 8-gate scaffold + two-layer card model + subtype axis.
- `MODALITY_TAXONOMY.md` — the `measurement:` / modality enums this axis reads.
- `FRAMEWORK_OVERVIEW.md` — the two synthesis engines + guard rails.
- `SUBGROUP_PANORAMA_PLAYBOOK.md` — the lineage/subtype-scoped dependency readers to reuse.
