# tumor-presence — design contract & rationale

This document holds the *why* behind `scripts/run.py`. `run.py` itself is a thin
configuration over the shared dispatcher (`_skills_common/dispatcher.py`) and carries
only terse comments; the design decisions, invariants, and the history that justifies
them live here. See [SKILL.md](SKILL.md) for the user-facing contract and flags, and
[README.md](README.md) for a first-run guide.

## What the skill computes

`tumor-presence` answers a Phase-A question: *is target X present in indication Y's
tumor tissue, and how does it distribute across cancer cell lines vs. tumor samples, at
RNA, whole-cell protein, and single-cell resolution?* It reads 14 pre-computed cards and
emits:

- a collapsed one-word `presence_verdict` (+ `driving_rule_id`), and
- one sub-verdict per `(measurement, sample_context)` bucket
  (`presence_verdict_by_modality`), so a cell-line signal is never conflated with a tumor
  signal and cross-modal tension is legible.

It reads pre-computed derived products; it does **not** recompute any DGE, and it does
**not** compare against GTEx population-normal (that is `tumor-selectivity`).

## The four moving parts in run.py

1. **`CARDS` + `CARD_CONTEXT`** — the 14 cards consumed, each tagged with its
   `(measurement, sample_context)` bucket. `CARD_CONTEXT` mirrors the `measurement:` /
   `sample_context:` tags in `target-contracts/cards/*.card.yaml`; a drift test
   (`test_card_context_matches_target_contracts_specs`) asserts they agree.
2. **Three ladders** — `_EXPRESSION_RANK` / `_PROTEIN_RANK` / `_SC_RNA_RANK`: ordered
   `(rule_id -> verdict)` lists, highest-precedence first, one per measurement layer.
3. **The collapse** — `_partition_measured` + `_VERDICT_RANK` fold the three ladders into
   one order (all measured positives, then all measured negatives, then coverage gaps),
   RNA-first within each tier. `_verdict()` returns the first fired rung.
4. **`_per_modality_verdicts` + `_headline`** — the same ladders applied *within* each
   bucket, plus the safety comparators and the verdict-inert display fields read off the
   cards.

`run.py`'s entry point hands these to `run_wired_skill(...)`, which runs
`resolve_cards -> fired_rules -> verdict_fn -> headline_fn -> write_package`.

## Card roster (14)

**Verdict-bearing (7)** — feed the presence ladders:
`cellline-rna-distribution`, `tumor-rna-vs-adjacent`, `tumor-rna-distribution`,
`tumor-protein-abundance-cptac`, `cellline-protein-abundance`, `tumor-elevation-breadth`,
`tumor-scrna-celltype-expression`.

**Display-only facets (5)** — additive context, feed no ladder (verdict byte-stable):
`tumor-rna-distribution-by-subtype`, `cellline-rna-distribution-by-subtype`,
`expression-purity-confound`, `cellline-rna-protein-concordance`,
`rna-protein-concordance-tumor`.

**Normal-tissue safety comparators (2)** — verdict-inert; they *frame* the presence read,
but the safety verdict itself is owned by `on-target-safety-liability`:
`normal-tissue-liability` (HPA-IHC, `protein_ihc/normal`),
`sc-normal-celltype-expression` (scRNA, `sc_rna/normal`).

`phospho-pathway-activity` was moved to `mechanism-and-pharmacology` (2026-08-05): it is a
signaling-*state* readout that presupposes presence rather than measuring it.

## Why two axes (measurement × sample_context)

Each card is tagged with two orthogonal axes: the measurement *layer* (`bulk_rna` /
`bulk_protein_ms` / `sc_rna` / `protein_ihc`) and the biological *sample*
(`cell_line` / `tumor` / `normal`). Keying the per-modality view off the measurement
alone conflated the cell-line-RNA card with the tumor-RNA card (both `bulk_rna`), so a
target-only query read identically to a target-indication query and hid that the tumor
axis was never touched. Bucketing by the *pair* makes the degenerate case honest:
`bulk_rna/cell_line: measured` alongside `bulk_rna/tumor: data_unavailable`.

The rule *vocabulary* is a function of the measurement layer only (a cell-line-RNA card
and a tumor-RNA card both fire `expression-*` rules), so the ladder is keyed by
measurement even though the bucket is keyed by the pair (`_MEASUREMENT_RANK`).

## Collapse invariants (what the ladder order guarantees)

The naive concatenation of the three ladders is wrong twice over; the collapse enforces:

- **Coverage gaps sink.** A measurement's `data_unavailable` rungs must not sit above
  another measurement's rules, or a protein-only target (RNA `data_unavailable`, CPTAC
  `strong_up`) would collapse to `data_unavailable`, discarding the measured protein
  signal.
- **Measured positives outrank measured negatives across modalities.** A target broadly
  *low* in DepMap cell-line RNA but strongly *up* in CPTAC tumor protein must not collapse
  to the RNA negative — that would be a false-negative headline contradicting its own
  `bulk_protein_ms/tumor: measured` bucket. So the collapse order is
  `[all measured positives] + [all measured negatives] + [gaps]`, RNA-backbone-first
  *within* each tier (byte-stable for positive-RNA targets). A flat/non-informative
  tumor-vs-adjacent read (`not_informative`) is treated as a coverage gap, not a measured
  negative, so it can never mask a measured positive elsewhere.

## Headline lens: tumor tissue outranks the pan-cancer cell-line proxy

Within `_EXPRESSION_RANK`, the tumor-tissue rungs (`tumor_broadly_expressed` /
`tumor_moderately_expressed`) rank **above** the pan-cancer cell-line distribution rungs
(`lineage_restricted`, `broadly_moderate`). Rationale: antigens that de-differentiate in
2D culture (EPCAM, FOLR1, CDH17, TACSTD2, …) show a collapsed cell-line median while the
tumor tissue reads top-percentile, so a cell-line-anchored one-word verdict *understates*
tumor presence. Cell-line `broadly_high` is kept at the top (when both lenses agree, the
verdict is unchanged), and a per-indication `tumor_sparsely_expressed` (neutral) stays
below the cell-line positives.

This ranking was justified by an offline A/B backtest over 43 target-indication pairs
across 10 indications: 23 verdict flips, every one to `tumor_broadly_expressed`, zero
dangerous flips. That conclusion is frozen as a credential-less regression matrix in
`tests/test_reanchor_flip_matrix.py`. The verdict-inert `cell_line_vs_tumor_discordant`
flag is now a standing invariant guard — it should read `False` for every target (the
tumor lens wins the headline whenever it out-tiers cell-line); a `True` value signals the
ladder regressed.

## Why the verdict is resolved inline (not via a `*.resolver.yaml`)

Every other verdict-bearing gate in the framework resolves via a declarative
`resolvers/<gate>.resolver.yaml`. `tumor-presence` deliberately does not. Its output is
two coupled things derived from the *same* ladders — the collapsed spine **and** the
per-`(measurement, sample_context)` bucket decomposition, which ranks *within* groups.
That grouping cannot be expressed in the resolver grammar (no grouping, lookups, or
loops). Splitting the collapsed order into YAML while the per-measurement ladders stayed
in Python would fragment one source of truth into two (drift risk), not simplify. The
ladder is instead frozen by the golden-spine test (`test_full_per_modality_golden_spine`)
plus the regression matrix — the golden-oracle guard a resolver migration would otherwise
provide.

## Verdict-inert facets (surfaced but never move the spine)

Everything except the three ladders and the collapse is verdict-inert. In particular:

- **RNA→protein proxy quality** (`bulk_rna_proxy_quality`) — qualifies a measured-positive
  bulk-RNA presence call by how well RNA proxies the protein it implies. Prefers the
  patient-tumor CPTAC arm (`rna-protein-concordance-tumor`) over the cell-line arm, since
  bulk-tumor purity / stroma / post-transcriptional regulation degrade RNA↔protein
  concordance far more than in cell lines, and it is strongly gene-specific
  (e.g. EPCAM/COAD: tumor `partial_proxy` r=0.46 vs cell-line `adequate` r=0.86). Flags an
  RNA-only presence claim that needs protein confirmation before an ADC/biologics read.
- **Two breadth layers** — `tumor-elevation-breadth` emits both a protein
  (`tumor_elevation_breadth_class`, CPTAC, ~10 indications) and an RNA
  (`rna_tumor_elevation_breadth_class`, DESeq2, ~27 indications) pan-cancer layer,
  surfaced side-by-side (never averaged) with `breadth_layer_concordance` so a protein
  coverage gap is legible rather than lost. The protein layer feeds the `_PROTEIN_RANK`
  ladder; the RNA layer is display-only.
- **Subtype panoramas** (tumor + cell-line) — raise confidence / define the patient
  population; one-directional, never a veto.
- **Purity confound** — is the tumor presence signal tumor-cell-intrinsic or
  microenvironment-driven? A caveat on the tumor presence call.
- **Normal-tissue comparators** — HPA-IHC and scRNA normal-tissue footprints; they frame
  the therapeutic window. High expression in normal tissue is a safety *liability* (the
  opposite polarity of high expression in tumor); the safety verdict is owned by
  `on-target-safety-liability`.

## Single-cell layer (`sc_rna`)

The single-cell tumor card (`tumor-scrna-celltype-expression`) fills the `sc_rna/tumor`
bucket and is verdict-bearing via `_SC_RNA_RANK` (malignant-anchored `sc_expression_class`
→ `sc_malignant_detected` / `sc_microenvironment_dominant` / `sc_broadly_low`). It ranks
below the bulk backbone (byte-stable) and carries no killer — a per-indication single-cell
read cannot kill a target-wide nomination.

Single-cell measures three things bulk cannot, all surfaced in the headline as
verdict-inert detail:

- **Per-compartment attribution** (`sc_per_compartment`, `sc_compartment_detection`) —
  cross-donor median detection fraction + abundance per compartment (malignant, stromal,
  immune, endothelial, epithelial_normal, other), so "present in the tumor" is decomposed
  into malignant-cell presence vs microenvironment presence.
- **CAF contrast** (`sc_caf_vs_malignant_class`, `sc_caf_detection_fraction`) — cancer-
  associated-fibroblast vs malignant expression. A target expressed mainly on CAFs looks
  tumor-present in bulk but is a stromal signal, not a malignant-cell antigen.
- **Expression homogeneity** (`sc_tce_homogeneity_class`) — how uniformly the malignant
  compartment expresses the target. Homogeneous expression is a prerequisite for T-cell
  engagers (heterogeneous expression permits antigen-negative escape). This class is
  rule-keyed only on the *surface* axis (`surface-modality-fit`); tumor-presence surfaces
  it as context.

Wired indications (method `INDICATION_TO_PRODUCT`): COADREAD, NSCLC/LUAD, LUSC, PAAD,
HNSC, KIRC, OV, **STAD**. Other indications read `data_unavailable` — an honest capability
ceiling, never a coarser fall-back.

The `sc_rna/normal` comparator (`sc-normal-celltype-expression`) covers each indication's
tumor-of-origin tissue plus an always-on critical-organ panel. Its per-cell-type footprint
is summarized in the headline as an organ-aware liability tier
(`sc_normal_safety_essential_class`) plus a ranked top-N of the most-detected cell types
(`sc_normal_top_essential_cell_types`); the full per-cell-type dict is retained as
`sc_normal_safety_essential_flags`.

## Version history

| version | date | change |
|---|---|---|
| 1.8.0 | 2026-08-18 | Production cleanup: run.py slimmed (rationale moved here); single-cell detail (per-compartment / CAF / homogeneity / abundance / dataset counts) and normal-tissue liability tier + top-N surfaced into the headline and synthesis facet; STAD sc coverage documented. Additive — verdict spine byte-stable. |
| 1.7.0 | 2026-08-14 | Tumor-tissue lens re-anchored above the pan-cancer cell-line proxy in `_EXPRESSION_RANK` (backtest-gated, verdict-moving). |
| 1.6.0 | 2026-08-13 | Added `headline_lens` + `cell_line_vs_tumor_discordant` + interpretation note (additive). |
| 1.5.0 | 2026-08-13 | Collapse re-ordered to `[positives] + [negatives] + [gaps]`; `not_informative` sinks to the gap tier; flat CPTAC read marks its bucket `measured`. |
| 1.4.0 | 2026-08-08 | RNA→protein tumor-arm concordance (`rna-protein-concordance-tumor`). |
| 1.3.0 | 2026-08-07 | scRNA normal-tissue comparator. |
| earlier | — | sc_rna/tumor card; tumor-elevation-breadth; per-`(measurement, sample_context)` bucket decomposition; two-slot `--synthesize`. |
