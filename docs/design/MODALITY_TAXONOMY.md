# Expression-evidence modality taxonomy

**Status:** design, Slice X (this PR) — landing the taxonomy + tagging the current expression-family cards. Card additions + verdict refactor land in later slices.

## Why this exists

The expression cards were labeled by biological question (level, tumor-vs-normal, selectivity, lineage-restriction) but not by measurement modality. A gene can be bulk-RNA-high in a tumor cohort while being single-cell-restricted, or bulk-RNA-detectable in a normal tissue while IHC-negative (DLL3, CLDN18.2 patterns). Averaging these away gives a false-precision "the target is expressed" answer. The taxonomy makes the modality first-class so the skill can surface concordance and disagreement instead of collapsing them.

## The 4 modalities

| Modality tag | What it measures | Population level | Data character | Coverage today |
|---|---|---|---|---|
| `bulk_rna` | transcript abundance from bulk RNA-seq | tissue / cohort average | log2(TPM+1), DGE logFC | 4 cards wired |
| `bulk_protein_ms` | protein abundance from mass-spec | tissue / cohort average | log2 ratio tumor-vs-normal | 2 cards wired |
| `sc_rna` | transcript abundance per cell type | single-cell resolution | per-cell UMI / normalized counts | 0 cards — gap |
| `protein_ihc` | protein staining per tissue | pathologist-scored, spatial | Not-detected / Low / Medium / High | 0 cards — gap |

Cards outside the expression family (dependency, mutation, mechanism, tractability, safety) omit `measurement:` entirely.

## Why per-modality sub-verdicts (not one concordance verdict)

The skill emits one verdict per modality — e.g. `{bulk_rna_verdict, bulk_protein_verdict, sc_rna_verdict, ihc_verdict}` — rather than collapsing them into one string. Rationale:
- **Honesty about what's known**: a target with `bulk_rna: supportive, ihc: data_unavailable` is a different epistemic state than `bulk_rna: supportive, ihc: supportive`, and the composer must be able to tell them apart.
- **Extensibility**: adding a 5th modality later is a schema addition, not a verdict-logic rewrite.
- **Simpler rule layer**: rules stay single-card (their current shape); no cross-card concordance rules needed. Concordance reasoning lives in the LLM synthesis prompt over the sub-verdict pattern, which is where it belongs.

## Current state after Slice X

| Card | Modality | Data source | Rules keying off it |
|---|---|---|---|
| expression-distribution | bulk_rna | DepMap 26Q1 cell-line RNA | 5 |
| expression-tumor-vs-adjacent | bulk_rna | TCGA DGE tumor-vs-adjacent (RNA-seq) | 4 |
| tumor-vs-normal-selectivity | bulk_rna | recount3 TCGA + GTEx (RNA) | 6 |
| protein-presence-cptac | bulk_protein_ms | CPTAC tumor-vs-normal (mass-spec) | 0 |
| surface-abundance-density | bulk_protein_ms | same CPTAC parquet | 0 |
| lineage-restriction-evidence | bulk_rna | HPA normal-tissue (RNA half) | 0 (legacy inline hints) |

Note the two `bulk_protein_ms` cards emit categoricals (`protein_expression_class`, `surface_density_class`) that **no rules currently consume** — the protein signal is displayed but doesn't influence any verdict. That's a Slice-Y fix, not a taxonomy fix.

## Gaps this taxonomy exposes

Named here so later slices execute against a concrete list, not memory.

**1. `protein_ihc` — no cards, no data source.** HPA IHC (Not-detected / Low / Medium / High per tissue, pathologist-scored) is the gold-standard normal-tissue-safety comparator ODDU uses for surface-modality decisions. The current `lineage-restriction-evidence` card targets the **RNA** half of HPA only; the IHC half is unrepresented. Slice-Y candidate: land the HPA-IHC source manifest + one card + associated rules.

**2. `sc_rna` — no cards, no data source.** Single-cell RNA in tumor (heterogeneity, minor-population expression, tumor-microenvironment breakdown) and in normal (bystander-cell safety) are unrepresented. Slice-Y-or-later candidate: pick an atlas (Human Cell Atlas / CellxGene / tabula sapiens for normals; Zhang et al. or Tumor Immune Cell Atlas for tumor), land the source manifest + one presence card + one bystander-safety card.

**3. `surface-abundance-density` conflates modalities.** Today it reads bulk-protein-MS (CPTAC), but the card's semantic intent ("surface abundance for modality feasibility") really wants IHC surface staining. It stays tagged `bulk_protein_ms` in Slice X (honest label of current data), but when the HPA-IHC card lands, the composer's surface-modality skill should consume BOTH — or `surface-abundance-density` should be replaced entirely by the IHC card. Slice-Y decision.

**4. Rules gaps for bulk_protein_ms.** The two protein cards emit `protein_expression_class` and `surface_density_class` with zero rules keyed off them. Adding rules is small, high-value — probably the first fix in Slice Y.

## Blast radius for Slice Y (previewing the next PR)

- `interpretation-rules/intracellular-intrinsic.rules.yaml`: add rules for `protein_expression_class`, `surface_density_class`.
- `skills/tumor-presence/scripts/run.py` (or its renamed successor): refactor `_verdict()` to emit per-modality sub-verdicts instead of one collapsed verdict.
- `skills/target-profile/scripts/run.py`: consume the new per-modality shape in `SUB_SKILL_CARDS` + `_build_synthesis_tool` schema.
- Doc updates in the `target-profile` review + the auto-generated card design docs (once the generator lands).

## What Slice X does NOT do
- No rule changes.
- No skill refactor.
- No new data sources.
- No new cards.
- No `schema_version` bump — the field is optional and backward-compatible; every existing untagged card still validates.
