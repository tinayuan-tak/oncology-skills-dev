---
name: tumor-presence
description: |
  Focused question skill: "Is target X present in indication Y's tumor
  tissue, and how does it distribute across cancer cell lines vs. tumor
  samples, at RNA and protein level?" Consumes 10 wired cards in two tiers.

  VERDICT-BEARING (5 cards — feed the rank-ordered presence ladder):
    - cellline-rna-distribution           (cell-line RNA, pan-cancer TPM distribution)
    - tumor-rna-vs-adjacent      (tumor RNA-seq DEG vs paired-adjacent; COADREAD
                                         adjacent, else tumor-vs-GTEx fallback)
    - tumor-protein-abundance-cptac            (tumor protein abundance, CPTAC per-cohort)
    - cellline-protein-abundance         (cell-line protein, DepMap/Gygi TMT-MS)
    - tumor-elevation-breadth           (pan-cancer K-of-N tumor-elevation, target-grain)

  DISPLAY-ONLY facets (4 cards — additive context, feed NO resolver, verdict
  byte-stable; one-directional gate):
    - tumor-rna-distribution         (per-sample tumor RNA distribution; rules
                                             not yet in the verdict ladder — follow-up)
    - tumor-rna-distribution-by-subtype (per-molecular-subtype panorama; COADREAD
                                             shard only, else subtype_axis_available:false)
    - expression-purity-confound            (is the tumor signal tumor-intrinsic or stromal?)
    - cellline-rna-protein-concordance               (is RNA an adequate protein proxy?)
    (phospho-pathway-activity RE-HOMED 2026-08-05 → mechanism-and-pharmacology: an ACTIVITY /
     signaling-state readout, not a presence/abundance signal.)

  Runs the expression-* + protein-* rule subset over two measurement ladders
  (bulk_rna, bulk_protein_ms). Emits a data-package output tree with a
  rank-ordered presence verdict + per-(measurement, sample_context) sub-verdicts.

  Use for questions like "is EPCAM expressed in CRC?", "how does MET
  distribute across colon cell lines?", "is CDX2 tumor-elevated relative
  to adjacent margin?"

  This skill answers Phase-A questions (presence) — distinct from Phase-B
  (selectivity vs. normals), which is `tumor-selectivity`.

  Biology-first output. Modality is a POST-HOC lens exposed via optional
  --modality flag.

metadata:
  version: 1.1.0
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
    - cellline-rna-protein-concordance               # Q5 (2026-07-23): rna_as_biomarker — RNA-as-proxy-for-protein quality; biomarker preferred_assay input (render facet)
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
    - rna_protein_concordance
  rules_scope:
    - cellline-rna-distribution
    - tumor-rna-vs-adjacent
    - tumor-protein-abundance-cptac
    - cellline-protein-abundance
    - tumor-elevation-breadth
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

- Fetches the two expression cards via compose-dashboard live-reader
  dispatchers. Reuses the exact same read path Macro uses — no drift.
- Runs the expression-* rule subset (9 rules across the 2 cards) against
  the summaries.
- Emits a data-package output tree with:
  - `decision.json` — presence_verdict + fired rules
  - `summary.yaml` — per-card summary dicts
  - `tables/` — per-card summary_stats CSVs
  - `figures/` — populated per-card if a card emitter is wired
  - `provenance.yaml` — audit anchor including `invoked_lenses`

## Verdict resolution (rank-ordered)

1. `expression-broadly-high-supportive` fires → `broadly_high_expression`
2. `expression-strong-upregulation-supportive` fires → `strongly_upregulated_in_tumor`
3. `expression-lineage-restricted-supportive` fires → `lineage_restricted`
4. `expression-modest-upregulation-neutral` fires → `modestly_upregulated_in_tumor`
5. `expression-broadly-moderate-neutral` fires → `broadly_moderate_expression`
6. `expression-broadly-low-degrader-killer` fires → `broadly_low_expression`
7. `expression-call-not-informative-degrader-killer` fires → `not_informative`
8. `expression-data-unavailable-insufficient` fires → `data_unavailable`
9. else → `insufficient`

The `driving_rule_id` is captured in the headline so a reviewer can trace
the verdict back to the exact rule in intracellular-intrinsic.rules.yaml.

## Per-(measurement, sample_context) sub-verdicts

Beyond the collapsed `presence_verdict`, the skill emits
`presence_verdict_by_modality` keyed by `measurement/sample_context`
(e.g. `bulk_rna/cell_line`, `bulk_rna/tumor`, `bulk_protein_ms/tumor`).
A **target-only** query honestly reads cell-line buckets as `measured`
and the per-indication tumor buckets as `data_unavailable` — EXCEPT
`bulk_protein_ms/tumor`, which `tumor-elevation-breadth` keeps `measured`
even without an indication (it rolls up CPTAC over all cohorts). That is
the one tumor-context presence signal a target-only query gets.

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
   Add `--subtype <SUBTYPE>` (with `--synthesize`) if the user asks about a specific
   molecular subtype (e.g. `--subtype MSI_H`): the narration foregrounds that stratum's
   position in addition to the across-subtype omnibus. Emphasis-only — no spine change;
   if the subtype is not among the computed strata, the narration says so rather than
   inventing a position.
4. Read `<OUT_DIR>/decision.json`, present the headline (presence_verdict +
   driving_rule_id + per-card summary highlights) inline. If `--synthesize` was used,
   the `llm_synthesis` block carries the narration (tagged `_source: llm_synthesized`).
