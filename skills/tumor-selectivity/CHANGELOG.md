# Changelog — tumor-selectivity

The `version` in [SKILL.md](SKILL.md) and `SKILL_VERSION` in
[scripts/run.py](scripts/run.py) must always match (guarded by
`skills/tests/test_version_parity.py`); bump both together and add an entry here.

## 1.31.0
(2026-10-01, PR-1d of epic SK#2210 / #1507, #2213 — the SELECTIVITY generalisation of the tumor-presence L2a vertical, replicating the safety/dependency/genomic seeds): the per-source observational (L2a) properties for 6 sources (tumor_vs_normal_rna_window, patient_distribution_separation, malignant_cell_intrinsicity, sc_normal_tissue_window, protein_tvn_window_cptac, protein_tvn_window_tphp) are lifted into a NAMED typed map `claim_vector.source_properties` (selectivity_claims.py `_SOURCE_PROPERTY_RECIPES_SELECTIVITY`), each carrying its L1 card_id, the resolved observational class, the RETAINED quantitative anchors ({field, value, scale}) + comparability metadata, and the #2306 typed `reliability` facet (n_effective projected from each property's own n-anchor where the authoritative table names a genuine sample-size anchor; powered='unmeasured' uniformly — no selectivity property-kind has a calibrated floor yet; confound_flags/artifact_flags=[] — no anchor in this table carries a purity-confound r or an allgene-percentile floor-tie flag; detection_strength FIRES on malignant_cell_intrinsicity via the calibrated sc_malignant_detection_fraction scheme, OMITTED on the other five non-detection-kind properties). Under --emit-envelope evidence_package.json gains the NAMED top-level sections source_properties (L2a) / integrated_properties (L2b selectivity_concordance) / local_composites (the four WIN/DIST/INT/SAFE axes), built by _evidence_sections(headline) and threaded through run_wired_skill(evidence_sections_fn=...). No `l3d` section yet. Like genomic/dependency, selectivity emits NO `comparability.valence` marker (a tumor-vs-normal window is the SIGNAL this domain seeks, not a liability) and NO `interpretation` provenance object (every property_field below is a verbatim card read). Contracts governance: contracts/vocabularies/property_catalog/selectivity.yaml (6 L2a props); claim_axis.enum.yaml 1.3.0->1.4.0 (WIN/DIST/INT/SAFE now cite selectivity.* — DIST and INT move from resolves_pending to resolved). ADDITIVE / VERDICT-INERT: no axis renamed, no new L2b family, no token minted; `source_properties` omitted byte-stably when no source resolves; carries no `signal` key and read by no rule/verdict/ladder, so selectivity_class + the CEACAM5/TACSTD2 replay goldens are byte-stable.

## 1.30.0
(2026-09-28, #1669/#1831): DISPLAY de-anonymization + comparator-breadth honesty (VERDICT-INERT). #1669: the selective_but_broadly_normal KILL tension was the last un-de-anonymized veto arm — it borrowed only the sc-normal arm's sc_normal_liability_detail and named NO organ when a therapeutic-window arm fired ALONE. _headline now surfaces max_full_normal_organ / max_full_normal_tpm (read NOWHERE until now) and _selectivity_tension_extra branches on driving_rule_id so tvn-no-full-normal-window-veto names max_full_normal_organ (the non-essential TROP2/salivary blind spot) and tvn-no-therapeutic-window-veto names max_essential_normal_organ — the sibling of the sc-normal #572 / TPHP v1.26.0 de-anonymizations. #1831: the Q2 "Robust across independent comparators?" question-row and the hero Cross-comparator axis scored breadth from the raw cell COUNT (cells A raw + B ComBat = the SAME tumor-vs-adjacent comparison scored twice) and ignored comparator_concordance, so an adjacent-only run rendered as "N/N independent comparators agree · HIGH". Both now read comparator_concordance and cap tier/confidence/status/wording: single_comparator → not high/good and named as one resolved family; discordant → disagreement wording; concordant/unknown → today's cell-count rendering (byte-stable) — mirroring the cap _sel_coverage / _win_corroboration already apply. Resolver + apply_normal_breadth_veto spine + CEACAM5/TACSTD2 replay verdicts byte-stable. # 1.29.0 (2026-09-27, #1776): VETO-COVERAGE certainty demotion + structured flag (VERDICT-INERT). The normal-breadth / stromal vetoes are one-directional (downgrade-only) and no-op when their card is data_unavailable, so a clean axis-A selective call whose window / sc-normal / tphp / sc-tumor veto arm could not look passed as CONFIDENTLY tumor-selective as one measured clean — the unassessed arms were surfaced only narratively (_selectivity_tension_extra) and numerically (_sel_unknown_mass), moving neither the verdict nor the reported certainty. `_strength_certainty` now computes a structured `certainty.veto_coverage` census (status fully_vetted / unvetted_for_normal_breadth_stromal_confound / not_applicable + the named blind arms) via new `_sel_veto_coverage`, and DEMOTES the reported certainty.level ONE band (high→medium→low, floored at low) when a clean axis-A positive rests on ≥1 unmeasured veto arm — so a clean pass on MISSING evidence is distinguishable, in the reported-certainty object, from a clean pass on MEASURED evidence. FAIL-OPEN PRESERVED: read AFTER the resolver+veto walk, it only ever LOWERS certainty on a clean positive (a fired veto → verdict ∉ _AXIS_A_SELECTIVE → status not_applicable → no-op) and NEVER clears/fabricates a KILL. No rule, card, resolver, ledger, schema or golden reads the new field; the selectivity_class spine + veto walk are byte-stable (the standalone emit does not carry the sidecar; the flag surfaces in the composed target-profile certainty_by_axis.selectivity). # 1.28.0 (2026-09-27, #796): MARROW-COVERAGE TRANSIENT ABSTAIN (verdict-MOVING only under a transient marrow-HPA read failure; VERDICT-INERT offline — a transient never occurs in replay). analysis-methods marrow.py now mints marrow_substrate == "unavailable_transient" for a transient read failure (network/creds/throttle/5xx/parse), distinct from the DEFINITIVE "unavailable" config miss. A transient used to be indistinguishable from a config miss, so marrow dropped out of the essential-organ denominator, window_ratio_essential inflated, therapeutic_window_class moved off no_therapeutic_window, tvn-no-therapeutic-window-veto never fired, and the essential-window KILL SILENTLY VANISHED for myeloid-argmax targets (CD33/CLEC12A/IL3RA/FLT3). New apply_marrow_coverage_abstain (in _skills_common/selectivity_veto.py) runs AFTER apply_normal_breadth_veto and WITHHOLDS a still-selective axis-A call as selective_pending_marrow_coverage when marrow_substrate=="unavailable_transient" AND the target is marrow-PLAUSIBLE by an INDEPENDENT substrate (sc-normal-celltype-expression sc_normal_essential_max_tissue=="bone marrow"). withhold_only: never fabricates a KILL, never clears a KILL that fired on other grounds (if a veto fired the verdict is ∉ _AXIS_A_SELECTIVE and it no-ops); fail-open when the independent plausibility signal is absent so it never scope-creeps to all targets during a process-wide transient. Consumes TC pin 8c4bba3 (resolver clamp_verdicts + nomination_verdict_gate registration). # 1.27.0 (2026-09-19): the sc-normal clamp's GATING FIELD is now PROJECTED (VERDICT-INERT). tvn-sc-normal-critical-organ-veto was repointed onto `sc_normal_essential_veto_grade` because `sc_normal_safety_essential_class` is a near-constant (473 of 504 corpus-20260914 pairs, 93.8%, vs 329/65.3% for the grade), but the skill never lifted the grade: every OTHER input to the arm was in the headline -- the class, the named driver cell/tissue, its detection fraction, its atlas count, and a skill-side RE-DERIVATION of the severity (`sc_normal_essential_severity`) -- so `decision['headline']` could carry a `selective_with_normal_liability` verdict containing no field that explains the downgrade. Measured on DLL3-SCLC: the card summary read `accessible_high_severity` while the headline read nothing. Adds the field to `_headline` and to `_SYNTHESIS_FACET_KEYS` beside its own re-derivation (projecting the re-derivation but not the gating value was the worse half of the gap -- a reviewer could not tell a skill-side drift from a method-side call), and corrects the block comment, which named `sc_normal_safety_essential_class` as the gating field and was measurably false against intracellular-intrinsic.rules.yaml. No rule, card, ledger, schema or golden reads the new field; resolver/veto spine byte-stable.

## 1.29.0
- **Veto-coverage certainty demotion + structured flag (VERDICT-INERT; #1776).** The normal-breadth /
  stromal vetoes are one-directional (downgrade-only) and no-op when their card is `data_unavailable`,
  so a target that is axis-A selective but whose window / sc-normal / tphp / sc-tumor veto card could
  not look was reported as confidently tumor-selective as one measured clean — the unassessed arms were
  surfaced only narratively (`_selectivity_tension_extra`) and numerically (`_sel_unknown_mass`), moving
  neither the verdict nor the reported certainty. `_strength_certainty` now attaches a structured
  `certainty.veto_coverage` census (`status` ∈ {`fully_vetted`, `unvetted_for_normal_breadth_stromal_confound`,
  `not_applicable`} + the named blind arms), computed by the new `_sel_veto_coverage`, and DEMOTES
  `certainty.level` by one band (high→medium→low, floored at low) when a clean axis-A positive rests on
  ≥1 unmeasured veto arm. A clean pass on MISSING evidence is therefore distinguishable — in the
  reported-certainty object — from a clean pass on MEASURED evidence.
- **Fail-open direction preserved.** The census is read AFTER the resolver + veto walk; it only ever
  LOWERS certainty on a clean axis-A positive (a fired veto puts the verdict ∉ `_AXIS_A_SELECTIVE`, so
  `status` is `not_applicable` and nothing is demoted) and can neither clear nor fabricate a KILL. No
  rule, card, resolver, ledger, schema or golden reads the new field; the `selectivity_class` spine and
  the veto walk are byte-stable (the flag surfaces in the composed target-profile
  `certainty_by_axis.selectivity`, mirroring where `_sel_unknown_mass` already lives).

## 1.25.0
- **The sc-normal essential SEVERITY ladder is realigned with analysis-methods (VERDICT-INERT).**
  `_sc_normal_essential_severity` is a hand-copy of `_essential_severity` in analysis-methods
  `methods/sc_normal_expression/stats.py`, and 1.23.0 described its thresholds as "ported verbatim".
  A **616-cell differential grid** — every cutoff in either ladder bracketed on both sides, `None` on
  all three axes, so it is exhaustive over the input's equivalence classes rather than a sample of
  them — measured the copy **disagreeing on 394 of 616 cells via four independent causes**, with an
  empty unexplained bucket. All four are closed here:
  - **The `REPLICATION_DOMINANT` rung was missing.** `det >= 0.40 ∧ donor >= 0.70 ∧ n_datasets >= 15`
    now reaches `high_severity` without clearing the 0.50 detection line. This is the **MSLN-PAAD**
    shape from the audit's OPEN defect #2: detection 0.413, donor fraction 0.881, **26 independent
    atlases**. Magnitude and confidence are different axes, and 26 atlases agreeing is not a marginal
    result. Live, this rung alone promotes 60 pairs from `moderate_severity`, and all 60 have
    detection in `[0.405, 0.497]` — i.e. every one was unreachable by the plain high rung.
  - **Absent grading fields were defaulted to `0.0` / `0`** and then run through the ladder,
    manufacturing `low_severity` — a measured-sounding claim — out of a missing column. A hit that
    FIRED but cannot be graded now reads **`ungraded`**, which the method deliberately ranks *above*
    `moderate` precisely so that thinner data can never RELAX a veto. `None` is now reserved for its
    one honest meaning: no essential hit fired, so there is nothing to grade.
  - **`low_severity` → `low_confidence`.** A detection-0.85 / donor-0.90 hit seen in **one** atlas is
    UNREPLICATED, not SMALL; `low_severity` asserted a magnitude claim the evidence does not license.
  - **The read-out is now an explicit map, not a string transform.** The old
    `f"{sev.split('_')[0]}-severity"` prints **"low-severity" for `low_confidence`**, so renaming the
    token alone would have changed nothing a human sees — the same shape as the named-driver defect
    fixed in analysis-methods #665, where a corrected grade never reached the name printed beside it.
    An unknown token now raises `KeyError` rather than inheriting a plausible-looking wording.
- **This is a copy on purpose and must not be "fixed" into an import.** Skills CI checks
  analysis-methods out at a **pinned SHA** (`skills-validate.yml`, `0006164e`) that *predates*
  `_essential_severity` (AM #647, `fe65660`), so an import would pass locally off the editable path
  dep and raise `ImportError` in CI. That same pin is why the copy rotted unnoticed: any CI test
  comparing the two ladders compares against a tree where one of them is absent. The guard is
  therefore split — an **unconditional** test pins the five cutoffs as literals and runs in CI, while
  the cell-for-cell agreement test reads the method and **skips in CI with the pin named in the skip
  reason**. The reasoning is recorded in-code above the constants block.
- **Verdict-inert, and measured as such.** No rule, card, field-disposition ledger, schema or golden
  reads `sc_normal_essential_severity`. Backtested live over all **504 corpus-20260914 pairs** (the
  full unfiltered per-cell-type pull from S3, never the stored packages — `per_cell_type_top` is
  `head(15)` sorted by detection descending, so its truncation correlates with the measurand):
  agreement with the method goes **391/451 → 451/451** by severity rank *and* **356/451 → 451/451**
  by string equality, closing the threshold and vocabulary halves together. The only user-visible
  change is the wording inside `sc_normal_liability_detail` and the `headline.sc_normal_essential_
  severity` token.

## 1.24.0
- **Modality-conditional normal-breadth KILL suppression (VERDICT-MOVING, `--modality` runs only).**
  The five selectivity veto rules in target-contracts have always declared per-modality `signals:`, and
  three of them declare `adc: neutral` deliberately — `tvn-no-full-normal-window-veto` carries the
  comment *"the TROP2/TACSTD2 salivary-gland archetype: broad-LOW normal (clean vs the essential set) is
  ADC-tolerable — sacituzumab/Dato-DXd are validated ADCs here"*. But `apply_normal_breadth_veto` took
  **no modality argument** and mapped every fired arm straight to its verdict, so the framework issued
  the housekeeping KILL (`selective_but_broadly_normal`) for validated ADC antigens **in their approved
  indication**, on evidence its own contract calls neutral for that modality. The clamp now reads the
  fired rule's OWN `signals[modality]` — contract-driven, no Python-side modality table, so a new arm's
  lens is honoured with no code change here.
- **The waiver requires the essential-organ axis to be affirmatively CLEAN** (`modality-therapeutic-
  window.therapeutic_window_class == clean_window`) — the *"clean vs the essential set"* clause of the
  contract's own ADC-neutrality comment. Waiving on the `adc: neutral` declaration alone was measured on
  the 36-target panel to let designed true negatives ESCAPE: **RPL13A/COADREAD** (a ribosomal
  housekeeping decoy — tumor 641.4 TPM vs BONE_MARROW 617.5, essential ratio 1.04) and **MUC1/BRCA**
  (182.3 vs LUNG 133.8, ratio 1.36) both rose from the housekeeping KILL to the selectivity-PRESERVING
  `selective_with_normal_liability`. Both are `narrow_window` on the essential axis, and `narrow_window`
  fires **no rung** in the intracellular lens, so the full-normal KILL was the only thing holding a
  600-TPM-everywhere gene down. Every non-clean value (narrow / no-window / not-expressed /
  data_unavailable / absent card) now fails CLOSED. `_verdict` and `_headline` receive the resolved
  `cards` from the dispatcher to read this field, and both apply the precondition identically so the
  headline can never claim a waiver the verdict did not grant.
- **MEASURED panel effect: ZERO on today's data (36/36 unchanged, both lenses).** With the precondition
  in force the waiver is currently unreachable: the full-normal KILL fires on 20/36 panel targets and
  *none* of them has a clean essential window (16 are `no_therapeutic_window` — already KILLed by the
  ADC-`opposing` essential arm — and 4 are `narrow_window`). So this release does **not** rescue
  TACSTD2, NECTIN4, CLDN18 or EGFR in their approved indications: the max-of-15/31 window **denominator**
  is what blocks them, and that fix is tracked separately. What lands here is the mechanism plus its
  guards; it becomes live when a clean essential window can co-occur with a broad-but-low pan-normal one.
- **Scope is deliberately narrow.** (a) Only the two KILL outcomes can be suppressed; the
  selectivity-PRESERVING `selective_with_normal_liability` always stands (its arms also declare
  `adc: neutral`, and suppressing it would DELETE safety signal rather than unblock a nomination).
  (b) Suppression **falls through** to the next arm in precedence, so an arm that is `opposing` for the
  chosen modality still KILLs — `tvn-no-therapeutic-window-veto` (tumor below a VITAL organ) is
  `opposing` for all four modalities, so an ADC lens never rescues a target failing that arm.
  (c) Only an explicit `neutral`/`supportive` suppresses; a missing/unknown signal and `insufficient`
  (a coverage-gap token, not a safety judgement) keep the KILL.
- **Byte-identical without `--modality`.** `modality=None` reproduces the pre-change worst-case clamp
  exactly, which covers every default run plus the composed (`compose_core.resolve_gate_spine`) and
  `flip_analysis` paths.
- **A waived arm stays VISIBLE.** New `modality_suppressed_kill_arms()` helper + three headline fields
  (`verdict_modality_lens`, `modality_suppressed_veto_arms`, `modality_suppressed_veto_note`) name which
  arm fired and was waived for which modality, and state that the liability is real and arbitrated by
  payload/bystander buffering + density (owned by on-target-safety-liability and modality-fit) rather
  than dismissed. A suppressed KILL must never read as an arm that never fired. The three keys are
  emitted **only under a lens** and OMITTED (not present-and-`null`) otherwise — three always-present
  nulls would churn every golden/replay snapshot and every consumer schema to say "no lens was used",
  which their absence already says, and would break the byte-identity claim above.
- **Plumbing.** `run_wired_skill(verdict_modality_aware=True)` calls `verdict_fn(fired, modality=…)`;
  every other skill keeps the 1-arg `VerdictFn` contract. `_headline` receives `modality` through the
  existing signature-gated optional-kwargs mechanism (same pattern as `target` / `indication` /
  `preprocess_provenance`), so no other `headline_fn` changes behavior.

## 1.23.0

> Superseded in part by 1.25.0, which renamed `low_severity` → `low_confidence` and added the
> replication rung. This entry is left as the record of what 1.23.0 actually shipped and is
> deliberately NOT retro-edited — a changelog that describes today's code under yesterday's version
> number stops being usable as history.

- **sc-normal essential-liability SEVERITY grade (W3c, VERDICT-INERT).** A fired critical-organ /
  origin-tissue liability is now graded `high_severity | moderate_severity | low_severity` from the
  driver's magnitude × donor consistency × independent-atlas replication — the three fields
  analysis-methods #572 already emits per-driver, so this is DERIVED in the skill (`_sc_normal_essential_
  severity`), **not** a new card field (no re-freeze, no shared-card `field_disposition` churn). It
  distinguishes a robust hit (INS β-cell 1.0 / 11 atlases → high) from a marginal single-atlas one just
  above the 0.20 off-origin floor (→ low). Surfaced inside `sc_normal_liability_detail`
  (`"…(11 atlases, high-severity)"`), a new `headline.sc_normal_essential_severity` field, and the
  synthesis facet. Thresholds mirror the card's HIGH_LIABILITY ladder (det≥0.50 ∧ donor≥0.70) + a
  ≥2-atlas replication floor.
- **`data_unavailable` → explicit "unknown-mass", not a silent clean pass (W3c).** When the single-cell
  critical-organ safety arm is `data_unavailable` on an otherwise clean axis-A selective call, a new
  severity-2 tension (`source: sc_normal_unassessed`) says the arm is UNASSESSED — not safety-cleared at
  cell-type resolution. Complements the pre-existing numeric `_sel_unknown_mass` (which already counts
  the blind arm) by NAMING it in the narrative. Silent when sc-normal is measured or a veto already
  downgraded (the veto tension keeps the slot).
- **Verdict-INERT / additive:** derivations over the already-built headline / driver fields; never
  touches `selectivity_class`, the normal-breadth / stromal-confound veto spine, or any resolver rung.
  CEACAM5/TACSTD2 replay verdicts unchanged; resolver golden-stable.

## 1.21.0
- **`measurement_caveat` — disambiguate a coverage-gap verdict that rests on a measured signal (VERDICT-INERT).**
  A live FAP/PDAC pass exposed that a decisively **stroma-driven** target resolves to `not_informative`
  (the aggregate axis-A card abstains on the single-comparator field effect, so the stromal-confound veto
  is armed-but-moot) — the same token used for "unmeasured", so the composed profile (which treats
  `not_informative` like a gap) would miss the decisive INT-negative that lives only in the claim_vector.
  New `_measurement_caveat` (in `_headline`) flags, when the resolved class is a coverage-gap token
  (`not_informative`/`insufficient`/`data_unavailable`) yet the claim vector carries a decisive measured
  signal: `reason` ∈ {`stromal_confounded_false_window`, `stroma_dominant_signal`,
  `present_but_not_tumor_selective`} + a human note. Emitted as `headline.measurement_caveat` and added to
  the synthesis facet so the composed layer *can* read it. `None` for a measured call or a genuine gap.
- **Verdict-INERT / additive:** a projection over the already-built claim_vector — never touches the
  `selectivity_class` / normal-breadth / stromal-confound veto spine (resolver golden-stable; CEACAM5/
  TACSTD2 replay unchanged). Actually consuming it in the composed gate (so a stromal false window scores
  as a negative, not a gap) is a deliberate spine follow-up, NOT in this change.

## 1.20.0
- **`--literature` retriever → `default_retrieve` (multi-source, lens-specific queries).** Shared
  `_skills_common/literature_retrieval.py` gains (1) `pubtator3_retrieve` (NCBI PubTator3 entity-index
  search) + `default_retrieve` = Europe PMC → PubTator3 **fallback chain**, so a transient single-source
  outage no longer collapses grounding to internal-knowledge/unverified (the failure mode seen on the
  1.19.0 validation run); (2) **per-subskill query specificity + variations** — `_build_query_variations`
  issues a broad gene∧disease query AND a lens-specific query whose terms come from the LensConfig's own
  `axis_labels` + a curated per-lens map (selectivity → therapeutic window / normal-tissue / IHC), merged
  and deduped by PMID; (3) a `verify_citations` NCBI E-utilities fallback. tumor-selectivity flips its
  `retrieve_fn` from `europe_pmc_retrieve` to `default_retrieve`. VERDICT-INERT / best-effort — spine
  untouched. (Shared-module change; coordinated with the presence literature arc.)

## 1.19.0
- **OPTIONAL `--literature` lane (VERDICT-INERT), Phase-5 fast-follow to 1.18.0.** Wires the shared
  `_skills_common` literature lane (`make_literature_fn`) into `run_wired_skill(literature_fn=…)`, scoped
  to this skill's WIN/DIST/INT/SAFE axes via the `TUMOR_SELECTIVITY` LensConfig (its thesis / axis_labels /
  polarity_note + the claim_vector drive the prompt). Grounded on **live Europe PMC** (`europe_pmc_retrieve`)
  and **PMID-verified** (`verify_citations`), attached as `decision['literature_synthesis']` and fed to the
  `--synthesize` narrator as a corroboration/contradiction lane. `--literature-model` overrides the model.
- Reuses the shared lane READ-ONLY (landed via the tumor-presence literature arc, #965) — NOT
  re-implemented. `--literature`/`--synthesize` need system python + `BEDROCK_AWS_PROFILE=cmp-dev`
  (+ `AWS_PROFILE=cbg` for the card reads). Verdict-inert: the lane runs AFTER the spine and never enters
  `fired`/the resolver/the veto; `selectivity_class` byte-stable.

## 1.18.0
- **Multi-platform corroboration folded into the claim vector (VERDICT-INERT signals-first enrichment).**
  The WIN/INT axes were single-lane (WIN = bulk-RNA comparators only; INT = single-cell only), so the
  claim vector — which the narrator LEADS with — was blind to signals the headline already computes.
  Three quorum-aware additions (`_skills_common/selectivity_claims.py`):
  - **WIN protein quorum.** The two tumor-vs-normal PROTEIN cards (CPTAC TMT + TPHP DIA-MS) now cap WIN
    corroboration when they FAIL to corroborate the RNA window (2 non-significant platforms → `low`; 1 →
    `moderate`; a significant OPPOSITE direction → `low`) and surface it as a WIN conflict. A fully
    corroborating protein layer imposes no cap. Catches the RNA-up / protein-flat false positive
    (EPCAM/COADREAD: CPTAC not-significant + TPHP tumor<normal → the RNA window is not confirmed at protein).
  - **INT spatial quorum.** In-situ `spatial-region-rna-expression` is now an independent arm of the
    malignant-compartment attribution: an agreeing `tumour_enriched_rna` lifts INT corroboration one step
    (single-cell + spatial concur); a `tme_enriched_rna` caps it and flags the conflict.
  - **WIN field-effect signature.** The per-comparator log2FCs (`log2fc_cell_a` adjacent vs `log2fc_cell_c`
    distant GTEx) the collapsed class hides are surfaced as a HIGH-NORMAL-BASELINE FIELD EFFECT note
    (tumor≈adjacent-normal but tumor>distant-normal — a genuine but NARROW window) — the EPCAM/CEACAM
    epithelial-marker archetype.
- **Narrator rule + thesis (LensConfig).** `TUMOR_SELECTIVITY` thesis extended to name the corroboration
  lanes; a new `polarity_note` instructs the synthesis to LEAD with whether independent platforms (protein
  MS + in-situ spatial) corroborate the RNA window, and to distinguish a field effect from a broadly wide
  window. Verified on a live EPCAM/COADREAD `--synthesize` run: the narrative now frames the field effect
  and cites the 2-platform protein non-corroboration.
- **Byte-stability:** all additions gate on the new headline fields (protein-concordance / spatial /
  per-cell log2FC), so they are NO-OPs when those inputs are absent; the CEACAM5/TACSTD2 replay fixtures'
  `selectivity_class` + normal-breadth/stromal-confound veto spine are untouched (resolver golden-stable).
  Corroboration *tiers* on the three curated fixtures are unchanged (already ≤ the protein cap; INT already
  high); only evidence/conflict strings enrich. Full `_skills_common` suite green (1038 passed).
- **PENDING fast-follow (Phase 5, blocked on `feat/presence-literature-and-claims`):** a `--literature`
  lane reusing the shared `_skills_common/literature_synthesis.py` (`make_literature_fn(TUMOR_SELECTIVITY)`)
  lands once that branch merges its `run_wired_skill(literature_fn=...)` + `--literature` dispatcher seam.
  This skill's LensConfig is already literature-ready (its thesis/axis_labels/polarity_note + the enriched
  WIN/INT claim axes are exactly what `build_literature_prompt` consumes). The lane is NOT re-implemented here.

## 1.17.0
- **INT-axis stromal-confound veto (verdict-MOVING, backtest-gated).** `tumor-scrna-celltype-expression`
  is now verdict-driving: its provenance-gated `stromal_confound_class == stromal_confounded` fires the
  `tvn-stromal-confound-veto` rule, and the shared `_skills_common.selectivity_veto` clamp (both engines)
  downgrades a selective axis-A call to the new `selective_but_stromal_confound` — a bulk selective signal
  that single-cell attribution shows is CAF/stroma-driven, not malignant-cell-intrinsic (a false window
  for tumor-cell-targeted modalities; ADC/TCE/CAR/degrader all opposing).
- **Precedence (Option B):** the stromal-confound KILL outranks the normal-breadth window KILL when both
  fire — the more fundamental disqualifier for a tumor-cell modality. Order: stromal-confound > window >
  full-normal > sc-normal > tphp.
- **Provenance-gated:** fires only on a trustworthy cube (curated/inferCNV, entity-specific); a
  phenotype_proxy / multi-entity-pooled cube reads `inconclusive_low_confidence` and cannot move the verdict.
- Backtest passed: RETAIN CEACAM5/EPCAM/CDH17/MSLN (malignant-intrinsic); DOWNGRADE FAP/POSTN/COL1A1/THY1.
  CEACAM5/TACSTD2 replay fixtures byte-stable. Cross-repo: analysis-methods #537 (the field) +
  target-contracts #590 (the rule + `selective_but_stromal_confound` token) landed first.
- Fixed a doc bug: the roadmap referenced `caf_vs_malignant_class == caf_high` (nonexistent); the real
  value is `caf_dominant`.

## 1.14.0
- Added the `tumor-vs-normal-protein-abundance-tphp` card — a VERDICT-INERT RNA→PROTEIN tumor-vs-normal
  corroboration facet, PARALLEL to `tumor-protein-abundance-cptac`, over the TPHP DIA-MS product
  `tphp-tumor-vs-normal-protein-per-cohort-v1` (Xu et al., Nature 2026): 22 carcinoma cohorts, several
  OUTSIDE CPTAC coverage (gallbladder, laryngeal, GIST, testis, thymoma, ...). New reader
  `methods/tphp_tumor_vs_normal_protein/read.py` emits CPTAC-ALIGNED field names
  (`protein_effect_size` / `protein_bh_q_value` / ...), so the existing `_rna_protein_tvn_concordance`
  projection consumes it UNCHANGED; the `_headline` surfaces a namespaced `_tphp` corroboration block.
- Fires NO resolver rung and NO veto clamp — verdict-INERT (absent from `card_resolver_consumption`).
  Added to run.py `CARDS` + `SKILL.md` cards_used/measurement_types_pulled + the 3 parity lists
  (`CARDS`, `SUB_SKILL_CARDS[tumor-selectivity]`, `DIMENSION_CARDS[selectivity]`). NOT wired into the
  certainty corroboration model (kept a pure display facet — the CPTAC sibling remains the sole
  selectivity certainty-corroboration source). New measurement_type `tumor_vs_normal_protein_abundance`
  (target-contracts). Selectivity verdict byte-stable (CEACAM5/TACSTD2 replay guard).

## 1.13.0
- Promoted the `normal-tissue-protein-abundance-tphp` card from DISPLAY-only to a VERDICT-BEARING
  NORMAL-BREADTH veto arm (the 4th). Its new `tphp_normal_protein_liability_class == broad_and_abundant`
  fires `tvn-tphp-broad-abundant-normal-protein-veto`; the shared `selectivity_veto` clamp then
  downgrades an axis-A-selective call to `selective_with_normal_liability` (a SELECTIVITY-PRESERVING
  named liability, NOT the housekeeping KILL — same outcome as the sc-normal critical-organ arm).
- Gated on ABUNDANCE, not DIA detection (Floor-C): `broad_and_abundant` requires a BROAD count of adult
  tissues (>=35) each at/above a global per-tissue abundance floor (product p75). A broadly-DETECTED-but-
  not-broadly-abundant protein (CEACAM5: 63 tissues detected, 30 above floor) reads `detected_not_abundant`
  and does NOT fire — the deliberate DIA-detects-broadly-at-trace correction.
- Applied SKILLS-SIDE (no target-contracts resolver rung; a conjunction the single-rung resolver cannot
  express). Precedence: window > full-normal > sc-normal > tphp-normal-protein (a no-window KILL outranks
  the liability flag). Card moved DISPLAY-ONLY -> `rules_scope`; the 3 parity lists intact. Golden
  snapshot regenerated (selectivity gate rule_ids += the new rule; resolver treats it inert — verdicts
  unchanged, since the clamp is skills-side). Replay fixtures (CEACAM5/TACSTD2) refrozen.
- VERDICT-FLIP DELTA (panel): ZERO flips. CEACAM5/ERBB2/FOLR1/MSLN/EPCAM/TACSTD2 read
  detected_not_abundant/restricted (no fire); DLL3 data_unavailable; GAPDH fires but the window KILL
  outranks it; KRAS fires but is not axis-A-selective (clamp no-op). No approved antigen is downgraded.

## 1.12.0
- Added the canonical HEADLINE layer (verdict + confidence + top-tension), mirroring the merged
  tumor-presence / functional-requirement exemplars (docs/HEADLINE_CONTRACT.md). `_headline` now emits
  `headline_block` — a verdict-INERT projection over the resolved `selectivity_class` + the
  WIN/DIST/INT/SAFE `claim_vector` / `key_signals` (best-effort; a build fault degrades to
  `_enrichment_errors["headline_block"]` and never discards the spine). The `HeadlineSpec` declares the
  four selectivity axes (critical axis = WIN, the tumor-vs-normal window), a curated verdict→phrase map,
  a polarity read (positive = a tumor-selective call, negative = not-selective / broadly-normal KILL
  veto, neutral = gaps + the selectivity-preserving `selective_with_normal_liability` flag, mirroring
  functional-requirement's `pan_essential_killer` treatment), and a `tension_extra` surfacing the
  normal-breadth VETO downgrade as the sharpest cross-cutting caveat.
- `--figures` now also emits the shared `figure_headline_hero.{svg,png,json}` ALONGSIDE the existing
  selectivity evidence-strip hero (`emit_selectivity_hero` unchanged; the two are complementary).
- `headline_block` added to `_SYNTHESIS_FACET_KEYS` so the target-profile fan-out carries the canonical
  headline. Verdict-INERT throughout: `selectivity_class` + the normal-breadth veto spine are
  byte-stable (CEACAM5/TACSTD2 replay guard).

## 1.11.1
- Doc hygiene: documented the Phase S normal-breadth veto SPLIT in SKILL.md — the sc-normal
  critical-organ arm now downgrades to `selective_with_normal_liability` (selectivity-preserving
  named-organ safety flag), distinct from the therapeutic-window arms' `selective_but_broadly_normal`
  KILL; corrected the sc-tumor coverage list (STAD = 8th cube). No behavior change (Phase S behavior
  shipped in _skills_common via #554); this aligns the skill docs + version with it.

## 1.11.0
- Added `tumor-protein-abundance-cptac` as an 11th card — an RNA→PROTEIN tumor-vs-normal
  CORROBORATION arm (verdict-INERT). Projects `protein_tumor_vs_normal_effect_size` +
  `protein_tumor_vs_normal_q_value` (CPTAC per-cohort TMT-MS,
  `cptac-protein-tumor-vs-normal-per-cohort-v1`) plus a derived, spine-inert
  `rna_protein_tvn_concordance` (does the protein direction agree with the RNA call at BH q<0.05?).
  Closes the aggregate card's caveat #5 (RNA selectivity does not guarantee protein selectivity — the
  RNA-up/protein-flat false-positive). Feeds no resolver rung / no clamp: the `selectivity_class`
  verdict spine + normal-breadth veto are byte-identical (guarded by the CEACAM5/TACSTD2 replay).
  `data_unavailable` off the ~10 CPTAC cohorts (honest abstain).

## 1.10.1
- Productionization cleanup (behavior-preserving): consolidated the documentation and removed
  internal edit-tracking labels from all prior edits; moved the inline version history out of
  `run.py` into this file; single-sourced the axis-A "selective" set in `selectivity_hero.py` from
  `selectivity_veto.py`; consolidated repeated per-card summary lookups in `run.py::_headline`. The
  `decision.json` verdict spine + headline are byte-identical.

## 1.10.0
- Surfaced the `sc-normal-celltype-expression` card into the headline
  (`sc_normal_expression_class`, `sc_normal_safety_essential_class`,
  `sc_normal_max_detection_cell_type`/`_fraction`, `sc_normal_n_cell_types_above_20pct`). This card
  was already verdict-driving via the veto, but its descriptive output reached no
  `decision['headline']` consumer. Additive / display-only; the `selectivity_class` spine is unchanged.

## 1.9.0
- Single-cell + in-situ spatial coverage expansion (the tumor side of the selectivity question).
  Composed the tumor single-cell card (`tumor-scrna-celltype-expression`) + two in-situ spatial RNA
  cards (`spatial-region-rna-expression`, `spatial-tumor-normal-colocalization`) + the spatial protein
  card (`spatial-surface-protein-abundance`, which abstains where GeoMx panels are absent). All are
  verdict-inert additive facets: they surface the malignant-cell-intrinsic-vs-stroma + in-situ
  tumour-enrichment + normal-epithelium-adjacency evidence next to the bulk axis-A call, but feed no
  resolver rung and no clamp, so the `selectivity_class` spine is byte-stable. The malignant-vs-stroma
  signal is the intended input for the roadmap stromal-confound veto (see SKILL.md § Roadmap).

## 1.8.0
- The normal-breadth veto clamp was single-sourced into `_skills_common.selectivity_veto` and applied
  by the compose-dashboard engine (`compose_core.resolve_gate_spine`), closing the gap where the
  engine had resolved the raw resolver verdict without the clamp. No verdict change for the standalone
  skill (the clamp already ran here); the bump reconciled the emitted provenance with the SKILL.md
  contract, which had been drifting.

## 1.7.0
- SKILL.md doc-drift fixes (percentile-crossing, sc-normal, purity-confound, and surface-density all
  declared in `cards_used` / `measurement_types`).

## 1.6.0
- Added the absolute surface-density facet (`surface-abundance-density`): Tier-1 calibrated
  copies/cell + floor standing + modality-viability flags. Verdict-inert — below-floor is a modality
  caveat, not a downgrade (CD19 is the counterexample). `selectivity_class` byte-stable.

## 1.5.0
- Added the cell-type-resolved veto arm: `sc-normal-celltype-expression` with
  `sc_normal_safety_essential_class == critical_organ_liability` fires
  `tvn-sc-normal-critical-organ-veto` → downgrade. The third normal-breadth veto arm.

## 1.4.0
- Added the pan-normal window veto arm (`tvn-no-full-normal-window-veto`).

## 1.3.0
- The headline now emits the resolved (post-veto) verdict; added the purity-confound facet.

## 1.2.0
- Opt-in `--synthesize` selectivity-lens narrator.
