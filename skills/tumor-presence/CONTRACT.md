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

## Robustness guards (verdict-inert; added 1.9.0)

Three additive legibility facets close known misread paths without moving the spine (all frozen by the
golden-spine test + the guards' own unit tests):

- **`presence_headline_conflict`** (Principle 1 — *the headline must not silently contradict its own
  measured killer*). The collapse ranks measured positives over measured negatives (to protect antigens
  that de-differentiate in 2D culture), so an RNA-high target whose protein is a **measured** absence
  (cell-line `protein_broadly_low`) or down-contrast (CPTAC `protein_*_downregulated`) still reads
  present in the one-word verdict. The flag fires when a presence-positive headline co-exists with a
  measured presence-negative in another bucket, names the bucket(s), and emits an interpretation note. It
  stays silent on a measured *neutral* (e.g. CPTAC `present_not_elevated`) and on coverage gaps — those
  are not killers. Mirrors the `cell_line_vs_tumor_discordant` guard pattern.

  **Stage B (verdict-moving, 1.10.0)** — Stage A (above) makes the buried killer legible; Stage B also
  changes the WORD. When the winning rung is an RNA(expression)-lens positive AND a genuine protein-
  **ABSENCE** rule fired (`_PROTEIN_ABSENCE_RIDS`) AND no protein-positive fired, `_verdict` demotes the
  collapsed `presence_verdict` to **`present_rna_only_protein_absent`** (a distinct value minted post-
  collapse — a conjunction the single-field ladder grammar cannot express as a rung). It is still a
  PRESENT call (`_is_presence_positive` → True; the driving RNA rung is retained for traceability), so it
  is not a false-negative — but a consumer reading only the one word (not `presence_verdict_by_modality`)
  is no longer falsely reassured that protein was confirmed. Verdict-inert to the nomination spine
  (presence ∉ target-profile `_SHORT_TO_GATE`).

  **Absence ≠ down-contrast (finding G2b, 2026-08-20).** The demotion trigger is genuine protein ABSENCE
  ONLY — cell-line `protein_broadly_low` (the reachable signal: detected in <30% of the Gygi MS panel and
  not a rescued lineage-restricted antigen). It deliberately EXCLUDES
  the tumor-vs-normal DOWN contrasts (`protein-{modestly,strongly}-down-opposing`): a protein measured
  present-but-lower in tumor is a Phase-B *selectivity* signal, not Phase-A absence, so demoting a present
  call to "protein_absent" off a down-contrast is a category error. Those down rungs remain in the
  collapse's measured-negative tier (and in the `presence_headline_conflict` guard) — only the WORD-level
  demotion is narrowed to `_PROTEIN_ABSENCE_RIDS`. (The former CPTAC `not_detected` token was retired —
  whole-proteome TMT cannot assert per-gene absence, so a missing protein resolves to `data_unavailable`,
  not a measured negative: the dead rule + card vocab value were dropped in target-contracts #467, and the
  unreachable `protein_not_detected` verdict token was removed from `_MEASURED_NEGATIVE_VERDICTS` /
  `_PROTEIN_ABSENT_VERDICTS` in the 2026-08-21 sweep. Cell-line `protein_broadly_low` is the sole reachable
  protein-absence trigger.) Regression-covered by `test_per_modality_verdict.py::{test_genuine_protein_absence_demotes_
  collapsed_verdict, test_protein_down_contrast_does_not_demote_G2b_regression,
  test_protein_absence_demotion_requires_all_three_conditions}`.

- **`abundance_floor_flag`** (Principle 2 — *breadth ≠ level*). The presence classes are
  breadth-of-detection dominant: a protein detected in 100% of cell lines but sitting at the bottom decile
  of all-protein abundance still classes `broadly_moderate`. The flag reads `present_low_abundance` when a
  presence-positive call co-occurs with a bottom-decile abundance **level** anchor (tumor-RNA / cell-line
  RNA / cell-line protein — the CPTAC and RNA-vs-adjacent percentiles rank a tumor-vs-normal *contrast*,
  not a level, and are deliberately excluded), and names the low lens. It also caps the claim-vector's
  Claim-A corroboration so a `broadly_moderate` presence is never read as `abundant` without checking the
  level anchor. Canonical case: EPCAM/COADREAD — tumor RNA top-1% but cell-line protein bottom-decile.

- **`presence_abundance_is_relative`** (Principle 6 — *name the ceiling*). A standing `True` provenance
  flag: every protein signal here is RELATIVE (TMT log2-ratios, panel percentiles), never absolute
  copies/cell. Surface topology and absolute antigen density are owned by `surface-modality-fit`; do not
  infer "enough antigen" for a modality decision from a presence-positive.

- **`protein_confirmation_state`** (finding G5 — *name the untested case*). For a PRESENT collapsed
  verdict, states whether protein was `confirmed` (measured present in the tumor-CPTAC or cell-line-MS
  bucket), `measured_absent` (measured cell-line `protein_broadly_low` and nowhere confirmed present),
  `untested` (no protein bucket is `measured` — RNA-only presence), or `not_applicable` (the collapsed
  verdict is not a presence-positive). A protein PRESENT reading in ANY context wins (cell-line MS
  under-samples surface antigens, so a tumor-present / cell-line-absent target is `confirmed`), mirroring
  the positives-over-negatives collapse. **Design note:** the measured-ABSENT contradiction is a rare,
  alarming state and is handled at the SPINE (`present_rna_only_protein_absent`); the UNTESTED case is
  the MODAL case (most indications lack CPTAC / cell-line-MS) and is *lower confidence, not a different
  presence state*, so it is surfaced HERE as a verdict-inert facet rather than minting a new default
  spine word (which would rewrite the most common presence verdict and conflate confidence with
  presence). The one word therefore stays byte-stable; read `protein_confirmation_state` (and the claim
  vector) for the confidence behind it. Regression-covered by `tests/test_protein_confirmation_state.py`.

- **`presence_signal_strength`** (verdict-inert — *name the neutral-only present call*). `supportive`
  (a `-supportive` rung drove the collapse), `neutral` (only a `-neutral` low/moderate rung — e.g. a
  sole single-cell `sc_broadly_low` or a `tumor_sparsely_expressed`), `none` (nothing fired →
  `insufficient`), or `other` (a measured-negative / gap drove it). These neutral/low rungs collapse
  INTO the positive tier BY DESIGN (a per-indication low read must never kill a target-wide nomination),
  so `_is_presence_positive` is `True` for them — but the driving evidence is only neutral. This facet
  lets a downstream consumer distinguish a strong present call from an only-neutral-evidence one WITHOUT
  re-tiering the collapse. Keyed on the driving rule (self-maintains with the ladder via the
  `-supportive`/`-neutral` rule_id suffix). Pinned by `tests/test_collapse_tier_legibility.py`.

- **`measured_present_despite_insufficient`** (verdict-inert — *name the insufficient-vs-measured
  disagreement*). Sorted list of `(measurement, sample_context)` buckets that read a MEASURED-present
  sub-verdict while the collapsed word is `insufficient`. The one case this fires on is a CPTAC-flat-only
  target: `protein_present_not_elevated` is rescued into the `bulk_protein_ms/tumor` bucket by
  `_MEASURED_UNRULED_PRESENT` but fires NO ladder rung, so it cannot lift the collapsed word off
  `insufficient`. The field keeps the one word from being mistaken for "nothing measured". Empty for
  every other case. Pinned by `tests/test_collapse_tier_legibility.py`.

## Ladder governance (why an inline verdict is still guarded)

Because the verdict is resolved inline (not via a `*.resolver.yaml`), the ladder ORDER — which encodes
scientific-priority judgments — has no declarative-resolver governance. `tests/test_ladder_invariants.py`
supplies it, asserting the ordering principles directly (positives > negatives > gaps; tumor tissue >
cell-line proxy; RNA backbone > protein > single-cell; protein-absence is a negative) so a reorder that
violates a principle fails and forces the rationale to be updated with it. The same file proves the
**no-dangerous-flip** invariant *totally* (a presence-positive can never be conjured from a fired-set of
only negatives/gaps) — a structural property over the whole ladder that supersedes the original,
now-unreproducible ("run out-of-tree, ephemeral") 43-pair re-anchor backtest, whose per-pair data was
never committed. The synthetic flip-class assertions in `test_reanchor_flip_matrix.py` are retained.

## Version history

| version | date | change |
|---|---|---|
| 1.13.0 | 2026-08-21 | Verdict-inert collapse-tier legibility: `presence_signal_strength` (M1 — distinguishes a supportive present call from an only-neutral-evidence one, e.g. sole `sc_broadly_low`) + `measured_present_despite_insufficient` (M2 — names a CPTAC-flat-only bucket measured-present under an `insufficient` collapse). `cell_line_vs_tumor_discordant` unreachability now proved TOTAL over the two-lens RNA space (L6). Spine byte-stable. |
| 1.12.0 | 2026-08-20 | Surface the variance-standardized CPTAC effect (analysis-methods #432 / card #450) into the headline + synthesis facet (`protein_effect_standardized_class`, `protein_effect_cohens_d`, `protein_effect_standardized_t`, `protein_effect_standardized_method`) — the variance-aware companion to the raw `protein_effect_size` the class thresholds on. Verdict-inert. |
| 1.11.0 | 2026-08-20 | Surface the two-axis TCE antigen-escape readout (analysis-methods #429 / card #449) into the headline + synthesis facet (`sc_within_tumor_coverage_class`, `sc_inter_donor_consistency_class`, `sc_tce_antigen_escape_class`, `sc_malignant_detection_donor_iqr`, `sc_fraction_donors_broadly_detecting`) — the honest heterogeneity call superseding the lenient `sc_tce_homogeneity_class` (retained). Cosmetic: `present_rna_only_protein_absent` added to the composite-panel color map + target-profile risk-render MEDIUM bucket. Verdict-inert. |
| 1.10.0 | 2026-08-20 | **Verdict-moving**: protein-absence demotion (Principle 1 Stage B) — an RNA-lens positive with a MEASURED protein-negative and no protein-positive now collapses to the new value `present_rna_only_protein_absent` (still a present call; driving RNA rung retained) instead of an un-caveated RNA positive that buried the protein contradiction. Verdict-inert to the nomination spine. |
| 1.9.0 | 2026-08-20 | Verdict-inert robustness guards: `presence_headline_conflict` (buried measured-negative), `abundance_floor_flag` (breadth≠level, caps claim-A corroboration), `presence_abundance_is_relative` ceiling flag; claim-vector Claim-D corroboration now scales with cohorts-tested (was hardcoded `moderate`). Ladder-invariant + no-dangerous-flip governance test. Spine byte-stable. |
| 1.8.0 | 2026-08-18 | Production cleanup: run.py slimmed (rationale moved here); single-cell detail (per-compartment / CAF / homogeneity / abundance / dataset counts) and normal-tissue liability tier + top-N surfaced into the headline and synthesis facet; STAD sc coverage documented. Additive — verdict spine byte-stable. |
| 1.7.0 | 2026-08-14 | Tumor-tissue lens re-anchored above the pan-cancer cell-line proxy in `_EXPRESSION_RANK` (backtest-gated, verdict-moving). |
| 1.6.0 | 2026-08-13 | Added `headline_lens` + `cell_line_vs_tumor_discordant` + interpretation note (additive). |
| 1.5.0 | 2026-08-13 | Collapse re-ordered to `[positives] + [negatives] + [gaps]`; `not_informative` sinks to the gap tier; flat CPTAC read marks its bucket `measured`. |
| 1.4.0 | 2026-08-08 | RNA→protein tumor-arm concordance (`rna-protein-concordance-tumor`). |
| 1.3.0 | 2026-08-07 | scRNA normal-tissue comparator. |
| earlier | — | sc_rna/tumor card; tumor-elevation-breadth; per-`(measurement, sample_context)` bucket decomposition; two-slot `--synthesize`. |
