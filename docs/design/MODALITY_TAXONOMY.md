# Expression-evidence modality taxonomy

**Status:** design, Slice X (this PR) — landing the taxonomy + tagging the current expression-family cards. Card additions + verdict refactor land in later slices.

## Why this exists

The expression cards were labeled by biological question (level, tumor-vs-normal, selectivity, lineage-restriction) but not by measurement modality. A gene can be bulk-RNA-high in a tumor cohort while being single-cell-restricted, or bulk-RNA-detectable in a normal tissue while IHC-negative (DLL3, CLDN18.2 patterns). Averaging these away gives a false-precision "the target is expressed" answer. The taxonomy makes the modality first-class so the skill can surface concordance and disagreement instead of collapsing them.

## The 4 modalities

| Modality tag | What it measures | Population level | Data character | Coverage today |
|---|---|---|---|---|
| `bulk_rna` | transcript abundance from bulk RNA-seq | tissue / cohort average | log2(TPM+1), DGE logFC | 4 cards wired |
| `bulk_protein_ms` | protein abundance from mass-spec | tissue / cohort average | log2 ratio tumor-vs-normal | 2 cards wired |
| `sc_rna` | transcript abundance per cell type | single-cell resolution | per-cell UMI / normalized counts | **2 cards wired** (see below) |
| `protein_ihc` | protein staining per tissue | pathologist-scored, spatial | Not-detected / Low / Medium / High | **1 card wired** (HPA-IHC comparator) |

> **Status update 2026-08-13:** the `sc_rna` and `protein_ihc` "0 cards — gap" state below reflects the
> original Slice-X snapshot and is now SUPERSEDED — the gaps in §"Gaps this taxonomy exposes" #1 and #2
> have LANDED. `sc_rna/tumor` = `tumor-scrna-celltype-expression` (verdict-bearing, #199);
> `sc_rna/normal` = `sc-normal-celltype-expression` (safety comparator, #267); `protein_ihc/normal` =
> `normal-tissue-liability` (HPA-IHC safety comparator, #213). See the updated grid + gaps section.

Cards outside the expression family (dependency, mutation, mechanism, tractability, safety) omit `measurement:` entirely.

## The orthogonal second axis: `sample_context` (added 2026-07-21)

`measurement` names the measurement LAYER (how it was measured). It does NOT say WHAT was measured — and that omission caused a real conflation: BOTH `cellline-rna-distribution` (DepMap **cell-line** RNA) and `tumor-rna-vs-adjacent` (TCGA **tumor** RNA) carry `measurement: bulk_rna`, so the skill's per-modality view bucketed them together. A target-only query (only the cell-line card fires) then read identically to a target-indication query — the tumor-contrast axis was invisibly absent, not represented.

The fix is a second, ORTHOGONAL tag: **`sample_context` ∈ {cell_line | tumor | normal}** (the biological sample). The two axes are genuinely independent — every combination is real:

| | cell_line | tumor | normal |
|---|---|---|---|
| **bulk_rna** | DepMap cellline-rna-distribution | TCGA tumor-rna-vs-adjacent / tumor-rna-distribution / tumor-vs-normal-selectivity | (GTEx, via selectivity's comparators) |
| **bulk_protein_ms** | Gygi cellline-protein-abundance | CPTAC tumor-protein-abundance-cptac / tumor-elevation-breadth | — |
| **sc_rna** | — | tumor-scrna-celltype-expression *(verdict-bearing, #199)* | sc-normal-celltype-expression *(comparator, #267)* |
| **protein_ihc** | — | — | HPA normal-tissue-liability *(comparator, #213)* |

Genuinely-empty cells (real remaining gaps): `sc_rna/cell_line`, `protein_ihc/tumor` & `/cell_line`,
`bulk_protein_ms/normal`. Entirely-absent measurement LAYERS (the grid would extend to hold them, but
no cards/data exist): single-cell PROTEIN (CITE-seq/CyTOF), SPATIAL transcriptomics/proteomics,
methylation, ATAC.

The per-modality sub-verdict view buckets by the PAIR `(measurement, sample_context)`, so a cell-line-RNA signal is never conflated with a tumor-RNA signal. A target-only query now honestly reads `bulk_rna/cell_line: broadly_moderate (measured)` alongside `bulk_rna/tumor: data_unavailable` — the collapsed headline is unchanged (still additive), but the breakdown no longer over-reads.

`sample_context` is OPTIONAL and DEFAULTS from `measurement_type` (cell_line_* → cell_line, tumor_* → tumor, normal_tissue_* → normal); `validate_cards._sample_context_check` enforces that a card declaring both agrees. Cards without a sample substrate (dependency, mutation, mechanism, tractability) omit it. This is the axis this doc previously left as uncaptured prose in the "Data source" column — now first-class.

## Why per-modality sub-verdicts (not one concordance verdict)

The skill emits one verdict per modality — e.g. `{bulk_rna_verdict, bulk_protein_verdict, sc_rna_verdict, ihc_verdict}` — rather than collapsing them into one string. Rationale:
- **Honesty about what's known**: a target with `bulk_rna: supportive, ihc: data_unavailable` is a different epistemic state than `bulk_rna: supportive, ihc: supportive`, and the composer must be able to tell them apart.
- **Extensibility**: adding a 5th modality later is a schema addition, not a verdict-logic rewrite.
- **Simpler rule layer**: rules stay single-card (their current shape); no cross-card concordance rules needed. Concordance reasoning lives in the LLM synthesis prompt over the sub-verdict pattern, which is where it belongs.

## Current state after Slice X

| Card | Modality | Data source | Rules keying off it |
|---|---|---|---|
| cellline-rna-distribution | bulk_rna | DepMap 26Q1 cell-line RNA | 5 |
| tumor-rna-vs-adjacent | bulk_rna | TCGA DGE tumor-vs-adjacent (RNA-seq) | 4 |
| tumor-vs-normal-selectivity | bulk_rna | recount3 TCGA + GTEx (RNA) | 6 |
| tumor-protein-abundance-cptac | bulk_protein_ms | CPTAC tumor-vs-normal (mass-spec) | 0 |
| surface-abundance-density | bulk_protein_ms | same CPTAC parquet | 0 |
| lineage-restriction-evidence | bulk_rna | HPA normal-tissue (RNA half) | 0 (legacy inline hints) |

Note the two `bulk_protein_ms` cards emit categoricals (`protein_expression_class`, `surface_density_class`) that **no rules currently consume** — the protein signal is displayed but doesn't influence any verdict. That's a Slice-Y fix, not a taxonomy fix.

## Gaps this taxonomy exposes

Named here so later slices execute against a concrete list, not memory.

**1. `protein_ihc` — RESOLVED (2026-08-05, #213).** HPA IHC (Not-detected / Low / Medium / High per tissue, pathologist-scored) landed as `normal-tissue-liability` — the `protein_ihc/normal` normal-tissue-safety comparator (verdict-inert in tumor-presence; the safety verdict is owned by on-target-safety-liability). `protein_ihc/tumor` + `/cell_line` remain unrepresented.

**2. `sc_rna` — RESOLVED (2026-08-04/07, #199 + #267).** Single-cell RNA in tumor landed as `tumor-scrna-celltype-expression` (the `sc_rna/tumor` bucket; VERDICT-BEARING via the skill's `_SC_RNA_RANK` — malignant-anchored detection + malignant-vs-microenvironment attribution), and in normal as `sc-normal-celltype-expression` (the `sc_rna/normal` bystander-cell safety comparator). Remaining sc gaps: `sc_rna/cell_line` (low value), and the entirely-distinct single-cell PROTEIN + spatial layers (no cards/data).

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
