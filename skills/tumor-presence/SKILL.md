---
name: tumor-presence
description: |
  Focused question skill — "Is target X present in indication Y's tumor tissue,
  and how does it distribute across cancer cell lines vs. tumor samples, at RNA,
  protein, and single-cell level?"

  Consumes 14 cards across three measurement layers (bulk RNA, bulk protein MS,
  single-cell RNA), grouped by role:

    VERDICT-BEARING (7) — feed the rank-ordered presence ladders:
      - cellline-rna-distribution        cell-line RNA (pan-cancer TPM distribution)
      - tumor-rna-vs-adjacent            tumor RNA-seq DEG vs paired-adjacent
      - tumor-rna-distribution           per-sample tumor RNA distribution
      - tumor-protein-abundance-cptac    tumor WHOLE-CELL-LYSATE protein abundance (CPTAC per-cohort, TMT-MS)
      - cellline-protein-abundance       cell-line WHOLE-CELL-LYSATE protein abundance (DepMap/Gygi TMT-MS)
      - tumor-elevation-breadth          pan-cancer K-of-N tumor-elevation (target-grain)
      - tumor-scrna-celltype-expression  single-cell per-compartment tumor presence

    DISPLAY-ONLY facets (5) — additive context, feed NO ladder (verdict byte-stable):
      - tumor-rna-distribution-by-subtype   per-subtype panorama (per-indication strata: COADREAD
                                            molecular subtypes CMS/CIMP/MSI/sidedness/stage; LUAD & NSCLC
                                            driver-mutation strata EGFR/KRAS/ALK/HER2/BRAF; else
                                            subtype_axis_available:false)
      - cellline-rna-distribution-by-subtype  cell-line RNA by DepMap driver/molecular subtype (COADREAD proof)
      - expression-purity-confound          tumor-intrinsic vs stromal/immune signal
      - cellline-rna-protein-concordance    is RNA an adequate protein proxy? (cell-line arm)
      - rna-protein-concordance-tumor       is RNA an adequate protein proxy? (patient-tumor CPTAC arm)

    NORMAL-TISSUE SAFETY COMPARATORS (2) — verdict-inert; they FRAME the presence
    read, but the safety VERDICT itself is owned by on-target-safety-liability:
      - normal-tissue-liability          HPA-IHC normal-tissue comparator (protein_ihc/normal)
      - sc-normal-celltype-expression    scRNA cell-type-resolved normal comparator (sc_rna/normal)

  Fires the expression-* / protein-* / sc-expression-* rules over three measurement
  ladders (bulk_rna, bulk_protein_ms, sc_rna) and emits a data-package with a
  rank-ordered presence verdict PLUS one sub-verdict per (measurement, sample_context).

  Use for questions like "is EPCAM expressed in CRC?", "how does MET distribute
  across colon cell lines?", "is CDX2 tumor-elevated relative to adjacent margin?"

  This answers a Phase-A question (presence) — distinct from Phase-B (selectivity
  vs. normals), which is `tumor-selectivity`. Biology-first output; modality is a
  POST-HOC lens exposed via the optional --modality flag.

metadata:
  version: 1.13.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [A]
  cards_used:
    # VERDICT-BEARING (7) — feed the presence ladders
    - cellline-rna-distribution
    - tumor-rna-vs-adjacent
    - tumor-protein-abundance-cptac
    - cellline-protein-abundance
    - tumor-elevation-breadth
    - tumor-rna-distribution
    # DISPLAY-ONLY facets (5) — additive context, feed no ladder (verdict byte-stable)
    - tumor-rna-distribution-by-subtype
    - cellline-rna-distribution-by-subtype
    - expression-purity-confound
    - cellline-rna-protein-concordance
    - rna-protein-concordance-tumor
    # VERDICT-BEARING single-cell (sc_rna/tumor)
    - tumor-scrna-celltype-expression
    # NORMAL-TISSUE SAFETY COMPARATORS (2) — verdict-inert
    - normal-tissue-liability
    - sc-normal-celltype-expression
  # measurement_type claims (DATA_TO_SKILL_CONTRACT Rule 3). RNA, patient CPTAC protein,
  # and cell-line MS protein are DISTINCT measurement types — the multi-layer presence
  # pattern is surfaced side-by-side, never averaged. tumor_elevation_breadth is the
  # DERIVED target-grain roll-up over tumor_protein_abundance (breadth over indications
  # for one target). expression_purity_confound is an additive, verdict-inert render facet.
  #
  # MEASUREMENT SCOPE (objective-declaration discipline): the protein layers (CPTAC + DepMap/Gygi)
  # quantify WHOLE-CELL-LYSATE protein by TMT-MS — i.e. whether the protein is PRODUCED, aggregated
  # over all subcellular compartments. They do NOT measure plasma-membrane / surface-accessible
  # protein. This skill therefore answers "is the target PRESENT at RNA / total-protein / single-cell
  # level", NOT "is it a surface-accessible antigen at a dosable density". Surface topology, absolute
  # antigen density, and shed-ectodomain liability are DISTINCT questions owned by surface-modality-fit
  # (and on-target-safety-liability); do not read a `protein_present` sub-verdict as a surface-antigen
  # readiness call.
  measurement_types_pulled:
    - cell_line_rna_expression
    - tumor_vs_adjacent_expression
    - tumor_protein_abundance
    - cell_line_protein_abundance
    - tumor_elevation_breadth
    - tumor_expression_distribution
    - expression_purity_confound
    - rna_protein_concordance             # BOTH the cell-line arm AND the tumor arm — same type, different grain
    - sc_tumor_celltype_expression
    - sc_normal_celltype_expression
    - normal_tissue_protein_breadth       # normal-tissue-liability HPA-IHC comparator (protein_ihc/normal)
  rules_scope:
    - cellline-rna-distribution
    - tumor-rna-vs-adjacent
    - tumor-rna-distribution              # tumor-expression-* rules → _EXPRESSION_RANK (VERDICT-BEARING)
    - tumor-protein-abundance-cptac
    - cellline-protein-abundance
    - tumor-elevation-breadth
    - tumor-scrna-celltype-expression     # sc-expression-* rules → _SC_RNA_RANK
  synthesis:
    - rule_engine
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  optional_lenses:
    - modality
  status: wired
---

# tumor-presence

## What this skill does

- Fetches the 14 cards via the compose-dashboard live-reader dispatchers — the exact same
  read path the composed engines use, so there is no computation drift.
- Fires each card's rules on the `intracellular_intrinsic` axis across THREE measurement ladders
  (`_EXPRESSION_RANK` / `_PROTEIN_RANK` / `_SC_RNA_RANK`, keyed by the card's `measurement`), then
  emits BOTH a collapsed `presence_verdict` AND one sub-verdict per `(measurement, sample_context)`
  bucket (`presence_verdict_by_modality`). The 4 display-only facets + 2 normal comparators feed no
  ladder (verdict byte-stable).
- Emits a data-package output tree with:
  - `decision.json` — `presence_verdict` + `presence_verdict_by_modality` + fired rules + provenance
  - `summary.yaml` — per-card summary dicts
  - `tables/` — per-card summary_stats CSVs
  - `figures/` — populated per-card if a card emitter is wired
  - `provenance.yaml` — audit anchor including `invoked_lenses`

## Verdict resolution (rank-ordered collapse)

The collapsed `presence_verdict` is the highest-ranked fired rung of `_VERDICT_RANK`, built from the
three measurement ladders (`run.py`) as:

1. **all measured PRESENCE-POSITIVES** — expression, then protein, then sc_rna (RNA is the backbone,
   so a positive-RNA target's verdict is byte-stable). Positives = present (supportive/neutral-present).
2. **then all measured PRESENCE-NEGATIVES** — the opposing/killer reads (down-regulated, broadly-low,
   protein-not-detected) across the same modality order. A measured positive in ANY modality therefore
   outranks a measured negative in another — a cell-line-RNA killer no longer buries a measured
   tumor-protein/sc positive.
3. **then coverage GAPS** — `data_unavailable` plus tumor-vs-adjacent `not_informative` (a flat
   differential is a coverage gap, not a measured negative).
4. else → `insufficient` (nothing fired).

The per-`(measurement, sample_context)` buckets rank WITHIN each bucket using that measurement's ladder
(they are NOT collapsed). `driving_rule_id` is captured in the headline so a reviewer can trace the
verdict to the exact rule in `intracellular-intrinsic.rules.yaml`.

NOTE — inline verdict, BY DESIGN: tumor-presence resolves its verdict inline in `run.py` rather than via
a `*.resolver.yaml`. The collapsed spine AND the per-bucket decomposition derive from the same ladders,
and the resolver grammar (no grouping) cannot express that bucket decomposition. The ladder is instead
frozen by the golden-spine test + the regression matrix (the golden-oracle guard a resolver migration
would otherwise provide).

## Per-(measurement, sample_context) sub-verdicts

Beyond the collapsed `presence_verdict`, the skill emits `presence_verdict_by_modality` keyed by
`measurement/sample_context` (e.g. `bulk_rna/cell_line`, `bulk_rna/tumor`, `bulk_protein_ms/tumor`,
`sc_rna/tumor`).

A **target-only** query honestly reads cell-line buckets as `measured` and the per-indication tumor
buckets as `data_unavailable` — EXCEPT `bulk_protein_ms/tumor`, which `tumor-elevation-breadth` keeps
`measured` even without an indication (it rolls up CPTAC over all cohorts). That is the one
tumor-context presence signal a target-only query gets.

The **`sc_rna/tumor`** bucket is card-backed by `tumor-scrna-celltype-expression`. It reads `measured`
for the indications with a landed single-cell pseudobulk product carrying a per-cell malignant
annotation (**COADREAD, NSCLC, LUSC, PAAD, HNSC, KIRC, OV, STAD** — see `INDICATION_TO_PRODUCT` in
`methods/sc_tumor_expression_celltype/read.py`) and `data_unavailable` for every other indication (an
honest capability ceiling, never a coarser fall-back). The matching `sc_rna/normal` comparator
(`sc-normal-celltype-expression`) covers each indication's tumor-of-origin tissue PLUS an always-on
critical-organ panel (heart, liver, kidney, bone marrow) queried for every indication.

The single-cell bucket carries what bulk cannot, surfaced in the headline as verdict-inert detail:
per-cell `detection_fraction` and malignant-vs-microenvironment attribution (`sc_expression_class` ∈
malignant_broadly_detected / malignant_subset_detected / microenvironment_dominant / broadly_low /
data_unavailable); the full per-compartment vector (`sc_per_compartment` / `sc_compartment_detection` —
detection + abundance per malignant/stromal/immune/endothelial/epithelial_normal/other); a
cancer-associated-fibroblast contrast (`sc_caf_vs_malignant_class` — a target expressed mainly on CAFs
looks tumor-present in bulk but is a stromal signal); and malignant-expression homogeneity
(`sc_tce_homogeneity_class`, a T-cell-engager prerequisite — rule-keyed only on the surface axis, shown
here as context). The normal comparator is summarized as an organ-aware liability tier
(`sc_normal_safety_essential_class`) plus a ranked `sc_normal_top_essential_cell_types` (the full
per-cell-type footprint is retained verbatim as `sc_normal_safety_essential_flags`). See
[CONTRACT.md](CONTRACT.md) § "Single-cell layer" for the full field list and rationale.

## Headline lens: tumor tissue outranks the pan-cancer cell-line proxy

The collapsed `presence_verdict` is the first rung that fires in `_EXPRESSION_RANK`, where the
**TUMOR-tissue rungs outrank the pan-cancer CELL-LINE distribution rungs** (`tumor_broadly_expressed` /
`tumor_moderately_expressed` sit above the cell-line `lineage_restricted` + `broadly_moderate`).
Rationale: for antigens that **de-differentiate in 2D culture** (EPCAM, FOLR1, CDH17, TACSTD2 …) the
pan-cancer cell-line median collapses while the tumor tissue reads top-percentile — a cell-line-anchored
headline would UNDERSTATE tumor presence. Cell-line `broadly_high` is kept at the top (when both lenses
agree the verdict is unchanged), and a per-indication `tumor_sparsely_expressed` (NEUTRAL) stays below
the cell-line positives. This ranking is backed by a 43-pair backtest across 10 indications (23 flips,
all → `tumor_broadly_expressed`, zero dangerous flips) frozen in `test_reanchor_flip_matrix.py`.

Verdict-inert lens fields (they feed no rule):
- **`cell_line_vs_tumor_discordant`** — a STANDING INVARIANT GUARD: it should be `False` for every
  target (the tumor lens now wins the headline whenever it out-tiers cell-line). A `True` value would
  signal the ladder regressed.
- **`headline_lens`** — the `measurement/sample_context` bucket whose `driving_rule_id` won the
  collapsed verdict (e.g. `bulk_rna/tumor` for a de-differentiating antigen).
- **`presence_interpretation_note`** — a human/LLM-facing sentence, populated only in the (now
  guard-only) discordant case.

Always consult `presence_verdict_by_modality` for the per-lens breakdown; the collapsed headline is a
roll-up and the tumor vs cell-line vs protein vs single-cell lenses each carry distinct evidence.

## What this skill does NOT do

- Does NOT recompute the DGE — reads pre-computed derived products.
- Does NOT compare tumor to GTEx-population-normal — that's `tumor-selectivity`.
- By default emits NO narrative (the deterministic verdict + fields only). An OPT-IN `--synthesize`
  flag attaches an LLM narration under `decision["llm_synthesis"]`. It is a SIBLING key — it never
  mints or flips a verdict, and the decision is byte-identical without the flag (two-slot design; see
  `_skills_common/synthesis.py`). For the fully composed cross-skill narrative, use `target-profile`.

## Command-line flags

Set by the skill's `run.py` via the shared dispatcher (`_skills_common/dispatcher.py`):

| Flag | Purpose |
|------|---------|
| `--target` (required) | HGNC gene symbol, uppercase (e.g. `EPCAM`). |
| `--indication` | AACR OncoTree code, uppercase (e.g. `COADREAD`). Optional; omitting it runs a target-only query (tumor buckets read `data_unavailable`, except the breadth-backed protein bucket). |
| `--out` (required) | Output directory for the data-package tree. |
| `--modality <M>` | OPTIONAL post-hoc modality lens (small_molecule / degrader / adc / bite / antibody). |
| `--synthesize` | OPT-IN LLM narration under `decision["llm_synthesis"]`. Needs Bedrock (see synthesis env note below); degrades to a note if unavailable. Never touches the verdict spine. |
| `--synthesis-model <id>` | Override the Bedrock synthesis model id (default: framework Opus). |
| `--subtype <S>` | With `--synthesize`: foreground one molecular subtype (e.g. `MSI_H`) in the narration. Emphasis-only — no spine change. |
| `--subtypes <a,b>` | Inert for tumor-presence (no subtype-panorama resolver wired); a complete no-op. |
| `--verdict-only` | FAST mode: read only verdict-relevant cards, skip enrichment reads + synthesis. Verdict spine byte-identical. No-op for tumor-presence (no verdict-card subset declared → reads all cards). |
| `--emit-envelope` | OPT-IN: ALSO write a governance-grade `evidence_package.json` beside `decision.json`. Purely additive — `decision.json` byte-identical. |
| `--data-mode <m>` / `--release-pin <p>` | Carried into the emitted envelope's governance block only. Inert unless `--emit-envelope` is set. |

## How Claude invokes this skill

When called as `/tumor-presence`, Claude should:

1. Extract `target` (HGNC gene symbol, uppercase) and `indication` (AACR OncoTree code, uppercase —
   e.g. COADREAD, LUAD, BRCA) from the user's prompt. Ask if either is missing or ambiguous.
2. Pick an `out` directory. Default: `/tmp/tumor-presence/{target}-{indication}`.
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/tumor-presence/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
   Add `--modality <M>` if the user names a modality; otherwise omit.
   Add `--synthesize` if the user wants an LLM narration (optional; needs Bedrock access —
   degrades to a note under `llm_synthesis` if unavailable, leaving the deterministic verdict intact).

   NOTE (synthesis env): `--synthesize` requires an interpreter with `anthropic[bedrock]` AND
   `BEDROCK_AWS_PROFILE` set to a Bedrock-entitled profile (e.g. `cmp-dev`), which is a DIFFERENT
   account from the `cbg` profile used for the S3 card reads (the LLM layer resolves the Bedrock
   profile's frozen creds internally — `AnthropicBedrock` does not honor `AWS_PROFILE`). The DEFAULT
   pixi env does NOT include `anthropic`, so `--synthesize` under it SILENTLY DEGRADES: `llm_synthesis`
   becomes a `_synthesis_error` note and the run still exits 0 (the deterministic spine is unaffected).
   Invoke with an interpreter that has `anthropic[bedrock]` and both profiles available:
   ```
   export AWS_PROFILE=cbg BEDROCK_AWS_PROFILE=cmp-dev && \
   python3 .../tumor-presence/scripts/run.py --target <T> --indication <I> --out <D> --synthesize
   ```
   Add `--subtype <SUBTYPE>` (with `--synthesize`) if the user asks about a specific molecular subtype
   (e.g. `--subtype MSI_H`): the narration foregrounds that stratum. Emphasis-only — no spine change;
   if the subtype is not among the computed strata, the narration says so rather than inventing a
   position.
4. Read `<OUT_DIR>/decision.json`, present the headline (`presence_verdict` + `driving_rule_id` +
   per-card summary highlights) inline. If `cell_line_vs_tumor_discordant` is `true`, surface
   `presence_interpretation_note` and the `bulk_rna/tumor` sub-verdict alongside the headline word — the
   one-word verdict understates tumor-tissue presence in that case. If `--synthesize` was used, the
   `llm_synthesis` block carries the narration (tagged `_source: llm_synthesized`).

See [README.md](README.md) for a first-run setup + example command aimed at new contributors.
