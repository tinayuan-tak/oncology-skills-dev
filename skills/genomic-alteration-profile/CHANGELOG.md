# genomic-alteration-profile — changelog

Development history for the skill. The `SKILL.md` header describes the CURRENT
contract only; dated design decisions and reclassification notes live here so the
contract stays readable.

## 2026-09-13 (v2.18.0)
UNIFIED-OUTPUT completion + shadow/verdict coherence, all VERDICT-INERT, plus the companion golden
re-baseline for contracts resolver **1.10.0** (TC #739 CN-deletion/fusion specificity composed with
TC #760's role asymmetry).

Output-completion fixes, each of which was `None` or wrong on **26/26** panel runs before:
- `skill_report.subgroup_signals` was computed into the headline and then dropped at the
  `build_skill_report` call site — now passed.
- `skill_report.modality_scope` + `claim_record_shadow.modality_scope` were `None` on every run. New
  `_ga_modality_scope`: allele-selectable GoF driver → `small_molecule: favorable`; GoF driver with no
  selectable allele → `conditional` (the amplicon/fusion/WT-binding targets); recurrent biallelic
  deletion → `unfavorable`; else `na`. `biologics` is **always** `na` — this is an intracellular-intrinsic
  axis with no localization read, and asserting otherwise is exactly how CD19/TACSTD2/FOLR1 would
  acquire a fabricated biologics favorability. Reads the SHARED
  `wt_loss_safety_conditioning.yaml` triple rather than restating it, and additionally requires
  POSITIVE selectable-allele evidence: the triple is a NEGATIVE screen only, and without the positive
  conjunct TACSTD2 and FOLR1 read SM-favorable.
- `recurrent_snv_subclonal_uncertain` and `biomarker_dependency_unconfirmed` were in no `_GA_*` bucket,
  so they fell through `_ga_availability` to `measured_positive` — two tokens whose whole purpose is to
  WITHHOLD a driver call were published as measured positives. Now NEUTRAL + `insufficient`.
- `_claim_record` / `_strength_certainty` scored the RAW ladder, so TP53/COADREAD published
  `supports` / `measured_positive` / `strong` against its own emitted
  `biomarker_dependency_unconfirmed`. Both now score the reconciled word via
  `reconciled_verdict_from_cards`.

`scope_of_driving_verdict` — **SPECIFICITY IS NOT SCOPE.** 1.10.0's new
`cn-recurrent-homozygous-deletion-supportive` was unmapped, so a deletion-driven verdict would have
published `unclassified`. It is mapped to `_PAN_CANCER_RULES`, not `_INDICATION_ANCHORED_RULES`:
#739 replaced a 60.1%-null shallow predicate with a 1.5% biallelic one on the SAME cell-line panel, so
the call got much sharper without becoming any more indication-native. Only GISTIC per-sample
`cn-patient-focal-deleted-supportive` is indication-anchored. Caught by
`test_every_resolver_driving_rule_is_scoped`, which derives its population from the resolver.

## 2026-09-06 (v2.17.0)
MIGRATED off the hand-rolled `main()` onto the shared `run_wired_skill` dispatcher — genomic-alteration-profile
was the last hand-rolled fan-out `main()`, so every fan-out skill now shares one dispatcher path. Enabled by 3
ADDITIVE, None/signature-gated dispatcher hooks (byte-stable for the other 14 skills):
- `preprocess_provenance` is threaded into `headline_fn` via signature introspection, so `_build_headline`
  receives the family-wise-FDR + copy-number-gated amplicon-fusion provenance the `preprocess_gate=
  "genomic_alteration"` preprocessor computes (the same two functions the old `main()` called inline);
- `subtype_merge_fn` — a bespoke `--subtypes` merge hook (the dispatcher's generic flat merge cannot write
  genomic's NESTED `genomic_alteration_by_scope['subtype']` block);
- `claim_record_fn` — attaches the M1 `claim_record_shadow` (genomic is the only skill that emits it standalone).

The deterministic verdict spine + the entire headline are byte-IDENTICAL on the whole-cohort path.
Fleet-alignment deltas (all verdict-INERT, no test/schema pinned them):
- `run_health` adopts the fleet-standard shape (adds `read_secs`/`compute_secs`/`total_secs`,
  `provenance_warnings`, `cards_skipped_a4`); core status/counts unchanged.
- a `consolidation` sibling key is now emitted (fleet-standard).
- the headline-hero figure is now `--figures`-gated (was emitted unconditionally); matches every other skill.
- on `--subtypes`, the 3 panorama cards now receive whole-cohort `evidence_capsules` (fleet capsule source),
  so their `evidence_graph` nodes render at base detail — the panorama block itself is byte-identical.

## 2026-09-03 (v2.15.0)
Verdict-INERT signals-first fidelity fixes surfaced by the KRAS/COADREAD-vs-MET/LUAD literature-benchmark
review (follow-up to v2.14.0 #982). The multi-class resolver spine is byte-stable throughout.
- **SPLICE promoted to a first-class member of the signals-first layer.** `splice-exon-skip-landscape`
  became VERDICT-DRIVING in v2.13.0 (CASE-002, `splice_exon_skip_driver` rung) but the SURFACING layer was
  never extended, so a splice-driven verdict had NO representation in the class decomposition, claim vector,
  question table, key-signals headline, or narrator lead — for MET/LUAD the deterministic
  `key_signals.headline` read "Multi-class alteration driver (SNV/indel + Fusion)", naming two non-driving
  classes and omitting the splice class that IS the verdict. Now added:
  `genomic_alteration_by_class['splice']` (primary `splice_exon_skip_class` + event_id/driver_direction/
  n_depmap_carriers), a `SPL` claim-vector axis (`genomic_claims`, signal from `splice_exon_skip_class`,
  corroboration from DepMap-carrier confirmation), a question-table row, `key_signals` driver-naming, the
  `GENOMIC_ALTERATION` lens `axis_labels`, and headline lifts (`splice_exon_skip_class`, `splice_event_id`,
  `splice_n_depmap_carriers`).
- **Confidence-aware FUS downgrade (verdict-INERT).** A `recurrent_fusion_driver` claim flagged
  `fusion_recurrence_confidence == moderate_promiscuous` (promiscuous recurrence, no recurrent partner — the
  mixed bucket that also catches amplicon-artifact SVs) now downgrades `strong`→`weak` in the claim vector,
  so the signals-first layer stops over-reading a thin/promiscuous fusion as a co-driver (MET/LUAD n=3,
  literature-contradicted). The resolver rung is untouched — that verdict-moving fusion-competence/CN gate
  is tracked in #983.
- **Blast radius contained:** the `HeadlineSpec` hero axes stay `(SNV, CN, FUS, DEP)`, so `headline_block` /
  confidence / the hero figure are byte-stable for every target (SPL is surfaced via the claim vector /
  by_class / question_table / narrator, not the hero). Verified: KRAS/COADREAD verdict+headline_block
  byte-identical; MET/LUAD `key_signals.headline` now leads with the splice class.

## 2026-09-03 (v2.14.0)
- **OPTIONAL `--literature` lane** wired into the hand-rolled `main()` (this skill does NOT use
  `run_wired_skill`, so it attaches the lane itself, mirroring the dispatcher seam and tumor-presence
  #965 / tumor-selectivity #968). Reuses the shared `_skills_common.literature_synthesis.make_literature_fn`
  with `retrieve_fn=default_retrieve` (Europe PMC → PubTator3 fallback chain, #975) +
  `verify_fn=verify_citations` (Europe PMC / NCBI PMID verification). Verdict-INERT: attached as
  `decision['literature_synthesis']` AFTER the deterministic spine and BEFORE the `--synthesize` narrator
  (so the narration can CITE it via `narrator_engine._render_literature`); a network/Bedrock failure
  degrades to a note and can never break the spine. The `genomic-alteration-profile` lens query terms
  already live in `literature_retrieval._LENS_QUERY_TERMS`, and the lens's SNV/CN/FUS/DEP `axis_labels`
  match the genomic `claim_vector`, so the literature prompt is grounded on the right axes.
- **VERDICT-INERT claim-vector enrichment: CIViC therapy-resistance actionability.** A 4-facet
  KRAS/COADREAD literature benchmark (SNV-hotspot / copy-number / fusion / dependency+drug-response, all
  PMID-verified) confirmed the omics class-attribution is CORRECT (SNV/mutation class drives
  `biomarker_stratified_dependency`; CN + fusion correctly `absent`) and the LLM numbers faithful — but
  the single most clinically-important CRC-specific KRAS fact, that KRAS mutation is a NEGATIVE predictive
  biomarker for anti-EGFR mAbs (cetuximab/panitumumab; extended-RAS testing = SoC), was INVISIBLE to the
  narrator: it lives in `variant-level-interpretation.civic_resistance_variants` but the capsule projection
  never surfaces `resistance_variants`, so the synthesis missed it. `genomic_claims._resistance_actionability`
  now folds a compact, class-generic CIViC therapy-resistance clause into the DEP ("actionability so what")
  claim's rendered `evidence` (and thereby `key_signals`), so the narrator surfaces it. Verdict spine
  byte-stable (live KRAS/COADREAD: verdict / driving_rule / fired_rules identical). LensConfig thesis
  extended to name variant-level clinical interpretation + therapy-resistance actionability.
- SCOPE respected: therapeutic-window / selectivity stays owned by tumor-selectivity; dependency magnitude
  by functional-requirement. This surfaces only clinical interpretation of the target's OWN alterations
  (this skill's own `variant-level-interpretation` card), verdict-inert.

## 2026-09-02 (v2.13.0)
- **splice-exon-skip-landscape** card wired as a VERDICT-DRIVING genomic axis (CASE-002). A curated
  exon-skipping DRIVER event (METex14) that is oncogenic in-indication + live DepMap carrier
  confirmation fires `splice-exon-skip-driver-supportive` → `splice_exon_skip_driver` (genomic
  resolver v1.8.0, priority 36 — above the variant-class-shape rungs). So MET/LUAD reads a
  splice-skipping driver instead of a NEUTRAL `missense_dominant_pattern`: the signal-vector
  FIDELITY fix (the nomination veto was already resolved — this fixes WHY MET matters, per
  `eval/CASE_LOG.md` CASE-002). Backed by analysis-methods `exon_skip_carrier` (#551/#552/#554)
  over `depmap-somatic-splice-variants-v1` (#548). SURGICAL blast radius: fires only for a gene with
  a registered exon-skip event in its curated oncogenic indication (today: MET in LUAD/LUSC/NSCLC) —
  backtest-verified MET/LUAD flips; KRAS/COADREAD + EGFR/LUAD unchanged. New verdict phrase +
  positive polarity; question-hierarchy FUS binding + resolver golden regenerated.

## 2026-09-01 (v2.12.0)
- EMITTED-verdict reconciliation with the signal package (`reconcile_genomic_verdict`), mirroring
  tumor-presence's `reconcile_presence_verdict` (#860). The raw resolver ladder collapse (`_verdict`)
  is UNTOUCHED and remains what the composed target-profile GATE reads (tp_fanout stores the raw
  `resolve_verdict_for_gate` output in `sub_results`; genomic IS in `_SHORT_TO_GATE`, so the nomination
  spine + the tp_gates GoF co-condition keep the raw call). But the ONE WORD a human/LLM reads
  (`headline.genomic_alteration_profile` + `headline_block` + `key_signals` + `question_table` + the
  narrator's collapsed-verdict line) is now reconciled so it can't OVER-READ the decomposition. A
  biomarker-dependency-family verdict demotes to the new NEUTRAL caveat token
  `biomarker_dependency_unconfirmed` ONLY when BOTH orthogonal KO-dependency confidence cards contradict
  the claimed dependency: cross-consortium `concordant_non_dependent` AND event-model
  `event_matched_not_dependent`. The raw word is kept as `genomic_alteration_profile_ladder`.
  CD19-safe (categorical, no magic number; two explicit opposing measurements — a single card
  gap/agreement retains). Backtested on a LoF-suppressor + GoF-oncogene panel: only TP53/COADREAD
  demotes (its DEP is a low-confidence mutant-p53 correlation both cards oppose); KRAS/ERBB2/PIK3CA
  (real dependencies) and BRAF (event card absent) all retain. Verdict-INERT to the nomination spine
  (resolver golden byte-stable — the token is clamp-minted, not a resolver token).

## 2026-08-21 (v2.8.0)
- Emit the EXISTING per-question `genomic_question_table` into `decision.headline["question_table"]`
  (and add it to `_SYNTHESIS_FACET_KEYS`), mirroring tumor-presence / tumor-selectivity. Additive +
  verdict-INERT: a best-effort projection over the already-built headline + claim_vector; a formatting
  fault records `_enrichment_errors["question_table"]` and never aborts the multi-class genomic spine.

## 2026-08-19 (v2.7.0)
- Added the Q4 KO-dependency CONFIDENCE annotations (deferred item, verdict-inert): cross-consortium-dependency
  (Broad↔Sanger CRISPR agreement) + dependency-predictability (omics-learnability). Both are additive
  signal-only cards (fire NO genomic_alteration rung; verdict spine byte-stable) surfaced in the headline
  (cross_consortium_class, dependency_predictability_class, dependency_predictability_feature). Thematically
  aligned with the scope-coherence effort: dependency-predictability's predictability_lineage_collapsed
  flags the pan-cancer-vs-indication dependency scope-leak the Phase-1 biomarker rungs are gated against.
  (Surface-2 therapy/exposure signatures remains deferred — its SigProfiler Activities.txt intermediate is
  not stored, so it needs a full signature-assignment re-run, not a simple product re-emit.)

## 2026-08-19 (v2.6.0)
- Wired the POOLED multi-cohort patient recurrence into the verdict (scope-coherence Phase 2, the SNV
  indication-anchor gap). mutation-hotspot-frequency is now VERDICT-DRIVING: its pooled_driver_recurrence_class
  (TCGA-MC3 + GENIE + MSK-CHORD, backed by pooled-snv-recurrence-v1) fires snv-recurrence-top-driver-supportive
  -> the new recurrent_snv_driver resolver rung (tier 6, last — a dually-altered gene keeps its CN/fusion
  verdict). run.py surfaces the pooled fields in _HEADLINE_FIELDS + the genomic_alteration_by_scope.indication
  block (a top-recurrent SNV now reads scope=indication_anchored); added mutation-hotspot-frequency to
  rules_scope. Regenerated the _skills_common resolver golden (genomic gate: 12->13 rule_ids, 405->810
  combos) + added recurrent_snv_driver to the replay driver-outcomes. Full skills suite (1055) green.
  Pooled COADREAD recovers the canonical drivers as top_1pct (APC/TP53/KRAS/PIK3CA/SMAD4/FBXW7/BRAF).

## 2026-08-19 (v2.5.0)
- Broadened the subtype scope beyond SNV frequency (scope-coherence Phase 3, gap c): wired the two new
  DESCRIPTIVE panorama cards `subgroup-stratified-copy-number` + `subgroup-stratified-fusion` into
  `SUBTYPE_CARDS`. Generalized `_resolve_subtype_panorama` to a per-axis reducer (`_panorama_axis`) that
  emits `headline.subtype_axis` (SNV, unchanged keys — backward-compatible), `subtype_cn_axis`, and
  `subtype_fusion_axis`; the `genomic_alteration_by_scope.subtype` block now aggregates presence across
  all three axes. Registered `subgroup-stratified-{copy-number,fusion}` in compose-dashboard
  `_live_readers.PANORAMA_DISPATCHERS` (both reuse the TCGA molecular assignments shard — no LOT/GENIE
  split, unlike the mutation panorama) routing to `tcga_patient_cn.stratified.build_copy_number_panorama`
  / `tcga_fusion_consensus.stratified.build_fusion_panorama` (analysis-methods #414). DESCRIPTIVE /
  verdict-inert — `--subtypes`-gated, touches no resolver rung, whole-cohort verdict byte-stable.
- Updated the synthetic verdict tests for the Phase-1 indication-scope gate: a biomarker verdict now
  requires the `*-indication-scoped-context` co-fire (pan-lineage-only dependency falls through); added
  `test_biomarker_requires_indication_scope_gate` pinning the flip.

## 2026-08-19 (v2.4.0)
- Added `headline.genomic_alteration_by_scope` + top-level `scope_of_driving_verdict` — the per-SCOPE
  decomposition (pan-cancer / indication / subtype) of the collapsed verdict, mirroring
  `genomic_alteration_by_class` (which decomposes by CLASS). `scope_of_driving_verdict` ∈
  `indication_anchored` / `pan_cancer_extrapolation` / `mixed` / `not_applicable` / `unclassified`,
  derived deterministically from `driving_rule_id` + the driving card's own scope field
  (dependency rungs read `evidence_scope`; landscape/shape/pharmacology rungs are statically
  indication-native vs pan-cancer; a pan-cancer signal with indication-native corroboration reads
  `mixed`). Makes the verdict's SCOPE HYBRID explicit: the ladder-leading KO-dependency / variant-shape /
  drug-response are pan-cancer cell-line, while patient recurrence, patient-focal CN, TCGA fusion, and the
  IntOGen role are indication-native. Also surfaced the cn/fusion/amp-expr `evidence_scope`,
  `intogen_scope`, and `patient_focal_cn_class` at the headline top level. ADDITIVE / verdict-inert —
  reuses fields already emitted; `genomic_alteration_profile` is byte-stable (KRAS/BRAF COADREAD replay
  green). The functional-requirement `dependency_verdict_by_scope` analog; Phase 0 of the scope-coherence
  plan and the instrument that de-risks the (verdict-affecting) dependency-rung scope-gate harmonization.

## 2026-08-18
- Fixed a `depmap_common` lineage-ladder label bug (amp-expr strong→moderate downgrade
  never fired because the map keyed the abbreviated `amp_expr_*` class instead of the
  fully-spelled `amplified_overexpressed_*` the method emits). Corrected in analysis-methods.
- Added `fusion_recurrence_confidence` — a verdict-inert tier on a `recurrent_fusion_driver`
  call (`high_recurrent_partner` = reliable recurrent partner vs `moderate_promiscuous` =
  target recurs but no recurrent partner; the latter also catches amplicon-artifact SVs at
  amplified oncogenes, e.g. ERBB2/STAD ~1%). A panel backtest found no frequency/structural
  cut separates those from real promiscuous kinase fusions (ROS1/NTRK1), so the intended fix
  is a future fusion-competence / copy-number gate, not a threshold change.

## 2026-08-15
- Doc-parity fix: `fusion-rearrangement-landscape` and `mutation-drug-response` (STRONG class
  only) are VERDICT-DRIVING — they fire resolver rungs (`recurrent_fusion_driver` and
  `drug_response_biomarker` respectively) and belong in `rules_scope`. They had been
  mis-documented as additive signal-only.

## 2026-08-14
- Added `genomic_alteration_by_class`: the per-alteration-class decomposition of the collapsed
  multi-class verdict (`{snv_indel, copy_number, fusion}`), mirroring tumor-presence's
  `presence_verdict_by_modality`. Additive / verdict-inert — reuses fields already in the
  headline, so the verdict spine is byte-stable.
- Added `target-clonality` (ccf-based truncality from MC3 VAF × ABSOLUTE purity) as an additive
  durability/resistance facet.

## 2026-08-13
- Declared all pulled measurement types in `measurement_types_pulled` (previously 8 of 18: the
  3 stratified-dependency siblings, the drug-response biomarker, and the 5 cohort-context/variant
  layers were consumed by `cards_used` but never declared). `test_genomic_measurement_types.py`
  now enforces parity so it cannot silently re-drift.

## 2026-08-08 – 2026-08-12
- Reclassified `alteration-role` as VERDICT-DRIVING (fires the `confirmed_driver` rungs together
  with a mutation/CN driver rule) — it had been mis-filed as additive.
- Added the 3 stratified-dependency cards (cn/fusion/amp-expr) to `rules_scope`.
- Added indication-level cohort-context facets (additive, verdict-inert): `genomic-instability-state`
  (aneuploidy/CIN), `mutational-signature-context` (TCGA MC3 → COSMIC v3.3 SBS), `ddr-deficiency-context`
  (Knijnenburg 2018 DDR footprint), `oncogenic-pathway-alteration` (Sanchez-Vega 2018).

## 2026-08-05
- Dropped `mutation-hotspot-frequency` from `rules_scope`: it fires zero rules (its
  `overall_mutation_frequency` is display-only). A driver-recurrence percentile is the intended
  path to make frequency verdict-relevant.
- Renamed the `recurrent_*_driver` SNV verdicts to `*_dominant_pattern`: they report the
  variant-class COMPOSITION of the mutation spectrum (≥70% missense / ≥50% truncating), not
  patient recurrence, which the mutation-type card never computes.
- Added opt-in `--synthesize` (genomic-alteration-lens LLM narrator; verdict-inert).

## 2026-07-23
- `fusion-rearrangement-landscape` went LIVE (`tcga-fusion-consensus-v1`: TumorFusions/PRADA +
  Gao 2018 + cBioPortal-TCGA-SV, 3-caller consensus). A `recurrent_fusion_driver` fusion_class
  fires the fusion resolver rung.

## 2026-07-14
- REFRAMED from `mutation-profile` (SNV/indel only) to `genomic-alteration-profile`. The
  copy-number-distribution card + its copy-number rules already existed but had never been
  composed into a skill; a mutation-only skill implied "not a driver" for amplification-driven
  targets (ERBB2, MYC, MET). The skill now reports the alteration MIX and names which class drives.
