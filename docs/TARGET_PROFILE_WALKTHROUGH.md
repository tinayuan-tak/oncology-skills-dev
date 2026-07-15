# Target-Profile Skill — Review & Decisions
**Owner:** Ryan Abo · **Audience:** ODDU + oncology comp-bio · **Draft, 2026-07-14**

## Objective
We want to show the `target-profile` skill to ODDU and settle its design with comp-bio input. The skill answers a single question — should we nominate target X in indication Y? — and produces an evidence package where each verdict traces back to a specific dataset and a version-controlled rule. The narrative text is written by an LLM, but it's labeled as such and kept separate from the verdicts. This is a decision doc, not a technical tour: it says what we plan to show, then asks for input.

## How it works
Nine sub-skills each read their evidence and produce a rule-based verdict. An LLM then writes a summary over those verdicts and gives a recommendation (nominate / hold / veto). The verdicts and the prose are stored separately, so the verdicts stay fixed even when the wording changes between runs.

```
9 sub-skills  →  rule-based verdict each
      ↓
LLM synthesis  →  summary + nominate/hold/veto  (labeled, stamped)
      ↓
nomination.json · target_profile.md · provenance.yaml · figure
```

## Plan for the demo
Show `target-profile` running end to end as currently built — the full 9-sub-skill fan-out, on a small target set. **Target set: TBD** (see Decision 1). The set should exercise the whole skill as-is: the wired sub-skills returning real verdicts, and the partial ones honestly reporting `insufficient` where data isn't landed yet, so the demo reflects the true state rather than a curated best case.

- Run the full composed profile per target (not a trimmed subset of cards).
- Trace one target end to end — dataset → method → rule → verdict — to show the results are auditable.
- Keep the coverage honest: wired sub-skills show real calls; partial ones show `insufficient` with the reason.

## Questions the skill evaluates
Each sub-skill answers one question. This is the full set the composed profile assesses, mapped to the high-level data behind it. Wired = returns a real verdict today; Planned = data or method still landing.

| Question | Sub-skill | High-level data | Status |
|---|---|---|---|
| Is the target expressed in the tumor? | tumor-presence | DepMap RNA + TCGA RNA-seq + CPTAC protein | wired (RNA + protein) |
| Is it selective for tumor vs normal? | tumor-selectivity | TCGA + GTEx (recount3) expression | wired |
| Is the tumor dependent on it? | functional-requirement | DepMap CRISPR + RNAi | wired |
| What's the mechanism / MoA context? | mechanism-and-pharmacology | SIGNOR + CollecTri + Reactome | wired |
| How is it genomically altered (mutation + copy number)? | genomic-alteration-profile | DepMap + TCGA/GDC mutation + copy number | wired (fusion planned) |
| What co-occurs with or excludes it? | differentiation-landscape | TCGA MC3 + GENIE co-mutation | wired |
| Is it druggable by a small molecule? | tractability-small-molecule | DepMap PRISM + CRISPR | wired |
| Does the surface biology support a biologic (ADC/TCE)? | surface-modality-fit | surfaceome / topology / structure | planned (surface products pending) |
| Is there an on-target safety liability? | on-target-safety-liability | gnomAD LoF constraint | planned (method pending) |

## Cards wired today
Each sub-skill reads one or more evidence cards. A card names a data source, the method that turns that data into a summary, and the categorical it emits (which is what the rules interpret). These return real data now.

| Sub-skill | Card | Data source | Evidence it produces |
|---|---|---|---|
| tumor-presence | expression-distribution | DepMap 26Q1 (cell-line RNA) | `expression_class` — broadly high / moderate / lineage-restricted / low |
| tumor-presence | expression-tumor-vs-adjacent | TCGA tumor-vs-adjacent (RNA-seq) | tumor-vs-normal fold-change + q |
| tumor-presence | protein-presence-cptac | CPTAC (protein, mass-spec) | `protein_expression_class` — protein-level tumor elevation |
| tumor-selectivity | tumor-vs-normal-selectivity | TCGA + GTEx (recount3) | `selectivity_class` — selective / discordant / not-selective |
| functional-requirement | pan-cancer CRISPR + RNAi dependency | DepMap 26Q1 (Chronos + DEMETER) | dependency distribution + CRISPR/RNAi concordance |
| functional-requirement | dependency-lineage-selectivity | DepMap 26Q1 | `enrichment_class` — pan-essential / lineage-selective / non-dependent |
| mechanism-and-pharmacology | signaling-network-mechanism | SIGNOR (+ CollecTri, Reactome) | `network_class` + candidate MoA classes |
| genomic-alteration-profile | mutation-stratified-dependency | DepMap 26Q1 (mutant vs WT) | `mutation_stratification_class` |
| genomic-alteration-profile | mutation-hotspot-frequency | GDC / TCGA MC3 tumor MAF | hotspot frequency + top variants |
| genomic-alteration-profile | copy-number-distribution | DepMap 26Q1 (copy number) | `copy_number_class` — amplified / neutral / deleted |
| differentiation-landscape | co-mutation-and-mutual-exclusivity | TCGA MC3 + GENIE (Fisher scan) | `cooccurrence_class` — co-occurring / mutually-exclusive / both |
| tractability-small-molecule | prism-compound-activity | DepMap PRISM | `activity_class` + PRISM/CRISPR concordance + predictability |

**Partial (data landing or method pending):** surface-modality-fit cards — surface-topology, surfaceome-family, structure-features, abundance, adc-tce-fit (surface products not on S3); gnomad-lof-constraint (source landed, reader method not built).

**Not built (cards not designed):** combo/resistance, translational-readiness.

Every data source is referenced by manifest ID, not a file path — so each number carries its release pin and md5 automatically.

## What we need input on
| # | Topic | Question |
|---|-------|----------|
| 1 | Targets | Which target set for the demo? Textbook targets (KRAS/EGFR/BRAF), or add a less obvious ODDU target plus one deliberately weak case to show a hold or veto? |
| 2 | Data | Protein presence (CPTAC) is now wired alongside RNA. How do we present it? Unstratified bulk dilutes amplicon-restricted markers (ERBB2 reads `ns` in BRCA), so a naive protein panel can look weaker than the biology — do we caveat, or stratify? |
| 3 | Cards | Show the full profile, or spotlight three strong cards? Is any card weak enough that we'd rather leave it out? |
| 4 | Plots | Standardize on one Takeda plot style and a single at-a-glance summary figure? |
| 5 | Nomination bar | What should justify nominate vs hold vs veto? Right now the LLM makes that call within prompt guidance. Do we want explicit rules instead — e.g. veto if the target is pan-essential — the way we already encode judgment at the card level? |

Point 5 matters most: it decides whether the nomination is LLM judgment we choose to trust, or logic we can audit. The other four are about presentation.

## Caveats (not blockers for this review)
- A few verdicts currently read "insufficient" because of a rule-matching bug, not missing data. Fixed separately (PR #60, merged); the demo run will be regenerated.
- The prompt hash isn't yet stable across separate runs — works as a per-run fingerprint but not yet a drift alarm. Fix is pinning `PYTHONHASHSEED`.
- The safety verdict is a real data gap — the gnomAD method isn't built yet.

## Appendix — full sub-skill detail (for review)
One block per sub-skill: the wired card(s), the data source, the method that computes it, the categorical emitted, the plots, and the number of interpretation rules that read it. The chain is always: manifest → method → card categorical + plots → rules → sub-verdict. The method only computes the categorical; therapeutic judgment lives entirely in the rules (version-controlled YAML with a written rationale per rule, `killer` / `supportive` / `neutral` / `insufficient` signals per modality).

### tumor-presence (wired; RNA + protein)
- **expression-distribution** — DepMap 26Q1 cell-line RNA → `depmap-expression-distribution` → `expression_class` · plots: density, per-lineage strip, ranked waterfall · 5 rules.
- **expression-tumor-vs-adjacent** — TCGA tumor-vs-adjacent RNA-seq → `dge-deseq2` → fold-change + q · plots: volcano / MA.
- **protein-presence-cptac** — CPTAC protein mass-spec → `cptac-protein-deg` → `protein_expression_class` · wired (parquet + manifest + method + dispatcher all on main; returns real per-cohort protein tumor-vs-normal). Unstratified bulk dilutes amplicon-restricted markers (e.g. ERBB2 reads `ns` in BRCA) — documented in the CPTAC manifest.

### tumor-selectivity (wired)
- **tumor-vs-normal-selectivity** — TCGA + GTEx (recount3) → `dge-tumor-vs-normal-selectivity` → `selectivity_class` · plots: selectivity + pan-tissue landscape · 6 rules.

### functional-requirement (wired)
- **pan-cancer-crispr-dependency-distribution** — DepMap 26Q1 Chronos → `depmap-chronos-distribution` → dependency distribution · plot: distribution.
- **pan-cancer-rnai-dependency-distribution** — DepMap 26Q1 DEMETER2 → `depmap-demeter-distribution` → RNAi distribution · plot: distribution.
- **crispr-rnai-dependency-concordance** — DepMap 26Q1 → `depmap-crispr-rnai-concordance` → `concordance_class` · 5 rules.
- **dependency-lineage-selectivity** — DepMap 26Q1 Chronos → `depmap-chronos` → `enrichment_class` · plots: forest, per-lineage strip · 4 rules.

### mechanism-and-pharmacology (wired)
- **signaling-network-mechanism** — SIGNOR + CollecTri + Reactome → `signor-mechanism-network` → `network_class` + MoA classes · plot: network summary · 5 rules.

### genomic-alteration-profile (wired; fusion planned)
- **mutation-stratified-dependency** — DepMap 26Q1 mutant-vs-WT → `depmap-mutation-stratified` → `mutation_stratification_class` · plots: mut-vs-WT strip, per-hotspot Chronos · 6 rules.
- **mutation-hotspot-frequency** — GDC / TCGA MC3 tumor MAF → `gdc-somatic-hotspot` → hotspot frequency + top variants.
- **copy-number-distribution** — DepMap 26Q1 copy number → `depmap-cn-distribution` → `copy_number_class` · plots: density, per-lineage strip, waterfall · 5 rules.
- **fusion-rearrangement-landscape** *(planned)* — placeholder; resolves `_missing` today.

### differentiation-landscape (wired)
- **co-mutation-and-mutual-exclusivity** — TCGA MC3 + GENIE (Fisher scan) → `cooccurrence-fisher-pancohort` → `cooccurrence_class` · plot: forest (planned) · 8 rules.

### tractability-small-molecule (wired)
- **prism-compound-activity** — DepMap PRISM → `depmap-prism-activity` → `activity_class` · plots: top-compounds bar, per-lineage bar, vocab panel · 9 rules.
- **prism-crispr-concordance** — DepMap PRISM (v4) → `depmap-prism-crispr-concordance` → `crispr_prism_concordance_class` · 7 rules.
- **dependency-predictability** — DepMap predictability → `depmap-predictability` → `feature_class` · 5 rules.

### surface-modality-fit (planned)
- **surface-topology-and-ptm** — TMbed topology predictions → `topology-predictions-tmbed` → `topology_class` · 6 rules · derived product pending.
- **surfaceome-family-classification** — 4-source surfaceome fusion → `surfaceome-family-fusion` → `family_class` · 4 rules · derived product pending.
- **structure-features-static** — PDB + AlphaFold → `structure-features-static` → `alphafold_confidence_class` · 2 rules · source manifests not re-landed.
- **surface-abundance-density** — CPTAC protein / HPA IHC → `hpa_ihc_intensity_class` · HPA dispatcher not built.
- **adc-tce-modality-fit** — composed over the surface cards → `adc_grade` / `tce_grade` · 5 rules · depends on the above.

### on-target-safety-liability (planned)
- **gnomad-lof-constraint** — gnomAD constraint snapshot → `gnomad-constraint-lookup` → `constraint_class` · 3 rules · source landed, reader method not built.

### Rule layer
Rules live in two files under `target-contracts/interpretation-rules/`: `intracellular-intrinsic.rules.yaml` (96 rules) and `surface-intrinsic.rules.yaml` (20 rules). A rule fires when a card emits a specific categorical and maps it to a per-modality signal with a written rationale, often citing a drug precedent. A rule marked `dominant` can anchor a sub-verdict on its own. Each sub-skill resolves its fired rules into one categorical sub-verdict in a fixed rank order — the part the LLM never touches.
