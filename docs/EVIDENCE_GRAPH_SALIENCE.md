# Evidence-Graph Salience Audit (Stage 0)

**Status:** discovery deliverable — GATES Stage 1 (`key_evidence` promotion) and Stage 2 (grounded
narrative). No code. Every value below is from a REAL run under `~/dev/framework-runs/`.

**What this answers (the user's explicit ask):** *"what decisive data points actually exist per subskill,
which does our current structure DROP, and what does a great output read like?"*

- **§1 The projection gap** — verified root cause, with the exact lossy line.
- **§2 Cross-cutting salience findings** — the patterns that hold across all ~14 skills.
- **§3 Per-measurement_type audit** — one ranked table + salient-field spec per measurement_type.
- **§4 Ideal-bullet exemplars** — the narrative quality bar (Stage-2 few-shot target).
- **§5 Eval rubric** — the checks generated bullets must pass.
- **§6 Stage-1 consumption** — how §3's specs feed the `reader_spec` + `key_evidence` promotion.

---

## §1 — The projection gap (verified)

Each card computes a rich `summary`. `evidence_capsule.py::emit_capsules` selects six deterministic shapes
from it — `numeric_anchors`, `top_k_strata`, `n_basis`, `categorical_anchors`, `sibling_caveats`,
`conflict_pairs` (+ `cited_statements` for literature cards). The graph builder then projects the capsule
into each card node. **The single lossy line** (`evidence_graph.py`, in `build_evidence_graph`'s card loop):

```python
numeric = cap.get("numeric_anchors") or []
chain = {..., "data": [{"field": a.get("metric"), "value": a.get("value")} for a in numeric[:4]], ...}
key_fields = {a.get("metric"): a.get("value") for a in numeric if a.get("metric")}
```

The card node carries **only `numeric_anchors`**. `top_k_strata`, `n_basis`, `sibling_caveats`,
`conflict_pairs`, and `categorical_anchors[1:]` are all discarded. That is why graph-derived text reads
generic ("median Chronos −0.46") while the decisive facts sit unused in the capsule and the summary.

Three stacked defects, all verified on `functional-requirement KRAS·COADREAD`, driving card
`dependency-lineage-selectivity` (`measurement_type: crispr_lof_dependency`):

1. **Graph drops the capsule's sharp shapes.** The capsule *did* compute `top_k_strata` and
   `conflict_pairs`; the graph carried neither — only `numeric_anchors` = `{lineage_variance_explained:
   0.186, median_chronos_panel: −0.457}` (pan-panel scalars).
2. **The capsule selected the wrong array + dropped significance.** `_top_k_strata` took the *first*
   list-of-dicts (`per_lineage_stats`, 26 rows, **no q**) not `enriched_lineages` (3 rows, **carries
   q_value + effect_size + p_value**). It returned Pancreas (−1.83, n=74) and **Kidney** (−0.33, n=35) —
   and matched the indication row by substring, so **`COADREAD` never matched lineage `Bowel`** and the
   indication row was silently dropped. No q-value on any returned stratum.
3. **The omnibus is invisible.** `lineage_omnibus_p = 7.14e-50` (Kruskal H=304.6, effect class *large*)
   fails the `_ANCHOR_HINTS` `p_value` test (the substring is `omnibus_p`, not `p_value`/`pvalue`), so it
   is captured by neither `numeric_anchors` nor `n_basis`.

Net: the decisive message — *"Bowel (indication) Chronos −1.18, q=3.8e-16; Pancreas −1.83, q=2.7e-25;
omnibus p=7e-50"* — exists in `decision.cards[].summary` but reaches **neither** the card `key_fields`
**nor** anything the narrator can ground on. This is a **projection gap, not a 149-card authoring
problem.** (`enriched_lineages` already exists and already carries q.)

---

## §2 — Cross-cutting salience findings (hold across skills)

These recur in every skill's audit (§3) and drive the Stage-1 `key_evidence` shape and per-type spec.

**F1 — Significance is the most-dropped ★★★ field.** The q/p/omnibus/constraint stat is what a reviewer
cites to *break* a call, yet it is the most frequently lost datum:
- lands in a strata row `_top_k_strata` ignores (`enriched_lineages[].q_value`), OR
- is a scalar no hint matches (`lineage_omnibus_p`; `intogen_min_qvalue`; `amp_expr_mannwhitney_p`;
  `cn_stratification_mannwhitney_p`; gnomAD `loeuf_score`/`pli_score`/`mis_z_score`).
→ Stage-1 spec MUST name an explicit `significance_field`/`omnibus_field` per type and MUST carry `q` on
each `top_strata` row. Do NOT rely on `_ANCHOR_HINTS`.

**F2 — The indication row is the single most decisive stratum, and it's the one dropped.** Substring
matching (`ind in label`) fails on the framework's own vocabulary (`COADREAD`⊄`Bowel`;
`LUAD`⊄`Lung`). Resolve via the existing `INDICATION_TO_*` maps. A `key_evidence.top_strata` that omits
the indication row is worse than useless — it invites the narrator to cite the wrong lineage.

**F3 — `n_basis` is where the decisive COUNT hides for liability/categorical cards.** For safety and
categorical-verdict cards the load-bearing number is a *count*, not a float effect: `n_pathogenic_germline
= 118`, `n_lethal = 13`, `n_autosomal_dominant = 1`, `n_boxed_warning_terms = 2`. All computed into
`n_basis`, all dropped by the graph. `key_evidence` must carry `n_basis` (or promote the decisive count
into the `n`/`significance` slot).

**F4 — The decisive datum is often a STRING the numeric selectors can't carry.** `fit_class`,
`network_class`, `highest_tissue = SKIN`, `critical_organ_argmax = NERVE`, `dep_control_position_class =
between_controls`, best-compound name, top SL partner. These are visible only if the card *declares*
`categorical_fields` — most don't. `key_evidence` needs a small typed `categorical` slot fed by the
per-type spec, not just `class`.

**F5 — `conflict_pairs` is computed and decisive, and always dropped.** When siblings on one
measurement_type disagree ≥2 tiers (FR: `lineage_selective` vs `strongly_selective` vs
`broad_organoid_dependency`) that tension is exactly what a reviewer flags. It never reaches the graph.
Promote it (it is already bounded).

**F6 — Ranked LISTS are the payload for the relational/descriptive skills.** combination
(ranked SL/combo partner table), mechanism (upstream/downstream node lists), differentiation (co-mutation
partners + q), literature (`top_cited` pmids). A single scalar cannot represent them; `key_evidence` needs
a `top_strata`-shaped list that also accepts partner/node/citation rows (label + effect + q/rank).

**F7 — "generic pan-panel scalar wins the anchor slot."** Because `numeric_anchors` is hint-matched and
alphabetical-capped at 4, the fields that survive are the least decisive (`fraction_non_essential`,
`median_chronos_panel`, `cn_p95_panel`) while the sharp stratum/effect loses. The per-type spec fixes the
priority explicitly.

**F8 — Subtype/subgroup-stratified evidence is carried STRUCTURALLY but not as EVIDENCE.** The graph is
subtype-*aware* — `_ambiguous_measurement_types` disambiguates a `tier=subtype` card from its whole-cohort
sibling, `subtype: true` question rows exist, and the `subgroup_signals` spine is read — yet the actual
per-subtype numbers never reach `key_evidence`. Subtype-stratified cards carry a **parallel omnibus**
structure the current shapes cannot represent, and it is fully dropped (grounded, §3.16):
- FR `subgroup-stratified-dependency` — MSS Chronos −1.22 (n=71, strong) vs MSI_H −0.69 (n=17, moderate):
  capsule `numeric_anchors=None, top_k_strata=None` → the entire subtype split is dropped.
- tumor-presence `tumor-rna-distribution-by-subtype` (`tier=subtype`) — a `subtype_omnibus_by_axis` array,
  one row per molecular axis (CIMP/CMS/MSI/sidedness/stage), each with `subtype_omnibus_p`,
  `subtype_variance_explained`, `subtype_effect_size_class`, `which_subtypes_separate {highest,lowest}`,
  plus `subtype_stratification_class` (e.g. `pan_subtype_uniform`) + `subtype_omnibus_driving_axis`. Only
  `subtype_variance_explained` survives (it happened to match a hint); the axis breakdown, driving axis,
  and which-subtypes-separate are all lost.
- differentiation `subtype-survival-association` — `per_axis_association`: sidedness stratifies survival
  (logrank p=0.024) while CMS/MSI/CIMP/stage do not; `numeric_anchors=None, top_k_strata=None` → dropped.
→ `key_evidence` needs an OPTIONAL `subtype_axis` slot with a `subtype` role in `top_strata`, and the
per-type spec needs `subtype_array`/`subtype_omnibus_field`/`driving_axis_field`. It MUST be null-safe when
the subtype axis is absent (`--subtypes`-gated for most skills; tumor-presence + FR-full carry it by
default) so standard-run goldens stay byte-stable. Adversarial: the narrator must respect
`subtype_stratification_class=pan_subtype_uniform` (a decisive NEGATIVE — "no subtype restriction") and
never narrate a uniform axis as a subtype-restricted signal.

**Buckets used in §3:** `captured` (survives to graph today) · `dropped` (capsule computes, graph discards)
· `unranked` (in summary, no capsule shape selects it) · `uncomputed` (real upstream gap, out of scope).

**Proposed `key_evidence` shape (Stage 1 will refine):**
```
key_evidence = {
  effect:      {metric, value, direction},          # the load-bearing effect for THIS card
  n:           <int>,                                # panel/cohort/model basis
  significance:{stat, value},                        # q / p / LOEUF / mannwhitney_p — F1
  omnibus?:    {stat, value},                        # cross-stratum test — F1
  top_strata:  [≤3 {label, role(indication|strongest|weakest), value, n, q?}],  # F2, F6
  categorical?:[{field, value}],                     # F4 (fit_class, highest_tissue, …)
  n_basis?:    {<count>: <int>},                     # F3
  conflict?:   {this_class, other:[{card,class,tier}]}, # F5
  subtype_axis?: {                                     # F8 — null when subtype axis absent
    driving_axis, restriction_class,                   # e.g. MSI, pan_subtype_uniform
    omnibus:{stat,value},                              # subtype_omnibus_p on the driving axis
    which_separate:{highest,lowest},                   # e.g. {highest: MSI_H, lowest: MSS}
    top_subtypes:[≤3 {label, value, n}]                # per-subtype effect rows
  }
}
```
Full arrays stay in `decision.cards[].summary` for the deepest drill; `key_evidence` is the bounded,
grounded substrate for the narrator + card-chain renderer.

---

## §3 — Per-measurement_type audit

Legend: decisiveness ★★★ reviewer cites to make/break · ★★ supporting · ★ context. Bucket per §2.

### 3.1 functional-requirement (ANCHOR — worked reference)

#### measurement_type: crispr_lof_dependency   (skill: functional-requirement · example card: dependency-lineage-selectivity · run: KRAS·COADREAD · verdict-bearing: Y — DRIVING)

| # | data point | raw field (source array) | in graph today? | decisiveness | bucket | action |
|---|-----------|--------------------------|-----------------|:------------:|--------|--------|
| 1 | indication stratum effect | `enriched_lineages[Bowel].median_chronos` = −1.18 | no (substring miss) | ★★★ | unranked | resolve indication row via `INDICATION_TO_*`, promote |
| 2 | its significance | `enriched_lineages[Bowel].q_value` = 3.8e-16 | no | ★★★ | dropped | pin `enriched_lineages`, carry `q` on the row |
| 3 | strongest stratum + q | `enriched_lineages[Pancreas]` = −1.83, q=2.7e-25, effect 0.73, n=74 | partial (top_k, no q) | ★★★ | dropped | promote to `top_strata` with q |
| 4 | omnibus significance | `lineage_omnibus_p` = 7.14e-50 (Kruskal H=304.6) | no (hint miss) | ★★★ | dropped→uncaptured | declare `omnibus_field` explicitly |
| 5 | therapeutic-window position | `dep_control_position_class` = between_controls (ceiling −1.499 / floor −0.038) | partial (categorical[0] only) | ★★★ | dropped | carry as `categorical` (Q2 window) |
| 6 | sibling conflict | 3 crispr cards: lineage_selective vs strongly_selective vs broad_organoid | no | ★★ | dropped | promote `conflict` (F5) |
| 7 | panel n | `n_cell_lines_panel` = 1538 | yes (n_basis, dropped by graph) | ★★ | dropped | carry `n` |
| 8 | pan-panel median | `median_chronos_panel` = −0.457 | **yes (numeric_anchors)** | ★ | captured | keep as context, DEMOTE from headline |
| 9 | variance explained | `lineage_variance_explained` = 0.186 | yes | ★★ | captured | keep |

```
SALIENT-FIELDS SPEC (→ Stage 1 reader_spec):
  strata_array: enriched_lineages     effect_field: median_chronos     significance_field: q_value
  omnibus_field: lineage_omnibus_p    n_field: n_cell_lines_panel       direction: lower_is_stronger
  categorical: [dep_control_position_class]   extra_scalars: [selectivity_index]
```

#### crispr_lof_dependency siblings (same type, different cards)
- **pan-cancer-crispr-dependency-distribution** — decisive: `dep_control_position_class`+`selectivity_index`
  (0.855) + `distribution_shape` (bimodal_selective); strata = `top_dependent_lineages` (no q; use as
  supporting, defer to `enriched_lineages` for the significance-bearing view).
- **organoid-crispr-dependency** — decisive: indication `per_lineage_stats[Bowel].frac_dependent` = 0.95
  (n=22) + `median_gene_effect` −0.87 + `organoid_dependency_percentile` 94.4. Strata carry no q →
  `significance_field: —`, `effect_field: frac_dependent`, `direction: higher_is_stronger`.

#### rnai_lof_dependency (pan-cancer-rnai-dependency-distribution) — verdict-bearing
Decisive: `rnai_dependency_class` (strongly_selective) + `rnai_median_dep_score` (−0.12) + n (701 lines).
Orthogonal LoF confirmation of CRISPR. No strata q. `effect_field: rnai_median_dep_score`, `n_field:
<lines>`, `significance_field: —` (class-driven).

#### crispr_rnai_concordance — verdict-bearing (corroboration)
Decisive: `fraction_agree` (0.746) + `fraction_dependent_in_both` (0.239), n=133/556 shared lines. No q.
`effect_field: fraction_agree`, `n_field: <shared lines>`.

#### Confidence/context types (paralog_buffering, partner_conditional_dependency, chemical_genetic_concordance, cross_consortium_dependency, dependency_predictability, coessential_module, expression_dependency_correlation, abundance_dependency_correlation, patient_model_correspondence, genomic_event_model_match)
Lower-stakes for `key_evidence` (mostly class + one scalar). Spec = `{effect_field: <the one scalar>,
significance_field: —}`. Worth carrying: `prism-crispr-concordance.best_spearman_r_crispr/rnai`
(chemical confirmation), `cross-consortium.broad_frac_dependent`/`sanger_frac_dependent` (agreement),
`dependency-predictability.pearson_r_squared_rf` + `delta_r2` (biomarker anchoring). `paralog-buffering`
carries a `strong` class + a `conflict`/top-tension already surfaced in the verdict; its buffering delta
is `uncomputed` in the projected fields → flag as a candidate promotion (the top-tension text cites NRAS
but no number reaches `key_evidence`).

### 3.2 on-target-safety-liability (ANCHOR — liability case)

#### measurement_type: gnomad_lof_constraint   (skill: on-target-safety-liability · example card: gnomad-lof-constraint · run: EGFR·LUAD + PLK1·LAML · verdict-bearing: Y)

| # | data point | raw field | in graph today? | decisiveness | bucket | action |
|---|-----------|-----------|-----------------|:------------:|--------|--------|
| 1 | LoF constraint (LOEUF) | `loeuf_score` = 0.505 (EGFR) / highly_constrained (PLK1) | **no** | ★★★ | dropped (uncaptured) | declare `loeuf_score` — the single most decisive constraint number |
| 2 | pLI | `pli_score` = 0.389 | no | ★★★ | dropped | carry as significance/extra |
| 3 | missense z | `mis_z_score` = 2.92 | no | ★★ | dropped | carry as extra |
| 4 | constraint class | `constraint_class` = moderately_constrained | yes (class) | ★★★ | captured | keep |
| 5 | synonymous z (null ctrl) | `syn_z_score` = −0.45 | yes (n_basis) | ★ | captured | DEMOTE — this is a negative control, must not read as the anchor |

```
SALIENT-FIELDS SPEC:
  strata_array: —   effect_field: loeuf_score   significance_field: pli_score   omnibus_field: —
  n_field: —        direction: lower_is_stronger (LOEUF↓ = more constrained)
  extra_scalars: [mis_z_score]   categorical: [constraint_class]
```
> Adversarial note: today the ONLY number in the capsule is `syn_z_score` (the null control). The verdict
> `highly_constrained` is emitted with **no decisive number attached**. This is the clearest "generic
> liability call" in the framework.

#### measurement_type: normal_tissue_rna_breadth   (skill: on-target-safety-liability · example card: normal-tissue-liability-gtex · run: EGFR·LUAD · verdict-bearing: Y — DRIVING)

| # | data point | raw field | in graph today? | decisiveness | bucket | action |
|---|-----------|-----------|-----------------|:------------:|--------|--------|
| 1 | highest normal tissue (label) | `highest_tissue` = SKIN | no | ★★★ | unranked | carry as `categorical` — "expressed WHERE" is the call |
| 2 | its level | `highest_tissue_median` = 5.83 log2TPM | yes (numeric_anchors) | ★★★ | captured | keep, pair with #1 |
| 3 | critical-organ (label) | `critical_organ_argmax` = NERVE | no | ★★★ | unranked | carry as `categorical` |
| 4 | critical-organ level | `critical_organ_max` = 5.12 | no | ★★★ | dropped | promote |
| 5 | breadth | `tissue_breadth_fraction` = 0.94 (29/31 tissues) | yes | ★★★ | captured | keep |

```
SALIENT-FIELDS SPEC:
  strata_array: —   effect_field: highest_tissue_median   significance_field: —   omnibus_field: —
  n_field: n_tissues_detectable   direction: higher_is_worse (safety)
  categorical: [highest_tissue, critical_organ_argmax, liability_class]
  extra_scalars: [critical_organ_max, tissue_breadth_fraction]
```

#### Other on-target-safety types (the ★★★-count pattern, F3)
- **clinvar_germline_pathogenicity_safety** — `n_pathogenic_germline` = 118 (confident 109). ★★★ count in
  `n_basis` → dropped. `n_field: n_pathogenic_germline`, `categorical: [class]`.
- **mouse_ko_phenotype_safety** — `lethal_ko`; `n_lethal` = 13, `n_developmental_lethal` = 11. class in
  categorical (captured), counts dropped. `n_field: n_lethal`.
- **alteration_role** — `intogen_min_qvalue` = 3.29e-53, `intogen_max_pct_samples` = 0.457. ★★★
  driver-significance, in `n_basis` → dropped. `significance_field: intogen_min_qvalue`.
- **dosage_sensitivity_safety** (clingen) — `autosomal_dominant_loss`; `n_autosomal_dominant`=1,
  `n_high_confidence`=1. class captured; count dropped.
- **normal_tissue_protein_breadth** (HPA) — `hpa_tissue_specificity` = "Low tissue specificity",
  `essential_tissue_flag` = present, `specific_tissues[]` strata. Decisive STRINGS → `categorical`.
- **copy_number_alteration** — see genomic §3.x (same card family): `cn_p*_panel` scalars win the anchor
  slot; the deleted/amplified lineage strata + fractions are the decisive facts.
- display-only context: `drug_warning_safety`, `onsides_adverse_event_safety` (`n_boxed_warning_terms`),
  `shet_lof_selection`, `human_genetic_safety`, `target_safety_prioritisation`, `functional_gene_state`.

### 3.3 genomic-alteration-profile (KRAS·COADREAD + MET·LUAD)

> Whole skill is **unranked**: this run predates the capsule seam (#1051), but the pattern is structural —
> the decisive per-class significance scalars (`*_mannwhitney_p/q`, `intogen_min_qvalue`) and mutant-vs-WT
> effects never match `_ANCHOR_HINTS`, and the alteration MIX lives in class STRINGS the numeric selectors
> drop. The verdict is multi-class (which alteration class DRIVES), so `key_evidence` must carry the
> per-class effect+q tuple, not one scalar.

#### measurement_type: mutation-stratified-dependency (DRIVING) · verdict-bearing
| # | data point | raw field | in graph? | ★ | bucket | action |
|---|---|---|---|:--:|---|---|
| 1 | mutant−WT dependency delta | `delta_chronos_hotspot_mut_vs_wt` = −1.14 (KRAS) / +0.013 (MET) | no | ★★★ | unranked | `effect_field` |
| 2 | its significance | `hotspot_mannwhitney_q` = 1.2e-10 (KRAS) / 0.586 (MET) | no | ★★★ | unranked | `significance_field` |
| 3 | stratification class | `mutation_stratification_class` = mutant_strongly_dependent (KRAS) | no | ★★★ | unranked | categorical |
| 4 | evidence scope caveat | `evidence_scope` = within_indication / pan_lineage_evidence_only | no | ★★ | unranked | categorical (F5-like caveat) |
| 5 | mutant PPV / n_mutant | `ppv`=1.0 · `n_mutant`=43 | no | ★★ | unranked | n_basis |
```
strata_array: —  effect_field: delta_chronos_hotspot_mut_vs_wt  significance_field: hotspot_mannwhitney_q
omnibus_field: —  n_field: n_mutant  direction: lower_is_stronger
categorical: [mutation_stratification_class, evidence_scope]  extra_scalars: [ppv]
```

#### measurement_type: alteration-role · verdict-bearing
`alteration_role` = direct_driver_gof (KRAS) / predictive_biomarker (MET); `intogen_min_qvalue` = 2.25e-51
(KRAS) / 5.72e-6 (MET); `intogen_max_pct_samples` = 0.447. All ★★★, all unranked/n_basis.
`significance_field: intogen_min_qvalue · categorical: [alteration_role] · extra: [intogen_max_pct_samples]`.

#### measurement_type: copy-number-distribution + copy-number-stratified-dependency + amp-expr-stratified-dependency
The CN mix: `cn_p*_panel` scalars win the anchor slot; the **decisive** facts are the
deleted/amplified lineage strata (`cn_top_amplified_lineages`), `patient_amplified_fraction` (MET 42% vs
KRAS 23%), and the stratified-dependency significance (`cn_stratification_mannwhitney_p` = 8.7e-12 KRAS /
0.586 MET; `amp_expr_mannwhitney_p` = 4.0e-11 KRAS / 0.604 MET). MET·LUAD is the teaching case: CN
amplification present in 42% but confers NO dependency (delta +0.013, q=0.586) — the graph must carry the
null q to let the narrator say "amplified but not amp-driven."
`strata_array: cn_top_amplified_lineages · effect_field: median_cn · significance_field: <cn/amp>_mannwhitney_p · n_field: <n> · direction: higher_is_stronger`.

#### measurement_type: mutation-hotspot-frequency · mutation-drug-response · fusion-rearrangement-landscape · splice-exon-skip-landscape
- **hotspot-frequency**: `pooled_driver_recurrence_percentile`=99.97 (KRAS), `overall_mutation_frequency`=0.42,
  `hotspot_frequencies[0]`={p.G12D, freq 0.109, n=61}, `genie_mutation_frequency`=0.435 (cross-registry).
  `strata_array: hotspot_frequencies · effect_field: frequency · n_field: n_covered_pooled`.
- **drug-response**: `drug_response_mannwhitney_q`=4.97e-28 (KRAS)/0.72 (MET), `ppv`=0.948, `delta_log2auc`=−0.46,
  `on_target_compounds[0]`={BAY-293}. `significance_field: drug_response_mannwhitney_q`.
- **fusion**: `fusion_class`=recurrent_fusion_driver (MET); `fusion_frequency`=0.0048; `n_samples_with_fusion`=3.
- **splice**: `splice_exon_skip_class`=recurrent_splice_driver, `event_id`=METex14, `driver_direction`=activating,
  `oncogenic_indications`=[LUAD,LUSC,NSCLC] — the MET·LUAD verdict rests entirely on these STRINGS.

#### Thin/context (one-liners)
mutation-type-counts (`mutation_landscape_class`=missense_dominant + `mut_fraction_lof` 0.016/0.279) ·
functional-gene-state (**uncomputed**: `patient.state_counts` is a NESTED dict — no flat
`patient_biallelic_fraction`; needs a summary reshape) · variant-level-interpretation (`resistance_variants`
strata — G12D→Cetuximab/Panitumumab, 23 profiles: a liability strata array, unranked) · target-clonality
(`clonal_fraction` 0.916) · cross-consortium · genomic-instability-state · mutational-signature-context
(`dominant_process`=mmr_deficiency/tobacco) · ddr-deficiency · oncogenic-pathway-alteration · dependency-predictability
(`pearson_r_squared_rf`=0.468, `pred_dominant_feature_class`=own_mut_hotspot) · genomic-event-model-match.

**OMISSIONS (top):** (1) mutation-stratified-dependency effect+q+class+scope tuple entirely unranked; (2)
`intogen_min_qvalue` (strongest stat in the skill) dropped; (3) functional-gene-state nested-dict is an
uncomputed reshape gap; (4) MET null CN/amp q-values dropped (can't say "amplified-not-driven"); (5)
`resistance_variants` liability strata unranked; (6) `evidence_scope` caveat dropped fleet-wide.

**EXEMPLARS:**
- △ **Hotspot-mutant dependency (KRAS·COADREAD)** — mutant lines are strongly dependent (Chronos −1.73 vs WT
  −0.59; Δ−1.14; q=1.2e-10; PPV=1.0), confirmed within-indication; drug sensitivity concurs (PPV 0.95,
  q=5e-28; BAY-293). Liability: 23 CIViC resistance profiles incl. G12D→Cetuximab. [mutation-stratified-dependency, mutation-drug-response, variant-level-interpretation]
- ◆ **Splice-driven, not CN-driven (MET·LUAD)** — METex14 recurrent activating splice driver
  (alteration_role=predictive_biomarker, IntoGen q=5.7e-6); CN-amplified in 42% of tumors but amplification
  confers no dependency (Δ+0.01, q=0.59) — the call is splice-event-gated. [splice-exon-skip-landscape, copy-number-stratified-dependency]

### 3.4 tumor-presence (EPCAM·COADREAD + FAP·COADREAD — compartment-confound)

The decisive fact for presence is *compartment* (malignant vs stromal/CAF), which lives entirely in
STRING classes + `sibling_caveats` the graph drops (F4). FAP is the teaching case: strong bulk-RNA +
protein elevation that is stromal-driven.

#### measurement_type: sc_tumor_celltype_expression (DRIVING for compartment call) · verdict-bearing
| # | data point | raw field | in graph? | ★ | bucket | action |
|---|---|---|---|:--:|---|---|
| 1 | malignant detection fraction | `malignant_detection_fraction` = 0.895 (EPCAM) / 0.008 (FAP) | yes (na) | ★★★ | captured | keep |
| 2 | CAF detection fraction | `caf_detection_fraction` = 0.077 (EPCAM) / 0.289 (FAP) | yes (na) | ★★★ | captured | keep |
| 3 | compartment verdict | `sc_expression_class` = malignant_broadly_detected / microenvironment_dominant | no | ★★★ | unranked | promote categorical |
| 4 | stromal confound | `stromal_confound_class` = caf_low / stromal_confounded | no | ★★★ | dropped (sibling_caveat) | promote |
| 5 | TCE antigen-escape | `tce_antigen_escape_class` = escape_risk_low / high | no | ★★ | dropped | promote |
| 6 | donor n / broadly-detecting frac | `fraction_donors_broadly_detecting` 0.953 / 0.011; n_donors 280 | partial | ★★ | dropped | n_basis |
```
strata_array: —  effect_field: malignant_detection_fraction  significance_field: —
n_field: n_donors  direction: higher_is_stronger
categorical: [sc_expression_class, stromal_confound_class, caf_vs_malignant_class, tce_antigen_escape_class]
```

#### Other tumor-presence types (specs)
- **tumor_vs_adjacent_expression** (VB): `log2_fc`+`gtex_log2_fc`+`gtex_q_value` captured; **`q_value`
  (adjacent) unranked** (FAP 5.07e-40, EPCAM 1.23e-6) + `expression_call_class` dropped.
  `effect: log2_fc · significance: q_value · categorical: [expression_call_class]`.
- **tumor_protein_abundance** (VB for FAP): `protein_bh_q_value`+`protein_effect_size` captured;
  `protein_expression_class` (FAP modest_up) dropped; n_tumor/n_normal in n_basis.
- **tumor_expression_distribution** (VB): fraction-above-normal-p95 captured; `normal_p95_log2tpm` (the
  comparator ceiling) + `fraction_tumor_above_normal_p99` unranked/n_basis (floor-quorum incomplete).
- **expression_purity_confound**: r captured; **p + `purity_confound_class`** dropped (FAP r=−0.47,
  p=4.3e-30, microenvironment_confounded — the confound VERDICT is invisible).
- **tumor_protein_ihc_presence** (HPA): fraction_detected captured; class `ihc_detected_high` + n_patients unranked.
- **tumor_rna_distribution_by_subtype** (`tier=subtype`): see §3.16 — FAP CMS axis omnibus p=4.6e-58, CMS4 highest.

**OMISSIONS (top):** compartment verdict (`stromal_confound_class`/`sc_expression_class`) is the #1 dropped
★★★ fact — a narrator on numeric_anchors alone cannot tell a stromal target from a malignant one; adjacent
q-values; purity-confound p + class; per-cohort q in `most_elevated_cohorts`; the CMS subtype signal (§3.16).

**EXEMPLARS:**
- △ **Malignant-intrinsic (EPCAM·COADREAD)** — single-cell: detected in 89.5% of malignant cells across 280
  donors (broadly-detecting in 95%), CAF fraction 7.7% → malignant_intrinsic, antigen-escape low. [tumor-scrna-celltype-expression]
- ▽ **Stromal over-call (FAP·COADREAD)** — bulk RNA up (log2FC 2.93, q=5.1e-40) and protein broadly elevated
  (8/10 CPTAC cohorts) but single-cell shows FAP is CAF-dominant (malignant 0.8%, CAF 28.9%;
  purity r=−0.47, p=4.3e-30) → microenvironment_dominant, NOT malignant-intrinsic; TCE antigen-escape high. [tumor-scrna-celltype-expression, expression-purity-confound]

### 3.5 tumor-selectivity (EPCAM·COADREAD)

The verdict is a multi-comparator selectivity call; the decisive facts are the per-comparator q-values +
the `selectivity_class` label + the modality-viability verdicts — all dropped today.

#### measurement_type: tumor_vs_normal_selectivity (DRIVING) · verdict-bearing
| # | data point | raw field | in graph? | ★ | bucket | action |
|---|---|---|---|:--:|---|---|
| 1 | log2FC per comparator | `log2fc_cell_a/b/c` = −0.33 / +1.68 / +2.09 | yes (na) | ★★★ | captured | keep |
| 2 | q per comparator | `q_value_cell_a/b/c` = 2.5e-4 / 1.2e-3 / 1.6e-72 | no | ★★★ | unranked | pin as `significance` per comparator |
| 3 | selectivity verdict | `selectivity_class` = discordant_across_comparators | no | ★★★ | dropped | promote categorical |
| 4 | concordance flag | `comparator_concordance` = discordant; `sig_all_cells`=False | no | ★★★ | dropped/n_basis | promote |
| 5 | per-comparator percentile | `selectivity_allgene_percentile` = 25.8 (a, TCGA-adj) vs 87.8/88.4 | no | ★★★ | unranked | promote — quantifies the discordance |
```
strata_array: —  effect_field: log2fc_cell_a/b/c  significance_field: q_value_cell_a/b/c
n_field: —  direction: higher_is_stronger
categorical: [selectivity_class, comparator_concordance]
extra_scalars: [selectivity_allgene_percentile(_cell_b/_cell_c), sig_all_cells]
```
> Adversarial: TCGA-adjacent (cell_a) is the most conservative comparator and INVERTS the signal (tumor
> lower, 25.8th pctile); the narrator must cite it, not the favorable GTEx +2.09.

#### Other tumor-selectivity types (specs)
- **surface_density** (VB): copies/cell captured; **`is_tce_viable`=False, `density_floor_verdict`=below_tce_floor,
  `is_adc_high_payload_viable`=False, `surface_density_class`=very_low** all dropped (the actionable
  modality verdicts). `categorical: [surface_density_class, density_floor_verdict, is_tce_viable, is_adc_high_payload_viable]`.
- **modality_window**: `numeric_anchors=None`; **`window_class`=essential_tissue_liability +
  `max_essential_normal_tpm`=168.71** dropped (the whole window verdict invisible).
- **sc_normal_celltype_expression** (VB): max_detection_fraction captured; `sc_normal_expression_class`=HIGH_LIABILITY
  unranked, `n_cell_types_above_20pct`=143 in n_basis; top cell type (early colonocyte/colon) unranked.
- **tumor_vs_normal_percentile_crossing** (VB): fractions captured; `normal_p95_log2tpm`=9.24 (the ceiling) unranked.
- display-only: normal_tissue_protein_abundance (tphp), spatial_colocalization (`spatial_coloc_class`=immune_excluded unranked),
  spatial_region_rna, tumor_vs_normal_protein_abundance.

**OMISSIONS (top):** per-comparator q-values + `selectivity_class` + per-comparator percentile (the discordance
quantification); modality viability verdicts (`is_tce_viable`/`density_floor_verdict`); `window_class` + GTEx TPM ceiling.

**EXEMPLARS:**
- ▽ **Discordant selectivity (EPCAM)** — selectivity flips by comparator: tumor is LOWER than TCGA-adjacent
  (log2FC −0.33, q=2.5e-4, 25.8th pctile) yet higher vs GTEx (+2.09, q=1.6e-72); `sig_all_cells`=False →
  discordant_across_comparators. The conservative adjacent comparator governs. [tumor-vs-normal-selectivity]
- ▽ **Below modality floor (EPCAM)** — despite high RNA/IHC, measured surface density is 35 copies/cell →
  below_tce_floor, is_tce_viable=False, is_adc_high_payload_viable=False; 143 normal cell types express
  above 20% and GTEx essential-tissue ceiling 168.7 TPM → essential_tissue_liability. [surface-abundance-density, modality-therapeutic-window]

### 3.6 surface-modality-fit (ERBB2·STAD + MSLN·PAAD)

The verdict is a per-modality fit class (ADC vs TCE) governed by KILLER caveats. Two severe gaps: (a) the
composed **adc-tce-modality-fit card's capsule is entirely empty** — the skill's primary verdict node
(`fit_class`, `endocytosis_confidence`, rationale) has ZERO graph representation; (b) the TCE killer labels
that flip `both_viable`→`adc_preferred_tce_unsafe` are all in dropped categorical/sibling shapes.

#### measurement_type: sc_normal_surface_protein / sc_normal_celltype_expression (drives the TCE-killer) · verdict-bearing
| # | data point | raw field | in graph? | ★ | bucket | action |
|---|---|---|---|:--:|---|---|
| 1 | max normal detection | `max_detection_fraction`=0.853 (airway submucosal gland) | yes (na) | ★★★ | captured | keep |
| 2 | normal-safety class (KILLER) | `sc_normal_safety_essential_class`=critical_organ_liability | no | ★★★ | dropped | promote — fires sc-normal-high-liability-bite-killer |
| 3 | n normal cell types >20% | 82 cell types | no | ★★★ | dropped (n_basis) | promote |
| 4 | top normal cell-type strata | `per_cell_type_top[]` {tissue, cell_type, fraction} (15 rows) | no | ★★ | unranked | pin strata |
```
strata_array: per_cell_type_top  effect_field: median_detection_fraction  n_field: n_cell_types_above_20pct
direction: higher_is_worse_safety  categorical: [sc_normal_safety_essential_class]
```

#### Other surface types (specs)
- **adc-tce-modality-fit** (the composed VERDICT card): `fit_class`=both_viable, `endocytosis_confidence`=clinically_internalizing,
  `bite_tce`=unsafe, `tce_antigen_escape_class`=escape_risk_high, `tce_homogeneity_class`=heterogeneous,
  `within_tumor_coverage_class`=low — **capsule EMPTY, all unranked**. This is the #1 fix: the verdict card must
  populate a capsule + `key_evidence` (fit_class + the killer labels).
- **surface_density**: copies/cell captured; `density_floor_verdict`=above_adc_high_payload_floor (ERBB2 ~30k copies/cell).
- **modality_window**: `window_ratio_essential`=0.57 + `window_max_essential_organ`=NERVE (headline-only);
  `max_essential_normal_tpm`=67.68 n_basis.
- **rna_protein_concordance**: **`rna_protein_r`=0.786 (n=114 tumors, MSLN)** — highest-quality proxy validation — dropped (n_basis).
- **pmhc_epitope_evidence**: `pmhc_epitope_evidence_class`=tcell_validated + n_epitopes(151)/n_hla(43) unranked/n_basis.
- **shed_ectodomain_liability**: `shed_liability_class`=clinically_shed + protease ADAM10 + `shed_product`=HER2-ECD dropped
  (graph shows shedding without naming what/by what).
- copy_number, structure_druggability, surfaceome-cohort-ranking, pmhc_presentation: display context.

**OMISSIONS (top):** adc-tce-modality-fit verdict card capsule empty (fit_class + killer labels absent → the
whole modality call is ungrounded); TCE-killer labels (`tce_antigen_escape_class`/`homogeneity`/`coverage`)
dropped; `sc_normal_safety_essential_class`=critical_organ_liability dropped; `window_max_essential_organ`=NERVE
+ ratio dropped; MSLN `rna_protein_r`=0.786 dropped; shed product/protease identity dropped.

**EXEMPLARS:**
- △▽ **ADC-viable, TCE-unsafe (ERBB2·STAD)** — surface density is high (~30k copies/cell, above ADC high-payload
  floor) and topology is `both_viable`, BUT ERBB2 is detected in 82 normal cell types (max 85% in airway
  submucosal gland; NERVE window ratio 0.57) → sc-normal-high-liability killer fires → adc_preferred_tce_unsafe.
  The killer labels are all dropped today. [adc-tce-modality-fit, sc-surface-normal-safety, modality-therapeutic-window]
- △ **RNA is a good surface proxy (MSLN·PAAD)** — tumor RNA↔protein r=0.79 (n=114 paired, CI 0.77–0.88) supports
  using RNA as a MSLN surface-abundance proxy — the single most reassuring number, currently dropped. [rna-protein-concordance-tumor]

### 3.7 tractability-small-molecule (KRAS·COADREAD)

Strong positive case. Verdict is chemical-genetic concordance; the decisive additions are the COMPOUND NAMES
(RMC-7977, ELIRONRASIB) + the indication (Bowel) activity row + the class labels — all unranked/dropped.

#### measurement_type: chemical_genetic_concordance (DRIVING) · verdict-bearing
| # | data point | raw field | in graph? | ★ | bucket | action |
|---|---|---|---|:--:|---|---|
| 1 | concordance class | `crispr_prism_concordance_class`=triangulated_target_engaged | no | ★★★ | unranked | categorical |
| 2 | best Spearman r CRISPR/RNAi | `best_spearman_r_crispr`=0.372 / `_rnai`=0.438 | yes (na) | ★★★ | captured | keep |
| 3 | per-compound concordance | `per_compound_concordance[]` {drug_name, spearman_r} (21) — which compound triangulates | no | ★★★ | unranked | pin strata w/ drug_name |
```
strata_array: per_compound_concordance  effect_field: spearman_r_crispr  n_field: n_compounds_evaluated  categorical: [crispr_prism_concordance_class]
```

#### Other tractability types (specs)
- **prism_compound_activity**: `median_log2auc` captured; **top_compounds drug NAMES (RMC-7977 median_log2auc
  −0.54; ELIRONRASIB best_responder_lfc −13.6) + MoA strings + the Bowel lineage row (median_log2auc −0.154,
  n=42, top RMC-7977)** all unranked; `prism_activity_class`=clinical_precedent_only unranked.
- **measured_potency_tractability**: `chembl_best_pchembl`=10.7 captured; `best_measured_potency_neglog_m`=12.7
  (BindingDB) + `measured_bioactivity_class`=potent_measured_ligand + `chembl_clinical_phase_class`=approved dropped.
- **known_drug_tractability**: `known_drug_tractability_class`=approved_drug_tractable + `druggability_tier`=clinically_actionable
  + n_approved_drug_interactions(95) unranked/n_basis.
- **structure_druggability**: `structural_ligandability_class`=experimental_ligandable + `mutation_hotspot_in_druggable_pocket`=True
  + `hotspot_pocket_adjacency_call`=adjacent — the decisive structural facts — all dropped.
- **degradation_feasibility**: `degradability_feasibility_class`=ubiquitination_substrate + `degrader_precedent`=False dropped.
- **dependency_predictability**: r captured; class + dominant feature + indication per-lineage r² dropped (as elsewhere).

**OMISSIONS (top):** compound NAMES (RMC-7977/ELIRONRASIB) + MoA + the Bowel indication activity row unranked
(a narrator can't name the tool compound); all structure class labels dropped; BindingDB best affinity + approved-phase
dropped; concordance class + per-compound drug names unranked.

**EXEMPLARS:**
- △ **Chemically tractable + triangulated (KRAS·COADREAD)** — best measured pChEMBL 10.7 (BindingDB affinity
  neglog_M 12.7; approved phase 4; 95 approved-drug interactions); structurally experimental_ligandable with the
  mutation hotspot in a druggable pocket (PDB 0.95 Å); CRISPR↔PRISM triangulated_target_engaged (best r 0.37/0.44). [measured-potency-tractability, structure-features-static, prism-crispr-concordance]
- ◆ **PRISM signal is clinical-precedent, not clean viability (KRAS·COADREAD)** — 23 compounds; top RMC-7977
  (tri-complex RAS inhibitor, median_log2AUC −0.54; Bowel lineage −0.15, n=42); prism_lineage_selectivity=no_lineage_signal
  → the graph must name the compound + the Bowel row, both currently dropped. [prism-compound-activity]

### 3.8 mechanism-and-pharmacology (KRAS·PAAD)

The payload here is ranked NODE LISTS + MoA STRING classes (F4, F6). The network's interpretive content
(what kind of target, which modalities) is entirely in strings/lists no capsule shape carries.

#### measurement_type: signaling_network_mechanism (DRIVING) · verdict-bearing
| # | data point | raw field | in graph? | ★ | bucket | action |
|---|---|---|---|:--:|---|---|
| 1 | network class | `network_class` = well_characterized | no | ★★★ | unranked | categorical |
| 2 | actionable-MoA classes | `moa_classes_present` = [molecular_glue_disruptor, upstream_gap_modulation, upstream_gef_modulation, …9] | no | ★★★ | unranked | declare categorical LIST anchor |
| 3 | actionable flag | `has_actionable_moa` = True | no | ★★★ | unranked | categorical |
| 4 | node counts | `n_upstream_regulators`=71, `n_downstream_effectors`=12 | no | ★★ | dropped (n_basis) | n_basis |
| 5 | per-node rows | `upstream_regulators[].{partner_gene_symbol, moa_class, direct_flag}` (71+12) | no | ★★★ | unranked | strata w/ STRING effect (no numeric) — needs list-role salience |
```
strata_array: upstream_regulators/downstream_effectors  effect_field: moa_class(string)  significance_field: —
n_field: n_upstream_regulators  categorical: [network_class, has_actionable_moa, moa_classes_present]
```

#### Other mechanism types (specs)
- **phospho_pathway_activity** (VB): `phospho_activity_class`=phospho_not_detected (verdict fact, unranked);
  `n_phosphosites`=0, `n_tumors`=250. `categorical: [phospho_activity_class]`.
- **pathway_activity_context**: `per_pathway` (TGFb activity_z=2.26, EGFR 1.96), `pathway_activity_class`=relatively_high.
  `strata_array: per_pathway · effect_field: activity_z`.
- **dependency_predictability** (VB): R² captured; `predictability_class`=own_omics_driven +
  `pred_dominant_feature_class`=own_mut_hotspot dropped; **indication (Pancreas) per-lineage r² unextracted**
  (top_k picks only global strongest Biliary 0.256 / weakest Soft Tissue 0.0001).
- **tahoe_drug_perturbation**: `tahoe_perturbation_class`=weakly_perturbed, `n_strong_movers`=0.

**OMISSIONS (top):** MoA payload (`network_class`+`moa_classes_present`+`has_actionable_moa`) fully absent →
graph says nothing about mechanism; `phospho_activity_class` verdict unrepresented; per-node partner lists
(with moa_class) unranked; predictability indication-row unextracted.

**EXEMPLARS:**
- △ **Well-characterized actionable hub (KRAS·PAAD)** — 71 upstream regulators / 12 downstream effectors
  (network_class=well_characterized, 0% MoA-unmapped); actionable classes incl. upstream_gap_modulation
  (e.g. DAB2IP), upstream_gef_modulation, molecular_glue_disruptor. [signaling-network-mechanism]
- ◆ **No direct phospho-PD readout** — CPTAC PAAD (250 tumors) detects 0 phosphosites on KRAS while its
  total protein IS detected (phospho_not_detected — a measured no-detection, not a claim that KRAS is
  unphosphorylatable; it does carry sites in other CPTAC cohorts) → no phospho-PD marker is available for
  this target *in this cohort's panel*. [phospho-pathway-activity]

### 3.9 combination-and-vulnerability (KRAS·COADREAD + BRCA2·BRCA)

Gateless (verdict=None): the DESCRIPTIVE ranked partner/co-target/mediator tables ARE the output (F6). Every
one is in the headline but invisible to the capsule; graph emits no partner names, effects, or classes.

#### measurement_type: combinatorial_ko_dependency (representative) · verdict-driving
| # | data point | raw field | in graph? | ★ | bucket | action |
|---|---|---|---|:--:|---|---|
| 1 | class | `combinatorial_dependency_class` = strong_synthetic_lethal | no | ★★★ | unranked | categorical |
| 2 | strongest partner + GI + p | `ranked_partner_table[0]` = {NRAS, mean_gi −0.486, gi_ttest_pvalue 1e-50, frac_strong 0.47, interaction_class constitutive_buffering} | no | ★★★ | unranked | pin as `top_strata` w/ effect+q+class |
| 3 | 2nd partner | HRAS mean_gi −0.471, p=9.3e-56 | no | ★★★ | unranked | same |
| 4 | indication row | `ranked_partner_table[].min_gi_lineage` = Bowel (RRAS2/REM2/RRAD) | no | ★★★ | unranked | resolve indication-strongest |
```
strata_array: ranked_partner_table  effect_field: mean_gi  significance_field: gi_ttest_pvalue
n_field: n_interacting_partners  direction: lower_is_stronger  categorical: [combinatorial_dependency_class, interaction_class(per-row)]
```

#### Other combination types (specs)
- **synthetic_lethal_partner** (VB): `top_partners[]` rows carry **NO effect/significance field** (only
  partner, cell_line, evidence_tier, pubmed_id) — **uncomputed** per-partner effect/precedent; canonical
  PARP1/PARP2 (BRCA2) live only in a flat 222-item `sl_partner_symbols` list, unranked. `sl_partner_class`=has_experimental_sl_partner;
  n_experimental_partners=65(BRCA2)/1647(KRAS). → flag upstream: add per-partner effect + validated_precedent flag.
- **drug_anchored_combination** (VB): `top_co_targets[0]`={PTPN11, mean_effect_shift −0.70, frac_significant 0.83,
  anchor_drug MRTX1133, combination_class robust_combination}. `effect: mean_effect_shift · significance: frac_models_significant`.
- **drug_anchored_resistance** (VB): `top_resistance_mediators[0]`={NF1, mean_effect_shift +0.84, frac 0.83, robust_resistance_mediator} —
  a LIABILITY (positive shift = rescue). `direction: higher_is_stronger`.
- **chemical_combination_synergy** (VB): `synergy_opportunity_class`=no_synergy_screen, n=0 (the whole axis verdict).

**OMISSIONS (top):** the ranked partner/co-target/mediator tables (with per-row effect+q+class+anchor-drug)
are the entire skill and carry ZERO graph representation; SL `top_partners` lacks a per-partner effect/precedent
field (uncomputed) so canonical PARP–BRCA2 can't be surfaced; all 5 `*_class` labels unranked.

**EXEMPLARS:**
- △ **Constitutive RAS-paralog co-dependency (KRAS·COADREAD)** — dual-KO with NRAS (GI −0.49, p=1e-50, 47%
  of lines) and HRAS (−0.47, p=9e-56); interaction_class=constitutive_buffering. [combinatorial-dependency]
- △▽ **MRTX1133 combination + resistance (KRAS·COADREAD)** — top co-target PTPN11 (effect shift −0.70, 83% of
  models, robust_combination) and GRB2; but NF1 loss RESCUES under MRTX1133 (shift +0.84, robust_resistance_mediator)
  — a resistance liability. [combo-crispr-screen, resistance-emergence-signature]
- ◆ **Canonical SL under-surfaced (BRCA2·BRCA)** — 65 experimental SL partners; PARP1/PARP2 present in the
  curated symbol list but absent from the top-20 (no per-row effect to rank by; no validated_precedent flag). [synthetic-lethal-partners]

### 3.10 immune-context (SKCM·PMEL + PAAD·MSLN)

Gateless. The decisive target-dependent fact is the antigen-CONDITIONED CD8 split (is the target-high tumor
hotter or colder?) — a STRING call + a signed delta the graph drops. MSLN·PAAD is the liability case.

#### measurement_type: immune_context (DRIVING) · verdict-bearing
| # | data point | raw field | in graph? | ★ | bucket | action |
|---|---|---|---|:--:|---|---|
| 1 | CD8 frac antigen-high / -low | `cd8_fraction_antigen_high/low` = 0.069/0.109 (PAAD) | yes (na) | ★★★ | captured | keep |
| 2 | antigen-conditioned call | `antigen_conditioned_call` = antigen_high_is_colder (PAAD) / antigen_high_immune_hot (SKCM) | no | ★★★ | dropped | promote — THE target-relevant fact |
| 3 | antigen-high immune class | `antigen_high_immune_context_class` = immune_cold (PAAD) | no | ★★★ | dropped | promote — the TCE liability call |
| 4 | signed delta | `cd8_high_minus_low` = −0.040 (PAAD) / +0.026 (SKCM) | no | ★★★ | unranked | pin as `effect` (sign = hotter/colder) |
| 5 | context class + n | `immune_context_class` immune_intermediate; `n_patients_joined`=178 | no | ★★ | dropped | promote |
```
strata_array: —  effect_field: cd8_high_minus_low  significance_field: —  n_field: n_patients_joined  direction: higher_is_stronger
categorical: [immune_context_class, antigen_conditioned_call, antigen_high_immune_context_class]
```

#### Other immune types (specs)
- **ici_response_expression**: `ici_response_class`=higher_in_nonresponders (decisive negative for PMEL) unranked;
  `median_log2fc_resp_vs_nonresp`=−0.19 captured but alone looks like noise; `rollup_stouffer_p`=0.67 dropped.
- **sc_tumor_myeloid_state_expression / sc_tumor_caf_state_expression**: max_detection captured; **off-indication
  caveat** dropped — `max_detection_cancer_type`=LYM (myeloid) / ICC (CAF), i.e. the peak is NOT in the run's
  indication; `max_detection_myeloid_subtype`/`_caf_subtype` + `expressing_*_subtypes` unranked.
- **spatial_til_fraction**: median TIL % captured; `til_fraction_class` (til_high) unranked.

**OMISSIONS (top):** `antigen_conditioned_call`+`antigen_high_immune_context_class`+`cd8_high_minus_low` (the
reversal that makes MSLN·PAAD a liability) all dropped; `ici_response_class`=higher_in_nonresponders dropped
(only the null log2FC survives); myeloid/CAF off-indication `max_detection_cancer_type` caveat unranked.

**EXEMPLARS:**
- ▽ **Antigen-high is colder (MSLN·PAAD)** — MSLN-high tumors are immunologically COLDER: CD8 fraction
  antigen-high 0.069 vs antigen-low 0.109 (Δ−0.040), antigen_high_immune_context_class=immune_cold (n=178)
  — a direct TCE/CAR-T context liability the graph currently cannot narrate. [immune-context]
- ◆▽ **Hot background but non-responder-marking (PMEL·SKCM)** — CD8 antigen-high 0.173 (immune_hot, n=103), yet
  PMEL is higher in ICI non-responders (log2FC −0.19, Stouffer p=0.67, 2 cohorts) — expression may mark a
  non-responding subpopulation. [immune-context, ici-response-association]

### 3.11 differentiation-landscape (KRAS·COADREAD)

The driving signal is the ranked co-mutation / mutual-exclusivity partner table (partner + odds ratio + q) —
`numeric_anchors=None, top_k_strata=None`, so it is entirely dropped. Survival legs lose their logrank p.

#### measurement_type: mutation_cooccurrence (DRIVING) · verdict-bearing
| # | data point | raw field | in graph? | ★ | bucket | action |
|---|---|---|---|:--:|---|---|
| 1 | top co-occurring partner + OR + q | `top_cooccurring[0]` = {partner, `log2_odds_ratio`, `bh_q_value`} (10 rows) | no | ★★★ | unranked | pin strata w/ partner label + effect + q |
| 2 | top mutually-exclusive partner | `top_mutually_exclusive[0]` = {partner, log2_odds_ratio, bh_q_value} (10 rows) | no | ★★★ | unranked | pin strata |
| 3 | significant-pair counts | `n_significant_cooccurring`=709, `n_significant_mutually_exclusive`=59 | no | ★★ | dropped (n_basis) | n_basis |
| 4 | panel-intersect eligibility | `n_pairs_panel_intersect_eligible`=1084 (the pooled-Fisher guard) | no | ★★ | dropped | n_basis (caveat) |
```
strata_array: top_cooccurring (+ top_mutually_exclusive)  effect_field: log2_odds_ratio  significance_field: bh_q_value
n_field: n_significant_cooccurring  direction: higher_is_stronger (cooccur) / lower (exclusive)
categorical: [cooccurrence_class]   NOTE: rows need a partner-gene LABEL field pinned (not in default _STRATUM_LABELS)
```

#### Other differentiation types (specs)
- **expression_clinical_association** (VB): median OS high/low (669/609 days) captured; **`logrank_p`=0.016**
  (the significance) DROPPED; `expression_survival_class`=expression_high_better_survival unranked.
- **alteration_clinical_association** (VB): OS medians captured; `logrank_p`=0.876 dropped (null result).
- **subtype_survival_association** (VB): see §3.16 — sidedness stratifies survival (logrank p=0.024); `per_axis_association` dropped.
- display-only: clinical_precedent (`n_active_trials`=33, `n_agents_engaging_target`=12 — n_basis, dropped),
  competitor_landscape (`example_programs` strata, unlabeled), pathway_node_leverage (`strongest_buffering_paralog`=NRAS
  in sibling_caveats), precog_prognostic_association, stemness_context (`median_mrnasi`=0.51 captured).

**OMISSIONS (top):** the co-mutation/mutual-exclusivity partner tables (partner+OR+q) — the entire driving
signal — carry ZERO graph representation; every survival `logrank_p` dropped (medians survive, significance
lost); clinical-precedent trial counts dropped.

**EXEMPLARS:**
- △ **Both co-mutation patterns present (KRAS·COADREAD)** — 709 significant co-occurring and 59 mutually-exclusive
  partners across TCGA MC3 + GENIE (panel-intersect-eligible n=1084); the top co-occurring and exclusive
  partners (with log2 odds ratio + BH-q) are the patient-selection hypotheses — none currently reach the graph. [co-mutation-and-mutual-exclusivity]
- ◆ **Expression-survival signal, significance dropped** — high-expression tumors show better survival (median
  OS 669 vs 609 days, logrank p=0.016) — but the p-value (the only reason to believe it) is dropped from the
  graph. [expression-clinical-association]

### 3.12 cis-feature-coherence (ERBB2·BRCA)

Gateless coherence chain (locus→expr→protein→dependency). Correlation `r` values are captured; **every
`p`-value is unranked** (none match hints), and the `evidence_scope` downgrade + a class↔r contradiction are dropped.

#### measurement_type: amp_expr_stratified_dependency (DRIVING leg) · verdict-inert
| # | data point | raw field | in graph? | ★ | bucket | action |
|---|---|---|---|:--:|---|---|
| 1 | amp+OE stratum dependency | amp-expr stratum median Chronos −1.02 vs −0.24 comparator | partial | ★★★ | unranked | promote |
| 2 | its significance | mannwhitney p=8.7e-13 (effect size 0.82) | no | ★★★ | unranked | significance_field |
| 3 | scope downgrade | `evidence_scope`=pan_lineage_evidence_only + `lineage_evidence_scope_reason` (BRCA underpowered) | no | ★★★ | unranked | categorical caveat — why moderate not strong |
```
strata_array: — effect_field: <amp_expr median chronos delta>  significance_field: amp_expr_mannwhitney_p  categorical: [evidence_scope]
```

#### Other cis types (specs)
- **methylation_silencing_coupling**: `methyl_expr_pearson_r`=−0.531 captured; `p`=8.3e-61 + slope
  (−6.44 log2TPM/methyl) + hyper- vs unmethylated means (2.31 vs 4.48) unranked/n_basis.
- **patient_cis_coherence**: `cn_expr_spearman_r`=0.653 captured; **`p`=1.1e-130** (strongest stat in skill) in
  n_basis→dropped; Δlog2TPM amplified-vs-neutral 1.82 dropped; `evidence_scope`=patient_indication unranked.
- **cis_protein_dosage_coupling**: `cn_prot_pearson_r`=0.55 captured but **`cis_protein_dosage_class`=prot_dosage_uncoupled**
  (a class↔r contradiction) unranked; slope 0.13 dropped.
- **expression_dependency_correlation / abundance_dependency_correlation**: r captured; p (2.4e-49 / 2.6e-18) unranked.
- isoform-dominance/expression: dominant_isoform_fraction captured; low priority.

**OMISSIONS (top):** all correlation p-values unranked (graph shows r with no significance); `evidence_scope` +
`lineage_evidence_scope_reason` downgrade dropped (BRCA sample underpowered → moderate not strong); the
class↔r contradiction (`prot_dosage_uncoupled` at r=0.55); slope magnitudes.

**EXEMPLARS:**
- △ **Cis-dosage chain coheres (ERBB2·BRCA)** — CN→expr coupled (Pearson r=0.47, p=7e-53; amplified lines
  Δ+3.05 log2TPM) and amp+overexpressed lines selectively dependent (Chronos −1.02 vs −0.24, p=9e-13) — but
  scope=pan_lineage_evidence_only (BRCA within-lineage underpowered). [amp-expr-stratified-dependency]
- ◆ **Patient-confirmed, protein-uncoupled** — TCGA BRCA CN→expr Spearman r=0.65 (p=1e-130, n=1065); yet
  CN→protein is uncoupled (`prot_dosage_uncoupled`) despite r=0.55 — a coherence break the graph hides. [patient-cis-coherence, cis-feature-protein-coherence]

### 3.13 target-intrinsic (MYC)

Indication-independent dossier; verdict=None. Same **gnomAD LOEUF/pLI-uncaptured** gap as safety (§3.2), plus
the ranked paralog table and every categorical verdict (family, ligandability, KO class) dropped.

#### measurement_type: gnomad_lof_constraint · paralog_buffering (representative)
| # | data point | raw field | in graph? | ★ | bucket | action |
|---|---|---|---|:--:|---|---|
| 1 | pLI / LOEUF | `pli_score`=1.000, `loeuf_score`=0.156 | no | ★★★ | unranked | declare (essentiality crux) |
| 2 | obs/exp LoF | `obs_lof_count`=1 / `exp_lof_count`=30.5 | no | ★★ | unranked | n_basis |
| 3 | strongest paralog + buffering | `functional_paralogs[0]`={MYCL, dep_delta 1.768, ohnolog True}; MYCN 1.695 | no | ★★★ | unranked | pin strata (partner+delta+ohnolog) |
| 4 | buffering class | `paralog_buffering_class`=strong (sibling_caveat) | no | ★★ | dropped | promote |
```
gnomad: effect_field: loeuf_score  significance_field: pli_score  direction: lower_is_stronger  categorical: [constraint_class]
paralog: strata_array: functional_paralogs  effect_field: dep_delta_paired_vs_max_single  categorical: [strongest_paralog_symbol, paralog_buffering_class]
```

#### Other target-intrinsic types (specs)
- **measured_potency_tractability**: `chembl_best_pchembl`=9.7 captured; `chembl_clinical_phase_class`=approved +
  n_potent_ligands(123) dropped.
- **structure_druggability**: `disordered_fraction` captured; **`structural_ligandability_class`=predicted_ligandable,
  `has_druggable_pocket`, `alphafold_confidence_class`=low (pLDDT 60.4)** all in categorical_anchors → dropped
  (the ligandability caveat is invisible).
- **domain_modality_relevance**: card class `removal_favored` (the TF/degrader verdict) — **uncomputed** (no shape
  captures a bare card-level class); flag.
- **mouse_ko_phenotype_safety**: `ko_phenotype_class`=developmental_only + evidence_tier=inferred (categorical, dropped).
- **protein_domains_class / ppi_interactome / signaling_network_mechanism**: family (transcription_factor), hub
  counts (348 HC interactors), node counts — all n_basis/categorical, dropped.

**OMISSIONS (top):** LOEUF/pLI absent (same as §3.2); paralog partner table (MYCL/MYCN + ohnolog) unranked;
ALL categorical verdicts (ligandability, KO class, family, phase) stripped at graph; `domain_modality_relevance`
card-class uncomputed; `alphafold_confidence_class`=low caveat dropped.

**EXEMPLARS:**
- △ **Constrained, paralog-buffered (MYC)** — highly constrained (pLI 1.00, LOEUF 0.156; 1 obs vs 30.5 exp
  LoF); strongly buffered by MYCL (dep_delta 1.77, ohnolog) and MYCN (1.70) → single KO insufficient, combination
  required. [gnomad-lof-constraint, paralog-buffering]
- ◆ **Chemically annotated but structurally uncertain (MYC)** — best pChEMBL 9.7 (ChEMBL phase 4, 123 potent
  ligands) yet predicted_ligandable rests on a low-confidence AlphaFold model (pLDDT 60.4, disordered 0.41), no
  co-crystal. [measured-potency-tractability, structure-features-static]

### 3.14 translational-readiness (ERBB2·BRCA)

Descriptive; verdict=None. Model COUNTS + treatment NAMES are the payload — dropped (n_basis / unranked).

#### measurement_type: genotype_matched_model · model_availability (representative)
| # | data point | raw field | in graph? | ★ | bucket | action |
|---|---|---|---|:--:|---|---|
| 1 | model coverage | `n_patient_derived_models`=69 (HCMI) | no | ★★★ | dropped (n_basis) | promote |
| 2 | matched fraction | `n_models_with_alteration`=4 / 69; `n_models_with_recurrent_hotspot`=1 | no | ★★★ | dropped | promote — matched_sparse rests on 4/69 |
| 3 | variant identities | `hgvsp_examples`=p.A293T/p.E698del/p.R517Q/p.V777L | no | ★★ | unranked | categorical |
```
model_availability: n_field: n_patient_derived_models  categorical: [primary_site_breakdown]
genotype_matched: n_field: n_models_with_alteration/n_models_in_indication  categorical: [variant_classes_present, hgvsp_examples]
```

#### Other translational types (specs)
- **pdx_drug_response**: `responder_fraction`=0.097 + median BAR captured; **`most_active_treatment`=LJM716+trastuzumab**
  (the only treatment name) unranked; `min_best_avg_response`=−91.8 (deep responder) dropped.
- **crispr_lof_dependency** (organoid): frac_dependent + Breast-lineage frac (0.625) captured; per_lineage full
  table dropped (top_k=2 rows); `frac_strongly_dependent`=0.114 unranked.

**OMISSIONS (top):** n_patient_derived_models=69 (headline coverage) dropped; matched fraction 4/69 dropped
(verdict uninterpretable without it); `most_active_treatment` name unranked; organoid per-lineage table dropped.

**EXEMPLARS:**
- ◆ **Sparse genotype match (ERBB2·BRCA)** — 69 HCMI BRCA patient-derived models, but only 4/69 carry an ERBB2
  alteration (1 recurrent hotspot; p.V777L, p.A293T) → matched_sparse. [target-genotype-matched-model, target-model-availability]
- △ **Organoid + PDX signal** — Breast organoids 62.5% dependent (n=16, gene effect −0.82); PDXE 9.7% responders
  across 84 models, most active LJM716+trastuzumab (min BAR −91.8, deep responder present). [organoid-crispr-dependency, target-pdx-drug-response]

### 3.15 literature-context (KRAS·COADREAD)

Descriptive; verdict=None. The `top_cited` statements (pmid/year/cooccur/sentence) + the relation-direction
mix are the entire human-readable payload — and (despite a planned `cited_statements` shape) `top_k_strata=None`
in this run, so they are dropped.

#### measurement_type: cited_literature_evidence · verdict-inert
| # | data point | raw field | in graph? | ★ | bucket | action |
|---|---|---|---|:--:|---|---|
| 1 | relation volume + direction mix | `total_relation_publications`=5106 (associate 5093 / stimulate 10 / inhibit 3) | no | ★★★ | dropped/unranked | pin relation_direction strata |
| 2 | top cited statement | `top_cited[0]`={pmid 37937641, 2023, cooccur 755, sentence "…KRAS-mutant CRC depends on glutamine…"} | no | ★★★ | unranked | pin `cited_statements` |
| 3 | volume + recency | `paper_disease_mentions`=12691, `recent_mentions`=4919, years 1983–2026 | no | ★★★ | unranked | promote |
```
strata_array: top_cited (effect: cooccur; label: sentence/pmid/year) + relation_direction.relations (effect: n_publications; label: relation_type)
n_field: total_relation_publications  extra_scalars: [paper_disease_mentions, recent_mentions]
```

**OMISSIONS (top):** entire `top_cited` array (the only qualitative evidence) unranked; relation-direction mix
(5093 associate vs 3 inhibit — observational, not mechanistic) unranked; volume/recency counts not captured.

**EXEMPLARS:**
- ◆ **Observational, association-dominated (KRAS·COADREAD)** — 5106 relation publications but only 3 mechanistic
  "inhibit" vs 5093 "associate" (12,691 disease mentions, 1983–2026) → literature is descriptive, low mechanistic
  confidence. [cited-literature-evidence]
- ◆ **Top co-cited (cooccur 755, 2023)** — "KRAS-mutant colorectal cancer depends on glutamine for survival…"
  (pmid 37937641); recency incl. a 2025 JOSD2/KRAS feedback-circuit paper. [cited-literature-evidence]

### 3.16 Subtype / subgroup-stratified signals (cross-skill axis — per user request)

Subtyping is a distinct evidence axis orthogonal to the whole-cohort signal: *is the call restricted to a
molecular subtype, and which one?* The graph is subtype-STRUCTURE-aware but subtype-EVIDENCE-blind (F8). Three
grounded shapes exist, all dropped:

**(a) Subtype-stratified DEPENDENCY** — FR `subgroup-stratified-dependency` (`--subtypes`-gated; present in
KRAS·COADREAD-full). `per_subgroup_metrics`: MSS median Chronos −1.22 (n=71, strong_dependency, 42 strong) vs
MSI_H −0.69 (n=17, moderate_dependency, 6 strong); `cross_subgroup_delta_dependency`=0.0. Capsule
`numeric_anchors=None, top_k_strata=None` → **the MSS>MSI_H dependency split is entirely dropped.**

**(b) Subtype-stratified PRESENCE (multi-axis omnibus)** — tumor-presence `tumor-rna-distribution-by-subtype`
(`tier=subtype`, present by default). `subtype_omnibus_by_axis` = one row per molecular axis:

| axis | subtype_omnibus_p | var_explained | which_subtypes_separate | effect_class |
|---|---|---|---|---|
| MSI (driving) | 0.0002 | 0.050 | highest MSI_H / lowest MSS | negligible |
| CMS | ~0 | 0.039 | CMS3 / CMS2 | negligible |
| sidedness | 0.0034 | 0.026 | right / left | negligible |
| CIMP / stage | 0.035 / 0.029 | — | — | negligible |

`subtype_stratification_class`=**pan_subtype_uniform** (a decisive NEGATIVE — EPCAM/KRAS presence is NOT
subtype-restricted), `subtype_omnibus_driving_axis`=MSI, `n_subtypes_measured`=14. Capsule caught only
`subtype_variance_explained`=0.050 (matched a hint); the axis breakdown + driving axis + which-separate all
dropped. FAP·COADREAD contrasts: CMS axis omnibus p=4.6e-58, `subtype_variance_explained`=0.486, CMS4 (mesenchymal)
highest — a REAL subtype restriction (co-localizing with the CAF confound, §3.4).

**(c) Subtype-stratified SURVIVAL** — differentiation `subtype-survival-association`. `per_axis_association`:
sidedness `subtype_stratifies_survival` (logrank p=0.024) while CMS/MSI/CIMP/stage do not (p 0.10–0.69);
`subtype_survival_association_class`=subtype_stratifies_survival. Capsule `numeric_anchors=None, top_k_strata=None`
→ dropped (which axis stratifies + its logrank p invisible).

```
SALIENT-FIELDS SPEC (subtype axis — feeds key_evidence.subtype_axis, §2):
  subtype_array: subtype_omnibus_by_axis (presence) | per_subgroup_metrics (dependency) | per_axis_association (survival)
  driving_axis_field: subtype_omnibus_driving_axis    restriction_class_field: subtype_stratification_class / subtype_survival_association_class
  omnibus_field: subtype_omnibus_p | logrank_p         which_separate_field: which_subtypes_separate
  per_subtype_effect_field: median_chronos | median_log2tpm | median_ostime_days   n_field: subgroup_n / n_patients
  NULL-SAFE: absent subtype axis (--subtypes off) → subtype_axis = null; standard-run goldens byte-stable.
```

**EXEMPLARS (subtype):**
- △ **Subtype-restricted dependency (KRAS·COADREAD, --subtypes)** — dependency is stronger in MSS (Chronos −1.22,
  n=71, 42/71 strong) than MSI-H (−0.69, n=17) — an MSS-leaning window worth carrying for patient selection. [subgroup-stratified-dependency]
- ◆ **NOT subtype-restricted presence (EPCAM·COADREAD)** — presence is pan-subtype-uniform across 14 subtypes
  on 5 axes (driving axis MSI omnibus p=2e-4 but negligible effect, var 0.05) → no subtype gate needed. [tumor-rna-distribution-by-subtype]
- ▽ **Subtype-confounded over-call (FAP·COADREAD)** — the bulk-RNA signal is CMS-restricted (CMS axis omnibus
  p=4.6e-58, var 0.49; CMS4-mesenchymal highest) and co-localizes with CAF enrichment — the subtype signal is a
  symptom of the stromal confound, not malignant subtype-restriction. [tumor-rna-distribution-by-subtype]
- ◆ **Sidedness stratifies survival (KRAS·COADREAD)** — only sidedness associates with survival (logrank p=0.024);
  CMS/MSI/CIMP/stage do not — a right/left prognostic axis, not a molecular-subtype one. [subtype-survival-association]

---

## §4 — Ideal-bullet exemplars (Stage-2 narrative quality bar)

Hand-authored from real runs; each carries the §3-ranked datum + is anchored to a `card_id`. These are the
few-shot TARGET the Stage-2 narrator is tuned against and the RUBRIC (§5) source. Polarity glyph: △ supportive
· ▽ opposing/liability · ◆ neutral/gap.

**functional-requirement — KRAS·COADREAD (positive, DRIVING):**
- △ **Lineage-selective dependency** — the indication lineage Bowel shows Chronos −1.18 (q=3.8e-16) and
  Pancreas −1.83 (q=2.7e-25) against an omnibus p=7e-50; the panel sits *between* essentiality controls
  (selectivity index 0.85), i.e. a real therapeutic window, not pan-essential tox. [dependency-lineage-selectivity]
- ◆ **Orthogonal + chemical confirmation** — RNAi agrees (strongly_selective, 701 lines) and PRISM×CRISPR
  triangulates target engagement; cross-consortium Broad↔Sanger concordant. [prism-crispr-concordance,
  cross-consortium-dependency]
- ▽ **Redundancy caveat** — a strong NRAS paralog buffer means single-gene KO may be masked; a degrader or
  upstream pan-RAS node may be needed. [paralog-buffering]

**on-target-safety-liability — EGFR·LUAD (liability):**
- ▽ **Broad normal-tissue expression** — GTEx-detectable in 29/31 tissues (breadth 0.94), highest in skin
  (log2TPM 5.83) with critical-organ expression in nerve (5.12): a full-KO modality carries on-target tox
  risk. [normal-tissue-liability-gtex]
- ◆ **Moderate LoF constraint** — LOEUF 0.50, pLI 0.39: some intolerance of loss but not the extreme-
  constraint tier, so the concern is expression-breadth-driven, not constraint-driven. [gnomad-lof-constraint]
- ▽ **Germline dosage signal** — 118 ClinVar pathogenic germline variants and a lethal mouse KO
  (13 lethal alleles) corroborate loss-intolerance. [clinvar-pathogenicity-safety, mouse-ko-phenotype]

**on-target-safety-liability — PLK1·LAML (pan-essential liability, contrast):**
- ▽ **Highly constrained + pan-essential** — gnomAD highly_constrained and DepMap common_essential
  (median Chronos −2.76, 98.8% of lines strongly dependent): broad-tox liability for any full-KO agent —
  the window is the opposite of a selective dependency. [pan-cancer-crispr-dependency-distribution,
  gnomad-lof-constraint]

**Per-skill exemplars** (covering positive / liability / gateless / thin) are inlined at the end of each
§3.x block and the subtype exemplars in §3.16 — they are the primary few-shot corpus (each derived from that
skill's §3-ranked ★★★ fields). Two COMPOSED cross-skill exemplars (the target-profile pattern — reasoning
ACROSS subskills, Stage-2 step 5) that a graph-grounded narrator should be able to assemble:

**Composed — KRAS·COADREAD (positive, cross-subskill):**
- △ **Selective, chemically-confirmable dependency with a resistance caveat** — KRAS is a lineage-selective
  dependency (Bowel Chronos −1.18, q=3.8e-16; omnibus p=7e-50) that is hotspot-mutant-driven (mutant−WT Δ−1.14,
  q=1.2e-10) and chemically tractable (pChEMBL 10.7, RMC-7977 triangulated); but NF1 loss rescues under MRTX1133
  (resistance mediator) and a strong NRAS paralog buffers single-gene KO. [dependency-lineage-selectivity,
  mutation-stratified-dependency, prism-crispr-concordance, resistance-emergence-signature, paralog-buffering]

**Composed — MSLN·PAAD (modality tension, cross-subskill):**
- △▽ **Present and surface-adequate, but a cold, shed antigen** — MSLN is malignantly present with a high-quality
  RNA→protein proxy (r=0.79, n=114) and adequate surface density, yet MSLN-high tumors are immunologically COLDER
  (CD8 Δ−0.04, antigen_high=immune_cold) and the antigen is clinically shed — TCE/CAR-T context is unfavorable
  even though ADC topology is viable. [rna-protein-concordance-tumor, immune-context, shed-ectodomain-liability, adc-tce-modality-fit]

---

## §5 — Narrator eval rubric (generated bullets must pass)

A generated exec-summary bullet is ACCEPTABLE only if:

1. **Grounded number** — contains ≥1 of its card's §3-ranked ★★★ data points *with its significance* where
   one exists (effect **and** q/p/LOEUF, not effect alone). "median Chronos −0.46" alone FAILS.
2. **Right stratum** — when the signal is stratified, the number cited is the **indication** row (or the
   named strongest, explicitly labelled) — never an unlabeled pan-panel scalar standing in for a stratum.
3. **Anchored** — cites ≥1 real `card_id`/`question_id`/`citation_id` present in the package (reuse the
   existing `cites` mechanism; no invented ids).
4. **Cross-signal reasoning** — the bullet set as a whole connects ≥2 signals (corroboration, tension, or
   modality implication), not one bullet per card in isolation.
5. **Literature woven** — where a literature axis exists, the bullet states agreement direction using
   `agreement_vs_omics` (agree / contradicts / omics-blind) and cites the pmid, e.g. "[Went 2006 ✓]".
6. **Polarity-correct** — a liability/opposing signal is not narrated as supportive (respect the canonical
   polarity + the `liability` boolean).
7. **Bounded** — ≤ ~6 bullets total; each ≤ ~40 words.
8. **Deterministic fallback intact** — the always-on `Summary` block (no LLM) still renders the same ranked
   numbers when `--synthesize` is off; goldens never depend on LLM output.
9. **Subtype-correct** — a subtype claim names the axis + its omnibus p + which subtypes separate
   (e.g. "MSS Chronos −1.22 vs MSI-H −0.69"); and RESPECTS `subtype_stratification_class` — a
   `pan_subtype_uniform` axis is never narrated as subtype-restricted (F8). When the subtype axis is absent
   (`--subtypes` off) no subtype bullet is emitted.

**Scoring for the Stage-2 backtest:** grade each driving-signal bullet A/B/C against 1–6; a skill passes if
its driving bullet is grade A (all of 1–3 + polarity) and the set passes 4/7. Track the count of bullets
that cite the exact §3 ★★★ field vs. a generic scalar (the headline regression metric).

---

## §6 — Stage-1 consumption (how this feeds the code)

- **Per-type `reader_spec`** extends the existing `subgroup_derivation.reader_spec` precedent
  (`{class, n, label, present_synonyms}`) with the salience keys from every §3 spec block:
  `{strata_array, effect_field, significance_field, omnibus_field, n_field, direction, categorical,
  extra_scalars}`. ~20 verdict-bearing types need a real spec; the confidence/context tail can default.
- **`key_evidence`** (the §2 shape) is promoted in ONE edit to `evidence_graph.py`, reading the capsule's
  already-computed `top_k_strata`/`n_basis`/`categorical_anchors`/`conflict_pairs` PLUS the newly-pinned
  significance fields. Start with `crispr_lof_dependency` (spec in §3.1) — the verify case is Bowel
  (indication) + Pancreas (strongest) with q-values and omnibus p=7e-50 in the driving card's `key_evidence`.
- **Capsule sharpening** (`_top_k_strata`): carry `q`/`p` per row; resolve the indication row via
  `INDICATION_TO_*` (F2); pin the significance-bearing array per type (F1); declare `lineage_omnibus_p`
  explicitly (fails the hint heuristic).
- **Subtype axis (§3.16, F8):** add `subtype_array`/`driving_axis_field`/`restriction_class_field`/
  `omnibus_field`/`which_separate_field`/`per_subtype_effect_field` to the specs of the subtype-stratified
  cards, projecting into `key_evidence.subtype_axis`. MUST be null when the subtype axis is absent
  (`--subtypes` off for most skills; tumor-presence + FR-full carry it) so standard-run goldens stay byte-stable.
  The graph is already subtype-structure-aware (`_ambiguous_measurement_types` + `subtype:true` join) — this
  only adds the missing per-subtype EVIDENCE, changing no join.
- **Byte-stability:** all additive; deterministic sort/round via existing `_num`/`_R`; absent→omit/null.
  Verdict-inert throughout.

## §7 — Scope notes for Stage 1 (upstream gaps found, out of scope to build here)

These are `uncomputed` (bucket iv) — real gaps the audit surfaced; record + flag, do NOT build in this arc:
- **SL `top_partners` rows carry no per-partner effect/significance/validated-precedent field** (combination §3.9)
  — so canonical PARP–BRCA2 can't be ranked/surfaced. Needs an upstream card-summary field.
- **functional-gene-state `patient.state_counts` is a NESTED dict** (genomic §3.3) — no flat
  `patient_biallelic_fraction`; needs a summary reshape before any selector can reach it.
- **adc-tce-modality-fit verdict card emits no capsule** (surface §3.6) — confirm the capsule seam covers the
  composed card so `fit_class` + killer labels can be promoted.
- **A partner/gene LABEL field for co-mutation strata** (differentiation §3.11) is outside the default
  `_STRATUM_LABELS` — the spec must name it explicitly.
