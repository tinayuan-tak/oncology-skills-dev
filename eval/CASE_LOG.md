# eval/CASE_LOG.md — the framework's improvement cadence ledger

The persistent, durable ledger of the test-and-iterate loop (Phase 3). Replaces the ephemeral
`~/dev/framework-runs/KNOWN_ISSUES-*.md`. Each entry is a qualitative miss the scorecard's metrics
can't fully encode — a known target the framework gets wrong (or right-for-the-wrong-reason) — with
the deciding axis, the planned fix, and the ratchet that locks the gain.

## How the cadence runs (one turn)

1. **Pick** the top of the build queue (below) — the blind-axis family costing the most known
   targets, from `validate_framework_discrimination.py`'s `blind_axis_load_bearingness`.
2. **Close** the gap (data/method/card/rule across the repos), backtested against the calibration
   set's flip-test anchors **and** its traps (a fix must not regress a target it wasn't aimed at).
3. **Ratchet**: flip the target's calibration `assertion_type` (`known_gap_expected_fail →
   must_not_veto`, or `selectivity_verdict_expected` `should_be`), tighten `_FLOORS` in the
   discrimination harness, and re-run `python eval/run_scorecard.py` to prove the gain with no
   regression. Update this entry's status.

## Build queue — `blind_axis_load_bearingness` (snapshot 2026-09-02)

The framework sees the deciding axis for only **~6% of approved targets** (`approved_deciding_axis_
capture_rate = 0.056`; `blind_rate = 0.727`). Ranked by known targets each missing axis costs:

| # blind | axis family | representative known targets |
|--------:|-------------|------------------------------|
| **13** | **surface_antigen_biology (density / topology / avidity)** | CD19, TROP2, DLL3, FOLR1, CD22, NECTIN4, BCMA, CD20, CEACAM5, HER2, GRIN2D, STEAP1, MUC13 |
| 7 | synthetic_lethal / partner_conditional | PARP1, SMARCA2, MARK2_3, PELO, SKP2, CDS2, CNDP2 |
| 6 | cell_state_window / pan_essential_buffered | BCL2, XPO1, PSMB5, CDK4_6, RBM39, RIPK1 |
| 3 | modality_feasibility (degrader / glue / neomorph) | MLLT1_3, KAT2A_B, CNDP2 |
| 1 | IO / TME / immune_context | ADAR1 (dangerous FP) |
| 1 | captured_lane (mutation / pocket) | FLT3 |

Dangerous false-positives to keep pinned: ADAR1, CLDN18.2_LRRC15, EGFR_cMET_VEGF.

---

## Open cases

### CASE-001 — surface-antigen TOPOLOGY killer — DEMOTED by live data (2026-09-02)
- **Original hypothesis:** add a multi-TM/ion-channel topology-killer to surface-modality-fit,
  subordinate to clinical precedent — flip GRIN2D (calibration said `framework_abstains_correctly`,
  "highest-value buildable E2 fix"), guardrail STEAP1 (the clinically-de-risked 6-TM trap).
- **LIVE BASELINE OVERTURNS IT** (emitted GRIN2D/STAD, STEAP1/PRAD, HER2/BRCA, DLL3/SCLC):
  - `GRIN2D` → **already `veto`** (reco=veto), driven by `normal-tissue-essential-bite-killer`
    (surface verdict `tce_unsafe_normal_liability`). It is NOT abstaining — the calibration label is
    **stale**. A topology-killer adds ~no value (already vetoed) and its outcome is already correct.
  - `STEAP1` → **`None` / safe**, carried by a POSITIVE `pmhc_tce_supported`
    (`pmhc-iedb-tcell-validated-tce-supportive`). A blind topology-killer risks flipping STEAP1 to
    veto — the exact documented trap — for no GRIN2D gain.
  - `HER2` → `None`, validated_lane, scored hit (deciding axes captured on genomic/tractability, not
    surface — its home turf).
- **Decision:** DO NOT build the topology-killer now (low value + regression risk). Instead:
  1. **Fix the stale calibration labels** (a ratchet action): GRIN2D `framework_abstains_correctly`
     → it now vetoes (right outcome, via normal-tissue not topology — record as `agree`/adjacent-axis);
     STEAP1 note it is correctly safe via pMHC. This keeps the truth-set honest — the point of the loop.
  2. Re-target the surface_antigen_biology gap to **antigen DENSITY capture** (CASE-004), the axis the
     approved ADC targets (FOLR1 `E2_antigen_density_CDx`, TROP2, CD22) actually decide on and where
     the density card returns `insufficient`.
- **Status:** DEMOTED. Superseded by CASE-004 as the first build turn.

### CASE-005 — biologics-modality surface antigens read as HOLD — RESOLVED as a BACKTEST fidelity bug (NOT a gate bug)
- **Initial live read:** DLL3/SCLC, FOLR1/OV, TROP2/BRCA all `forced=hold` via `dependency:non_dependent`
  despite `surface_modality=adc_preferred`. Looked like the gate using the wrong necessity criterion.
- **VERIFY-FIRST OVERTURNED IT (the CASE-001 lesson, again):** re-emitting WITH the profile's curated
  modality — `DLL3 --modality bite_tce`, `FOLR1 --modality adc` — the gate FULLY SUPPRESSES
  `dependency:non_dependent` (branch B `modality_scoped`) and the safety concern (`exists_safe_modality`)
  → "no gate fired" (unforced; LLM free to nominate). **The framework is working as designed.**
- **Mechanism (`tp_gates.py::_suppressed_gate_hits`):** with an explicit biologics `--modality`, branch B
  clears the non_dependent veto; WITHOUT a declared modality, branch C only DOWNGRADES it to `hold` —
  deliberately conservative (don't fully nominate a non-dependency target until the modality that makes
  it work is committed). Correct behavior.
- **The real bug was in the HARNESS:** `run_known_target_panel.py` emitted modality-BLIND, so surface
  antigens hit the conservative no-modality `hold` and manufactured false silent-FNs. **Fixed**:
  `emit_packages` now passes `--modality <profile.modality>` per target (reference_profiles carry it).
- **Outcome:** no verdict-moving change (a gate "fix" here would have REGRESSED correct conservative
  behavior). This is the loop catching a false alarm before it damaged the framework — the whole point
  of scoring fresh output + verify-before-build.
- **Status:** RESOLVED (harness fix in this PR). Re-emit with modality confirms DLL3/FOLR1/TROP2 clear.

_Lesson (now applied 3×): every candidate turn gets a live-emit verification BEFORE any code changes.
Curated labels drift; the collapsed word hides modality-conditioning; verify against the real output._

### CASE-004 — antigen-DENSITY capture (separate axis-capture item, lower priority) — QUEUED
- **Axis family:** surface_antigen_biology — antigen density (FOLR1 `E2_antigen_density_CDx` etc.).
  NOTE (live-refined): for FOLR1/TROP2 the surface verdict is already `adc_preferred` — density is NOT
  the blocker there (CASE-005's dependency gate is). Density remains a genuine deciding-axis-CAPTURE
  gap (the framework doesn't credit the quantitative density that gates a CDx), just not the lever for
  these specific holds. Lower priority than CASE-005.
- **Candidate fix (lowest-effort, per data assessment):** `antigen-prevalence-protein` card is
  **buildable from the EXISTING catalog** (`cptac-protein-tumor-vs-normal-per-sample-v1`, no ingestion)
  — derive a per-cohort protein-prevalence aggregation (threshold per aliquot → fraction per cohort),
  reader `protein-prevalence-aggregator`. See the PR#489 data-needs assessment in the plans archive.
- **Ratchet:** once density is credited, flip the FOLR1/TROP2 `honest_blind` labels toward a captured
  deciding axis; tighten `approved_deciding_axis_capture_rate` floor (currently 0.056).
- **Status:** QUEUED — verify against a fresh FOLR1/TROP2 emit first (both need a solid cohort; FOLR1/OV,
  TROP2/BRCA are runnable).

### CASE-002 — MET-LUAD METex14 — veto RESOLVED (stale); residual is SIGNAL-VECTOR fidelity, not a veto
- **Original premise (KNOWN_ISSUES-2026-08-26):** MET-LUAD → veto (`dependency:non_dependent` +
  coverage gaps); a false-negative for an approved LUAD target.
- **VERIFY-FIRST (live emit 2026-09-02):** MET/LUAD **no modality → "no gate fired"** — `non_dependent`
  suppressed via `context_escape` (branch A), safety via `exists_safe_modality`. **The veto is gone**
  (fixes landed since 08-26). `--modality small_molecule` → `hold` via `safety:highly_constrained_
  safety_concern` (gnomAD WT-loss) — DEFENSIBLE for a WT-kinase-inhibiting TKI, not an obvious bug.
- **The one clearly-real residual = genomic mischaracterization (signal-vector fidelity):**
  `genomic_alteration → missense_dominant_pattern`, but MET's LUAD driver is METex14 splice-SKIPPING,
  invisible to the missense/hotspot-centric genomics layer. Does NOT change the nomination (gate
  already clears MET); it mis-states WHY MET matters — a substrate defect a reasoner would be misled by.
- **Fix (if pursued):** derive a per-sample/cell-line METex14 classifier (MAF splice donor/acceptor at
  the exon-14 boundary + CIViC) feeding `mutation-stratified-dependency`/`mutation-hotspot-frequency`
  as an alteration class beyond missense-hotspot. A data+method+card build (analysis-methods +
  data-catalog + target-contracts), NOT a nomination-gate change. Detail in the 08-26 issue doc.
- **Status:** veto RESOLVED. Residual genomic-fidelity fix QUEUED as a real (non-false-alarm) build.

### CASE-007 — MET-LUAD differentiation co-occurrence reads `strong_cooccurring` vs literature MUTUAL-EXCLUSIVITY — TRIAGED (literature-discordance loop, 2026-09-07)
- **Surfaced by:** the literature↔deterministic discordance loop (`eval/harvest_literature.py` →
  `eval/build_discordance_ledger.py`, MET/LUAD, scope=gating). Top row = **calibration_gap** (MET is
  a `known_gap_watchlist` target): `differentiation-landscape` verdict `strong_cooccurring`
  (`driving_rule_id: cooccurrence-strong-supportive`), lane `agreement_vs_omics: contradicts`, **2/2
  verified citations** (PMID 42650153, 42442843). NOTE this is a NEW axis, distinct from CASE-002 —
  the METex14 genomic fix has landed (`genomic_alteration → splice_exon_skip_driver`).
- **Literature claim (verified):** de-novo MET drivers (exon-14 skipping, MET amplification) in LUAD
  are canonically **mutually exclusive** with EGFR/KRAS/ALK/ROS1 at diagnosis; MET co-occurrence is
  chiefly an **acquired EGFR-TKI bypass** (secondary MET amplification), i.e. a treatment-context /
  temporal association, not a same-clone co-driver interaction.
- **Root cause (candidate, real):** `cooccurrence_fisher_pancohort` (differentiation-landscape's
  co-mutation method) pools cross-sectional TCGA MC3 + GENIE samples and cannot separate (a) de-novo
  same-clone co-mutation from (b) acquired/treatment-context bypass co-occurrence. For MET/LUAD the
  pooled Fisher reads `strong_cooccurring` where the de-novo biology is mutual-exclusivity — a temporal
  / lineage-subtype confound, not a wrong count. Same *family* as the pooled-signal caveat that already
  restricts pooled Fisher to the panel-intersect gene set, but the confound here is TEMPORAL, not panel.
- **Classification:** REAL substrate-fidelity gap (not lane noise): verified, mechanistically grounded,
  and it mis-states the co-mutation *interpretation*. Does NOT flip the MET nomination (differentiation
  is a landscape/hypothesis axis, not a gate) — like CASE-002 it is a signal-vector fidelity defect.
- **Proposed fix (propose-only; cross-repo, NOT in this PR):**
  1. *method* (analysis-methods `cooccurrence_fisher`): a treatment-naive / diagnosis-only stratum
     (restrict the pooled cohort to treatment-naive samples where annotation exists), and/or
  2. *card annotation* (target-contracts differentiation card): a verdict-INERT
     `cooccurrence_temporal_context_caveat` that flags a co-occurrence as candidate **acquired-bypass**
     when the partner is a known first-line-TKI target (EGFR/ALK/ROS1) and the target is a known bypass
     (MET-amp) — mirroring the existing 3-tier confidence-caveat pattern. Precedence/resolver UNCHANGED
     (the interpreter only orders fired rule-IDs; this is a label/method concern).
- **Proposed ratchet (for the target-contracts owner):** add a `differentiation` expectation to the
  MET `known_gap_watchlist` entry (co-occurrence should read mutually-exclusive / bypass-context, not
  `strong_cooccurring`) so the fix is regression-locked by `run_scorecard.py`. Cannot be set from this
  eval/-scoped PR (different repo) — flagged here.
- **Status:** TRIAGED / CONFIRMED real. Method+card fix QUEUED (cross-repo). This entry is the
  propose-only output of the discordance loop's first triage; no gate/verdict change.

### CASE-010 — full-sweep ledger FINISH: remaining 14 calibration_gap rows triaged (2026-09-07)
Disposition of every remaining calibration_gap row after CASE-007/008/009 (the full 37-pair sweep
ledger `~/dev/discordance_full_sweep_ledger_2026-09-07.json`). One clean fix + 13 dismiss/defer.
- **FIXED (verdict-INERT):** `differentiation-landscape` KRAS/COADREAD SURVIVAL — omics
  `expression_high_better_survival` vs literature KRAS-*mutation*→worse-outcome. Generalizable
  EXPRESSION-vs-MUTATION direction confound → `_survival_direction_scope_caveat` (v1.12.0): fires on a
  directional expression-survival class, clarifies the axis is mRNA-expression↔survival, not
  mutation-outcome. Target-agnostic; verdict/golden/replay byte-stable.
- **DISMISSED — literature CONCORDANT with the verdict (lane over-flagged a sub-axis):**
  - functional-requirement STEAP1/prostate, CEACAM5/NSCLC, DLL3/SCLC (all SEL, `non_dependent`): each is a
    lineage-restricted surface ANTIGEN (biologics target), NOT a genetic dependency — `non_dependent` is
    CORRECT; literature agrees. tumor-selectivity DLL3/SCLC (`selective_with_normal_liability`): literature
    cites DLL3's low normal expression = good therapeutic index → concordant. surface STEAP1/prostate FIT
    (`pmhc_tce_supported`) + FOLR1/OV TOPOLOGY (`adc_preferred_tce_unsafe`): verdicts already match the
    surface biology the literature describes.
- **DISMISSED — `data_unavailable` omics (coverage gap; cannot "contradict" an absent signal):**
  differentiation CHEK1/COADREAD (SURVIVAL), HIF2A/RCC (NODE); mechanism-and-pharmacology TROP2/TNBC
  (PERTURBATION — ADC biologics), HER2/BRCA (PHOSPHO — HER2 is a validated phospho-RTK; real coverage gap,
  DEFERRED: wiring a phospho card is a data build); mechanism XPO1/MM (`partial` — cautious, honest).
- **DEFERRED — real but weak/needs-data:** surface NOX1/CRC SAFETY (`pmhc_tce_supported`) — NOX1 is broadly
  normal-expressed (colon epithelium/vasculature), a TCE safety concern; only 1 verified cite + would need a
  normal-expression flag the surface skill's normal-tissue leg should carry. QUEUED as a data-coverage item.
- **Meta:** of 32 calibration_gaps, **4 real fixes** (CASE-007 + 008 + 009-caveat + 010-caveat) and
  **~10 dismissed as concordant/scope + ~4 deferred-for-data** + 128 staleness→atlas. Ledger FINISHED.

### CASE-009 — on-target-safety PHARMACOVIGILANCE `no_warning` vs literature on-target toxicity — MOSTLY SCOPE-MISMATCH; scope caveat added (full-sweep, 2026-09-07)
- **Surfaced by:** the full 37-pair sweep — the on-target-safety-liability calibration_gap cluster (4):
  BCL2/CLL_AML, PSMB5/MM, XPO1/MM, PARP1/OV. Each: PHARMACOVIGILANCE axis `drug_warning_class=no_warning`
  (signal=absent), literature `agreement=contradicts` (≥2–3 verified cites) documenting real on-target
  dose-limiting toxicity (venetoclax→TLS; PARPi→cytopenias/MDS; bortezomib→neuropathy; selinexor→cytopenias).
- **Triage — NOT a framework error (unlike CASE-007/008):**
  - The OVERALL verdict for all 4 is already `highly_constrained_safety_concern` (the strongest safety call,
    from gnomAD WT-constraint) — the framework is NOT missing the safety risk; it is maximally conservative.
  - The flagged axis (PHARMACOVIGILANCE) is BY DESIGN a coarse FDA black-box/withdrawn detector (OT
    drug-warning ⋈ MoA + OnSIDES-BOXED), explicitly verdict-INERT context that "orients, never HOLDs" and is
    left out of the HeadlineSpec.axis_keys. `no_warning` vocab = "engaging drugs exist but none warned
    (measured-negative)" — distinct from `no_targeted_drug` (coverage gap).
  - So the literature "contradiction" is a SCOPE mismatch: dominant mechanism-based dose-limiting toxicities
    (TLS, cytopenias, neuropathy) are frequently NOT boxed warnings, so they lie outside this axis's scope.
    The axis is honest within its declared scope; the verdict is correct + conservative. → the 4 rows are
    DISMISSED as bugs.
- **The one real (target-agnostic) honesty improvement — LANDED:** `_pharmacovigilance_scope_caveat`
  (on-target-safety-liability v1.18.0) fires ONLY on `drug_warning_class=no_warning`, clarifying that this
  means "no OT-registered FDA warning among engaging drugs," NOT absence of on-target toxicity — so a reader
  cannot misread the measured-negative as "safe." No curated list (fires on the axis state itself, unlike the
  CASE-007/008 crosswalks); verdict/resolver/golden/replay byte-stable (safety golden 2/2; 3 new tests + 25
  sibling tests green). Added to `_SYNTHESIS_FACET_KEYS`.
- **Meta:** demonstrates the loop's triage DISCIPLINE — a verified-literature calibration_gap that is a
  scope/annotation clarification, not a verdict bug. Not every discordance is a defect.
- **Status:** TRIAGED → mostly scope-mismatch (dismissed as bugs) + one verdict-INERT scope caveat landed.
  Deeper (deferred): a broader on-target-toxicity signal beyond OT boxed-warnings would need a new data
  source (e.g. per-drug ADE severity ⋈ target) — out of scope for this axis's coarse OT feed.

### CASE-008 — tractability-small-molecule credits SM tractability from a BIOLOGICS approval — FIXED verdict-INERT (full-sweep, 2026-09-07)
- **Surfaced by:** the FULL 37-pair calibration sweep (`eval/harvest_literature.py` →
  `build_discordance_ledger.py`; ledger `~/dev/discordance_full_sweep_ledger_2026-09-07.json`). The
  single largest calibration_gap cluster: **13 of 32** rows are `tractability-small-molecule`.
- **Triage — the 13 split into THREE mechanisms (not one):**
  1. **Biologics-approval → SM inflation (the fix target):** DLL3, STEAP1, FOLR1, NECTIN4, CEACAM5 — the
     DRUG axis credits SM tractability from an approved BIOLOGIC (tarlatamab TCE; mirvetuximab / enfortumab
     vedotin / tusamitamab ADCs; STEAP1 TCE). Verified lit (≥2–4 cites) states every approved agent is a
     biologic and no approved SM binder exists.
  2. **PRISM coverage false-NEGATIVE (opposite direction):** HER2/BRCA reads `chemically_unhit` despite
     approved SM TKIs (lapatinib/neratinib/tucatinib) — a chemical-genetic under-credit, NOT inflation.
     Separate gap (PRISM/ChEMBL coverage), not addressed here.
  3. **Approval-status / indication-floor noise:** IDO1 (SM-directed but not approved), NLRP3 (heme floor
     under-credit), XPO1 DEGRADER axis, KIF11 (arguably honest `discordant`). Not modality mismatch.
- **Root cause (mechanism 1):** the DGIdb `known-drug-tractability` card + `dgidb_drug_gene` method are
  **modality-BLIND** — `has_approved_drug` tabulates the approved biologic against the gene with no drug-TYPE
  field. So a biologics-approved antigen can fire the DRUG rung
  (`known-drug-approved-antineoplastic-sm-supportive` → `chemically_active`) or otherwise read as
  SM-druggable. (`structurally_ligandable` for DLL3/STEAP1 comes from the STRUCTURE card, independent of the
  drug annotation — the DRUG-axis over-credit is the modality-mismatch tell either way.)
- **Fix (LANDED, verdict-INERT):** `_sm_modality_mismatch_caveat` in `skills/tractability-small-molecule/`
  (v3.10.0) — fires for a curated biologics-approved antigen (`_BIOLOGICS_APPROVED_NONSM`, seeded from
  `target-contracts/vocabularies/biologics_precedent_targets.yaml`: DLL3/STEAP1=tce, FOLR1/NECTIN4=adc,
  CEACAM5=adc_tce, …) WHEN `has_approved_drug` is true, naming the biologic modality and that the DRUG
  annotation is NOT SM-tractability evidence. Mirrors the in-skill `_directness_caveat` (annotation-vs-direct)
  — this is annotation-vs-MODALITY. Verdict/resolver/golden/replay **byte-stable** (37 tests green; golden
  2/2); target signature-introspected in `_headline`/`_synthesis_facet`. Retires the display-inflation for
  the 5-target cluster at once.
- **Why NOT a verdict flip (yet):** the honest verdict-moving fix (demote biologics-only SM tractability)
  needs a real drug-modality field on the card + method (DGIdb has none) → curated crosswalk + resolver/rule
  change + golden regen + a backtest that flips the BRAF replay fixture — a cross-repo build. PROPOSED as the
  deeper follow-up; the caveat is the landable, byte-stable first step.
- **Proposed ratchet / follow-ups:** (i) wire a live reader for `biologics_precedent_targets.yaml` (replace
  the curated in-run.py set); (ii) verdict-moving modality-aware DRUG signal (cross-repo); (iii) the HER2
  PRISM-coverage false-negative (mechanism 2) is a distinct queued gap.
- **Status:** FIXED (verdict-INERT caveat). Deeper verdict-moving fix + reader-wiring QUEUED.

### CASE-006 — CNDP2-COADREAD neomorphic-GoF silent-FN — CONFIRMED (full-panel, 2026-09-02)
- Full-panel sweep flagged the one genuine fresh miss: `CNDP2/COADREAD [small_molecule] → veto`
  (`dependency:non_dependent`). CNDP2 is an `active` program; its deciding axis is a **neomorphic
  gain-of-function** the framework can't see (whole-gene KO ≠ neomorphic-enzyme inhibition), so it
  reads non-dependent and hard-vetoes. A real silent-FN (same family as the IDH1 GoF-driver-downgrade
  branch D in tp_gates, but CNDP2's GoF isn't captured genomically to trigger it).
- **Status:** CONFIRMED real gap (genomic/GoF fidelity). Distinct from the demoted false alarms —
  this one survives a live re-run. Queued alongside CASE-002 as a genomic-fidelity build.

### Full-panel baseline (2026-09-02) — 22/26 emitted (4 timeouts), scored 12/13 (acc 0.923)
- Ran `run_known_target_panel.py --emit` over all 26 in-scope profiles (modality-aware). 22 OK; 4
  TIMEOUT at 600s (ADAR1, CD20/DLBC, HIF2A, SCD1 — heavier targets/indications; bump `--timeout` or
  investigate). Recommendation-gate: **12/13 hit (0.923)** over scored known targets; the lone miss is
  CASE-006 CNDP2. Signal ledger: avg 29.9 positive / 33.1 negative per target; **54 negatives surviving
  vs 72 suppressed** (modality/context-cleared). Deciding-axis capture: partial 14 / captured 6 / blind 1.
- **Instrument fix (this PR):** the `_drift` heuristic wrongly flagged RBM39 (`validated_lane` but
  outcome=`declined`, correctly vetoed) as a REGRESSION. Now gated on a POSITIVE outcome — the
  full panel catching a flaw in its own instrument.

---

## Meta-finding (2026-09-02) — the nomination GATE is healthy; remaining work is SUBSTRATE FIDELITY

Four consecutive cases (CASE-001, -004, -005, -002) that looked like nomination-gate false-negatives
**dissolved on a live re-run** — the documented 08-26/08-31 vetoes were fixed by intervening work
(context_escape, modality_scoped suppression, exists_safe_modality). The gate is in good shape. The
genuine remaining gaps are **signal-vector FIDELITY** — the framework reaching the right call but
mischaracterizing WHY (MET read as missense-dominant; approved surface antigens under-credited on the
deciding axis; `approved_deciding_axis_capture_rate = 0.056`). This is exactly the axis the
signal-vector backtest measures, and it's where the cadence should aim next. See
[[project_substrate_sufficiency_improvement_loop]].

### CASE-003 — DLL3-SCLC holds on gate-C despite approved TCE — REPORTED
- Fresh run: `hold` forced by `dependency:non_dependent` (gate C), though DLL3 is an approved SCLC
  TCE target (tarlatamab). A surface-antigen (A2 aberrant-surface-trafficking) target, not a genetic
  dependency — the framework under-reads even RNA presence. Same surface_antigen_biology family as
  CASE-001; the deciding axis (aberrant surface trafficking) is blind. `honest_blind` in the
  calibration set — not scored as failure, but the exemplar of why the #1 axis matters.
- **Status:** REPORTED (folds into the surface-antigen program; no standalone fix).

---

## Closed cases

_(none yet — first turn lands under CASE-001)_
