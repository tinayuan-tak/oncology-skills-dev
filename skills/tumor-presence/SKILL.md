---
name: tumor-presence
description: |
  Focused question skill: "Is target X present in indication Y's tumor
  tissue, and how does it distribute across cancer cell lines vs. tumor
  samples, at RNA, protein, and single-cell level?" Consumes 13 wired cards
  (7 verdict-bearing + 4 display-only facets + 2 normal-tissue SAFETY COMPARATORS).

  VERDICT-BEARING (7 cards — feed the rank-ordered presence ladders):
    - cellline-rna-distribution           (cell-line RNA, pan-cancer TPM distribution)
    - tumor-rna-vs-adjacent      (tumor RNA-seq DEG vs paired-adjacent; COADREAD uses paired
                                         tumor-adjacent, else the tumor-vs-adjacent cell of the
                                         {indication}-dge-tumor-vs-normal-sensitivity product — NOT GTEx)
    - tumor-rna-distribution         (per-sample TUMOR RNA distribution; bulk_rna/tumor bucket.
                                         VERDICT-BEARING: its tumor-expression-* rules ARE in the
                                         bulk_rna ladder — verdicts tumor_broadly/moderately/
                                         sparsely_expressed. 2026-08-07: reclassified from display-only;
                                         the "follow-up rules PR" that would wire it HAS landed.)
    - tumor-protein-abundance-cptac            (tumor protein abundance, CPTAC per-cohort)
    - cellline-protein-abundance         (cell-line protein, DepMap/Gygi TMT-MS)
    - tumor-elevation-breadth           (pan-cancer K-of-N tumor-elevation, target-grain)
    - tumor-scrna-celltype-expression   (SINGLE-CELL per-compartment tumor presence — malignant-
                                         anchored detection + malignant-vs-microenvironment
                                         attribution; sc_rna/tumor bucket; COADREAD+NSCLC)

  DISPLAY-ONLY facets (4 cards — additive context, feed NO resolver, verdict
  byte-stable; one-directional gate):
    - tumor-rna-distribution-by-subtype (per-molecular-subtype panorama; COADREAD
                                             shard only, else subtype_axis_available:false)
    - expression-purity-confound            (is the tumor signal tumor-intrinsic or stromal?)
    - cellline-rna-protein-concordance               (is RNA an adequate protein proxy? CELL-LINE arm)
    - rna-protein-concordance-tumor          (is RNA an adequate protein proxy IN PATIENT TUMORS?
                                             CPTAC per-cohort arm — graduated 2026-08-08; the tumor
                                             rna_as_biomarker is the PREFERRED input to
                                             bulk_rna_proxy_quality, since bulk-tumor purity/stroma/
                                             post-transcriptional regulation degrade concordance far
                                             more than in cell lines. Reported SIDE-BY-SIDE with the
                                             cell-line arm; their disagreement is the signal.)
    (phospho-pathway-activity RE-HOMED 2026-08-05 → mechanism-and-pharmacology: an ACTIVITY /
     signaling-state readout, not a presence/abundance signal.)

  NORMAL-TISSUE SAFETY COMPARATORS (2 cards — verdict-inert; NOT presence signals.
  Kept in this skill because normal-tissue expression FRAMES the tumor presence read;
  the safety VERDICT itself is owned by on-target-safety-liability):
    - normal-tissue-liability        (HPA-IHC normal-tissue comparator; protein_ihc/normal bucket)
    - sc-normal-celltype-expression  (scRNA cell-type-resolved normal comparator; sc_rna/normal
                                             bucket; colon+lung shards → COADREAD/NSCLC, else
                                             data_unavailable. Dispatcher wired 2026-08-08.)

  Runs the expression-* + protein-* + sc-expression-* rule subset over three
  measurement ladders (bulk_rna, bulk_protein_ms, sc_rna). Emits a data-package
  output tree with a rank-ordered presence verdict + per-(measurement,
  sample_context) sub-verdicts.

  Use for questions like "is EPCAM expressed in CRC?", "how does MET
  distribute across colon cell lines?", "is CDX2 tumor-elevated relative
  to adjacent margin?"

  This skill answers Phase-A questions (presence) — distinct from Phase-B
  (selectivity vs. normals), which is `tumor-selectivity`.

  Biology-first output. Modality is a POST-HOC lens exposed via optional
  --modality flag.

metadata:
  version: 1.6.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [A]
  cards_used:
    - cellline-rna-distribution
    - tumor-rna-vs-adjacent
    - tumor-protein-abundance-cptac         # Layer 6c addition: dual RNA + protein presence (patient CPTAC)
    - cellline-protein-abundance      # Gygi cell-line MS (bulk_protein_ms x cell_line) — see run.py CARDS
    - tumor-elevation-breadth        # Slice B3: pan-cancer K-of-N tumor-elevation (target-grain); the one tumor-context card that fires in a target-ONLY query
    - tumor-rna-distribution         # Q1 per-sample tumor RNA distribution (was run.py-present, doc-stale)
    - tumor-rna-distribution-by-subtype # Q1 subtype-grain panorama (was run.py-present, doc-stale)
    - expression-purity-confound            # Q9 (2026-07-23): purity-confound caveat — tumor-intrinsic vs microenvironment (render facet)
    # phospho-pathway-activity RE-HOMED 2026-08-05 → mechanism-and-pharmacology (activity, not presence)
    - cellline-rna-protein-concordance               # Q5 (2026-07-23): rna_as_biomarker — RNA-as-proxy-for-protein quality (CELL-LINE arm); biomarker preferred_assay input (render facet)
    - rna-protein-concordance-tumor         # Q5 TUMOR arm (2026-08-08 graduation): CPTAC per-cohort RNA↔protein concordance — the PREFERRED input to bulk_rna_proxy_quality (disease-context proxy quality). Render facet, verdict-inert.
    - tumor-scrna-celltype-expression       # sc_rna slice (2026-08-04): single-cell per-compartment tumor presence (sc_rna/tumor). VERDICT-BEARING via _SC_RNA_RANK
    - normal-tissue-liability               # P8.3 (2026-08-05): HPA-IHC normal-tissue SAFETY COMPARATOR, protein_ihc/normal bucket — verdict-inert (feeds no ladder)
    - sc-normal-celltype-expression         # Phase 3.3 (2026-08-07 CARDS; dispatcher wired 2026-08-08): scRNA cell-type-resolved normal-tissue SAFETY COMPARATOR, sc_rna/normal bucket — verdict-inert
  # DATA_TO_SKILL_CONTRACT Rule 3 — measurement_type claims pulled. RNA (cell_line_rna_expression,
  # tumor_vs_adjacent_expression) and the TWO protein layers (patient tumor_protein_abundance from
  # CPTAC + cell_line_protein_abundance from Gygi MS) are DISTINCT types — the multi-layer presence
  # pattern is surfaced, not averaged. tumor_elevation_breadth is the DERIVED target-grain roll-up
  # over tumor_protein_abundance (breadth over indications for one target — NOT a ranking over targets).
  # expression_purity_confound (Q9) is an ADDITIVE render facet — a purity-confound caveat on the
  # tumor presence call, verdict-inert.
  measurement_types_pulled:
    - cell_line_rna_expression
    - tumor_vs_adjacent_expression
    - tumor_protein_abundance
    - cell_line_protein_abundance
    - tumor_elevation_breadth
    - tumor_expression_distribution
    - expression_purity_confound
    - rna_protein_concordance             # BOTH the cell-line arm (cellline-rna-protein-concordance) AND the tumor arm (rna-protein-concordance-tumor) — same measurement_type, different grain
    - sc_tumor_celltype_expression        # sc_rna slice (2026-08-04): single-cell per-compartment tumor presence
    - sc_normal_celltype_expression       # Phase 3.3: scRNA normal-tissue safety comparator (sc_rna/normal)
    - normal_tissue_protein_breadth       # L3 parity fix (2026-08-13): normal-tissue-liability HPA-IHC comparator (protein_ihc/normal) — was omitted
  rules_scope:
    - cellline-rna-distribution
    - tumor-rna-vs-adjacent
    - tumor-rna-distribution              # L3 parity fix (2026-08-13): tumor-expression-* rules → _EXPRESSION_RANK (VERDICT-BEARING) — was omitted
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

- Fetches the 13 wired cards via the compose-dashboard live-reader dispatchers — the exact same
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
   outranks a measured negative in another (H2 fix, 2026-08-13) — a cell-line-RNA killer no longer
   buries a measured tumor-protein/sc positive.
3. **then coverage GAPS** — `data_unavailable` plus tumor-vs-adjacent `not_informative` (M3: a flat
   read is a coverage gap, not a measured negative).
4. else → `insufficient` (nothing fired).

The per-`(measurement, sample_context)` buckets rank WITHIN each bucket using that measurement's ladder
(they are NOT collapsed). `driving_rule_id` is captured in the headline so a reviewer can trace the
verdict to the exact rule in `intracellular-intrinsic.rules.yaml`.

NOTE (inline verdict, by design): tumor-presence resolves its verdict inline in `run.py` rather than via
a `*.resolver.yaml` — the collapsed spine AND the per-bucket decomposition derive from the same ladders,
which the resolver grammar (no grouping) cannot express. The ladder is frozen by
`test_full_per_modality_golden_spine` + the G1/G2/G5/H2/M2/M3 regressions (the golden-oracle guard a
resolver migration would otherwise provide).

## Per-(measurement, sample_context) sub-verdicts

Beyond the collapsed `presence_verdict`, the skill emits
`presence_verdict_by_modality` keyed by `measurement/sample_context`
(e.g. `bulk_rna/cell_line`, `bulk_rna/tumor`, `bulk_protein_ms/tumor`,
`sc_rna/tumor`).
A **target-only** query honestly reads cell-line buckets as `measured`
and the per-indication tumor buckets as `data_unavailable` — EXCEPT
`bulk_protein_ms/tumor`, which `tumor-elevation-breadth` keeps `measured`
even without an indication (it rolls up CPTAC over all cohorts). That is
the one tumor-context presence signal a target-only query gets.

The **`sc_rna/tumor`** bucket (2026-08-04) was formerly a hard-coded named
gap; it is now card-backed by `tumor-scrna-celltype-expression`. It reads
`measured` for the indications with a landed single-cell pseudobulk product
that carries a per-cell malignant annotation (v1: **COADREAD + NSCLC**) and
`data_unavailable` for every other indication (an honest capability ceiling,
never a coarser fall-back). The single-cell bucket carries what bulk cannot:
per-cell `detection_fraction` and malignant-vs-microenvironment attribution
(`sc_expression_class` ∈ malignant_broadly_detected / malignant_subset_detected
/ microenvironment_dominant / broadly_low / data_unavailable). Only
`protein_ihc/normal` remains an unbuilt-substrate named gap.

## Headline-lens discordance (read this before trusting the one-word verdict)

The collapsed `presence_verdict` is byte-identical to whichever lens wins the ladder, and the
cell-line RNA rungs (`broadly_high` … `broadly_moderate`) rank ABOVE the tumor-lens rungs by
design (byte-stability). So for antigens that **de-differentiate in 2D culture** — EPCAM, FOLR1,
CEACAM5 — the pan-cancer cell-line median collapses while the tumor tissue reads top-percentile,
and the one-word headline UNDERSTATES tumor presence. The skill makes this legible with three
ADDITIVE, verdict-inert headline fields (they feed no rule; `presence_verdict` is byte-stable):

- **`headline_lens`** — the `measurement/sample_context` bucket whose `driving_rule_id` won the
  collapsed verdict (e.g. `bulk_rna/cell_line`).
- **`cell_line_vs_tumor_discordant`** — `true` ONLY when the headline is cell-line-anchored AND
  the `bulk_rna/tumor` lens reads a strictly HIGHER presence tier (the understatement case).
  Verified spread: `true` for EPCAM/FOLR1/KRAS-COADREAD; `false` for ERBB2/MET (both lenses broad)
  and CEACAM5 (headline already tumor-anchored via strong upregulation).
- **`presence_interpretation_note`** — a human/LLM-facing sentence spelled out when discordant.

When `cell_line_vs_tumor_discordant` is `true`, read `presence_verdict_by_modality['bulk_rna/tumor']`,
not just the headline word. (A future re-anchor that promotes the tumor lens in the ladder is a
separate, backtest-gated change — this flag is the non-flipping interim.)

## What this skill does NOT do

- Does NOT recompute the DGE — reads pre-computed derived products.
- Does NOT compare tumor to GTEx-population-normal — that's `tumor-selectivity`.
- By default emits NO narrative (the deterministic verdict + fields only). An OPT-IN
  `--synthesize` flag attaches an LLM narration under `decision["llm_synthesis"]` that
  explains the deterministic verdict in light of the contextualized axes (all-gene
  percentile, control-benchmark position, across-subtype effect). It is a SIBLING key —
  it never mints or flips a verdict, and the decision is byte-identical without the flag
  (two-slot design; see `_skills_common/synthesis.py`). For the fully composed cross-skill
  narrative, use `target-profile`.

## How Claude invokes this skill

When called as `/tumor-presence`, Claude should:

1. Extract `target` (HGNC gene symbol, uppercase) and `indication`
   (AACR OncoTree code, uppercase — e.g. COADREAD, LUAD, BRCA) from the
   user's prompt. Ask if either is missing or ambiguous.
2. Pick an `out` directory. Default: `/tmp/tumor-presence/{target}-{indication}`.
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/tumor-presence/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
   Add `--modality <M>` if the user names a modality; otherwise omit.
   Add `--synthesize` if the user wants an LLM narration of the read (optional; needs
   Bedrock access — degrades to a note under `llm_synthesis` if unavailable, leaving the
   deterministic verdict intact).
   NOTE (synthesis env): `--synthesize` requires an interpreter with `anthropic[bedrock]`
   AND `BEDROCK_AWS_PROFILE` set to a Bedrock-entitled profile (e.g. `cmp-dev`), which is a
   DIFFERENT account from the `cbg` profile used for the S3 card reads (the LLM layer resolves
   the Bedrock profile's frozen creds internally — `AnthropicBedrock` does not honor
   `AWS_PROFILE`). The DEFAULT pixi env does NOT include `anthropic`, so running
   `pixi run python3 run.py --synthesize` under the default env SILENTLY DEGRADES:
   `llm_synthesis` becomes a `_synthesis_error` note and the run still exits 0 (the
   deterministic spine is unaffected — two-slot design). Invoke with an interpreter that has
   `anthropic[bedrock]` installed and both profiles available, e.g.:
   ```
   export AWS_PROFILE=cbg BEDROCK_AWS_PROFILE=cmp-dev && \
   python3 .../tumor-presence/scripts/run.py --target <T> --indication <I> --out <D> --synthesize
   ```
   Add `--subtype <SUBTYPE>` (with `--synthesize`) if the user asks about a specific
   molecular subtype (e.g. `--subtype MSI_H`): the narration foregrounds that stratum's
   position in addition to the across-subtype omnibus. Emphasis-only — no spine change;
   if the subtype is not among the computed strata, the narration says so rather than
   inventing a position.
4. Read `<OUT_DIR>/decision.json`, present the headline (presence_verdict +
   driving_rule_id + per-card summary highlights) inline. If
   `cell_line_vs_tumor_discordant` is `true`, surface `presence_interpretation_note`
   and the `bulk_rna/tumor` sub-verdict alongside the headline word — the one-word
   verdict understates tumor-tissue presence in that case. If `--synthesize` was used,
   the `llm_synthesis` block carries the narration (tagged `_source: llm_synthesized`).
