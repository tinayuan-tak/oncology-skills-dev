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

### CASE-016 — Takeda ONC composed backtest Phase 3 (surface/biologics): the gate's decision-attribution is dependency+safety-dominated; surface biology MODULATES but never DECIDES (2026-09-08)
- **Surfaced by:** the per-axis backtest (CASE-015 tool) over the surface/biologics cohort (14 targets, composed
  `--verdict-only`). **Axis-attribution match = 0.0 (0/14)**: the ground-truth `deciding_axis` is `surface`
  (E2/density/topology) for all 14, but the framework's composed gate DECIDES on `dependency` (13) or `safety`
  (ERBB2). Combined with Phase 2 (dependency cohort, 0.18 — decided on `safety` 9/11), the unified picture:
  **the composed nomination gate is dependency+safety-attribution-dominated across the whole portfolio.**
- **Determination — NOT hard-veto false-negatives; conservative-by-design (mechanism understood):** the surface
  biology DOES participate — for an approved ADC antigen (DLL3/FOLR1/NECTIN4/CEACAM5/TACSTD2) the dependency
  `non_dependent` VETO is DOWNGRADED to a HOLD via `biology_axis_downgrade` (surface_verdict=adc_preferred_*), and
  the safety concern is suppressed by `exists_safe_modality` (adc/antibody channels). So the framework does NOT
  hard-veto biologics winners (consistent with the intended gate-C modality-scoping) — but it lands on HOLD, not
  GO, because the DECIDING axis is still the intracellular `dependency: non_dependent` (a surface antigen is not a
  genetic dependency). CD22 fully passes (context_escape: has_experimental_sl_partner). GRIN2D veto = correct
  true-negative (ion-channel topology). NOX1 advanced→veto is the one worth a second look.
- **The structural point (design question, NOT a bug):** the gate PRECEDENCE is dependency-veto + safety-hold
  first; the surface/biologics thesis can only DOWNGRADE those, never become the DECIDING axis. So the framework
  structurally cannot emit a clean GO on a pure surface antigen — at best `hold: surface-viable non-dependency`.
  For a framework meant to nominate biologics targets, whether surface should be able to DECIDE a GO (not just
  downgrade) is a product/gate-policy decision — DEFERRED to the user (verdict-moving, mirrors the pan-essential
  + modality-conditional-safety adjudications: the conservative hold is the safe default).
- **Unified backtest conclusion (Phases 1-3):** the composed gate avoids hard-veto false-negatives (via
  downgrades/suppressors/context-escape) but is calibrated CONSERVATIVE — it lands on HOLD rather than GO for most
  known advanced/approved targets because each has some non-clean axis (dependency non_dependent, safety WT-loss).
  The per-axis backtest quantifies WHY per target. This is calibrated conservatism, not a defect.
- **Tool fix (this PR):** `eval/backtest_per_axis.py` family-mapper bug — the `window` token in the dependency
  pattern mis-mapped surface descriptors (`B2_window_E2_density`, `F_restricted_GI_window`) to dependency; surface
  is now matched FIRST. + 4 HGNC→ref-key aliases (ERBB2→HER2, MS4A1→CD20, TNFRSF17→BCMA, TACSTD2→TROP2).
- **Phase 4 DONE (remainder/mixed cohort, 18 single-gene targets scored; 8 multi-gene/non-gene compounds —
  CLDN18.2_LRRC15, CTHRC1_PDL1, EGFR_cMET_VEGF, KAT2A_B, MLLT1_3, POSTN_PDL1, panRAF_MEK_FAK, CA19_9 — not
  single-target runnable; SCD1 timed out, 1 skip):** axis-attribution match = **0.5 (9/18)** — higher because
  this cohort is pan-essential/dependency-heavy. MATCHES = the pan-essential DECLINED negatives (CHEK1/KIF11/
  PLK1/RBM39/WEE1/MMP9 correctly veto on `dependency`; AURKA/MCL1 correctly hold on `safety`) — right call, right
  axis. MISMATCHES = immune/IO/genomic theses (ADAR/IDO1/NLRP3/RIPK1/EGFR/FLT3/WRN decided on safety or dependency,
  not their actual axis).
- **★ UNIFIED 4-PHASE RESULT: axis-attribution match ≈ 0.26 (11/43 scored)** — Phase 2 (dependency/SL) 0.18,
  Phase 3 (surface/biologics) 0.0, Phase 4 (mixed) 0.50. **The composed gate's decision axis is systematically
  `dependency`+`safety`; the surface / immune-TME / genomic-context theses MODULATE (downgrade vetoes, get
  suppressed) but rarely DECIDE.** Calibrated-conservative: strongest on pan-essential negatives (correct
  true-negatives on the right axis), avoids hard-veto false-negatives (downgrades/suppressors/context-escape), but
  lands HOLD-not-GO for validated targets whose thesis lives on a non-dependency/non-safety axis. This is the
  attribution bias the per-axis backtest (eval/backtest_per_axis.py) was built to quantify — not a defect, a
  calibration/gate-precedence property.
- **Status:** Takeda ONC composed backtest COMPLETE (phases 1-4). OPEN (user call, verdict-moving): GO-on-surface
  gate-policy (should surface/immune theses be able to DECIDE a GO, not just downgrade?); context-conditional-
  safety suppressor (CASE-015); NOX1 advanced→veto re-check; SCD1 re-run (lone timeout).

### CASE-015 — Takeda ONC composed backtest: the nomination is SAFETY-axis-dominated (per-axis attribution) — mostly DEFENSIBLE + a per-axis backtest tool (2026-09-08)
- **Surfaced by:** the Takeda ONC backtest (c). Re-ran the composed target-profile (`--verdict-only`, 90s/target
  vs ~20min with default grounding+Bedrock) over the dependency/SL cohort, then scored it PER CLAIM-VECTOR AXIS
  (`eval/backtest_per_axis.py`) — consistent with the ledger-v2 claim-vector-axis design (not verdict-vs-outcome).
- **Finding — axis-attribution mismatch:** on the 11-target dependency/SL cohort the framework DECIDES on the
  `safety` axis 9/11 times, but the ground-truth `deciding_axis` (reference_profiles) is `dependency` — **axis-
  attribution match = 0.18 (2/11)** (only PSMB5/XPO1 match: dependency=pan_essential veto). The dependency FNs we
  rescued (SMARCA2→partner_conditional_dependent, EPAS1, MARK2/3, CDS2/SKP2/CDK4/6) all read non-veto on the
  dependency axis, but the composed call is HELD by `safety` (`highly_constrained_safety_concern` /
  `normal_tissue_protein_safety_concern`). The verdict-level backtest says "held"; the per-axis backtest says
  "held on a DIFFERENT axis than the program's actual thesis."
- **Determination — mostly DEFENSIBLE, NOT a bug (same shape as the pan-essential adjudication):** the composed
  gate ALREADY has a modality-conditional safety suppressor (`exists_safe_modality`, tp_gates.py) — it correctly
  SUPPRESSES the safety hold when a WT-sparing modality exists (BCL2→`safe_channels:[small_molecule]`→pass; KRAS,
  CTNNB1 pass) and HOLDS when none does (SMARCA2 advanced as a DEGRADER = destroys WT SMARCA2 → real WT-loss risk;
  its window is SMARCA4-mutant SELECTIVITY, a dependency/context argument, not a WT-sparing modality). Holding a
  full-KO/degrader of a gnomAD-constrained gene pending a demonstrated window is a defensible conservative call.
- **Narrow residual (debatable, deferred, verdict-moving):** `exists_safe_modality` keys on WT-SPARING modality;
  it does NOT model CONTEXT-CONDITIONAL normal-tissue tolerance (e.g. SMARCA4-intact normal cells tolerate SMARCA2
  loss; VHL-intact normal cells have little HIF2α to inhibit). A "context_conditional_safety_window" suppressor
  could soften these holds — but it loosens a safety gate on constrained genes (false-positive risk). DEFERRED to
  a user design decision; the conservative hold is the safe default.
- **Tool landed:** `eval/backtest_per_axis.py` — reusable per-claim-vector-axis backtest scorer (axis-attribution
  match + per-axis capture + outcome polarity) over composed `nomination.json` files vs reference_profiles. Run:
  `python eval/backtest_per_axis.py --nominations '<dir>/*/nomination.json' --calibration-set <cal.yaml>`.
- **Also queued (separate defect):** the composed `--emit` evidence_package envelope FAILS
  `evidence_package.schema` validation for the `translational_readiness` + `literature_context` claim-vectors
  (6 errors; non-fatal — target_profile.md/nomination.json still emit). A real schema/emitter mismatch to fix.
- **Status:** composed backtest phases 1-2 DONE (dependency/SL cohort, per-axis scored). Phases 3 (surface/
  biologics) + 4 (remainder) + the context-conditional-safety extension are OPEN (user's call).

### CASE-014 — functional-requirement EPAS1/HIF2A/RCC `non_dependent` vs belzutifan-validated VHL-conditional dependency — REAL biomarker-conditional FN — ✅ RESOLVED (verdict-moving fix landed, 2026-09-07)
- **Surfaced by:** the CASE-011 re-harvest de-masking (`~/dev/discordance_full_sweep_ledger_2026-09-07.json`;
  the HIF2A→EPAS1 alias fix removed the phantom data-unavailable and exposed the real signal). functional-requirement
  `EPAS1 | RCC` reads `sub_verdict = non_dependent` (driving `non-dependent-killer`); claim `DEP = absent` (moderate),
  `SEL = absent` (high), `COND = unmeasured`. Literature (verified) contradicts DEP: EPAS1/HIF-2α is THE canonical
  oncogenic driver of VHL-deficient ccRCC, and belzutifan (approved HIF-2α antagonist) is on-mechanism clinical
  validation; the COND lane assertion is explicit — "HIF2α addiction is CONDITIONAL on VHL loss."
- **Determination — a REAL biomarker-conditional dependency FN (not noise, not a caveat), but the omics is HONEST:**
  the framework reads `non_dependent` because 2D pan-line DepMap CRISPR/RNAi genuinely under-represents this
  dependency — EPAS1/HIF-2α addiction is in-vivo / VHL-loss-conditional, and the partner-conditional `COND` axis is
  UNMEASURED for EPAS1×VHL. Critically, ccRCC is near-uniformly VHL-null, so there is **no in-panel VHL-WT contrast**
  to compute a conditional stratum from — the conditional lane cannot be built from the RCC-restricted panel alone
  (it needs a pan-cancer VHL-status stratification). Same CLASS as [[CASE-010]] PARP1/COND (HRD-conditional) and the
  known_gap_watchlist entries MET/LUAD (`biomarker_conditional`, METex14) + SMARCA2/LUAD (`partner_conditional_sl`).
- **Not a resolver-rule bug:** `non-dependent-killer` firing on a flat pan-line distribution is correct behavior;
  the gap is a MISSING conditional-dependency measurement, not a mis-firing rule. Literature stays OUT of the verdict.
- **Ratchet (LANDED):** target-contracts PR #676 — a `known_gap_watchlist` entry `EPAS1` (keyed by HGNC per the
  [[CASE-011]] alias lesson), `dependency_mode: biomarker_conditional`, `biomarker: VHL_loss`,
  `assertion_type: known_gap_expected_fail`, `expected_verdict_current: non_dependent` /
  `expected_driving_rule_current: non-dependent-killer`, flip target
  `expected_after_vhl_conditional: [biomarker_stratified_dependency, conditional_dependent, insufficient]`.
  `measured: false` (reasoned-only) — the live `epas1_rcc.functional-requirement.json` snapshot needs a cbg `--emit`;
  upgrade to `measured: true` when captured. DISTINCT from the pre-existing `reference_profiles` HIF2A/RCC anchor
  (which frames the OVERALL nomination as `clinical_precedent`/`license_blocked` honest_blind — the Cortellis wall);
  this pins the dependency-axis FN specifically.
- **✅ FIX LANDED (verdict-moving) — the deferred data-build turned out to already exist:** the conditional lane the
  gap needed is the existing `depmap_partner_conditional_dependency` method — it just lacked an `EPAS1→VHL` map entry.
  A live DepMap 26q1 probe over the VHL-LoF stratum confirmed the signal is REAL and powered:
  **delta -0.066 Chronos, mann-whitney q 2.1e-3, rank-biserial 0.32, n=28 VHL-LoF / 1510 neutral →
  `partner_conditional_moderately_dependent`** (moderate via the rank-biserial arm; modest absolute delta, consistent
  with HIF-2α addiction being context/in-vivo-heavy in 2D CRISPR). Adding `EPAS1: [{partner: VHL,
  deficiency_type: lof_mutation}]` to `partner_map.yaml` (analysis-methods PR #582) was sufficient — the dependency
  resolver already rescues `partner_conditional_moderately_dependent` ABOVE the `non_dependent` rung, so NO resolver
  change was needed. Live functional-requirement re-run (post-#582) confirms the flip:
  **`non_dependent` → `partner_conditional_dependent`** (driving `partner-conditional-moderately-dependent-supportive`).
- **Ratchet — flipped to `must_not_veto` measured:true (contracts PR #677):** the CASE-014 `known_gap_watchlist` EPAS1
  entry now asserts EPAS1/RCC must NOT hit a gate-C dependency veto, locked by the captured
  `epas1_rcc.functional-requirement.json` snapshot. Supersedes the reasoned-only anchor from #676.
- **Cross-repo landed:** AM #582 (partner_map EPAS1×VHL + lock test) → TC #677 (watchlist flip + snapshot). Only EPAS1
  affected (no prior partner map); low blast radius, data-justified (p=0.002), belzutifan-validated. Literature stayed
  OUT of the verdict — the in-data VHL-conditional signal carries it.
- **Status:** ✅ RESOLVED. The gate-C `non_dependent` FN is closed; EPAS1/RCC reads `partner_conditional_dependent`
  and is regression-locked. Distinct from the reference_profiles HIF2A/RCC licensing-blind anchor (Cortellis wall),
  which remains an honest-blind clinical-precedent coverage gap (out of scope here).

### Regression-lock verification pass — discordance-loop fixes CASE-007…013 (2026-09-07)
Ran the full loop-level regression lock against **clean trunk** (skills worktree off `v2-architecture` @ b2de9bd;
target-contracts clean `main` @ 7028540) — NOT the dirty home checkout — to confirm every landed discordance fix is
asserted where CI catches a regression.
- **`eval/run_scorecard.py`** — the 4 regression-relevant steps are GREEN: `calibration` PASS, `discrimination` PASS,
  `known_target_panel` (signal-vector score-only) PASS, `eval_ledger` PASS. The 2 RED steps — `framework_health` and
  `runs_clean_smoke` — are **STALE-dashboard structural checks** (committed `framework_health.json` / `subskill_health.json`
  differ from computed); a KNOWN pre-existing trunk condition (health/atlas staleness track), NOT a discordance regression
  and NOT caused by CASE-007…013 (all eval/ + verdict-INERT headline-field changes). Out of scope here → owned by the
  health/atlas-rebuild track.
- **Each fix is regression-locked** (hermetic tests, run with worktree `--rootdir/--confcutdir`):
  - CASE-007 `cooccurrence_temporal_context_caveat` + CASE-010 `survival_direction_scope_caveat` →
    `differentiation-landscape/tests/test_cooccurrence_confidence_caveat.py` (27 passed) + MET `differentiation_note`
    present in `target-contracts/vocabularies/known_target_calibration_set.yaml` (and the calibration suite PASSED).
  - CASE-008 modality gate / `sm_modality_mismatch_caveat` → `tractability-small-molecule/tests/test_modality_gate.py`
    (11) + `test_directness_and_agreement.py` (12 passed).
  - CASE-009 `pharmacovigilance_scope_caveat` → `on-target-safety-liability/tests/test_pharmacovigilance_scope_caveat.py`
    (3 passed).
  - CASE-013 `concordant_over_flag` guard → `eval/tests/` (38 passed).
- **Verdict spines byte-stable:** the caveats are verdict-INERT headline fields (not resolver rungs), and the
  `calibration` suite — which loads the resolver-golden regression snapshots — PASSED, confirming the goldens are intact.
- **Monitor baseline clean:** rebuilt the ledger over the pinned `eval/literature-snapshots/` and diffed vs
  `eval/discordance_baseline.json` (33 sharp keys) → **0 NEW / 0 RESOLVED**, all count deltas 0 — the committed baseline
  matches the current triaged set. **Conclusion: the loop's gains are locked.**

### CASE-013 — discordance-loop guard-tightening: auto-demote the dominant `dismissed_concordant` noise — LANDED (verdict-INERT, eval-only, 2026-09-07)
- **Surfaced by:** `LOOP_HEALTH.md` (the loop's own precision instrument). The dominant NOISE source in the
  sharp candidate-gap set was `dismissed_concordant` (10 of 14 noise rows) — the `--literature` lane flags a
  sub-axis `contradicts` even though its own holistic read of the (target, indication) agrees. LOOP_HEALTH
  named the "next guard tightening" as a direction cross-check.
- **Determination — a `claim_signal`-direction cross-check is NOT viable; the lane's own summary IS:** I
  cross-tabbed every sharp row's `claim_signal` × `literature_read` × disposition over the pinned 37-pair
  corpus. Direction alone does not separate noise from real gaps: `absent`+supporting-lit appears in BOTH
  `dismissed_concordant` (STEAP1/SEL) and `real_deferred` (PARP1/COND, an HRD-conditional SL the COND axis
  under-calls) and `dismissed_scope` (pharmacovig); `strong`+supporting-lit appears in BOTH concordant noise
  and a real FIXED gap (MET/COMUT, the CASE-007 temporal-context miss). Any direction rule that catches the
  noise also demotes a REAL gap. The ONE field-clean discriminator is the lane's OWN
  `overall_consistency == concordant`: it occurs on exactly 4 sharp rows, ALL noise, with **0 collisions**
  against any `fixed`/`real_deferred`/`dismissed_scope` row (those are all `partially_concordant`/`insufficient`).
- **Fix (LANDED):** new gap class `concordant_over_flag` (severity 1, non-actionable, non-sharp) in
  `eval/build_discordance_ledger.py`. `_classify` now takes `overall_concordant` and, for a verified
  `contradicts` on a MEASURED axis, returns `concordant_over_flag` when the lane's `overall_consistency` is
  `concordant` — an isolated axis contradiction against a concordant summary is an internal over-flag. Placed
  AFTER the unmeasured-axis check (a genuine coverage gap still routes to `blind_spot`). The row is still
  EMITTED (review-queue) but leaves the `calibration/verdict_rule` SHARP set the monitor diffs and the
  `actionable` set. Literature stays `citable_in_nominations: false`; no verdict/resolver/card/method touch.
- **Effect (pinned corpus, fingerprint `583e151e85f4d624`):** 4 rows demote out of sharp — `functional-requirement|DLL3|SCLC|SEL`,
  `surface-modality-fit|FOLR1|OV|TOPOLOGY`, `tractability-small-molecule|XPO1|MM|DEGRADER`,
  `surface-modality-fit|SCD1|CRC|DENSITY` (the last previously untriaged; `not_addressed` lit + concordant
  summary → concordant noise). Baseline regenerated **37 → 33 sharp keys** (`eval/discordance_baseline.json`);
  re-diff clean (0 NEW / 0 RESOLVED). `LOOP_HEALTH.md`: n_sharp 32→29, precision_strict 0.438→**0.483**,
  precision_incl_scope 0.562→**0.621**, noise_rate 0.438→**0.379**; 3 manual `dismissed_concordant` triage
  rows graduated to `auto_demoted_concordant` (excluded from n_sharp).
- **Ratchet:** 4 new hermetic tests in `eval/tests/test_discordance_ledger.py` (demote on concordant summary;
  NO demote on `partially_concordant` — MET/PARP1 protection; concordant summary does NOT hijack an unmeasured
  coverage gap; demoted class is non-actionable + non-sharp) + updated `test_loop_health.py`
  (`auto_demoted` excluded from n_sharp; committed dispositions n_sharp==29). Full `eval/tests/` suite: 38 passed.
- **Residual (by design):** the `partially_concordant` `dismissed_concordant` rows stay in the queue —
  separating them from real gaps needs biology the lane fields do not carry, and a broader rule would demote
  a real gap. This guard trades coverage for a provable no-false-demote invariant.

### CASE-011 — HER2/BRCA tractability `chemically_unhit` — HARVEST gene-alias artifact, NOT a skill FN — FIXED (2026-09-07)
- **Surfaced by:** the full-sweep ledger (`~/dev/discordance_full_sweep_ledger_2026-09-07.json`) —
  `tractability-small-molecule | HER2 | BRCA` reads `chemically_unhit` (driving rule
  `prism-no-compounds-found-neutral`) across DRUG + ACTIVITY, tagged `calibration_gap` (verified lit:
  approved HER2 TKIs lapatinib/neratinib/tucatinib). Originally queued as CASE-008 **mechanism 2**
  ("PRISM/ChEMBL coverage false-negative"). **That triage was wrong** — it is not a data-coverage gap.
- **Root cause (named):** `eval/harvest_literature.py` ran the fan-out on the calibration-set **KEY**
  verbatim — `HER2` — with **no** HGNC canonicalization. Every gene-keyed reader keys on the HGNC symbol
  (`dgidb_drug_gene.read` filters `gene_symbol == target.upper()`; PRISM / `measured_potency_tractability` /
  structure likewise), and the alias `HER2` matches **no** `ERBB2` row → each gene-keyed axis read a spurious
  `data_unavailable` / no-compounds-found. The verdict is a phantom: harvest snapshot
  `eval/literature-snapshots/HER2__BRCA.json` fired only `*-data-unavailable-insufficient` /
  `prism-no-compounds-found-neutral` / `*-no-coverage` rules.
- **Proof it's the symbol, not coverage:** the properly-resolved run reads a strong TRUE POSITIVE.
  `eval/known-target-packages/ERBB2__brca.json` (the panel canonicalizes HER2→ERBB2 via
  `run_known_target_panel.TARGET_CANON`): `prism-compound-activity = clinically_active` (37 compounds:
  afatinib/neratinib/tucatinib/lapatinib/pyrotinib), `known-drug-tractability = approved_drug_tractable`
  (201 approved / 224 antineoplastic DGIdb interactions), `measured-potency = potent_measured_ligand`
  (ChEMBL 2728 potent, phase=approved), `structure = experimental_ligandable`. Resolver →
  `prism-clinically-active-supportive-sm` (priority 3) → **`chemically_active`**. Direct standalone re-run
  confirms: `--target HER2` → `insufficient` (nothing resolves); `--target ERBB2` → resolves cards
  (`structurally_ligandable` even offline; `chemically_active` with S3/PRISM).
- **Scope of the bug (not just HER2):** the harvest iterated the SAME aliased calibration KEYS the panel
  canonicalizes — **HER2, TROP2, BCMA, CD20, SCD1, HIF2A, ADAR1** — so every gene-keyed axis for all 7
  was silently mis-harvested. This inflates the ledger's `blind_spot_gap` / `calibration_gap` counts with
  phantom rows fleet-wide (a review-queue integrity issue, beyond CASE-011's HER2 instance).
- **Fix (LANDED, eval-only, verdict/golden/replay BYTE-STABLE):** `harvest_literature._canonical_symbol`
  single-sources `run_known_target_panel.TARGET_CANON`; `harvest_pair` runs the fan-out on the HGNC symbol
  while keeping the record `target` = the display/alias key (so calibration_gap tagging + the snapshot
  filename stay keyed by the calibration symbol — mirrors the panel's `name` vs `emit_target`). Records now
  carry `resolved_symbol` for audit. The tractability SKILL, its resolver, golden, and replay fixtures are
  **untouched** — no verdict moved (the ERBB2 verdict was already correct). 4 new hermetic tests
  (`test_canonical_symbol_maps_aliases`, `test_harvest_pair_runs_on_canonical_symbol_but_labels_the_alias`);
  `eval/tests/` 28/28 green.
- **NO calibration anchor added:** this is NOT a genuine `known_gap_expected_fail` — the framework gets
  HER2/ERBB2 SM-tractability RIGHT on the canonical symbol. Adding a `should_be` anchor would encode a
  harness artifact as truth. (HER2 already sits in `reference_profiles`.)
- **Follow-up (needs Bedrock + `AWS_PROFILE=cbg`):** re-harvest the 7 aliased pairs (`HER2/BRCA`, `TROP2/…`,
  `BCMA/…`, `CD20/…`, `SCD1/…`, `HIF2A/…`, `ADAR1/…`) to refresh `eval/literature-snapshots/*` + rebuild the
  ledger; the HER2 tractability rows should drop out of the calibration_gap set (→ `chemically_active`,
  concordant). Corrects CASE-008 mechanism 2 (there is no HER2 PRISM-coverage gap to close).
- **Deeper hardening (proposed, out of scope):** the gene-keyed readers classify an *unresolvable* symbol as
  an affirmative "no compounds found" (`prism-no-compounds-found-neutral` → `chemically_unhit`) rather than a
  coverage-gap `insufficient` — an absent-vs-unresolved conflation. Alias→HGNC resolution in the reader/
  dispatcher layer (vs each harness's curated `TARGET_CANON`) would be the robust cross-repo fix, but it is
  verdict-moving with wide golden fan-out; keep it as a follow-up, not part of this eval-only fix.
- **Re-harvest DONE (2026-09-07, `AWS_PROFILE=cbg BEDROCK_AWS_PROFILE=cmp-dev`):** re-harvested the 6
  harvestable aliased pairs (`HER2/BRCA`, `TROP2/TNBC`, `BCMA/MM`, `CD20/lymphoma`, `SCD1/CRC`, `HIF2A/RCC`;
  `ADAR1` skipped — `indication: multi`), `--literature-scope gating`, overwriting `eval/literature-snapshots/*`;
  every record now carries `resolved_symbol` = the HGNC symbol (ERBB2/TACSTD2/TNFRSF17/MS4A1/SCD/EPAS1) and all
  8 gating axes RESOLVE (were phantom `data_unavailable`/`insufficient` before). Rebuilt
  `~/dev/discordance_full_sweep_ledger_2026-09-07.json` (pre-fix copy kept as `*.pre-case011.bak.json`).
  **HER2/BRCA tractability confirmed FIXED:** `chemically_unhit` → **`chemically_confirmed_genetic`**
  (`e7-crispr-confirmed-supportive-sm`) — the top on-target rung; the 2 phantom calibration_gap rows
  (ACTIVITY, DRUG) are GONE. Ledger delta: `blind_spot_gap` 1204→1129 (−75 phantom rows), `calibration_gap`
  32→37, total 1373→1302. Monitor diff vs the old baseline: **5 RESOLVED** (HER2 tractability ACTIVITY+DRUG,
  HER2 mechanism PHOSPHO, TROP2 mechanism PERTURBATION, HIF2A differentiation NODE — all phantom alias rows)
  + **10 NEW** sharp calibration_gaps DE-MASKED (real discordances previously hidden behind the alias). Baseline
  regenerated (`eval/discordance_baseline.json`, 37 keys, new corpus fingerprint) so the weekly monitor is
  coherent with the corrected corpus.
- **DE-MASKED triage queue (CASE-011 follow-on, NOT regressions — pre-existing truths the alias bug hid):**
  (a) **biologics-approved DRUG-axis inflation (CASE-008 pattern):** `BCMA/MM` + `CD20/lymphoma` tractability
  DRUG read druggable off the approved BIOLOGIC (BCMA = CAR/TCE; CD20 = rituximab antibody). BCMA (`TNFRSF17`)
  is already in `_BIOLOGICS_APPROVED_NONSM`; **`CD20`/`MS4A1` is NOT — add it to the curated set + the
  `sm_modality_mismatch_caveat` will fire** (verdict-inert, mirrors CASE-008). (b) **HIF2A/RCC
  functional-requirement DEP+SEL read `absent`** vs belzutifan-validated HIF2A dependency in ccRCC — a
  candidate genuine FN (VHL-loss-conditional; needs a biomarker-conditional look, SMARCA2/LUAD-style). (c)
  TROP2/SCD1 tractability + BCMA/SCD1 surface + BCMA tumor-selectivity SAFE — queued for per-row triage.
- **Status:** ✅ COMPLETE. Harvest canonicalization LANDED (PR #1175); corpus + ledger re-harvested and
  rebuilt; baseline refreshed. HER2 tractability false-negative resolved. 10 de-masked discordances queued
  above (separate cases). Deeper reader/dispatcher alias-resolution hardening remains a proposed cross-repo
  follow-up.

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
  **↳ SUPERSEDED by [[CASE-012]] (2026-09-07): NOT a data-coverage gap — the normal signal IS present
  (sc-normal-celltype colon), it is a resolver RULE gap. See CASE-012.**
- **Meta:** of 32 calibration_gaps, **4 real fixes** (CASE-007 + 008 + 009-caveat + 010-caveat) and
  **~10 dismissed as concordant/scope + ~4 deferred-for-data** + 128 staleness→atlas. Ledger FINISHED.

### CASE-012 — surface-modality-fit pMHC-TCE arm normal-tissue liability — RESOLVED via verdict-INERT intermediate-PRESENTATION caveat (expression-clamp thesis overturned) (discordance follow-up, 2026-09-07)
- **Surfaced by:** the full 37-pair sweep (`~/dev/discordance_full_sweep_ledger_2026-09-07.json`), NOX1/CRC
  `surface-modality-fit` SAFETY row — `sub_verdict=pmhc_tce_supported` (rule `pmhc-iedb-presented-tce-supportive`),
  literature (1 verified cite, Stalin 2023 PMID 38137406) states NOX1 is NOT tumor-restricted (constitutive in
  normal colonic epithelium + vasculature, its physiological ROS/host-defense niche). Was deferred at triage
  (thin lit) under [[CASE-010]] as a "data-coverage item" — this case corrects that framing.
- **Determination — DATA IS PRESENT (outcome 2, a RULE gap, NOT a coverage gap):** the normal-colon liability
  is carried by the `sc-normal-celltype-expression` card (products `sc-normal-celltype-expression-colon-v1` +
  `-large-intestine-v1`, field `sc_normal_expression_class`). Live query of the colon product for NOX1:
  `early colonocyte` median_det **0.662** / expressing_donor_fraction **1.00** (34 donors, 3 datasets),
  `intestinal crypt stem cell of colon` 0.569 / 1.00 (9 datasets), transit-amplifying/absorptive/secretory
  0.23–0.31. These CLEAR the `HIGH_LIABILITY` threshold (`median_det>0.50 AND expressing_donor_fraction>0.70`
  in ≥1 normal cell type — `interpretation-rules/surface-intrinsic.rules.yaml` sc-normal rationale), so the
  rule `sc-normal-high-liability-bite-killer` **fires**. (Bulk GTEx colon MISSES it — median ~0.9 TPM, mean
  skewed high — classic enterocyte-compartment dilution; hence NOT a bulk-floor `not_detected_in_normal` call.
  Confirmed entirely in-data; no literature needed in the verdict.)
- **The structural hole (`target-contracts/resolvers/surface_modality.resolver.yaml`):** `pmhc_tce_supported`
  fires ONLY paired with `neither-viable-killer` (folded-surface-dead route, rungs at priority 23/24). The
  bulk/sc normal-tissue killers (`normal-tissue-essential-bite-killer`, `sc-normal-high-liability-bite-killer`)
  are wired ONLY to surface-VIABLE fit_classes (`both-viable-supportive` / `tce-preferred-supportive`, rungs
  priority 3–10). No `when_all_fired` rung pairs `neither-viable-killer` + a pMHC-supportive rule + a
  normal-tissue killer, so those killers — though they FIRE — cannot enter any pMHC combination. The ONLY
  normal-tissue clamp on the pMHC arm is `pmhc-broadly-presented-normal-tce-opposing` (priority 21/22), which
  reads HLA-Ligand-Atlas immunopeptidome BREADTH, not RNA/protein expression — so a constitutively
  normal-expressed antigen with no broadly-presented benign epitope is invisible to the pMHC verdict.
- **PROPOSED FIX (verdict-moving, DEFERRED — not landed; a live parallel session `fix/surface-scnormal-killer-refine`
  is mid-flight on this exact resolver + sc-normal killer, land after it settles to avoid a golden clobber):**
  add clamp rungs to `surface_modality.resolver.yaml` mirroring the existing 21/22 (3b') pMHC-presentation
  veto, so the fired sc/bulk normal-tissue killer withdraws the un-earned pMHC promotion:
  ```yaml
  # (3b'') pMHC-TCE arm normal-EXPRESSION liability withdrawal (mirrors 3b' immunopeptidome-breadth veto)
  - {verdict: tce_unsafe_normal_liability, when_all_fired: [neither-viable-killer, pmhc-iedb-tcell-validated-tce-supportive, sc-normal-high-liability-bite-killer], driving_rule: sc-normal-high-liability-bite-killer, priority: 19}
  - {verdict: tce_unsafe_normal_liability, when_all_fired: [neither-viable-killer, pmhc-iedb-presented-tce-supportive,        sc-normal-high-liability-bite-killer], driving_rule: sc-normal-high-liability-bite-killer, priority: 20}
  - {verdict: tce_unsafe_normal_liability, when_all_fired: [neither-viable-killer, pmhc-iedb-tcell-validated-tce-supportive, normal-tissue-essential-bite-killer], driving_rule: normal-tissue-essential-bite-killer, priority: 19}
  - {verdict: tce_unsafe_normal_liability, when_all_fired: [neither-viable-killer, pmhc-iedb-presented-tce-supportive,        normal-tissue-essential-bite-killer], driving_rule: normal-tissue-essential-bite-killer, priority: 20}
  ```
  (priority <23 so the clamp outranks the `pmhc_tce_supported` rungs; lower number = higher precedence, per the
  resolver's own 21/22-over-23/24 convention.) Then bump resolver `version`, regenerate the surface golden via
  `skills/_skills_common/tests/regenerate_resolver_golden.py` (append the driving rule_ids to the surface_modality
  `rule_ids` list first if absent), run the FULL skills suite + offline replay (a verdict-contract change fans out
  across golden snapshots + synthetic fired-sets). Expected flip: NOX1/CRC `pmhc_tce_supported → tce_unsafe_normal_liability`.
- **Backtest guard (must-not-regress):** the fix is TCE-arm-only and preserves ADC (mirrors the design note —
  CEACAM5, a validated ADC target with normal-gut expression, must survive as `adc_preferred_tce_unsafe`, not be
  killed on both arms). Any pMHC target whose normal expression is genuinely tumor-restricted keeps
  `pmhc_tce_supported` (sc-normal killer does not fire). STEAP1/prostate `pmhc_tce_supported` (per CASE-010) must
  be re-checked against the sc-normal-celltype prostate product before landing.
- **Calibration:** if landed, anchor NOX1/CRC in `target-contracts/vocabularies/known_target_calibration_set.yaml`
  as a surface `tce_unsafe_normal_liability` / normal-liability expectation (escalate-only; literature stays OUT
  of the verdict — the in-data sc-normal signal carries it).
- **Status:** DOCUMENTED + PROPOSAL READY, fix DEFERRED per coordination. Determination: **rule gap, data present**
  — supersedes the CASE-010 "data-coverage" deferral. UPDATE (same day): the blocking parallel session merged
  (`fix/surface-scnormal-killer-refine` → PR #1173, CEACAM5 window-driven repoint) — the resolver is no longer
  contended, so the proposed clamp rungs are now UNBLOCKED for a clean follow-up build (verify STEAP1/prostate +
  CEACAM5 non-regression, regen surface golden, full suite).
- **RESOLUTION (2026-09-07, follow-up build) — the expression-clamp plan above was OVERTURNED by live verify;
  landed a modality-appropriate PRESENTATION caveat instead.** Running the live methods against the post-#1173
  trunk overturned the "expression RULE gap → flip NOX1" thesis on three counts:
  1. **NOX1/CRC fires NO hard-veto signal under the current framework.** HPA: `essential_tissue_flag=absent`,
     `normal_tissue_breadth_class=not_detected_in_normal` (bulk floor misses it → even a *supportive* signal).
     sc-normal: `sc_normal_safety_essential_class=origin_tissue_liability` — colon is CRC's ORIGIN tissue, and
     #1173 repointed `sc-normal-high-liability-bite-killer` from blunt `HIGH_LIABILITY` to organ-aware
     `critical_organ_liability` (essential expression in a NON-origin critical organ). Origin-tissue expression
     is deliberately window-arbitrated, NOT vetoed (backtested on CEACAM5). So the proposed clamp would NOT even
     have flipped NOX1.
  2. **The proposed clamp would have REGRESSED the flagship pMHC target WT1.** WT1/COADREAD =
     `critical_organ_liability` (driver: glomerular-capsule epithelium = kidney), so pairing the expression
     killers into the pMHC route flips WT1 `pmhc_tce_supported → tce_unsafe_normal_liability` — breaking the
     WT1 replay fixture and rejecting the framework's own canonical pMHC exemplar (WT1 is named in the resolver
     3b comment; it is a validated clinical TCR-T/vaccine/TCE target).
  3. **Expression is the WRONG safety axis for the pMHC modality.** The TCR-mimetic pMHC route EXISTS for
     self-antigens with some normal expression (WT1/PRAME/MAGE); its correct safety axis is immunopeptidome
     PRESENTATION breadth (`pmhc-broadly-presented-normal-tce-opposing`), not RNA/protein expression. The
     original "gap" is largely by design.
  **The genuine, modality-appropriate gap** is the MIDDLE presentation band: the presentation veto is binary
  (fires only at `broadly_presented_normal` ≥ atlas Q3), so `intermediate_presentation` (Q1–Q3) is uncaveated.
  NOX1 = `intermediate_presentation`, presented on **8 normal tissues** (colon + small intestine + bone marrow +
  lung/spleen/thymus/testis/cerebellum) via HLA-Ligand-Atlas — a real on-target/off-tumor liability the binary
  veto misses. **LANDED (verdict-INERT):** `surface-modality-fit` v1.10.0 `_pmhc_presentation_caveat` — fires on
  `pmhc_tce_supported` + `intermediate_presentation`, names the sensitive normal tissues (GI/marrow/vital-organ),
  calls for a tumor-vs-normal presentation differential; None on restricted (NY-ESO-1/MAGE-A4/STEAP1 clean) /
  broad (already vetoed) / non-pMHC verdicts. Fires additively for WT1/PRAME/KRAS (all intermediate) WITHOUT
  moving their verdicts. Spine/resolver/replay byte-stable (6 new tests + 120 surface-suite green). NOX1/CRC
  verdict UNCHANGED (`pmhc_tce_supported`) — correct by design (origin-tissue window) — now carrying the
  presentation caveat. NO calibration flip (NOX1 is not a hard-veto target); the earlier expression-clamp
  proposal + its target-contracts branch were DISCARDED.
- **Status:** RESOLVED — verdict-INERT presentation caveat landed (v1.10.0); expression-clamp thesis retired.

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

### CASE-008 — tractability-small-molecule credits SM tractability from a BIOLOGICS approval — FIXED + GRADUATED to a verdict-moving DRUG-axis modality gate (full-sweep, 2026-09-07)
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
     Separate gap (PRISM/ChEMBL coverage), not addressed here. **[CORRECTED by CASE-011 (2026-09-07): this
     was NOT a PRISM/ChEMBL coverage gap — it was a harvest gene-alias artifact. The harvest ran on the
     un-canonicalized alias `HER2`; the resolved `ERBB2` run reads `chemically_active` (37 PRISM compounds,
     201 DGIdb approved). Fixed in `harvest_literature.py`.]**
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
- **GRADUATED (2026-09-07, verdict-moving DRUG-axis signal, cross-repo):** the caveat is now backed by a
  real modality-aware DRUG signal. AM `dgidb_drug_gene` v0.3.0 (#581) reads the curated
  `biologics_precedent_targets.yaml` crosswalk and emits `approved_drug_modality` + a new
  `approved_biologic_only` value on `approved_drug_engagement_class`; TC (#672) adds the card fields, the
  rule `known-drug-approved-biologic-only-sm-not-supportive`, and the resolver v1.6.0 rung that routes a
  biologics-only approval's DRUG axis to `annotation_only_indirect` INSTEAD of the SM-supportive
  approved-drug rung. Skills v3.11.0 consumes the field; `_sm_modality_mismatch_caveat` now keys on the
  reader's authoritative `approved_drug_modality` (curated set = fallback) and reads as a CONFIRMATION when
  the gate fired.
- **CORRECTION to the earlier "flips the BRAF replay fixture" framing:** verified against LIVE DGIdb, the
  gate is VERDICT-STABLE for the 5 calibration targets — their SM verdicts are driven by the STRUCTURE
  predicted-pocket card (DLL3/STEAP1 → `structurally_ligandable`) or the e7 off-target read
  (FOLR1/NECTIN4/CEACAM5 → `discordant`), NOT the approved-drug rung (the pre-existing directness gate had
  already demoted it). The gate moves the DRUG-axis FIRED signal only (CEACAM5 was `approved_direct` via 8
  false-direct records → now `approved_biologic_only`; DLL3/FOLR1/NECTIN4 were `approved_indirect_only`) —
  byte-level golden regen, top-line verdict unchanged. BRAF (a genuine SM target, no `biologics_only` flag)
  stays `approved_direct` → `chemically_active`; its replay fixture is UNAFFECTED. FAIL-SAFE / osimertinib
  guard: EGFR/ERBB2/MET (dual-modality, in the vocab) + FOLH1/PSMA (SM radioligand) carry no flag → never
  demoted; KRAS/EGFR/BRAF untouched.
- **Proposed ratchet / follow-ups:** (i) #07 wire a shared live reader replacing the residual curated
  `_BIOLOGICS_APPROVED_NONSM` in-run.py set (now a fallback only); (ii) the HER2 PRISM-coverage
  false-negative (mechanism 2) is a distinct queued gap.
- **Status:** FIXED + GRADUATED (verdict-moving DRUG-axis signal, verdict-stable for the calibration set).
  AM #581 + TC #672 merged; skills v3.11.0. Regression-locked by the AM dgidb reader tests, the skills
  modality-gate + golden/replay suites, and the DLL3/CEACAM5 `tractability_modality_note` calibration anchors.

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
