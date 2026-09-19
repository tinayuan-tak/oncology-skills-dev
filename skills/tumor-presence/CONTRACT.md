# tumor-presence — design contract & rationale

This document holds the *why* behind `scripts/run.py`. `run.py` itself is a thin
configuration over the shared dispatcher (`_skills_common/dispatcher.py`) and carries
only terse comments; the design decisions, invariants, and the history that justifies
them live here. See [SKILL.md](SKILL.md) for the user-facing contract and flags, and
[README.md](README.md) for a first-run guide.

## What the skill computes

`tumor-presence` answers a Phase-A question: *is target X present in indication Y's
tumor tissue, and how does it distribute across cancer cell lines vs. tumor samples, at
RNA, whole-cell protein, and single-cell resolution?* It reads 17 pre-computed cards and
emits:

- a collapsed one-word `presence_verdict` (+ `driving_rule_id`), and
- one sub-verdict per `(measurement, sample_context)` bucket
  (`presence_verdict_by_modality`), so a cell-line signal is never conflated with a tumor
  signal and cross-modal tension is legible.

It reads pre-computed derived products; it does **not** recompute any DGE, and it does
**not** compare against GTEx population-normal (that is `tumor-selectivity`).

## The four moving parts in run.py

1. **`CARDS` + `CARD_CONTEXT`** — the 17 cards consumed, each tagged with its
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

## Card roster (17)

**Verdict-bearing (7)** — feed the presence ladders:
`cellline-rna-distribution`, `tumor-rna-vs-adjacent`, `tumor-rna-distribution`,
`tumor-protein-abundance-cptac`, `cellline-protein-abundance`, `tumor-elevation-breadth`,
`tumor-scrna-celltype-expression`.

**Display-only facets (8)** — additive context, feed no ladder (verdict byte-stable):
`tumor-rna-distribution-by-subtype`, `cellline-rna-distribution-by-subtype`,
`tumor-protein-distribution-by-subtype` (CPTAC protein by-subtype), `expression-purity-confound`,
`cellline-rna-protein-concordance`, `rna-protein-concordance-tumor`,
`cellline-protein-abundance-procan` (2nd MS platform, ProCan DIA — v1.19),
`hpa-pathology-cancer-ihc` (MS-independent antibody IHC protein-in-tumor, `protein_ihc/tumor` — v1.15).

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
  verdict, states whether protein was `confirmed` (measured present **in this indication's tumor** — a
  CPTAC/subtype TMT-MS positive **or** an HPA antibody-IHC detection), `confirmed_cell_line_only`
  (cell-line MS present, tumor-tissue protein untested), `measured_absent` (a measured indication-grain
  absence — an antibody-IHC `not_detected` or a bulk-MS `protein_broadly_low` — and nowhere confirmed
  present), `untested` (no indication-grain tumor-protein bucket is `measured` — RNA-only presence), or
  `not_applicable` (not a presence-positive). An indication-grain protein PRESENT reading wins over
  cell-line/pan-cancer (cell-line MS under-samples surface antigens), mirroring the
  positives-over-negatives collapse **applied at the right grain**. **Grain (v1.23.0):** two weaker grains
  also land in the `bulk_protein_ms/tumor` bucket and must NOT satisfy `confirmed`: (1) `tumor-elevation-breadth`
  is a pan-cancer *target-grain* card, so its breadth verdicts (`multi_tumor_elevated` etc.) are excluded
  from the confirmed trigger — a breadth-only bucket is `untested`, not `confirmed` (fixes GFAP/COADREAD
  reading `confirmed` with `protein_expression_class=data_unavailable`); (2) a MEASURED antibody-IHC
  `not_detected` in the indication tumor (`protein_ihc/tumor`) reaches `measured_absent` even when a
  pan-cancer/cell-line positive is present (fixes CD19/COADREAD reading `confirmed` despite a measured IHC
  absence). No new state token; verdict-inert (presence_verdict byte-stable). **Design note:** the measured-ABSENT contradiction is a rare,
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

## Why the `subset_high` rung exists (the population-vs-abundance split)

`tumor-rna-distribution` emits `tumor_expression_class`, and two of its values had shared one rung,
one verdict and one headline phrase:

| class value | fires at | population reading |
|---|---|---|
| `broadly_high` | `high_fraction >= 0.5` | a majority of patients express the target highly |
| `subset_high` | `high_fraction >= 0.1` **and** a bimodal / long-tail shape | as few as **10%** of patients do |

Both matched `tumor-expression-broadly-high-supportive` (`in: [broadly_high, broadly_detected,
subset_high]`), collapsed to `tumor_broadly_expressed`, and rendered as *"Broadly expressed in tumor"*.
For an ADC or T-cell-engager nomination that conflation is the difference between a **population
hypothesis** and a **patient-selection hypothesis** — and nothing downstream could recover it:
`presence_signal_strength` keys on the rule-id suffix, and both rungs are legitimately `-supportive`,
so that channel cannot separate them either (see § three strength channels below).

`tumor-expression-subset-high-supportive` → `tumor_subset_high_expression` splits them.

**Ordering.** The rung sits BELOW `tumor_broadly_expressed` and ABOVE the moderate rungs. A minority-high
subset is a *narrower population* than broad tumor expression, but a *stronger abundance read* than
broadly-moderate — those are two different axes, and the ladder ranks presence strength, so the rung
takes the position its abundance justifies while the verdict WORD carries the population caveat.

**Tier 2, deliberately.** `_PRESENCE_TIER` puts it at 2, not 3, which has two consequences and both are
intended: (a) the INV-1 tier cap (`_TIER3_TO_TIER2`) does not apply, because there is nothing to demote —
it is already tier 2; and (b) `cell_line_vs_tumor_discordant` becomes reachable in the
`cell_line_overstates_tumor` direction when a cell-line `broadly_high` (tier 3) sits beside it. That
`True` is a **legitimate reading**, not a regression: *the panel reads uniformly high, the tumor is high
in a subset.* It is the compensating channel where the collapsed word cannot carry the distinction,
because the cell-line rung still anchors the headline. Prose in SKILL.md/README.md that called any
`True` a ladder regression was corrected with this change.

**`_TIER3_TO_TIER2` deliberately does NOT map `tumor_broadly_expressed` → `tumor_subset_high_expression`.**
That would fabricate a prevalence claim (10%-of-patients) out of an abundance signal. Two different axes
wearing the same word "demote". The absence is documented at the map so a completeness sweep does not
"finish" it.

**Collapse invariant, restated.** The rung is a presence-POSITIVE (`-supportive` suffix; not in
`_MEASURED_NEGATIVE_VERDICTS` or `_COLLAPSE_GAP_VERDICTS`), so it sorts inside the positive tier and the
no-dangerous-flip proof in `test_ladder_invariants.py` is untouched: no fired-set of negatives and gaps
can reach it.

**Why the ladder must list it at all — the false-absence trap.** `_EXPRESSION_RANK` is a CLOSED
`(rule_id -> verdict)` list and `_rank_verdict` returns the first *fired* entry. A fired `rule_id` the
ladder does not list is therefore **invisible, not demoted** — the collapse falls through to
`insufficient`, a coverage-gap class *below* measured negatives. Re-routing `subset_high` to a new rule
without adding the rung would have reported "no data" for a target measured high in 10–50% of patients.
Guard 3 in `test_ladder_invariants.py` now checks the producer's whole declared vocabulary reaches a rung.

**Phase ordering (this is a 3-phase change across a live-read repo boundary).**

| phase | repo | edit | effect |
|---|---|---|---|
| 1 | target-contracts | ADD `tumor-expression-subset-high-supportive` (TC#805, `6ff21f8`) — `subset_high` still ALSO on the broad rule | none: both rules fire |
| 2 | claude-oncology-skills | this change — rung, phrase, facets, headline keys | none: broad rung still out-ranks |
| 3a | target-contracts | declare `tumor_subset_high_expression` in `$defs.presence_verdict_enum` (`schemas/_skill_output/pins/tumor-presence.pins.json`, append-only) + regenerate | none: additive |
| 3b | target-contracts | REMOVE `subset_high` from the broad rule's `in:` list | **the flip** |

Phase 2 is verdict-inert **by measurement**, not by intent — verified as a 2×2 (trunk vs this branch) ×
(overlap retained vs narrowed): identical on today's contracts, and `insufficient` on trunk under
narrowed rules, which is the false absence this rung prevents.

**3a is not optional and must precede 3b.** The verdict token is declared in a *second, separate* place
from the rule: the pinned `presence_verdict_enum` (33 values as of 2026-09-18) baked into
`schemas/skills/tumor-presence.decision.schema.json`. It did not contain `tumor_subset_high_expression`,
and injecting the token into the frozen EPCAM decision fails validation with the same *"is not one of
[…]"* error as a garbage string. Landing 3b first would make every `subset_high` run emit a
`decision.json` that fails its own data-product contract. Nothing in either repo compared the ladder's
tokens to that enum, which is how the gap survived a green suite; `test_ladder_invariants.py` guard 4
now does, holding the open gap as a **named** allowlist so it reds the moment 3a lands.

**Why the flip COUNT is a phase-3 measurement.** A live-panel flip matrix run at phase 2 is all-zeros by
construction, and the committed corpus contains **zero** `subset_high` exemplars (both frozen decision
fixtures read `broadly_high`), so re-scoring what is in the tree cannot move a row either. What phase 2
commits instead is the deterministic flip *semantics* — which fired-set shapes move, which must not, and
what compensates — in `tests/test_reanchor_flip_matrix.py`, mutated in both directions.

## The three strength channels (and what each one can and cannot separate)

"Strength" is not one thing in this skill. There are **three** independent channels, and a change that
sharpens one does not sharpen the others. Documented here because the distinction was nearly mis-stated
in the 1.22.0 review: an in-code comment initially claimed the new rung "delivers the split" in
`presence_signal_strength`, which it does not and cannot.

| channel | keyed on | what it separates | on the `subset_high` split |
|---|---|---|---|
| `presence_strength_from_state(presence_state, claim_vector)` | the claim vector — the PRIMARY basis | measured evidence weight | separates the two rungs, because the verdict token differs |
| `_presence_strength(verdict)` via the `_PRES_*_POS` sets | the verdict token — the LEGACY FALLBACK for 3-arg callers; also backs `_pres_direction` | verdict tier | `tumor_subset_high_expression` is in `_PRES_MOD_POS`, so it reads **moderate** where `tumor_broadly_expressed` reads strong |
| `presence_signal_strength` = `_presence_signal_strength(driving_rule_id, verdict)` | the rule-id **SUFFIX** | supportive vs neutral-only vs negative vs nothing | **cannot** separate them — BY DESIGN |

**The `presence_signal_strength` limitation, stated plainly.** Both rungs end in `-supportive`, so this
channel reports `supportive` for a 10%-of-patients target and for a 60%-of-patients target alike. That is
correct behaviour, not a gap to close: the facet's question is *"was the driving evidence supportive, or
merely neutral?"* — a minority-high subset **is** supportive evidence of presence. Renaming the rung to
break the suffix convention would corrupt the facet's own invariant
(`test_collapse_tier_legibility.py::test_signal_strength_sets_partition_the_positive_tier` asserts every
positive rung is `supportive` or `neutral`) to smuggle in a different axis.

Consumers that need the population distinction must read **`presence_verdict`** (the token and its
phrase) or **`tumor_high_fraction`** (the raw prevalence, newly lifted into the headline in 1.22.0) —
not `presence_signal_strength`.

## Version history

| version | date | change |
| 1.23.0 | 2026-09-19 | **`protein_confirmation_state` grain fix** (see § above). (1) The pan-cancer target-grain `tumor-elevation-breadth` verdicts share the `bulk_protein_ms/tumor` bucket with indication-grain CPTAC/subtype, so a breadth-only bucket read `confirmed`; those verdicts (derived from `_PROTEIN_RANK`'s `tumor-breadth-*` rules) are now excluded from the confirmed trigger → `untested`. (2) The facet now reads the `protein_ihc/tumor` bucket symmetrically, so a measured antibody-IHC `not_detected` reaches `measured_absent` (previously unreachable). No new state token, no contract change. **Verdict-inert** (presence_verdict + presence_verdict_by_modality + resolver goldens byte-stable; only the confidence facet + `presence_confirmation_caveat` move). |
|---|---|---|
| 1.22.0 | 2026-09-18 | **`subset_high` split, phase 2 of 3** (see § above): new `_EXPRESSION_RANK` rung `tumor-expression-subset-high-supportive` → `tumor_subset_high_expression` (tier 2) so a target high in as few as 10% of patients is no longer reported with the same word and phrase as a broadly-expressed one; prevalence-naming phrase; `tumor_expression_class` + `tumor_high_fraction` lifted into the headline and synthesis facet (that card's class/fraction had never been surfaced). New ladder guards: producer-vocabulary REACH (guard 3) and output-vocabulary DECLARATION against the pinned `presence_verdict_enum` (guard 4). **Verdict-inert by measurement** on today's contracts (2×2 verified); verdict-MOVING at phase 3, which needs 3a (declare the token in the enum) BEFORE 3b (narrow the broad rule). Also corrects stale prose in `run.py`/`SKILL.md`/`README.md` that called any `cell_line_vs_tumor_discordant: True` a ladder regression. |
| 1.21.0 | 2026-09-10 | `--literature` retriever routed through the shared `default_retrieve` (EPMC → PubTator3 fallback) so the optional literature lane no longer hard-depends on a single source (#1263). Verdict-inert (literature is a sibling key). |
| 1.20.0 | 2026-09-04 | Consolidated `presence_confirmation_caveat` (the RNA-only / protein-only / stromal-confound reconciliation caveat) + `thesis` / `polarity_note` surfaces + `--literature` refinement (#1033). Verdict-inert. |
| 1.19.0 | 2026-09-04 | Surface-class abundance anchor: for a surface/secreted-class target the abundance read prefers ProCan DIA / HPA-IHC over the Gygi TMT card (#980 / #1008). Verdict-inert. |
| 1.18.0 | 2026-09-03 | Consume `sc_normal_abundance_class` — abundance-aware window breadcrumb on the sc-normal comparator (#984 Tier-2 / #989). Verdict-inert. |
| 1.17.0 | 2026-09-03 | Tier-1 single-cell utilization: consume sc QC + malignant-annotation provenance into the sc_rna/tumor bucket (#984 / #985). Verdict-inert. |
| 1.16.0 | 2026-09-03 | Optional LLM `--literature` lane + verdict-inert claim-vector signal enrichment (#965). Sibling key — spine byte-stable. |
| 1.15.0 | 2026-08-27 | Wire HPA antibody IHC protein-in-tumor into the new `protein_ihc/tumor` bucket (`hpa-pathology-cancer-ihc`, MS-independent, ~20 cancer types) (#836). Measured-unruled → collapsed verdict byte-stable. |
| 1.14.0 | 2026-08-27 | Adopt the shared capsule-driven narrator engine (retire the bespoke tumor-presence narrator), part of the 13-skill fan-out (#828). Verdict-inert. |
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
