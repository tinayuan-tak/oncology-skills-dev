# Target-Profile Skill — Review & Decisions

**Owner:** Ryan Abo · **Audience:** ODDU + oncology comp-bio · **Draft, 2026-07-14**

## Objective

We want to show the `target-profile` skill to ODDU and settle its design with comp-bio input. The skill answers a single question — should we nominate target X in indication Y? — and produces an evidence package where each verdict traces back to a specific dataset and a version-controlled rule. The narrative text is written by an LLM, but it's labeled as such and kept separate from the verdicts.

This is a decision doc, not a technical tour. It says what we plan to show, then asks for input on five points.

## How it works

Nine sub-skills each read their evidence and produce a rule-based verdict. An LLM then writes a summary over those verdicts and gives a recommendation (nominate / hold / veto). The verdicts and the prose are stored separately, so the verdicts stay fixed even when the wording changes between runs.

```
9 sub-skills  →  rule-based verdict each
      ↓
LLM synthesis  →  summary + nominate/hold/veto  (labeled, stamped)
      ↓
nomination.json · target_profile.md · provenance.yaml · figure
```

Worked example: KRAS in COADREAD returns nominate / high confidence. It's staged at `docs/examples/target-profile-kras-coadread/` if you want to look at the actual output.

## Plan for the demo

- Three targets that are already built: KRAS/COADREAD (lead example), EGFR/LUAD, BRAF/SKCM.
- One target (KRAS) traced end to end — dataset to method to rule to verdict — to show the results are auditable.
- The cards that are wired today, with their data source and the evidence each one produces (below), so we're not overstating coverage.

## Cards wired today

Each sub-skill reads one or more evidence cards. A card is a contract: it names a data source, the method that turns that data into a summary, and the categorical it emits (which is what the rules then interpret). These are the cards that return real data now.

Note on presence: "expression" is not one thing. Two of the presence cards measure **RNA** (DepMap cell-line transcriptomes and TCGA tumor RNA-seq); one measures **protein** (CPTAC mass-spec). They can disagree — a target can be RNA-high but protein-low — so the doc keeps them separate rather than collapsing both into "expressed." RNA presence is wired now; protein presence is landing. This is the substance behind Decision 2.

| Sub-skill | Card | Data source | Evidence it produces |
|---|---|---|---|
| tumor-presence | expression-distribution | DepMap 26Q1 (cell-line **RNA**) | `expression_class` (RNA) — broadly high / moderate / lineage-restricted / low |
| tumor-presence | expression-tumor-vs-adjacent | TCGA tumor-vs-adjacent (**RNA-seq**) | RNA tumor-vs-normal fold-change + q |
| tumor-presence | protein-presence-cptac | CPTAC (**protein**, mass-spec) | protein-level tumor elevation (partial — data landing) |
| tumor-selectivity | tumor-vs-normal-selectivity | COADREAD DGE sensitivity product (**RNA**) | `selectivity_class` (RNA) — selective / discordant / not-selective |
| functional-requirement | pan-cancer CRISPR + RNAi dependency | DepMap 26Q1 (Chronos + DEMETER) | dependency distribution + CRISPR/RNAi concordance |
| functional-requirement | dependency-lineage-selectivity | DepMap 26Q1 | `enrichment_class` — pan-essential / lineage-selective / non-dependent |
| mechanism-and-pharmacology | signaling-network-mechanism | SIGNOR (+ CollecTri, Reactome) | `network_class` + candidate MoA classes |
| genomic-alteration-profile | mutation-stratified-dependency | DepMap 26Q1 (mutant vs WT) | `mutation_stratification_class` — e.g. mutant strongly dependent |
| genomic-alteration-profile | mutation-hotspot-frequency | GDC / TCGA MC3 tumor MAF | hotspot frequency + top variants |
| genomic-alteration-profile | copy-number-distribution | DepMap 26Q1 (copy number) | `copy_number_class` — amplified / neutral / deleted |
| differentiation-landscape | co-mutation-and-mutual-exclusivity | TCGA MC3 + GENIE (Fisher scan) | `cooccurrence_class` — co-occurring / mutually-exclusive / both |
| tractability-small-molecule | prism-compound-activity | DepMap PRISM | `activity_class` + PRISM/CRISPR concordance + predictability |

**Partial (data landing or method pending):**

| Sub-skill | Card | Gap |
|---|---|---|
| tumor-presence | protein-presence-cptac | CPTAC protein parquet in flight (PR pending) |
| surface-modality-fit | surface-topology, surfaceome-family, structure-features, abundance, adc-tce-fit | most surface derived products not yet on S3 |
| on-target-safety-liability | gnomad-lof-constraint | gnomAD source data landed; reader method not built yet |

**Not built (cards not designed):** combo/resistance, translational-readiness.

Every data source above is referenced by manifest ID, not a file path — so each number carries its release pin and md5 automatically.

## What we need input on

| # | Topic | Question |
|---|-------|----------|
| 1 | Targets | Stick with the three textbook targets, or add a less obvious ODDU target plus one deliberately weak case to show a hold or veto? |
| 2 | Data | Show RNA-only presence as-is, or land CPTAC protein data first? ODDU cares about protein for modality decisions. |
| 3 | Cards | Show the full profile, or spotlight three strong cards? Is any card weak enough that we'd rather leave it out? |
| 4 | Plots | Standardize on one Takeda plot style and a single at-a-glance summary figure? |
| 5 | Nomination bar | What should justify nominate vs hold vs veto? Right now the LLM makes that call within prompt guidance. Do we want explicit rules instead — e.g. veto if the target is pan-essential — the way we already encode judgment at the card level? |

Point 5 is the one that matters most. It decides whether the nomination is LLM judgment we choose to trust, or logic we can audit. The other four are about how we present things.

## Caveats (not blockers for this review)

- A few verdicts currently read "insufficient" because of a rule-matching bug, not missing data. That's being fixed separately (PR #60); the KRAS example will be regenerated after it merges.
- The prompt hash isn't yet stable across separate runs, so it works as a per-run fingerprint but not yet as a drift alarm. Fix is pinning `PYTHONHASHSEED`.
- The safety verdict is a real data gap — the gnomAD method isn't built yet.

## Appendix — full wiring map

For anyone who wants to trace a specific number, this is the complete chain for every card the composer touches: the data source it reads, the method that turns that data into a summary and plots, the categorical it emits, and how many interpretation rules read that categorical. The chain is always the same shape:

```
data-catalog manifest → analysis-methods reader → card categorical + plots → interpretation rules → sub-verdict
```

Two things hold across the whole table. First, every data source is a manifest ID (release-pinned, md5-checked), never a bare file path. Second, the method only computes the categorical; the therapeutic judgment lives entirely in the rules, which are version-controlled YAML with a human-readable rationale on each rule.

### Wired cards (return real data today)

| Card | Data source | Method | Emits | Plots | Rules |
|---|---|---|---|---|---|
| expression-distribution | DepMap 26Q1 (cell-line **RNA**) | depmap-expression-distribution | `expression_class` (RNA) | density, per-lineage strip, ranked waterfall | 5 |
| expression-tumor-vs-adjacent | TCGA tumor-vs-adjacent (**RNA-seq**) | dge-deseq2 | RNA fold-change + q | volcano / MA | — |
| tumor-vs-normal-selectivity | COADREAD DGE sensitivity product | dge-tumor-vs-normal-selectivity | `selectivity_class` | selectivity + pan-tissue landscape | 6 |
| pan-cancer-crispr-dependency-distribution | DepMap 26Q1 (Chronos) | depmap-chronos-distribution | dependency distribution | distribution plot | (with below) |
| pan-cancer-rnai-dependency-distribution | DepMap 26Q1 (DEMETER2) | depmap-demeter-distribution | RNAi distribution | distribution plot | (with below) |
| crispr-rnai-dependency-concordance | DepMap 26Q1 | depmap-crispr-rnai-concordance | `concordance_class` | — | 5 |
| dependency-lineage-selectivity | DepMap 26Q1 (Chronos) | depmap-chronos | `enrichment_class` | forest, per-lineage strip | 4 |
| signaling-network-mechanism | SIGNOR (+ CollecTri, Reactome) | signor-mechanism-network | `network_class`, MoA classes | network summary | 5 |
| mutation-stratified-dependency | DepMap 26Q1 (mutant vs WT) | depmap-mutation-stratified | `mutation_stratification_class` | mut-vs-WT strip, per-hotspot Chronos | 6 |
| mutation-hotspot-frequency | GDC / TCGA MC3 tumor MAF | gdc-somatic-hotspot | hotspot frequency + top variants | — | — |
| copy-number-distribution | DepMap 26Q1 (copy number) | depmap-cn-distribution | `copy_number_class` | density, per-lineage strip, waterfall | 5 |
| co-mutation-and-mutual-exclusivity | TCGA MC3 + GENIE (Fisher scan) | cooccurrence-fisher-pancohort | `cooccurrence_class` | — (forest planned) | 8 |
| prism-compound-activity | DepMap PRISM | depmap-prism-activity | `activity_class` | top-compounds bar, per-lineage bar, vocab panel | 9 |
| prism-crispr-concordance | DepMap PRISM (v4) | depmap-prism-crispr-concordance | `crispr_prism_concordance_class` | — | 7 |
| dependency-predictability | DepMap predictability | depmap-predictability | `feature_class` | — | 5 |

### Partial cards (data landing or method pending)

| Card | Data source | Method | Emits | Rules | Gap |
|---|---|---|---|---|---|
| protein-presence-cptac | CPTAC (**protein**, mass-spec) | cptac-protein-deg | `protein_expression_class` | — | parquet in flight |
| surface-topology-and-ptm | TMbed topology predictions | topology-predictions-tmbed | `topology_class` | 6 | derived product pending |
| surfaceome-family-classification | 4-source surfaceome fusion | surfaceome-family-fusion | `family_class` | 4 | derived product pending |
| structure-features-static | PDB + AlphaFold features | structure-features-static | `alphafold_confidence_class` | 2 | source manifests not re-landed |
| surface-abundance-density | CPTAC protein / HPA IHC | (HPA reader) | `hpa_ihc_intensity_class` | — | HPA dispatcher not built |
| adc-tce-modality-fit | composed (surface cards above) | adc-tce-modality-fit | `adc_grade` / `tce_grade` | 5 | depends on the surface cards |
| gnomad-lof-constraint | gnomAD constraint snapshot | gnomad-constraint-lookup | `constraint_class` | 3 | reader method not built |

### Not built (cards not designed)

combo-crispr-screen, resistance-emergence-signature (combo/resistance); models-registry, pd-assay-catalog, imaging-tracer-catalog (translational-readiness); fusion-rearrangement-landscape (placeholder inside genomic-alteration-profile).

### The rule layer

Rules live in two files under `target-contracts/interpretation-rules/`: `intracellular-intrinsic.rules.yaml` (96 rules) and `surface-intrinsic.rules.yaml` (20 rules). A rule fires when a card emits a specific categorical, and maps it to a per-modality signal (`killer` / `supportive` / `neutral` / `insufficient`) with a written rationale — often citing a drug precedent. A rule marked `dominant` can anchor a sub-verdict on its own. Each sub-skill then resolves its fired rules into one categorical sub-verdict in a fixed rank order; that is the part the LLM never touches.
