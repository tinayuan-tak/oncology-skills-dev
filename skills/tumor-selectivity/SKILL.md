---
name: tumor-selectivity
description: |
  Focused question skill: "How selectively is target X expressed in tumor
  vs normal for indication Y, and how robust is that call across
  independent comparators — bulk, single-cell, and in-situ spatial?" Consumes 13
  cards across three roles. VERDICT-DRIVING (5): tumor-vs-normal-selectivity (v3,
  four-cell sensitivity; the aggregate axis-A verdict — the ONLY card the resolver keys on)
  + four post-resolver VETO instruments that DOWNGRADE an axis-A-selective call via the
  Python clamp (_skills_common/selectivity_veto.py): the normal-breadth arms
  modality-therapeutic-window (2 arms), sc-normal-celltype-expression (1 arm), and
  normal-tissue-protein-abundance-tphp (1 arm, abundance-gated protein liability), plus the
  INT-axis stromal-confound arm tumor-scrna-celltype-expression (malignant-cell-intrinsic vs
  stroma/CAF; v1.17.0). The SPLIT (Phase S): the therapeutic-window / full-normal arms (tumor
  below the worst critical/full normal — housekeeping) → selective_but_broadly_normal (the KILL);
  the INT stromal-confound arm → selective_but_stromal_confound (the INT KILL — signal in the wrong
  cells); the sc-normal critical-organ + tphp normal-protein arms → selective_with_normal_liability
  (a selectivity-PRESERVING named-organ SAFETY flag — approved antigens DLL3/ERBB2/FOLR1 land here;
  severity owned by on-target-safety-liability + modality-fit). These 3 clamp verdicts are declared
  in selectivity.resolver.yaml `clamp_verdicts` (the resolver lists the full 11-verdict enum) and, as
  of gate v1.10.0, the two KILLs block `strong` in the composed nomination. CORROBORATION (1):
  tumor-vs-normal-percentile-crossing (per-sample). ADDITIVE facets, verdict-inert (7):
  expression-purity-confound, surface-abundance-density, tumor-protein-abundance-cptac +
  tumor-vs-normal-protein-abundance-tphp (two PARALLEL RNA→protein tumor-vs-normal corroboration
  facets: CPTAC TMT ~10 cohorts + TPHP DIA-MS 22 cohorts), and the tumor SIDE at in-situ spatial
  resolution (spatial-region-rna-expression + spatial-tumor-normal-colocalization +
  spatial-surface-protein-abundance: in-situ tumour enrichment + normal-epithelium bystander
  adjacency). (+1 subtype-gated card tumor-vs-normal-percentile-crossing-by-subtype under --subtypes.)
  Emits a data-package output tree (decision.json + summary.yaml + tables/ + figures/ + provenance.yaml).
  Optional --synthesize attaches a two-slot LLM narration (verdict-inert).

  Use for focused per-target questions like "is EPCAM tumor-selective in
  COADREAD?", "is KRAS overexpressed in colorectal tumors?", "how does APC
  read on tumor-vs-normal in CRC?" — cases where a full evidence package
  is overkill.

  Biology-first output. Modality is a POST-HOC lens exposed via optional
  --modality flag; the primary output (selectivity_class + cells_supporting
  + discordant flag) is modality-independent.

metadata:
  version: 1.25.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [B]
  cards_used:
    - tumor-vs-normal-selectivity            # aggregate axis-A verdict (verdict-driving)
    - tumor-vs-normal-percentile-crossing    # per-sample corroboration. Its tumor-vs-normal-crossing-*
                                             # rules emit SM/degrader signals; the selectivity resolver
                                             # stays keyed to the aggregate card (verdict byte-stable).
    - modality-therapeutic-window            # NORMAL-BREADTH VETO instrument. therapeutic_window_class ==
                                             # no_therapeutic_window downgrades an axis-A-selective call to
                                             # selective_but_broadly_normal via the run.py::_verdict
                                             # post-resolver clamp (a 2-card conjunction the single-rule
                                             # resolver cannot express).
    - sc-normal-celltype-expression          # NORMAL-BREADTH VETO instrument (sc-normal critical-organ liability).
    - expression-purity-confound             # additive purity-confound caveat (verdict-inert).
    - surface-abundance-density              # additive absolute surface density (verdict-inert).
    - tumor-protein-abundance-cptac          # RNA→PROTEIN corroboration (verdict-inert): tumor-vs-normal
                                             # protein_effect_size + protein_bh_q_value (CPTAC per-cohort
                                             # TMT-MS). Derived rna_protein_tvn_concordance surfaces the
                                             # RNA-up/protein-flat false-positive (closes caveat #5).
    - normal-tissue-protein-abundance-tphp   # QUANTITATIVE NORMAL-tissue PROTEIN comparator. Most fields DISPLAY; its
                                             # tphp_normal_protein_liability_class is VERDICT-BEARING (the 4th normal-breadth
                                             # veto arm): broad_and_abundant fires tvn-tphp-broad-abundant-normal-protein-veto,
                                             # which the _verdict clamp turns into selective_with_normal_liability. Abundance-
                                             # gated (Floor-C), NOT DIA detection. Per-tissue DIA-MS across 70 adult + 4 fetal
                                             # groups (TPHP; Xu et al. Nature 2026). No resolver rung (skills-side clamp).
    - tumor-vs-normal-protein-abundance-tphp # RNA→PROTEIN corroboration (verdict-inert), PARALLEL to
                                             # tumor-protein-abundance-cptac: tumor-vs-adjacent-normal protein_effect_size +
                                             # protein_bh_q_value from the TPHP DIA-MS proteome (Xu et al. Nature 2026), 22
                                             # carcinoma cohorts (several outside CPTAC). CPTAC-ALIGNED field names → the SAME
                                             # rna_protein_tvn_concordance projection consumes it unchanged. No resolver rung.
    - tumor-scrna-celltype-expression        # single-cell, tumor side — VERDICT-DRIVING (INT-axis
                                             # stromal-confound VETO, shipped v1.17.0): stromal_confound_class ==
                                             # stromal_confounded fires tvn-stromal-confound-veto, which the _verdict
                                             # clamp turns into selective_but_stromal_confound (the axis-A signal is in
                                             # CAF/stroma, not malignant cells). Resolves the purity confound at
                                             # single-cell resolution, which expression-purity-confound only proxies
                                             # via bulk. No resolver rung (skills-side clamp).
    - spatial-region-rna-expression          # in-situ spatial (GeoMx WTA) tumour-vs-TME RNA enrichment
                                             # (verdict-inert; deconvolution-free selectivity confirmation).
    - spatial-tumor-normal-colocalization    # in-situ spatial colocalization; normal-epithelium bystander
                                             # adjacency (verdict-inert; a spatial selectivity/safety facet).
    - spatial-surface-protein-abundance      # in-situ spatial PROTEIN (GeoMx DSP; verdict-inert);
                                             # data_unavailable where the protein panel doesn't cover the indication.
    - tumor-vs-normal-percentile-crossing-by-subtype  # SUBTYPE axis (Phase B): per-stratum tumor-vs-normal
                                             # percentile-crossing panorama; tier:subtype, DESCRIPTIVE, resolves
                                             # ONLY on the --subtypes path (SUBTYPE_CARDS / subtype_panorama_fn),
                                             # never the whole-cohort spine. Shares the tumor_vs_normal_percentile_
                                             # crossing measurement_type with the pooled sibling at target_subtype
                                             # grain (identity = type × grain), so it is NOT added to
                                             # measurement_types_pulled again.
  # One measurement_type per card in cards_used (DATA_TO_SKILL_CONTRACT Rule 3; enforced framework-wide
  # by test_measurement_types_resolver.py). tumor_vs_normal_selectivity is the efficacy-window framing,
  # distinct from safety's normal_tissue_breadth.
  measurement_types_pulled:
    - tumor_vs_normal_selectivity            # tumor-vs-normal-selectivity (verdict-driving)
    - tumor_vs_normal_percentile_crossing    # tumor-vs-normal-percentile-crossing (corroboration)
    - modality_window                        # modality-therapeutic-window (normal-breadth veto instrument)
    - sc_normal_celltype_expression          # sc-normal-celltype-expression (sc-normal veto arm)
    - expression_purity_confound             # expression-purity-confound (additive caveat)
    - surface_density                        # surface-abundance-density (additive)
    - tumor_protein_abundance                # tumor-protein-abundance-cptac (RNA→protein corroboration, additive)
    - normal_tissue_protein_abundance        # normal-tissue-protein-abundance-tphp (quantitative normal-PROTEIN comparator, additive)
    - tumor_vs_normal_protein_abundance      # tumor-vs-normal-protein-abundance-tphp (TPHP RNA→protein corroboration, additive)
    - sc_tumor_celltype_expression           # tumor-scrna-celltype-expression (single-cell, additive)
    - spatial_region_rna                     # spatial-region-rna-expression (spatial RNA, additive)
    - spatial_colocalization                 # spatial-tumor-normal-colocalization (spatial, additive)
    - spatial_surface_protein                # spatial-surface-protein-abundance (spatial protein, additive)
  rules_scope:
    - tumor-vs-normal-selectivity
    - tumor-vs-normal-percentile-crossing
    - modality-therapeutic-window            # tvn-no-therapeutic-window-veto + tvn-no-full-normal-window-veto feed the _verdict clamp
    - sc-normal-celltype-expression          # tvn-sc-normal-critical-organ-veto (the 3rd, verdict-driving veto arm)
    - normal-tissue-protein-abundance-tphp   # tvn-tphp-broad-abundant-normal-protein-veto (the 4th normal-breadth arm: quantitative
                                             # normal-PROTEIN abundance liability, Floor-C; feeds the _verdict clamp -> selective_with_normal_liability)
    - tumor-scrna-celltype-expression        # tvn-stromal-confound-veto (the INT-axis arm): stromal_confound_class == stromal_confounded
                                             # feeds the _verdict clamp -> selective_but_stromal_confound (Option B: outranks the window KILL)
  synthesis:
    - rule_engine
    - structured_llm    # opt-in --synthesize (selectivity-lens narrator, two-slot; verdict-inert)
  output_shape:
    - data_package
  steps_covered: [1, 2, 3, 4, 6]
  optional_lenses:
    - modality
  status: wired
---

# Tumor-vs-Normal Selectivity

## What this skill does

- Fetches 13 cards for a single (target, indication) via the shared
  live-reader dispatcher (reuses the exact same read path Macro uses — no drift):
  - `tumor-vs-normal-selectivity` (v3, four-cell sensitivity) — the aggregate axis-A verdict.
  - `tumor-vs-normal-percentile-crossing` — per-sample corroboration (fraction of
    tumors above the matched-normal p95).
  - `modality-therapeutic-window` — the NORMAL-BREADTH VETO (tumor ÷ worst
    critical-normal); its `therapeutic_window_class == no_therapeutic_window` downgrades
    an otherwise-selective call (see the veto note below).
  - `sc-normal-celltype-expression` — the sc-normal critical-organ veto arm (single-cell,
    NORMAL/safety side).
  - `expression-purity-confound`, `surface-abundance-density` — verdict-inert additive facets.
  - `tumor-protein-abundance-cptac` — RNA→PROTEIN corroboration (verdict-inert): does the
    tumor-vs-normal signal hold at the protein layer (CPTAC per-cohort TMT-MS)? The derived
    `rna_protein_tvn_concordance` surfaces the RNA-up/protein-flat false-positive (caveat #5).
  - `tumor-scrna-celltype-expression` (single-cell, TUMOR side), `spatial-region-rna-expression`,
    `spatial-tumor-normal-colocalization`, `spatial-surface-protein-abundance` — single-cell +
    in-situ spatial facets (verdict-inert; see the SINGLE-CELL + SPATIAL note below).
- Runs the tvn-* + tumor-vs-normal-crossing-* subset of the intracellular-intrinsic
  rules against the summaries. The selectivity RESOLVER stays keyed to the aggregate
  card's classes (verdict byte-stable); the crossing rules add SM/degrader signal.
- NORMAL-BREADTH VETO (SPLIT, Phase S): after the resolver returns an axis-A verdict,
  `run.py::_verdict` applies a one-directional post-resolver clamp with TWO distinct outcomes —
  (a) a therapeutic-window arm (`tvn-no-therapeutic-window-veto` / `tvn-no-full-normal-window-veto`:
  tumor BELOW the worst critical/full normal — a housekeeping/no-window gene) downgrades to
  `selective_but_broadly_normal` (the KILL — no real window at all); (b) the sc-normal critical-organ
  arm (`tvn-sc-normal-critical-organ-veto`: a real window but an essential-cell liability in a
  NON-origin critical organ) AND the tphp normal-PROTEIN arm (`tvn-tphp-broad-abundant-normal-protein-veto`:
  a real window but a quantitatively ABUNDANT — Floor-C, not trace — normal-protein footprint across a
  broad tissue count, TPHP DIA-MS) both downgrade to `selective_with_normal_liability` — a SELECTIVITY-
  PRESERVING named liability (the target IS tumor-selective; approved antigens DLL3/ERBB2/FOLR1
  land here — their normal expression is real but they are drugs via modality/accessibility/
  precedent; the SAFETY severity is owned by on-target-safety-liability + modality-fit). Precedence
  when both fire: window > full-normal > sc-normal > tphp-normal-protein (a no-window KILL outranks a
  liability flag, e.g. TROP2). This is a 2-card conjunction the single-rule resolver cannot express; it exists to stop a
  housekeeping-like gene passing as tumor-selective WITHOUT lumping approved antigens into that KILL.
  The clamp is applied in ALL THREE consumers — the
  standalone skill (`_verdict`), the composed target-profile (its fan-out calls `_verdict`, and
  all four veto cards are in `SUB_SKILL_CARDS[tumor-selectivity]`), and the compose-dashboard /
  target-profile `--emit` engine (the clamp is single-sourced in
  `_skills_common.selectivity_veto` and applied by `compose_core.resolve_gate_spine`). It is
  one-directional (only downgrades) and a no-op unless a normal-breadth veto rule actually fired.
- SINGLE-CELL + SPATIAL — the tumor SIDE of the selectivity question at
  single-cell + in-situ resolution. The bulk four-cell DESeq2 axis-A signal cannot tell whether a
  `tumor_selective` call is **malignant-cell-intrinsic** or driven by CAF/stromal/immune
  microenvironment content — the classic purity confound that `expression-purity-confound` only
  PROXIES via bulk deconvolution. Four cards MEASURE it directly and are surfaced in the headline —
  the single-cell card is VERDICT-DRIVING (the INT stromal-confound veto), the three spatial cards
  are VERDICT-INERT (selectivity_class byte-stable):
  - `tumor-scrna-celltype-expression` — per-compartment single-cell: `sc_malignant_detection_fraction`
    + `sc_caf_vs_malignant_class` → `stromal_confound_class`. **VERDICT-DRIVING** (v1.17.0): a
    `stromal_confounded` read fires the INT stromal-confound veto → `selective_but_stromal_confound`.
    (CEACAM5/COADREAD: 0.76 malignant vs 0.03 stromal, `caf_low` → malignant-cell-intrinsic, i.e. a
    *real* selective window, veto does not fire.)
  - `spatial-region-rna-expression` — in-situ (GeoMx WTA) tumour-vs-TME RNA enrichment
    (`spatial_rna_class`) — a deconvolution-free orthogonal confirmation.
  - `spatial-tumor-normal-colocalization` — in-situ `spatial_normal_epithelium_adjacency_fraction`
    (bystander/off-tumour risk to adjacent normal epithelium — a spatial safety dimension).
  - `spatial-surface-protein-abundance` — in-situ protein enrichment (GeoMx DSP; `data_unavailable`
    where the sparse protein panel doesn't cover the indication — honest abstain).
- Emits `decision.json` with:
  - `headline`: `selectivity_class`, `cells_supporting`, `dominant_direction`,
    `discordant`, `max_abs_log2fc`, the Axis-1 `selectivity_allgene_percentile*`
    (relative-selectivity context), the `percentile_crossing_class` corroboration, and
    the single-cell + spatial facets: `sc_tumor_expression_class`,
    `sc_malignant_detection_fraction`, `sc_caf_vs_malignant_class`, `spatial_rna_class`,
    `spatial_coloc_class`, `spatial_normal_epithelium_adjacency_fraction`, `spatial_protein_class`.
  - `verdict`: the resolved selectivity verdict, which may be a veto-clamp outcome —
    `selective_but_broadly_normal` (axis-A selective but no therapeutic window — the housekeeping
    KILL) or `selective_with_normal_liability` (a real window but a NON-origin critical-organ
    liability — selectivity preserved, a named-organ safety flag) via the `_verdict` clamp;
    `driving_rule_id` names the rule that set it.
  - `fired_rules`: which rules matched
  - `modality_lenses`: optional SM+degrader tally for callers who want it
  - `llm_synthesis` (only with --synthesize): a two-slot selectivity-lens narration.
  - `literature_synthesis` (only with --literature): a verdict-INERT published-literature read per
    axis + agreement-vs-omics + omics-blind signals, through this skill's selectivity lens.
    INDEPENDENT of `--synthesize` (pass `--literature` alone for the key with no narration); with
    both, it is attached first and fed to the narrator. Optionally `--literature-model <id>`.
    Without the flag the key is ABSENT — that is the flag not being passed, not a failed lane.

## What this skill does NOT do

- Does NOT recompute the DEG. Reads the v3 sensitivity.parquet from S3.
- Does NOT synthesize a full evidence package. That is `compose-dashboard`.
- Does NOT render a figure by default. If a caller wants the 4-panel figure
  they can either invoke `compose-dashboard` with a filtered spec or use
  the emitter directly via `methods.dge_deseq2.emit`.

## Invocation

```
python scripts/run.py --target EPCAM --indication COADREAD --out /tmp/tvn-epcam
# → writes /tmp/tvn-epcam/decision.json
```

## Data mode

Live-read only (a focused single-lens skill). Reads S3 via the same dispatcher chain
that Macro uses. If the sensitivity product is not yet in S3 for the
requested indication, the reader's v2 fallback kicks in and the skill
still returns a decision (with `_schema: v2_two_product_fallback` visible
in the underlying summary).

## Performance (cold single runs)

The 13 card reads are independent and run concurrently (shared `_skills_common.resolve_cards`),
so cold wall-clock is bounded by the slowest single read — not the sum of all 13.

A standalone run defaults to a **forked process pool** (set at the `run_wired_skill` entrypoint),
which bypasses the GIL on the readers' pandas-assembly CPU — the fastest cold path. Combined with the
data-catalog index disk cache (which skips the ~442-manifest cold parse in the provenance step), a
cold CEACAM5/COADREAD run is **~4s**; the thread pool is ~5s. The fork is safe — it engages only from
a single-threaded main thread (a multithreaded host or the composed target-profile fan-out
transparently stays on threads), any fork/pickling failure degrades to the thread pool, and the
output is byte-identical across both paths. Two optional env knobs (both with sensible defaults):

- `SKILLS_READ_POOL=thread` — force the thread pool (escape hatch; the standalone-run default is
  `process`).
- `SKILLS_READ_WORKERS=N` — max concurrent readers (default `8`; `1` forces the sequential path).

## How Claude invokes this skill

When called as `/tumor-selectivity`, Claude should:

1. Extract `target` (HGNC gene symbol, uppercase) and `indication`
   (AACR OncoTree code, uppercase — e.g. COADREAD, LUAD, BRCA) from the
   user's prompt. Ask if either is missing or ambiguous.
2. Pick an `out` directory. Default: `/tmp/tumor-selectivity/{target}-{indication}`
   unless the user specifies one.
3. Run (add `--synthesize` for the optional LLM narration; add `--literature` for the verdict-inert
   published-literature lane under `decision["literature_synthesis"]`). The run defaults to the fastest
   (forked process pool) read path; no read-pool env var is needed (see the Performance note below):
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/tumor-selectivity/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
4. Read `<OUT_DIR>/decision.json`, present the headline + the driving_rule_id
   inline, and offer to open the full JSON if the user wants details.
5. If the underlying card summary carries `_schema: v2_two_product_fallback`,
   flag that the v3 sensitivity product is not yet in S3 for that indication
   and the response is on legacy two-contrast data.

## The stromal-confound veto (INT-axis, verdict-driving — SHIPPED v1.17.0, 2026-08-31)

The tumor-side single-cell attribution is now VERDICT-DRIVING (the spatial cards remain verdict-inert
facets). `tumor-scrna-celltype-expression` promotes the malignant-vs-stroma signal to a verdict-driving
clamp, symmetric to the normal-breadth veto but on the tumor-cell-INTRINSIC (INT) axis rather than the
SAFE axis:

- **Motivation.** For target nomination (ADC/TCE/degrader), the most dangerous false positive is a
  bulk `tumor_selective` call actually driven by CAF/stromal content rather than the malignant cells —
  a payload built against it misses the cancer. Axis-A over-expression is necessary but NOT sufficient;
  it must also be malignant-cell-intrinsic (the same necessary-but-not-sufficient logic the
  normal-breadth veto applies on the safety side).
- **Instrument.** `tumor-scrna-celltype-expression` emits a dedicated, provenance-gated
  `stromal_confound_class` (analysis-methods); `stromal_confounded` fires the `tvn-stromal-confound-veto`
  rule (target-contracts), and the shared `_skills_common.selectivity_veto` clamp (BOTH engines)
  downgrades a selective axis-A call to `selective_but_stromal_confound`. The classifier requires
  `microenvironment_dominant` (malignant detection < 0.10) + `caf_dominant` + a stromal top compartment
  + a TRUSTWORTHY malignant annotation (curated/inferCNV, entity-specific); a phenotype_proxy /
  multi-entity-pooled cube reads `inconclusive_low_confidence` and does NOT fire (a mis-annotation
  cannot manufacture the downgrade).
- **Precedence (Option B).** The stromal-confound KILL OUTRANKS the normal-breadth window KILL when
  both fire (CAF genes are broadly-normal too): "the antigen is not on the tumor cells" is the more
  fundamental disqualifier and the more actionable nomination signal. Full order:
  stromal-confound > window > full-normal > sc-normal > tphp-normal-protein.
- **Backtest (passed).** RETAIN malignant-intrinsic antigens (CEACAM5 field-effect, MSLN/CDH17
  selective_with_normal_liability, EPCAM discordant — none flip); DOWNGRADE canonical CAF genes
  (FAP/POSTN/COL1A1/THY1 → `selective_but_stromal_confound`). Thresholds are the sc classifier's
  existing cuts (0.10 malignant / 0.25 microenvironment), not re-eyeballed — avoiding the CD19
  over-eager-clamp false-negative failure mode. CEACAM5/TACSTD2 replay fixtures byte-stable.
