# Target profile — KRAS in COADREAD

Generated 2026-07-14T00:40:35+00:00

![Target profile at a glance](figures/target_profile_at_a_glance.png)

## Executive summary *(LLM-synthesized)*

KRAS in COADREAD presents as a well-validated, biomarker-stratified oncology target with strong functional and pharmacological evidence. CRISPR and RNAi both show bimodal, lineage-selective dependency enriched in Bowel (54% strongly dependent) and Pancreas, and hotspot-mutant lines are dramatically more dependent than WT (delta Chronos -1.32, q~1e-102). ~42% of COADREAD tumors carry KRAS mutations (dominated by G12D/G12V/G13D; G12C only ~3%), co-occurring with APC/SMAD4/CDKN2A and mutually exclusive with BRAF/EGFR — a coherent biomarker-defined population. Tractability is de-risked by clinically active PRISM compounds (RMC-7977, eloronrasib, daraxonrasib) triangulated with CRISPR engagement, and mutation-driven dependency is highly predictable (RF R²≈0.47, top feature own_mut_hotspot). Expression is broadly moderate/non-selective and safety/surface data are uninformative — expected for an intracellular GTPase — so the target profile is intracellular small-molecule/tri-complex, not surface/ADC.

## Recommendation *(LLM-synthesized, enum-constrained)*

- **Action:** `nominate`
- **Confidence:** `high`

## Risk-by-category summary *(deterministic reshape of sub-verdicts)*

Governance-facing 6-category framing mapped from the rule-fired sub-verdicts below. Categories with no wired data return `insufficient_evidence` rather than fabricated risk levels.

| Category | Risk level | Driver |
|---|---|---|
| **biological** | `LOW` | strong support across A/B/C/mut sub-verdicts |
| **druggability** | `LOW` | e7-triangulated-target-engaged-supportive |
| **translational** | `insufficient_evidence` | Phase-J (translational-readiness) placeholder — data not wired |
| **clinical** | `insufficient_evidence` | Phase-E (clinical precedent) placeholder — data feed not wired |
| **safety** | `insufficient_evidence` | Phase-G (on-target-safety) placeholder — HPA + gnomAD cards not wired |
| **commercial** | `insufficient_evidence` | Phase-E (competitive/IP) placeholder — Cortellis/IQVIA not licensed |

## Tension analysis *(LLM-synthesized)*

Minimal biological tension. Expression is "broadly moderate" and tumor-vs-normal selectivity is discordant/down — but this is expected for a ubiquitously expressed intracellular GTPase where selectivity comes from mutant-state pharmacology, not expression differential. The main mismatch is dimensional: surfaceome/ADC/TCE cards are empty and cohort_rank is data_unavailable because KRAS is not a surface protein (surfaceome_confidence 1.0 not_surface, Kinase/Enzyme family) — these dimensions are not applicable rather than negative. Differentiation and safety sub-verdicts are flagged "insufficient" (no rule fired), though the underlying co-mutation card actually shows rich landscape data (APC/SMAD4 co-occurrence, BRAF/EGFR exclusivity) that is informative for combination strategy.

## Sub-verdicts *(deterministic, rule-fired)*

| Dimension | Verdict | Driving rule |
|---|---|---|
| expression | `broadly_moderate_expression` | `expression-broadly-moderate-neutral` |
| selectivity | — | (raw metrics; no rule verdict) |
| dependency | `lineage_selective` | `lineage-selective-supportive` |
| mechanism | `well_characterized` | `mechanism-well-characterized-supportive` |
| mutation | `biomarker_stratified_dependency` | `mutant-strongly-dependent-supportive` |
| differentiation | `insufficient` | `None` |
| tractability | `well_covered` | `e7-triangulated-target-engaged-supportive` |
| safety | `insufficient` | `None` |
| population | — | (raw metrics; no rule verdict) |
| cohort_rank | — | (raw metrics; no rule verdict) |

## Per-phase evidence *(deterministic, from card summaries)*

Key metrics inlined from each sub-skill's underlying card summaries. Use these to trace a verdict back to its supporting data.

### expression — `broadly_moderate_expression`

| Metric | Value |
|---|---|
| median log2TPM (pan-cancer) | `4.508` |
| fraction expressed | `0.999` |
| log2FC tumor vs adj | `-0.720` |
| q-value (tumor vs adj) | `3.29e-16` |

### selectivity

| Metric | Value |
|---|---|
| cells supporting | `2.000` |
| cells ran | `3.000` |
| dominant direction | `down` |
| max |log2FC| | `0.640` |
| discordant | `yes` |

### dependency — `lineage_selective`

| Metric | Value |
|---|---|
| CRISPR-RNAi concordance | `strongly_concordant_non_dependent` |

### mutation — `biomarker_stratified_dependency`

| Metric | Value |
|---|---|
| landscape class | `missense_dominant` |
| stratification class | `mutant_strongly_dependent` |
| dominant variant class | `missense` |
| cohort mutation frequency | `0.420` |

### tractability — `well_covered`

| Metric | Value |
|---|---|
| predictability | `own_omics_driven` |

### population

| Metric | Value |
|---|---|
| mutation frequency (indication) | `0.420` |
| n samples in indication | `559` |
| n samples mutated | `235` |

## Top arguments *(LLM-synthesized)*

**For:**
- Biomarker-stratified dependency is exceptionally strong: hotspot-mutant vs WT delta Chronos -1.32 (q~1.7e-102, effect size 0.90), and own_mut_hotspot is the dominant predictive feature (RF importance 0.44, R²≈0.47).
- Lineage-selective essentiality in Bowel (54.5% strongly dependent, median Chronos -1.18, q~4e-16) with CRISPR/RNAi concordance and bimodal selective distribution — hallmark of a genotype-defined driver.
- High indication prevalence: ~42% of COADREAD samples KRAS-mutant (n=559), missense-dominant, with a broad hotspot spectrum (G12D 10.9%, G12V 9.3%, G13D 7.2%, G12C 3.0%, A146T 2.9%) enabling pan-KRAS or multi-allele strategies beyond G12C.
- Tractability triangulated: 23 PRISM compounds with clinically active signal (RMC-7977, eloronrasib, daraxonrasib in phase 1+), CRISPR–PRISM concordance class 'triangulated_target_engaged', and best responder LFC -13.6 in mutant lines.
- Well-characterized mechanism (71 upstream regulators, 12 downstream effectors) supports rational combination design; co-mutation with APC/SMAD4/CDKN2A and mutual exclusivity with BRAF/EGFR define a clean CRC-specific biomarker context.

**Against:**
- Expression is broadly moderate across lineages (fraction_expressed 99.9%, no lineage restriction) and tumor-vs-adjacent is down/not-informative — no expression-based therapeutic window; selectivity must come entirely from mutant-state pharmacology.
- Tumor-vs-normal selectivity is discordant across comparators (dominant direction 'down'), meaning wild-type KRAS suppression risks on-target normal-tissue toxicity for pan-KRAS agents.
- Moderate paralog buffering by NRAS (dual-KO effect -1.04) and weaker HRAS/RALA buffering — pan-RAS or vertical pathway coverage may be required, complicating therapeutic index.
- Safety card is empty (no gnomAD LoF constraint data returned) and differentiation sub-verdict flagged insufficient — key risk dimensions not formally scored.
- Not a surface protein (surfaceome_confidence 1.0 not_surface; no PDB coverage in the structure card returned here) — ADC/TCE modalities inapplicable, and the competitive landscape in KRAS small molecules (G12C approved, G12D and pan-KRAS advancing) raises the bar for differentiation.

---

*LLM-synthesized sections carry `_source: llm_synthesized` provenance (see `nomination.json`). Sub-verdicts + per-phase evidence + risk-by-category are deterministic and reproducible from the same inputs. The composite figure is rendered from the same sub-verdicts and can be regenerated identically.*