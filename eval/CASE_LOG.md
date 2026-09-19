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

### CASE-035 — DLL3-SCLC reads `bite_tce: unsafe`: an **approved TCE** target killed by an ENTERIC-NEURON veto that the gut-organ promotion opened — ACCEPTED AS REAL (2026-09-18)

- **Surfaced by:** the tumor-selectivity content audit's end-to-end control set. DLL3-SCLC is on that
  list precisely as the target that **must not be killed** (tarlatamab is an approved DLL3×CD3 TCE), so
  the run was a pass/fail control, not exploration.
- **Measured end-to-end, live** (`surface-modality-fit`, `--target DLL3 --indication SCLC`):
  `surface_modality_verdict: adc_preferred_tce_unsafe`,
  `surface_modality_verdict_by_modality: {adc: viable, bite_tce: unsafe, antibody: viable}`,
  `driving_rule_id: sc-normal-high-liability-bite-killer`, confirmed present among the **13** fired rules
  with `dominant=True`. The internal contradiction is the tell: the `adc-tce-modality-fit` card
  **itself** fired `both-viable-supportive` (also dominant) — the modality card says both modalities are
  viable and the sc-normal killer overrides it.
- **★★ Cause: a DATA/GRADE change with NO rule edit.** AM #663 (`b6536b8`) moved DLL3-SCLC's
  `sc_normal_essential_veto_grade` from `accessible_moderate_severity` to `accessible_high_severity`,
  which is in the killer's `when … in: [accessible_high_severity, accessible_ungraded]` set. No
  interpretation rule was touched, so no rules diff, no golden diff and no verdict-level test could have
  flagged it. **A verdict can move because the gate's INPUT moved.**
- **★★ Mechanism — the gut promotion silently defeated BBB protection for a whole LINEAGE.** DLL3 is a
  Notch ligand restricted to neural/neuroendocrine lineage, so **all 14** of its essential normal hits
  are neurons or OPCs. Nine sit in `brain` and are correctly `bbb_protected` — a systemically dosed TCE
  does not cross the BBB. But the **`colon` shard is the only systemically-accessible tissue that
  contains neurons** (the enteric nervous system), so promoting `gut → "colon"` into
  `SC_NORMAL_CROSSWALK` converted a BBB-protected neural liability into an accessible one. Driver:
  `inhibitory motor neuron` / `colon`, det **0.747** / donor **1.000** / **6 atlases** — reached through
  the *plain* high rung (`det ≥ 0.50 ∧ donor ≥ 0.70 ∧ n_ds ≥ 2`), **not** the replication rung #660
  added. Its only non-gut accessible hit is a weak `neuron` / `lung` (det 0.345 / donor 0.500 / 4
  atlases → `moderate_severity`), which is why the kill rests entirely on the gut.
- **Attributed against the shipped ladder, not estimated.** `accessible_high_severity` over all 504
  corpus-20260914 pairs: **223 (44.2%)** pre-#660 → **284 (56.3%)** #660 → **292 (57.9%)** #661 →
  **330 (65.5%)** #663. So the gut promotion contributes **+38**. Gut-*driven* high is **50**, and
  50 − 38 = **12** pairs that were already high via a non-gut driver and merely re-named their driver.
- **★★ The obvious remedy was MEASURED AND REFUTED.** Excluding gut hits from the pool the severity is
  read from moves 330 → 292, **38 relieved / 0 newly killed** (strictly one-directional, as removing
  hits must be) — but it **breaks the grade-refines-class invariant on 6 pairs**, because the selector's
  empty-pool arm returns *class*-level tokens: CDH17-ESCA/CML/SCLC fall to `not_applicable` and
  MUC17-STAD / STEAP1-PAAD / TNFSF13-STAD to `origin_tissue`, while the class upstream stays
  `critical_organ_liability`. It also re-opens the CDH17-ESCA organ-panel fail-open this arc had just
  closed. Narrowing to gut *neurons* only relieves **11** (DLL3-SCLC, APC×6, RARA-AML, RET-THCA,
  SLC7A11-PAAD, SOX2-LUSC) and does preserve CDH17-ESCA (driver `enterocyte`, not a neuron) and leave
  MSLN-PAAD / FOLR1-OV / DPEP1-COADREAD untouched — but enteric neurons genuinely **are** outside the
  BBB, so excluding them is a real fail-open rather than a neutral correction.
- **Disposition: ACCEPTED AS REAL — no code, rule or panel change.** The substrate audit (below) shows
  the evidence is sound, and the framework flagging a well-replicated enteric-neuron liability is
  defensible on its own terms. The cost is recorded here rather than engineered away.
- **Substrate audit — the colon shard is clean where it matters.** Read the full product
  (`sc-normal-celltype-expression-colon-v1`, **1,565,555** rows): the `tissue` column is uniformly
  `['colon']`, so there is **no shard-construction leak**; 15 of its 156 cell types are neural and they
  form a *coherent* ENS panel at real depth — `enteroglial cell` 7 atlases / 110 reliable donors,
  `inhibitory motor neuron` 6 / 53, `motor neuron` 6 / 64, `enteric neuron` 5 / 68.
- **★★ NEW OPEN FINDING (a) — the safety-essential neural panel is INCOHERENT BY BIOLOGY.** The bare
  whole-token `"neuron"` entry (`methods/sc_normal_expression/stats.py:176`) is **pre-existing** — #663
  added `gut → "colon"` plus the *epithelial* prefixes, and its own comment justifies the pairing in
  epithelial terms only; the ENS sweep was an unintended interaction. Essential: `inhibitory motor
  neuron`, `motor neuron`, `enteric neuron`, `afferent neuron`, `Schwann cell`, `peripheral nervous
  system neuron`. **Not** essential: `enteroglial cell` — the **most deeply sampled** colon neural type
  in the shard and functionally essential to gut motility — plus `interneuron`, `glial cell`,
  `neural cell`, `neural crest cell`. Membership is decided by **label morphology**, not by the biology
  the panel claims to encode: the same defect class as the `"kidney proximal tubule"` prefix that
  matched 0 of 670 labels. Not fixed here — it is a panel change outside this case's remit.
- **★ NEW OPEN FINDING (b) — two 1-atlas labels are ONE ATLAS from being killer-eligible.** The colon
  shard carries `primary sensory neuron (sensu Teleostei)` — a **teleost-qualified** CL term in a human
  gut product, reaching **184** pairs (13 donors / 7 reliable / **1** atlas) — and
  `oligodendrocyte precursor cell`, **141** pairs (15 / 12 / **1** atlas) against the brain shard's OPC
  at **170** atlases, which is the control: a CNS-restricted lineage appearing *once* in gut is a
  curation artifact, not a population. Both return `essential=True` and sit in the veto pool today.
  They are inert **only** because 1 atlas forces `low_confidence`, and no killer-eligible pair is driven
  by either — but inert by corpus is not safe by contract: a second atlas would make them eligible.
- **★★ The 2026-09-07 triage row is now FALSE OF ITS OWN GROUND — forward-pointed, NOT retro-edited.**
  `loop_dispositions.yaml` carries `tumor-selectivity|DLL3|SCLC|SAFE|calibration_gap` as
  `dismissed_concordant` on the stated basis *"literature cites DLL3 low normal expr = good therapeutic
  index — concordant with selective"*. That basis no longer holds. The row is **deliberately left on its
  original token**: it is a dated snapshot (`snapshot: discordance_full_sweep_2026-09-07`) of what was
  triaged then, and a triage record rewritten to match today's code stops being usable as history.
  Two pins also forbid it, and both edit shapes were **measured, not assumed**:
  `test_loop_health.py:69` and `test_dispositions.py:851` pin `len == 32` / `n_sharp == 29` /
  `n_auto_demoted == 3` / `precision_strict == 0.483`; flipping the token yields **0.517** and adding a
  row yields **33**. A `note:` forward pointer is pin-safe because `load_dispositions` reads **only** the
  `disposition` key. Note also that `test_dispositions.py:849`'s own docstring says *"This feature adds,
  never moves."*
- **★ `discordance_baseline.json` is deliberately UNTOUCHED.** `diff_discordance_ledger.diff` computes
  `appeared = sharp_keys(ledger) − baseline_keys`, so `surface-modality-fit|DLL3|SCLC|…` will surface as
  a `new_sharp_gap` on the next sweep on its own. Adding the key to the baseline would **suppress** the
  finding rather than record it — the instrument is the diff, not the ledger.
- **Relation to CASE-003.** Same pair, **opposite direction**: CASE-003 recorded the framework
  *under*-reading DLL3 (`hold` via `dependency:non_dependent` despite an approved TCE). It now
  *over*-reads it. A pair that has been wrong in both directions is a calibration probe worth keeping.
- **Status:** OPEN — accepted as real; findings (a) and (b) filed for the normal-tissue safety panel,
  neither fixed here. Refs: AM #660, #661, #663 (`b6536b8`), skills #1447 (`3afa12df`), TC #786.

### GENOMIC-ALTERATION 20-pair literature panel RE-RUN (2026-09-13, post-land) — 20/20 emitted, 63 rows, SHARP 6 → **3**; all 3 still CN, all 3 one predicate

Second run of the **same registered** `genomic-alteration-profile-20` roster, after the four-leg land chain
(TC #739 `1387b36` → TC #742 `6c401b6` → AM #604 `612044c` → skills #1313 `7bb66c64`, resolver 1.10.0).
Snapshots pinned to a per-panel dir (`eval/literature-snapshots-genomic20/`, per `eval/.gitignore` — six
pairs are shared with other panels and would otherwise overwrite each other's corpora);
`--calibration-set` supplied (omitting it silently demotes every `calibration_gap` to `verdict_rule_gap`).

| | baseline 09-12 | re-run 09-13 |
|---|---|---|
| records / pairs | 20 / 20 | 20 / 20 |
| ledger rows | 71 | 63 |
| `calibration_gap` | 3 | **2** |
| `verdict_rule_gap` | 3 | **1** |
| `blind_spot_gap` | 51 | 43 |
| `staleness_gap` | 14 | 17 |
| axis reads | 100 | 100 (15 CN `agree`, **3 CN `contradicts`**, 2 CN `extends`; 0 contradicts on SNV/FUS/SPL/DEP) |

**The chain worked, and it is attributable.** SHARP halved 6 → 3 and the three that cleared are exactly the
three the chain aimed at:

- **CASE-028 (IDH2/AML) is CLOSED at the verdict.** Baseline: `confirmed_driver` driven by
  `cn-recurrently-deleted-supportive`. Now: `recurrent_snv_driver` driven by
  `snv-recurrence-top-driver-supportive`. The passenger deletion no longer drives anything; its residual
  `contradicts` sits on a **non-driving** axis.
- **CASE-030 (MET/LUAD, MDM2/LGG) is CLOSED.** Both CN axes now read `agree`; neither appears in the ledger's
  sharp set. Consistent with AM #617 mapping all 33 GISTIC cohorts.
- **★★ CASE-029's SNV-recurrence half is CLOSED, not open — re-measure before re-filing.** The case records
  the MC3 product as shipping "only 4 indications (COADREAD, NSCLC, GC, PAAD)" and IDH1/GBM, IDH2/AML,
  FLT3/AML as `data_unavailable`. Measured now: **17 of 20 pairs carry a measured recurrence class**, and all
  three named targets resolve — IDH1/GBM `top_1pct` (26/403, 99.85th pct), IDH2/AML `top_1pct` (8/140),
  FLT3/AML `top_1pct` (7/140) — plus SKCM 468, BLCA 411, PRAD 498, OV 412, LGG 526, HNSC 509, BRCA 1026,
  LUAD 1052. IDH1/GBM's verdict moved `mixed_pattern` → **`recurrent_snv_driver`**: the canonical R132 driver
  the case said "the skill cannot see" is now the driving axis. Of the 3 remaining `unmeasured` SNV reads,
  **only 1 (DLL3/SCLC) is a real coverage gap** — the other 2 are CASE-032 below.

**★ And the residual 3 are ONE defect, not three.** All three sharp rows (DLL3/SCLC + FLT3/AML `calibration`,
IDH2/AML `verdict_rule`) are CN-axis `contradicts` against the identical emitted shape: cell-line
`copy_number_class == recurrently_deleted` on a **near-diploid** panel. See CASE-031. Every one carries ≥1
VERIFIED citation (`confabulation_risk` False on all 63 rows).

**Two pre-registered predictions came back NOT MEASURABLE — for two different structural reasons, and that
is the finding.** Both are recorded here so the next run does not re-ask them of an instrument that cannot
answer: (1) *does IDH1/GBM still under-call `modality_scope`?* — the harvest snapshot record carries no
`skill_report` at all (keys: `_provenance`, `axis_short`, `claim_vector`, `indication`,
`literature_synthesis`, `resolved_symbol`, `skill`, `sub_verdict`, `target`), so `modality_scope`,
`alteration_role` and `subgroup_signals` — every field skills #1313 v2.18.0 just fixed — are **absent from
the pinned corpus** and invisible to the ledger. (2) *do the surface antigens' driver-axis reads now make a
literature `contradicts` a modality mismatch?* — `ROLE` is a `claim_vector` axis but is **not** in the lens
axis roster, so **0 of 100 axis reads touch it**. See CASE-034. The surface antigens' verdicts *did* land as
predicted (CD19/DLBC, DLL3/SCLC, FOLR1/OV all `missense_dominant_pattern` driven by
`mut-missense-dominant-supportive`), confirmed from `sub_verdict` — but that is read off the verdict, not off
the axis the lens was supposed to compare.

### CASE-031 — the shallow `recurrently_deleted` CN class still publishes a MEASURED-POSITIVE claim on 6 of 20 near-diploid pairs; it is the root of all 3 sharp rows (2026-09-13)

- **Surfaced by:** genomic-20 re-run, CN axis, 3 `contradicts` (DLL3/SCLC, FLT3/AML, IDH2/AML), all verified
  citations.
- **Determination (measured on all 20 pairs' emitted atoms).** `copy_number_class == recurrently_deleted`
  fires on **7 of 20**. Only PTEN/PRAD is a real deletion TSG — 3.9% deep-deletion fraction *and*
  `patient_focal_cn_class == recurrent_focal_deletion` → CN `strong`, corroboration `high`. The other **6**
  are near-diploid cell-line reads whose patient arm **contradicts or is missing**:

  | pair | `cn_median_panel` | `cn_fraction_deep_deletion` | `patient_focal_cn_class` | CN signal | CN corrob |
  |---|---:|---:|---|---|---|
  | CD19/DLBC | — | 0.1% | `focal_neutral` | moderate | low |
  | DLL3/SCLC | 0.99 | 0.3% | `data_unavailable` | moderate | moderate |
  | FGFR3/BLCA | — | 0.8% | `focal_neutral` | moderate | low |
  | FLT3/AML | 0.95 | 2.3% | `focal_neutral` | moderate | low |
  | IDH2/AML | 1.03 | 0.3% | `focal_neutral` | moderate | low |
  | SMARCA4/LUAD | — | 0.8% | `focal_neutral` | moderate | low |

  A panel median relative CN of ~1.0 with ≤2.3% deep deletion is not a deletion. This is TC #739's
  60.1%-genome-wide-null shallow predicate — **retired from every driver-establishing rung, but NOT from the
  emitted claim.** `SPECIFICITY IS NOT SCOPE` has a sibling: **retiring a predicate from the ladder does not
  retire it from the claim.** The claim layer is what the eval harness, the literature lane and this ledger
  all read, so the demotion is invisible to every instrument that measures it.
- **★ The mechanism is a one-directional guard.** In `skills/_skills_common/genomic_claims.py`,
  `_cn_corroboration:234` **already knows**: `focal_neutral` + a recurrent cell-line class returns `low`,
  commented *"cell-line recurrent but patient tumour focal-neutral — disagreement"*. But `_cn_signal:206`
  has only an **elevation** path — `_CN_FOCAL_POS` raises the tier when the patient arm agrees (the HER2/CCND1
  fix) and nothing lowers it when the patient arm disagrees. So corroboration is bidirectional and signal is
  one-way: the framework emits its own disagreement flag and publishes `moderate` anyway.
- **Fix — FILED, own skills PR (`_skills_common/` is a fleet-shared hot file, out of this branch's `eval/`
  scope).** Mirror the precedent 26 lines below in the same file: `_fus_signal` returns **`weak`** for
  `promiscuous_amplicon_fusion` with the rationale *"a real SV, but a passenger"* — never `absent` (the event
  is real), never `strong`. Same shape here: a recurrent cell-line CN class contradicted by
  `patient_focal_cn_class == focal_neutral` reads `weak`, not `moderate`.
  **Blast radius measured before proposing: 6 of 20 move** (the 5 `focal_neutral` deletions + EGFR/LUAD,
  which is `recurrently_amplified` + `focal_neutral` — the amplification side has the identical asymmetry).
  **4 protected controls stay put**: PTEN/PRAD and MYC/BRCA (both arms agree → `strong`), ERBB2/BRCA and
  CCND1/HNSC (cell-line `broadly_neutral` + patient focal amp → the elevation path must remain intact).
  DLL3/SCLC's `data_unavailable` patient arm is a **separate** hole — it falls through to corroboration
  `moderate`, giving an absent arm the same weight as a partial agreement; handle it explicitly rather than
  folding it in.
- **Status:** ✅ FIXED (root fix, `_skills_common/genomic_claims.py`). `_cn_signal` grew the mirror of its own
  elevation arm: an `elif cls in _CN_CELL_LINE_RECURRENT and focal in _CN_FOCAL_NEG` → **`weak`**, plus an
  evidence clause naming the disagreement (`weak` alone reads as a weak *measurement*, not as a contradiction —
  and the literature lane reads that string). Written as an explicit `if/elif` over two declared sets so the
  exclusivity is **structural**, with `test_cn_focal_populations_are_disjoint_and_declared` pinning
  `_CN_FOCAL_POS ∩ _CN_FOCAL_NEG = ∅`.
  **Made SYMMETRIC across amplification and deletion**, deliberately wider than the 5 deletion instances that
  surfaced it: the mechanism is direction-agnostic, `_cn_corroboration` already returns `low` for both, and
  fixing only the deletion arm would have recreated the very **mirror-guard DIRECTION gap** this case is about.
  The one amplification that moves, EGFR/LUAD (5.1% high-level), is the same minority-subset framing CASE-030
  already resolved as correctly `focal_neutral`.
  Re-measured live against the CN products (not quoted from the pre-fix note): **6 of 20 move, all 4 protected
  controls hold** — PTEN/PRAD + MYC/BRCA `strong` via the agree path, ERBB2/BRCA + CCND1/HNSC `moderate` via the
  elevation path. DLL3/SCLC (`data_unavailable` patient arm) is **untouched**, per the case's instruction to
  handle it explicitly: the demotion is keyed on the measured `focal_neutral` only, because an unmeasured arm is
  not a contradiction and demoting on it would price a coverage gap as disagreement. ★The **corroboration** half
  of the DLL3 hole (an absent arm still earning `moderate`) is NOT addressed here and stays open.
  **Verdict-inertness re-measured, not assumed:** `run.py:911` assigns `claim_vector` *after*
  `reconcile_genomic_verdict`, and the composed gate reads raw `resolve_verdict_for_gate`, so the spine cannot
  observe either fix; the `headline_block` / `question_table` display projections do move, as intended.
  Guards falsified by mutation — deleting the demotion arm reddens
  `test_cellline_recurrent_over_focal_neutral_patients_is_demoted_in_BOTH_directions` and nothing else.

### CASE-032 — `A or B` short-circuits on a TRUTHY `"data_unavailable"` sentinel and discards a MEASURED floor: 2 of 20 publish `unmeasured` where the data says `absent` (2026-09-13)

- **Surfaced by:** the CASE-029 re-measure above — 3 SNV reads remained `unmeasured`; only 1 is a coverage gap.
- **Determination (measured).** CD19/DLBC and NTRK1/THCA both emit
  `driver_recurrence_class == "bottom_decile"` with `n_samples_mutated: 0` — and
  `_RECURRENCE_SIGNAL["bottom_decile"] == "absent"`, a **measured floor**. Yet both publish signal
  `unmeasured`, corroboration `unmeasured`, and a rendered evidence string that reads
  **"recurrence data_unavailable"** — contradicting the atom it cites.
  Root cause, `genomic_claims.py:181`:
  ```python
  rec = h.get("pooled_driver_recurrence_class") or h.get("driver_recurrence_class") or bc.get("recurrence_class")
  ```
  `"data_unavailable"` is a **non-empty string**, so when the *pooled* arm is unavailable the `or` chain
  short-circuits on the sentinel and never reaches the per-indication arm that measured the floor. Same
  family as `±Inf is a NUMBER` (a sentinel that satisfies the guard meant to exclude it) — here the guard is
  truthiness.
- **Blast radius: 4 surfaces, one root.** The identical chain appears at `:181` (signal), `:192`
  (corroboration), `:411` (the evidence atom's `read` field) and `:507` (the narrated `key_signals` text), so
  a human reviewer reading the card sees a coverage *excuse* where the omics measured zero.
- **★ It fails OPEN in the direction that hides false negatives.** `build_discordance_ledger._axis_measured`
  reads the signal tier, so `unmeasured` demotes any literature `contradicts` on that axis to
  `blind_spot_gap` — "the omics cannot measure this" — when the omics measured 0 mutated samples and said so.
- **Fix — FILED (same skills PR as CASE-031).** Resolve the arm with an explicit unavailability predicate, not
  truthiness: take the first arm whose class is **not** in the unavailable sentinel set. Flip test is clean:
  CD19/DLBC + NTRK1/THCA move `unmeasured` → `absent`; **DLL3/SCLC stays `unmeasured`** (SCLC genuinely absent
  from the product), so the fix separates mislabelled floors from real gaps rather than blanket-converting.
- **Status:** ✅ FIXED (root fix, `_skills_common/genomic_claims.py`). One shared `_recurrence_class(h, *fallbacks)`
  resolver now takes the first candidate whose class is **not** a declared unavailability sentinel, keeping the
  pooled → per-indication → per-class precedence otherwise intact, and returning the first *present* value when
  every candidate is unmeasured so the evidence prose still says `data_unavailable` rather than `None`.
- **★ Correction to the blast radius above: it is FIVE surfaces, not four.** Re-grepping the file rather than
  trusting the filed list turned up `:536` `cav_snv` — the **caveat narrator**: *"Not a recurrent SNV driver —
  {…} recurrence"*. That is the one surface that narrates the negative, so it sat squarely in the fail-open
  direction the case describes, and a fix routed through only the four filed sites would have left the
  user-visible sentence still quoting `data_unavailable` while the tier beside it read `absent`. Grep the file,
  not the case note.
- **★ The sentinel set is DERIVED, not restated:**
  `_UNMEASURED_RECURRENCE = frozenset(k for k, v in _RECURRENCE_SIGNAL.items() if v == "unmeasured")`, so a new
  unavailability token joins by declaration — the hardcoded-set failure mode from
  `derive the check's OWN population`. A class **absent** from the map is deliberately *not* skipped: an
  unrecognised token is an unknown band, not a declared sentinel, and skipping it would silently drop a
  newly-added real band. Both directions are pinned
  (`test_unmeasured_recurrence_sentinel_does_not_shadow_a_measured_class` asserts the `some_future_band` case
  survives), and the set is additionally pinned **by name** so a rename cannot leave the guard green over ∅.
- Corrects CASE-029's residual from "3 blind" to **1 genuine coverage gap**. Falsified by restoring the
  or-chain: exactly the two new guards redden, including the fan-out one.

### CASE-033 — the ledger's atlas-exclusion hint is a SUBSTRING MATCH ON PROSE: 17 of 17 misroutes, 0 correct routes — FIXED (2026-09-13)

- **Surfaced by:** the baseline→re-run comparison. `staleness_gap` went **14 → 17** while total blind spots
  went 65 → 60 — a class that grew while its population shrank. A routing split that moves against its own
  population is keyed on something that is not the population.
- **Determination (measured, all 17).** `build_discordance_ledger._is_atlas_excluded` matches
  `_ATLAS_EXCLUDED_HINTS = ("pharmacovig", "splice", "exon skip", "exon-skip")` against
  `f"{assertion} {axis_key}"`, and for a `blind_spots[]` row the assertion is the concatenation
  `f"{signal}: {why_omics_blind}"`. `why_omics_blind` routinely **enumerates what the package DOES
  measure** — *"the genomic-alteration omics measure DNA-level SNV/CN/fusion/splice…"*, *"outside the
  SNV/CN/fusion/splice omics"*. So the hint fires on the **negated mention** of the axis.
  **All 17 `staleness_gap` rows matched on `'splice'`, and not one of them is about splicing** — they are
  protein-IHC (BRG1, FRα, TrkA, MET, MDM2, FGFR3), oncometabolite 2-HG (IDH1, IDH2), non-coding RNA
  (MYC, MDM2), antigen loss under therapy (CD19, DLL3), and drug-resistance states (BRAF, ERBB2). Precision
  **0/17**.
- **★ And the mechanism was VACUOUS for the case it was written for.** A genuine SPL-axis row carries
  `axis_key == "SPL"`, which contains none of the hints, and the 20 SPL axis reads were 19 `agree` + 1
  `extends` (no rows). So on this corpus the hint fired **17 times, all wrong, and 0 times right** —
  simultaneously a false-positive generator and dead code for its purpose. Cost: 17 rows demoted a severity
  tier (3 → 2) **and routed to the wrong owner** ("route to the atlas session" instead of "data/axis need").
- **Fix — DONE, in this PR.** Route on the **declared axis key**, never on prose:
  `_ATLAS_EXCLUDED_AXES = {"SPL"}` matched against `axis_key`, plus the existing skill-level allowlist. A
  `blind_spots[]` entry declares no axis, so it can no longer be atlas-excluded by wording. Guarded both
  directions: a genuine `SPL` gap **must** route to `staleness_gap` (the previously-unreachable true positive)
  and a blind-spot whose `why_omics_blind` text says "splice" **must not**.
- **Status:** ✅ FIXED. Re-scored the pinned corpus through the fixed builder with the real
  `_load_calibration_targets`: `staleness_gap` **17 → 0**, `blind_spot_gap` 43 → **60**,
  `n_actionable` **46 → 63** (staleness is non-actionable, so 17 real data/axis needs were being
  filed as someone else's problem). The **sharp set is unchanged at 3** (`calibration_gap` 2,
  `verdict_rule_gap` 1) — the fix moves only the blind-spot/staleness split, exactly as intended.
  Falsified against the pre-fix predicate reconstructed in memory (both halves reverted — the
  predicate body *and* the call site; never mutate a live file to test it): **3 of the 4 new guards
  redden** — the previously-unreachable SPL true positive, the CASE-033 false positive, and the
  structural "identical-except-prose must classify identically" pin. The fourth
  (`test_non_excluded_axis_key_still_routes_to_blind_spot`) correctly stays green both ways; it is the
  anti-vacuity companion. `eval/tests/` **131 passed**.

### CASE-034 — the `ROLE` claim axis is in the claim_vector but NOT in the lens roster, so the alteration-role axis is UNCOMPARABLE — and `skill_report` never enters the corpus (2026-09-13)

- **Surfaced by:** both pre-registered predictions of this run coming back unanswerable (above).
- **Determination (measured).** The genomic `claim_vector` carries 6 real axes (`SNV`, `CN`, `FUS`, `SPL`,
  `DEP`, `ROLE`, plus a `_disclaimer` key). The literature lane's axis roster comes from the fleet
  `LensConfig`, which declares 5 — **`ROLE` is absent**. Across 20 records, `axes[].axis_key` is
  `{SNV:20, CN:20, FUS:20, SPL:20, DEP:20}` and **ROLE: 0**. So `alteration_role` — the axis AM #604 just
  changed for four surface antigens, retracting `direct_driver_gof` → `curated_cancer_gene` — cannot be
  compared against literature by construction. A `contradicts` on the driver axis is not merely unfired: it
  is **unaskable**.
- **The second half is the record shape.** No snapshot record carries `skill_report`, so `modality_scope`,
  `alteration_role` and `subgroup_signals` are invisible to the ledger. This is exactly the Stage-1b
  "passthrough is its own slot" case: a field can be narrated on the dashboard and still be invisible to
  every eval harness, the literature lane and the discordance ledger. Three of the four fields skills #1313
  v2.18.0 repaired are in this state.
- **Fix — FILED, two parts, both outside this branch's `eval/` scope for the first half.** (a) Add `ROLE` to
  the genomic lens axis roster so the role axis is queried — with a guard asserting **every non-`_`-prefixed
  `claim_vector` axis appears in the lens roster**, derived from the claim vector rather than restated, so the
  next axis split (the SPL-out-of-FUS shape) cannot open this hole again. (b) Capture the `skill_report`
  projection into the harvest record. Note (a) changes what the model is asked and therefore the prompt hash —
  it needs a fresh corpus, not a re-score.
- **Status: ✅ BOTH PARTS FIXED (skills `fix/lens-roster-claim-axis-coverage`, 2026-09-13).** The role-axis
  concordance rate is now quotable **from a fresh harvest only** — see the corpus note at the end.

#### ★★The guard found the defect is THREE skills and NINE axes, not one

Writing (a)'s coverage guard as *derived* rather than as a genomic-specific assertion is what surfaced the
rest. Introspecting every `ClaimSpec` roster under `_skills_common/*claims*.py` and comparing each against
the lens that narrates it:

| skill | claim axes | on the lens roster | UNASKABLE |
|---|---|---|---|
| `genomic-alteration-profile` | 6 | 5 | `ROLE` |
| **`on-target-safety-liability`** | **8** | **1** | `CONSTRAINT` `BURDEN` `DOSAGE` `CLINVAR` `MOUSE_KO` `PAN_ESSENTIAL` `NORMAL_TISSUE` — **7 of 8** |
| `surface-modality-fit` | 6 | 5 | `PMHC` |

Safety is the severe one: every safety-lane literature read ever taken compared **one axis out of eight**,
while the lens *thesis* enumerates all of them by name (gnomAD constraint, gene-burden, ClinGen dosage,
ClinVar, mouse-KO, pan-essentiality). So this was an incomplete roster, never a scoped exclusion — and its
`questions.yaml` already carries all 8 `axis_id`s, i.e. everything downstream was ready and only the roster
was short. The other 13 lenses cover their rosters exactly. **Fixing only the filed instance would have left
7 of the 9 unaskable axes unaskable** — the same instance-vs-symmetry trap as CASE-031's deletion arm.

#### ★★A roster is not one surface: `axis_labels` feeds THREE consumers, and one of them TRUNCATES

`axis_labels` is read by `axis_measured_state` (the literature prompt), `render_narrator_signals` (the
narrator rows) **and** `literature_retrieval._lens_terms`, which caps the Europe-PMC query terms at 5 by
default. Measured, before any cap bump: completing the safety roster pushed 8 axes past that cap and
truncated `PHARMACOVIGILANCE` — *the single axis the lens previously queried on* — plus all 4 curated
discriminators, straight out of the query. **Declaring an axis would have NARROWED retrieval.** Fixed with
`_LENS_MAX_TERMS` = (axes + curated) for each of the three lenses, and pinned by
`test_every_axis_label_survives_the_literature_query_cap` over **all 16** lenses. Generalises: when one
declaration feeds several consumers, growing it is only additive for the consumer you were thinking about.

#### ★Two crosswalk gaps remain, and they are CONTRACTS-side — filed, not fixed here

The evidence-graph `axis_id → question_ids` crosswalk fails **soft** (`axis_to_questions.get(axis_id, [])`),
so an axis with no `axis_id`-tagged question yields a recorded-but-unattached literature read. Measured over
all 16 lenses × their `questions.yaml`: only **2** such gaps, both newly exposed by this fix — genomic `ROLE`
(no question at all) and surface `PMHC` (its `pmhc_tce_route` question is tagged `axis_id: FIT`, so the FIT
axis absorbs a pMHC read). Both fixes belong in target-contracts `vocabularies/target_profiling_axes.yaml`,
because `question_hierarchy.yaml` is GENERATED from it and `alteration_role` currently sits under the **SNV**
sub-group there — retagging `questions.yaml` alone would manufacture exactly the
[displayed-vs-scored two-files-route-the-same-axis](../skills/tests/test_question_hierarchy_drift.py) drift.
**This does NOT block the role-axis concordance read**: `build_literature_prompt` reads `claim_vector` +
`axis_labels` only, never `questions.yaml`, so the crosswalk leg can land later without invalidating a
corpus harvested now.

#### Part (b) — `skill_report` in the harvest record

`harvest_pair` now carries a `skill_report` projection (`call`/`role`/`polarity`/`honest_phrase`/
`confidence`/`top_tension`/`claim_chips`/`claim_scalars`/`modality_scope`/`provenance`). Declared as a
**bulk-key EXCLUSION** set (`evidence_graph`, `figures`, `per_phase_metrics`, `question_table`) rather than
an include-list, so a decision-bearing key added to the spine later is carried automatically — an
include-list would silently omit precisely the coordinate the next case needs, which is this case one level
up. `_skill_report_dropped_keys` records what was removed on each run, and a sub-skill composing no spine
records `None`, not `{}` (gap ≠ absent).

#### Falsification (round-trip writes, never `git checkout --`)

Six mutations, each firing only on its own guard: drop `ROLE` from the roster → 2 red; drop the safety
`_LENS_MAX_TERMS` bump → 2 red (the truncation guard + the pharmacovigilance pin); drop the 7 restored
safety axes (the pre-fix trunk state) → 2 red; drop one `claim_spec_ref` → 2 red (orphan roster + the exempt
set going silent); drop `skill_report` from the record → 3 red; capture the spine with no bulk exclusion →
1 red. Restored: 49 + 15 green.

- **★CORPUS:** (a) changes what the model is ASKED on three lenses, so the prompt hash shifts. Any panel
  re-measure must be a **fresh harvest**, never a re-score of `eval/literature-snapshots-*`. Until that
  harvest runs, the 0 contradicts on `ROLE` is still an absence of measurement — do not quote it.

### GENOMIC-ALTERATION 20-pair literature panel baseline (2026-09-12) — 20/20 emitted, 71 ledger rows, 6 SHARP (3 calibration + 3 verdict_rule), all on the CN axis

Ran `--panel genomic-alteration-profile-20 --literature-scope gating` (registered in
`eval/harvest_literature.py::_PANELS` by this PR) → `eval/discordance_ledger.genomic20.json` (gitignored).
Six strata: SNV recurrent-driver + controls, CN-amplification drivers, fusion drivers, the MET/LUAD
METex14 splice driver (exercises the SPL axis just split from FUS in #757/#1339), biomarker-stratified
dependency / mutation-drug-response (IDH1/2, FLT3, PIK3CA), and CN-deletion TSGs + three negative antigen
controls (CD19/DLL3/FOLR1). All 20 indication codes resolve in the crosswalk. by_gap_class:
`{calibration:3, verdict_rule:3, blind_spot:51, staleness:14}`. Every one of the 6 SHARP rows carries ≥1
VERIFIED citation (confabulation_risk=False) and lands on the **CN axis** — the panel discriminates (it is
not blunt: the controls KRAS/COADREAD + BRAF/SKCM read `agree` across all axes).

**★ ROOT CAUSE (one gap explains 5 of the 6, live-probed).** The SNV claim signal (`genomic_claims._snv_signal`)
is keyed on tumor-level `pooled_driver_recurrence_class` from `gdc_somatic_hotspot`, whose MC3 hotspot
product (`data-catalog tcga-mc3-hotspot-frequency-v1`) ships **only 4 indications: COADREAD, NSCLC, GC,
PAAD** (v1). Direct probe: `read_hotspot_summary` returns `data_unavailable` / `n_samples_mutated=0` for
IDH2/AML, IDH1/GBM, FLT3/AML — all canonical high-recurrence drivers — while KRAS/COADREAD reads `top_1pct`
(42%, 235 samples). So for every indication off those 4, the SNV recurrence axis is BLIND, and the
multi-class collapse fills the vacuum from a lower axis. This is a data-coverage gap, not a skill bug — but
it has a verdict-moving downstream (CASE-028).

### CASE-028 — IDH2/AML reads `confirmed_driver` DRIVEN BY A CELL-LINE FOCAL DELETION of an activating oncogene (verdict_rule_gap) — CONFIRMED

- **Surfaced by:** genomic-20 panel, CN axis, `contradicts` vs Abou Dalle 2018 (verified). Literature: IDH2
  is an activating R140/R172 SNV driver in AML (enasidenib-actionable); recurrent focal DELETION is not a
  described mechanism.
- **Determination (live-probed):** claim_vector for IDH2/AML = SNV `unmeasured` (root cause above),
  CN `moderate`, ROLE `strong`; verdict `confirmed_driver`, **driving_rule `cn-recurrently-deleted-supportive`**.
  The resolver rung is `genomic_alteration.resolver.yaml:100` —
  `{when_all_fired: [cn-recurrently-deleted-supportive, alteration-role-gof-driver-supportive], verdict:
  confirmed_driver, driving: cn-recurrently-deleted-supportive, priority: 30}`. A recurrent DELETION paired
  with a **GoF/activating** role is contradictory: a deletion is not the activating mechanism of an
  oncogene, so promoting it to `confirmed_driver` (over the blind SNV axis) is a false-positive driver. The
  LoF sibling (`:101`, `alteration-role-lof-driver-neutral → confirmed_lof_driver`) is correct — deletion
  IS the mechanism for a TSG; only the GoF pairing is wrong.
- **Fix — DONE (TC #760 `7f3975cf` resolver 1.9.0 + skills golden #1342 `669b1652`):** a CN deletion is a
  driver class only for a LoF/neutral role. Removed the 4 GoF+deletion multi_class rungs (fall to
  single-class confirmed_driver) and redirected the 2 GoF+deletion confirmed_driver rungs → mixed_pattern.
  Backtest replaying every panel target's live fired-set: IDH2/AML confirmed_driver→mixed_pattern,
  FGFR3/BLCA multi_class_driver→confirmed_driver, 13 others unchanged. Ratchet
  `test_a_deletion_never_confers_a_driver_verdict_on_a_gof_role` (falsified).
- **Status:** ✅ DONE. FGFR3/BLCA was the same family (multi_class over-crediting the deletion → now
  confirmed_driver). **MDM2/LGG is NOT this family** — it fired `cn-broadly-neutral` (not deleted) + missense
  → confirmed_driver, UNCHANGED by this fix; its `contradicts` was a missed AMPLIFICATION, so it belongs
  with CASE-030 (and is resolved there as an honest read).

### CASE-029 — SNV recurrence axis BLIND outside 4 indications → IDH1/GBM `mixed_pattern`, canonical R132 driver invisible (calibration_gap) — CONFIRMED

- **Surfaced by:** genomic-20 panel; the mixed_pattern gap flagged earlier for IDH1/GBM.
- **Determination:** IDH1/GBM claim_vector SNV `unmeasured` (GBM absent from the MC3 hotspot product),
  CN/FUS/SPL/DEP all `absent`, ROLE `strong` → verdict `mixed_pattern`, driving `mut-mixed-neutral`. IDH1
  R132 is THE defining LGG/GBM driver; the skill cannot see it. Same root as CASE-028; here it produces a
  false-NEGATIVE / uninformative read rather than a false driver.
CASE-029 has TWO coverage gaps, one per genomic axis. Both are materialized-product coverage limits (the
raw sources carry every cohort):

- **Patient-CN half — DONE (analysis-methods #617).** The CN axis (`tcga_patient_cn`) was blind for 20 of 33
  GISTIC cohorts: `INDICATION_TO_TCGA` mapped only 13, and `patient_cn_summary_for_gene` returns
  `data_unavailable` at the `if not codes` guard for an unmapped indication WITHOUT reaching the live-TSV
  fallback. So EGFR/GBM (44% high-level focal amp), CDKN2A/GBM homdel, and every driver outside the 13 read
  `data_unavailable` — a silent false-negative. Fix = map all 33 cohorts (AML→LAML the one alias); the new
  cohorts serve via the live-TSV fallback (product `tcga-patient-cn-per-gene-v1` still covers 13, so a
  rebuild is a speed follow-on). Verdict-moving downstream (un-blinds patient-focal CN for 20 indications);
  skills re-emit + backtest after #617 merges.
- **SNV-recurrence half — OPEN (data build, needs S3 publish).** `gdc_somatic_hotspot` is PRODUCT-ONLY (no
  live-MAF fallback): the MC3 product `tcga-mc3-hotspot-frequency-v1` ships only 4 indications (COADREAD,
  NSCLC, GC, PAAD), so IDH1/GBM, IDH2/AML, FLT3/AML etc. read `data_unavailable`. Fix = build the per-
  indication aggregate via `python -m methods.gdc_somatic_hotspot.cli --indication X` over the 718 MB MC3
  MAF for each missing indication, publish to the shared onc-compbio S3 bucket, register in the data-catalog
  manifest, re-emit. This is an outward, per-indication data-build workstream (writes production products to
  the shared bucket) — the durable root fix that un-blinds IDH1/GBM's `mixed_pattern` and de-fangs CASE-028's
  vacuum. **Gated on a go/no-go for publishing production data products.** GENIE (`genie_panel_recurrence`)
  is the parallel heme/panel-cohort source and would extend AML/DLBC coverage the MC3/TCGA cohorts lack.
- **Status:** patient-CN ✅ DONE (#617 pending CI); SNV-recurrence OPEN (data build). `blind_spot_gap`/
  `staleness` counts (51/14) are the fleet-wide tail of the SNV half.

### CASE-030 — MET/LUAD (and MDM2/LGG) CN `absent` vs an amplification literature — RESOLVED: honest read, no fix

- **Surfaced by:** genomic-20 panel, CN axis, `contradicts` vs Zeng 2026 + Sheng 2025 (MET), Yang 2022 +
  Guo 2023 (MDM2), all verified.
- **Determination (live-probed at the card level, `tcga_patient_cn`, TCGA GISTIC, focal bar = high-level +2
  in ≥10% of tumours):** MET/LUAD high-level focal amp = **2.2%** → `focal_neutral`; MDM2/LGG = **0.6%** →
  `focal_neutral`; MDM2/GBM = 8.2% → still `focal_neutral` (sub-10%). These are HONEST reads: MET amp in LUAD
  is a ~2-4% minority (largely an EGFR-TKI-resistance subpopulation the treatment-naive TCGA cohort
  under-represents), and MDM2 is not recurrently focally amplified in LGG. The literature "validated driver"
  refers to an actionable SUBSET, not population recurrence — a framing discordance, not an omics miss. Per
  the runbook, an honest low-frequency negative is documented, NOT forced.
- **The genuinely-amplified controls confirm the instrument works:** ERBB2/BRCA (11.5% high-amp) and
  CCND1/HNSC (23%) read `recurrent_focal_amplification`, and the claim_vector `_cn_signal` ALREADY elevates
  on `patient_focal_cn_class == recurrent_focal_amplification` (the pre-existing HER2/CCND1 fix), so they
  were NOT flagged by the panel. No claim-vector bug exists for CASE-030.
- **What CASE-030 DID surface** was the patient-CN coverage gap for MDM2/LGG (`n_samples=0` → the CASE-029
  patient-CN half, fixed in #617 — but even with coverage MDM2/LGG reads `focal_neutral` at 0.6%).
- **Status:** ✅ RESOLVED as honest. No code change. MET/LUAD's primary driver call (`splice_exon_skip_driver`)
  is correct; the missed amp is a real but sub-recurrence minority event.

### MECHANISM 20-pair literature panel baseline (2026-09-12) — 20/20 emitted, 73 ledger rows, **0 contradicts**

Ran `--panel mechanism-and-pharmacology-20 --literature-scope gating` (registered in
`eval/harvest_literature.py::_PANELS` by this PR) and built `eval/discordance_ledger_mech20.json`
(gitignored). The panel is 5 deliberate strata: RTK/kinase hubs + controls, non-signaling drivers,
surface antigens, SL/paralog, and phospho-PD readability.

| dimension | result |
|---|---|
| verdicts | 15 `well_characterized`, 5 `partial` |
| `overall_consistency` | 16 `concordant`, 4 `partially_concordant`, 0 `discordant` |
| axis reads (100) | 74 `agree`, 13 `extends`, 13 `omics_unavailable`, **0 `contradicts`** |
| ledger | 73 rows, **all** `blind_spot_gap`, all severity 3; 0 `calibration_gap`, 0 `verdict_rule_gap`, 0 `confabulation_or_unverified` |

**The panel's real predecessor was an AD-HOC run**, launched outside `_PANELS` from `/tmp/mech_panel`.
It produced discordances D1–D5, and D2 became the phospho-token retirement (target-contracts #746 →
analysis-methods #608 → skills #1326). Registering it is what makes the assessment repeatable — and
what put its pairs back under the two guards in `eval/tests/test_harvest_literature.py`. Dispositions
of the original five, re-read against this registered run:

- **D1** (non-signaling drivers under-read) — **still open, but for the first time trustworthy**: see CASE-023.
- **D2** (ALK phospho floor) — **CLEARED**: see CASE-024.
- **D3** (`has_actionable_moa` true on 20/20) — **reconfirmed and reclassified**: see CASE-027.
- **D4** (clinically-precedented guard) — **holds**: `has-pd-marker-supportive` fired 16/20 and every
  precedented target kept its supportive rung; nothing to file.
- **D5** (`curation_gap_note` false-positive on CEACAM5/MSLN) — **CLEARED**: the note is absent on all
  20 records including both surface antigens, confirming skills #1319 live.

**Zero `contradicts` in 100 axis reads is not self-evidently good news.** The token is reachable —
the FR panel produced 5 of 80 on the same harness — and the enum is not stuck here (13 `extends`,
13 `omics_unavailable`). The honest reading is that this panel has almost no discriminating power for
this skill: mechanism-and-pharmacology reads curated pathway/network facts about famous drivers, so
literature agreement is the expected outcome. A panel that cannot fail teaches nothing. The next
revision needs adversarial pairs — poorly-characterized or contested-mechanism targets — before its
concordance rate should be quoted as evidence of anything.

### CASE-023 — the ad-hoc mechanism panel read 5 of 20 pairs at DEGRADED PAN-SCOPE, and 4 of them were D1's evidence (2026-09-12)
- **Surfaced by:** registering the panel, not by running it. Five of the ad-hoc run's pairs used
  indication codes that are neither a `canonical_code` nor an alias in
  `target-contracts/vocabularies/indication_crosswalk.yaml`: `HGSOC`, `PLMESO` (×2), `DLBCL` (×2).
- **Why that is not cosmetic:** an unresolvable code resolves **no DepMap lineage** and the read
  quietly degrades to **pan-scope** — the documented EPAS1/RCC precedent — rather than erroring. The
  verdict still publishes, and it looks like a lineage read.
- **The damage:** four of the five sit in the D1 "non-signaling driver under-read" stratum, so **D1's
  original disposition was derived from degraded reads.** The finding may still be right; the evidence
  for it was not.
- **The guard already existed and had teeth.** `test_panel_indications_resolve_in_the_crosswalk`
  fails on exactly this shape (falsified by injecting `("ALK", "LUADX")`). The ad-hoc run bypassed it
  by never touching `_PANELS` — the guard is attached to the registry, not to the harvest path.
- **Fixed here:** codes corrected on registration (`HGSOC→OV`, `PLMESO→MESO`, `DLBCL→DLBC`,
  `COAD→COADREAD`) and the panel registered, which is what re-arms the guard.
- **Residual, OPEN:** `harvest_literature.py` itself still accepts an unresolvable `--pairs` code
  silently. The guard protects registered panels only, so any ad-hoc run remains free to publish a
  pan-scope read as a lineage read. The durable fix is for the harvest path to refuse (or loudly tag)
  a code that does not resolve, independent of `_PANELS`.
- **Status:** the crosswalk half FIXED; the ad-hoc-path half OPEN. **General lesson: a guard bound to
  a registry cannot protect the code path that skips the registry.**

### CASE-024 — D2 phospho-token retirement VERIFIED LIVE, but the distinction it bought is invisible downstream (2026-09-12)
- **Cleared:** `phospho-not-phosphoprotein-neutral` fires on **0 of 20** pairs. The retired token
  asserted biology (*this gene is not a phosphoprotein*) from a coverage floor. Replacement rungs
  distribute sensibly: 8 `phospho-data-unavailable-insufficient`, 6 `phospho-present-supportive`,
  4 `phospho-not-detected-neutral`, 1 `phospho-active-supportive`, 1 `phospho-low-neutral`.
- **ALK/LUAD, the original D2 case, is fixed end to end:** it now reads `data_unavailable`, its
  phospho axis returns `agreement_vs_omics: omics_unavailable` instead of a fabricated disagreement,
  and the pair moved `partially_concordant → concordant`.
- **The residual:** `data_unavailable` now covers **8 of 20 pairs (40%)** — AR/PRAD, BCL2/DLBC,
  BRAF/SKCM, EZH2/DLBC, IDH1/LGG, MSLN/MESO, TEAD1/MESO, ALK/LUAD — and **the record carries no
  reason**. Two very different states are collapsed: *CPTAC has no cohort for this indication at all*
  (PRAD, DLBC, MESO, LGG, SKCM are simply not CPTAC cohorts) versus *the cohort exists and the target's
  total protein is undetected in it* (the ALK/LUAD shape the fix was built for). The reader emits
  `phospho_axis_uninformative_reason` to separate them; nothing downstream reads it (CASE-025).
- **Status:** D2 CLOSED. The reason-collapse is OPEN and is really CASE-025's consequence.

### CASE-025 — the 4 summary_fields minted by the D2 fix are consumed by NOTHING in the skills repo (2026-09-12)
- **The mirror is one-directional.** target-contracts #746 declared and analysis-methods #608 emits
  `total_protein_detected_in_cohort`, `n_cohorts_with_phosphosites`,
  `phosphoprotein_detected_in_other_cohorts` and `phospho_axis_uninformative_reason`. A grep of
  `skills/` and `docs/` on trunk (excluding tests) returns **zero** references to any of the four.
  The card→reader guard checks *reader emits what card declares*; it is structurally blind to
  *nobody consumes what the reader emits*.
- **Concretely:** `claim_vector.PHOSPHO.evidence_atom.values` passes through `phospho_activity_class`
  and `n_phosphosites` only. So the harvested record — and therefore the ledger, the literature lane
  and any cross-evidence consumer — sees a bare `data_unavailable` on 8 of 20 pairs with no way to
  tell a missing cohort from an undetected protein. **The fix is correct at the reader and inert at
  the skill.**
- **Proposed fix:** propagate the four fields into the PHOSPHO `evidence_atom` values and narrate
  `phospho_axis_uninformative_reason` on the mechanism confidence caveat. Verdict-INERT.
- **Status:** OPEN, its own PR. Third instance of this exact shape (immune-context's six
  suppression/heterogeneity fields, TC #745/AM #607, is the second) — which argues for a **fleet-level
  emits→consumed guard**, not a third one-off patch.

### CASE-026 — axis_key NONDETERMINISM makes every per-axis panel statistic unsound, including the FR panel's (2026-09-12)
- **Surfaced by:** aggregating axis reads across the 20 records. **15 of 20 pairs** return the named
  axis keys (`NETWORK`, `PATHWAY`, `PERTURBATION`, `PHOSPHO`, `PREDICTABILITY`); the other **5 return
  generic `A`, `B`, `C`, `D`, `E`** — ALK/LUAD, CDK4/LUAD, CEACAM5/LUAD, CTNNB1/COADREAD, KRAS/PAAD.
  The lane's LLM is inventing ordinal keys instead of echoing the axis names on a quarter of pairs;
  nothing validates the key set.
- **Why it matters:** any per-axis roll-up silently under-counts. ALK/LUAD's phospho read is filed
  under `B`, so a query for "which pairs disagree on PHOSPHO" misses it and 4 others — a 25% blind
  spot that looks like a clean answer. This is the vacuous-statistic shape: the number computes, the
  denominator is wrong, and nothing fails.
- **It is not confined to this panel.** The FR panel baseline above quotes "80 axis reads — 41 agree,
  27 extends, 7 omics_unavailable, 5 contradicts" aggregated the same way, so those tallies carry the
  same defect. The per-pair verdicts are unaffected; only cross-pair per-axis aggregation is.
- **Proposed fix:** pin the axis key set in the lane's response schema and validate it on parse —
  reject/repair a record whose `axis_key` set is not the skill's declared axis enum, the same way
  citation verification already post-processes the lane. Cheap and mechanical.
- **Status:** OPEN. Blocks quoting per-axis concordance for any skill until fixed.

### CASE-027 — D1 persists on corrected codes (5 of 20 `partial`), and D3's `has_actionable_moa` is INVARIANT at 20/20 (2026-09-12)
- **D1, re-read cleanly:** 5 pairs read `mechanism-partial-neutral` — CEACAM5/LUAD, IDH1/LGG,
  MSLN/MESO, SMARCA2/LUAD, WRN/COADREAD. Every one is a non-signaling driver, a surface antigen, or an
  SL/paralog target; every kinase and pathway hub in the panel reads `well_characterized`. So the
  original D1 shape survives correction of the indication codes (CASE-023) — the skill's confidence
  scale is calibrated to **signaling** mechanism evidence, and reads a metabolic neomorph (IDH1), an
  antigen (CEACAM5, MSLN) or a synthetic-lethal partner (WRN, SMARCA2) as under-characterized when it
  is merely characterized in a different currency. IDH1/LGG is the sharpest instance: ivosidenib is
  approved and the 2-HG mechanism is textbook.
- **D3, reclassified:** `has_actionable_moa` is `true` on **20 of 20**. Zero variance means the field
  cannot discriminate on this panel, so it can neither support nor oppose anything — the vacuous-field
  shape. It may be defensible (all 20 are drugged or drug-adjacent), but it is then a *panel selection*
  artifact and the panel needs undrugged targets before the field's behaviour is observable at all.
- **Proposed fix (D1):** the mechanism confidence rungs need a mechanism-CLASS conditioning input so
  "well characterized" is judged against the evidence currency the target actually has (enzymatic /
  antigen-expression / partner-conditional), rather than against phospho-signaling evidence a
  non-kinase will never produce. Same family as CASE-018's `mechanism_mismatch`.
- **Status:** both OPEN. D1 is ranked #1 of this panel; D3 is a panel-design fix, not a code fix.

### FR 20-pair literature panel baseline (2026-09-12) — 20/20 emitted, 65 ledger rows / 62 actionable

Ran the `--literature` lane over 20 functional-requirement (target, indication) pairs spanning every
gate-C verdict family, then built the ledger (`eval/discordance_ledger_fr20.json`, gitignored) and
diffed it against `eval/discordance_baseline.json`. Verdicts as harvested:

| verdict | pairs |
|---|---|
| `lineage_selective` | EGFR/LUAD, BRAF/COADREAD, KRAS/COADREAD, MDM2/UVM, GATA3/NBL, IRF4/DLBC, SPI1/AML, STAG2/BLCA, MAPK1/COADREAD, SOX10/SKCM |
| `partner_conditional_dependent` | WRN/COADREAD, SMARCA2/LUAD, EPAS1/KIRC |
| `non_dependent` (gate VETO) | PARP1/BRCA, AR/PRAD, CD19/DLBC |
| `pan_essential_killer` | PLK1/OV, RBM39/AML |
| `discordant` | PRMT5/MESO — **now `partner_conditional_dependent`** under resolver v1.4.0 (TC #743); the snapshot predates the merge |
| `non_dependent_paralog_buffered` | ERBB2/BRCA — the inflated-paralog case, see FIX 1 |

Axis reads: 80 total — 41 `agree`, 27 `extends`, 7 `omics_unavailable`, **5 `contradicts`**. Ledger:
1 `calibration_gap`, 3 `verdict_rule_gap`, 58 `blind_spot_gap`, 2 `staleness_gap`, 1
`confabulation_or_unverified`. All 5 `contradicts` rows are accounted for below (3 = CASE-017,
1 = CASE-018, 1 = CASE-020) — the panel produced no unexplained contradiction.

**Fixes already landed off this panel:** FIX 1 = the paralog-buffering `max()`-baseline defect
(CASE-022; analysis-methods #606 + data-catalog #593); FIX 2 = `partner_conditional_dependent`
raised above `discordant` / `insufficient_underpowered` / `non_dependent_paralog_buffered`
(target-contracts #743 resolver v1.4.0 + skills #1322 golden, 374/8,640 frozen rows moved). FIX 3 =
the ledger-diff scope guard in this PR (CASE-021).

### CASE-017 — AR/PRAD is the panel's only fully DISCORDANT lane: 3 of 4 axes contradict a `non_dependent` VETO on an approved target (2026-09-12)
- **Surfaced by:** the FR 20-pair literature panel. AR/PRAD reads `non_dependent` via
  `non-dependent-killer` (a gate VETO) while the lane returns `overall_consistency: discordant` with
  DEP, SEL and CHEM all `contradicts` — DEP and SEL at `confidence: high`, and every citation
  VERIFIED (3/3, 2/2, 3/3). No other pair in the panel contradicts on more than one axis.
- **Why the framework is not simply wrong:** AR in DepMap CRISPR is genuinely not a strong pooled
  dependency — most PRAD lines are cultured androgen-independent, so the screen measures a
  ligand-deprived state the clinic does not. The lane is reading the CLINICAL dependency (enzalutamide,
  abiraterone, AR degraders) which is real and approved. Both are correct about different states.
- **The gap:** there is no rung for "dependency conditional on an EXOGENOUS LIGAND / culture context".
  `partner_conditional_dependent` requires a genetic partner stratification; AR needs a
  *hormone/microenvironment-conditional* stratification. Absent that, the pooled negative wins and the
  gate VETOES an approved target on its best-established axis.
- **Proposed fix:** a `context_conditional_dependent` rung keyed on a ligand-dependence card
  (androgen/estrogen/growth-factor withdrawal arms exist in the CRISPR metadata), sibling to the
  partner-conditional rungs and at the same precedence — i.e. above `non_dependent`. Do NOT reach for
  a curated AR exemption; that is the single-example overfit this loop exists to avoid.
- **Status:** OPEN, ranked #1 of the panel. Blocked on a ligand-context card (no data build yet). The
  3 rows are NEW sharp gaps in the ledger diff and are deliberately left in the queue, not baselined.

### CASE-018 — PARP1/BRCA + CD19/DLBC: a MECHANISM-MISMATCH class the lens vetoes instead of naming (2026-09-12)
- **Surfaced by:** the same panel. `non-dependent-killer` (gate VETO) fired on 3 of 20 pairs, twice on
  clinically validated targets, for two DISTINCT reasons that share one shape.
- **PARP1/BRCA** (`calibration_gap`, COND axis, `contradicts` at high confidence, 3/3 verified
  citations): the claim vector reads `not_partner_stratified` even though `PARP1: [BRCA1, BRCA2]` IS
  curated. This is genuine biology, not a lookup miss — PARPi is DNA-trapping, a gain-of-toxic-function
  that whole-gene KO does not phenocopy, so the CRISPR partner-stratification test correctly finds
  nothing. The framework is right about the KO and wrong about the drug.
- **CD19/DLBC**: a surface antigen whose therapeutic mechanism is redirected cytotoxicity. Cell-intrinsic
  essentiality is not the deciding axis at all; the same family as CASE-001/CASE-003.
- **The shared shape:** the modality's mechanism is NOT "loss of function of this gene." A KO-derived
  dependency scalar is the wrong estimator, and the honest output is *mechanism_mismatch — this axis
  does not adjudicate this modality*, not a veto.
- **Proposed fix:** a `mechanism_mismatch` disposition on gate C that SUPPRESSES the dependency veto
  (rather than inverting it to a positive) when the target's modality thesis is trapping / degrader-
  neomorph / redirected-cytotoxicity. Sits next to the existing `modality_scoped` suppression, and
  reuses `_fr_modality_fit`. Fails safe: suppression yields `hold`, never `nominate`.
- **Status:** OPEN. Two named instances plus the CASE-001/003/006 family; the strongest argument yet
  for making mechanism class a first-class input to gate C rather than a caveat string.

### CASE-019 — `lineage_selective` published alongside claim_vector DEP `absent` on 4 of 10 lineage pairs — REPORTABLE RISK, not a bug (2026-09-12)
- **Surfaced by:** the panel. GATA3/NBL, SPI1/AML, STAG2/BLCA and MAPK1/COADREAD all publish verdict
  `lineage_selective` while their claim-vector DEP atom reads `absent`.
- **Verified as designed:** the two slots answer different questions — DEP carries the POOLED
  dependency scalar (correctly `absent`), the verdict carries the LINEAGE-CONDITIONAL read. The split
  is intentional and each slot is individually honest.
- **The risk:** a reader (human or a downstream consumer keying on the claim vector) sees
  "selectively dependent" and "no dependency" in one package with nothing stating they are
  compatible. Two consumers already read the DEP atom directly (the discordance ledger's
  `claim_measured` test; the composed claim-vector spine).
- **Proposed fix:** emit the reconciliation explicitly — a note on the lineage rungs stating the DEP
  atom is the pooled estimator and is EXPECTED to read `absent` under lineage-conditional selectivity.
  Cheap, verdict-inert, and kills a whole class of misread. No resolver change.
- **Status:** OPEN (documentation/interpretation, low cost, no data dependency). Also the cleanest
  small win in the panel.

### CASE-020 — the literature lane's citation verification is RECENCY-BIASED: IRF4/DLBC's only high-confidence contradiction rests on two UNVERIFIED papers (2026-09-12)
- **Surfaced by:** the panel's `confabulation_or_unverified` row. IRF4/DLBC DEP is the panel's only
  DEP `contradicts` at `confidence: high` — and BOTH its citations (Yang 2012; Shaffer 2008) carry
  `pmid: None, verified: False`, while every other citation in the panel is a verified 2025/2026 paper.
- **Why it matters:** IRF4 in DLBC is textbook (the "IRF4 addiction" literature is foundational and
  pre-2015). The containment guard correctly demoted the row to `confabulation_or_unverified` — but for
  the WRONG reason. The claim is true; the verifier could not resolve an old citation. So the guard
  systematically discounts exactly the well-established biology, while a 2026 preprint passes.
- **Consequence for the loop:** every `contradicts` on a foundational mechanism lands in the discard
  tier. That is a silent, class-wide false-negative in the review queue itself — the instrument, not
  the framework.
- **Proposed fix:** measure it before fixing it — sample the lane's pre-2015 citations and compute the
  verification rate by publication year. If the bias is confirmed, either widen the resolver (title +
  first-author + journal/year lookup, not PMID-only) or split the class into
  `unverified_recent` (discard) vs `unverified_historical` (review), so an old-but-real citation is
  triaged rather than dropped.
- **Status:** OPEN, instrument-level. Same family as the CASE-005/RBM39 instrument self-catch — the
  panel again finding a flaw in its own measuring device.

### CASE-021 — the ledger diff reported 33 of 33 baseline gaps RESOLVED because it had no notion of the run's SCOPE — FIXED (2026-09-12)
- **Surfaced by:** diffing this FR-only panel ledger against the fleet baseline.
  `diff_discordance_ledger.py` computed `RESOLVED = baseline_keys - new_keys` over the whole baseline,
  so **all 33** baseline keys read as resolved: 28 belonged to skills this ledger never ran
  (tractability-small-molecule 15, on-target-safety 4, differentiation 3, surface-modality 3,
  tumor-selectivity 2, mechanism 1) and the other 5 to FR pairs outside the panel (CEACAM5/NSCLC,
  HIF2A/RCC ×2, PARP1/OV, STEAP1/prostate). **Zero were real.** The coarse trend was equally
  meaningless (`blind_spot_gap −1071`, `staleness_gap −127`).
- **Worse, `--write-baseline` compounded it:** it rebuilt the baseline wholesale from whatever ledger
  it was handed, so one scoped run would DELETE every out-of-scope key — destroying the review
  provenance the baseline exists to hold, and re-reporting all of it as NEW next full run.
- **Root cause:** a concordant pair emits zero rows, so the ROWS cannot distinguish "examined and
  clean" from "never in the corpus" — and nothing else recorded the corpus's scope.
- **Fix (this PR):** `build_discordance_ledger` now emits `covered` — the (skill, target, indication)
  triples the lane actually compared (schema v2.1), including concordant pairs and EXCLUDING
  skipped/errored lanes (a failed lane examined nothing). `diff_discordance_ledger` restricts RESOLVED
  to that scope, reports the rest as a new `UNCOVERED` class, marks the coarse delta comparable only
  at equal scope, and `--write-baseline` now MERGES (carrying out-of-scope keys forward) with
  `--replace-baseline` as the explicit opt-in for the old behaviour. Re-run: **RESOLVED 33 → 0,
  UNCOVERED 33, NEW 4** (the 3 AR/PRAD rows + PARP1/BRCA).
- **Ratchet:** `test_a_scoped_run_reports_out_of_scope_baseline_keys_as_UNCOVERED_not_resolved`,
  `test_write_baseline_merges_by_default_and_replaces_only_on_demand`,
  `test_covered_scope_includes_concordant_pairs_and_excludes_failed_lanes` and
  `test_covered_scope_predicate_is_shared_with_build_rows` — the last of which caught a real hole in
  the first cut of the fix (`literature_synthesis: None` read as "examined").
- **Status:** FIXED in this PR. The 4 NEW sharp gaps are deliberately NOT baselined — they are
  CASE-017 and CASE-018, and baselining them would silence the two findings the panel was run to find.

### CASE-022 — paralog buffering measured against the LEAST-lethal single KO: 35.7% of pairs over-classified, and it was DECIDING ERBB2/BRCA — FIXED (2026-09-12)
- **Surfaced by:** the panel. ERBB2/BRCA read `non_dependent_paralog_buffered` via
  `strong-paralog-buffering-degrader-preferred` — driven by a PTK2 "buffering" delta of **+0.731**.
- **Root cause:** the metric used `max(single_ko_a, single_ko_b) - median_dual_ko`. On the DepMap
  Chronos scale more-negative = more lethal, so `max()` selects the **LEAST** lethal single KO. For any
  pair with one baseline-essential member the delta collapses to that member's own essentiality and
  reports buffering where there is NO genetic interaction — the exact artifact a paired-vs-single delta
  exists to remove. ERBB2's +0.731 was PTK2's own gene effect (−0.637); corrected it is +0.156 = `none`.
- **Measured cohort impact** (same input bytes, only the baseline changed): **2,726/7,627 pairs (35.7%)**
  and **1,782/4,475 genes (39.8%)** reclassify, every change a DOWNGRADE. strong 836 → 281, partial
  1,710 → 814, none 1,929 → 3,380. **1,384 genes (30.9%)** named the wrong `strongest_partner`. Even the
  product manifest's own `validation_anchor` was contaminated: PSPC1/SFPQ delta 2.87 was SFPQ's
  essentiality (−2.71) and corrects to 0.42. True-redundancy anchors survive (VPS4A/VPS4B 1.55 → 1.38,
  ASF1A/ASF1B 1.82, STAG1/STAG2 1.02 → 0.82) — the fix does not break real paralog biology.
- **Fix:** `min()` baseline in `depmap_paralog_aggregator` (analysis-methods #606, reader 0.4.0, emitter
  `METHOD_VERSION` 2.0.0 — a MAJOR bump because v1 and v2 rows are not comparable). The reader gained a
  fail-closed staleness gate keyed on the manifest's `parameters.delta_definition`, so while the shared
  S3 product still declares `max()` every read falls back to a corrected live recompute — correctness
  without a rebuild.
- **The shared product is deliberately NOT rebuilt** (data-catalog #593): v1's manifest keeps every field
  describing the bytes truthfully, with a boxed SUPERSEDED-METRIC header and an explicit *do not "fix"
  `delta_definition` in place* warning — editing that string without new bytes would certify the stale
  parquet and re-inflate every downstream read. v2 build spec: `specs/depmap-paralog-buffering-v2.md`,
  **pending explicit authorization** to upload.
- **Consequence, deliberately taken:** ERBB2/BRCA loses its paralog rescue and falls to a flat
  `non_dependent` veto. That EXPOSES a real gap — no HER2-amplification-conditional stratification rung
  — rather than hiding it behind an inflated metric. Same shape as CASE-017/018.
- **Also fixed:** the vacuous `test_paired_vs_single_delta.py`, which could not fail (it asserted the
  delta against the same `max()` expression it was testing).
- **Status:** FIXED (analysis-methods #606 and data-catalog #593 both merged). Residual = the v2
  rebuild authorization and the HER2-conditional rung.

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

## Release-readiness triage (2026-09-18) — plan `polymorphic-questing-zephyr` Step 3

`RELEASE_GATE.md` criterion 7 is satisfied by gaps **measured and triaged**, not closed. This
section sweeps every case marker into the three release buckets. It is added as one section
rather than rewritten status lines throughout the file, so the per-case records above remain
the source of truth and this is their release-lens rollup.

**Headline:** of the 35 case ids, ~20 already carry a terminal `✅ FIXED / RESOLVED / DONE /
DEMOTED / TRIAGED` status — they live under `## Open cases` only because the `## Closed cases`
section below was never populated, not because they are open. The genuinely-unresolved set is
small, and **under Step 4's decided scope (deterministic spine + honest ceilings, conservative
hold as the safe default), zero open cases block the release.**

**Reframe (2026-09-19, evidence-signals lens — arc `evidence_signals_and_subtype_dup`).** An earlier
cut of this triage indexed the residual items on the *verdict* (should surface biology DECIDE a GO,
should a safety gate LOOSEN). That is the framing the 09-17 arc corrects: **emit as a DIMENSION, not a
GATE** — surface the evidence signal faithfully and keep the verdict optional/conservative; a gateless
axis is reported-not-scored and is never a verdict member. Applying that lens dissolves most of the
"scientific-call" load below: two of the three items become buildable dimension-emits with no policy
fork (moved to Bucket B), and Bucket A is revealed as the reframe's *model* (report faithfully, don't
gate), not a compromise. The one genuine residual is a signal↔verdict *reconciliation* contract, not a
gate-loosening decision.

### Bucket 0 — already terminal (no release action)

FIXED / root-fixed: **CASE-008, -011, -014, -021, -022 (core), -031, -032, -033, -034**.
RESOLVED / honest-read / verdict-inert: **CASE-005, -012, -013, -030**.
DONE: **CASE-028**. DEMOTED by live data: **CASE-001**. TRIAGED (dismissed/scope-caveat):
**CASE-007 (core), -009, -010, -023 (crosswalk half), -024**. These need only to be promoted
into `## Closed cases` in a future housekeeping pass; they carry no open risk.

### Bucket A — known-gap-accepted (documented honest ceiling; non-blocking)

| Case | Gap | Disposition |
|---|---|---|
| **CASE-003** | DLL3-SCLC holds on gate-C; deciding axis (aberrant surface trafficking) blind | `honest_blind` in the calibration set; folds into the surface-antigen program. Represented in `capture_by_family` as `surface_antigen_biology {blind}`. Accept as documented ceiling. |
| **CASE-035** | DLL3-SCLC reads `bite_tce: unsafe` via the enteric-neuron veto the gut-organ promotion opened | ACCEPTED AS REAL — the ENS liability is defensible biology; findings (a)/(b) already filed for the normal-tissue safety panel. Not a logic bug; document and keep. |
| **CASE-019** | `lineage_selective` published alongside claim_vector DEP `absent` on 4/10 lineage pairs | REPORTABLE RISK, not a bug. Cheapest small win: a verdict-inert reconciliation note. No data dependency. Accept + optional doc note. |

*Bucket A is the reframe's model: each is a signal surfaced faithfully without gating. CASE-019 is its
cautionary edge — a surfaced signal that visibly diverges from the verdict — and is exactly the floor
the Bucket C reconciliation contract must clear.*

### Bucket B — needs-build (named owner + queued; non-release-blocking)

| Case | What must be built | Owner / gating |
|---|---|---|
| **CASE-029** (SNV half) | per-indication MC3 hotspot-recurrence aggregates, published to shared S3 | data-build; **gated on your go/no-go for publishing a production data product** |
| **CASE-004** | antigen-DENSITY capture axis | data-build from existing catalog; verify vs a fresh FOLR1/TROP2 emit first |
| **CASE-002** (residual) | METex14 genomic-fidelity classifier (signal-vector, not veto) | data+method+card build; QUEUED as a real (non-false-alarm) build |
| **CASE-006** | CNDP2-COADREAD neomorphic-GoF fidelity | genomic/GoF data build |
| **CASE-007** (method) | co-occurrence temporal-context method + card | cross-repo build (analysis-methods + contracts) |
| **CASE-017** | ligand-context card for a `context_conditional_dependent` rung (AR/PRAD) | data build; ranked #1 of the FR panel |
| **CASE-022** (residual) | v2 paralog rebuild + HER2-conditional rung | needs rebuild **authorization** + build |
| **CASE-020** | recency-bias instrument for the literature lane | measure-first (instrument), then build |
| **CASE-025** | fleet-level `emits → consumed` guard (4 orphan summary_fields) | engineering; verdict-inert; its own PR |
| **CASE-026** | pin the `axis_key` set → deterministic per-axis panel stats | engineering; verdict-inert (per-pair verdicts unaffected) |
| **CASE-023** (residual) | `harvest_literature` should refuse unresolvable codes | engineering; ad-hoc-path half |
| **CASE-018 / -027-D1** | emit `mechanism_mismatch` as a first-class DIMENSION (PARP1/BRCA, CD19/DLBC) — **no gate-C wiring** | engineering; verdict-neutral. **Re-bucketed C→B under the reframe**: the defect is a signal the lens *vetoes instead of naming*, so name it |
| **CASE-016** | surface the surface/immune thesis as a first-class DIMENSION; verdict stays conservative | engineering; verdict-neutral. **Re-bucketed C→B**: the question was never "should surface DECIDE a GO" but "is its signal shown on its own axis" |

### Bucket C — needs-your-scientific-call (signal↔verdict reconciliation; NOT verdict-loosening)

Under the reframe this collapses to **one** genuine call. CASE-016 and CASE-018/-027-D1 moved to
Bucket B as dimension-emits (surface the signal, leave the verdict conservative — no policy fork).

- **CASE-015 — the signal↔verdict reconciliation contract.** The old framing ("extend the suppressor
  to *loosen* a safety gate on context-constrained genes") was the verdict-indexed version. The
  reframe: surface the context-conditional-safety **signal** faithfully as a dimension and leave the
  veto conservative. But safety-negative signals hit a floor the reframe does not clear — **CASE-019's
  exact shape**: a faithfully-surfaced "safe-in-context" signal sitting next to a still-vetoing verdict
  is a self-contradicting output. So the residual decision is not "loosen the gate" but: **when a
  surfaced signal and the conservative verdict diverge, which does the consumer act on, and how does the
  output say so?** That is a presentation/reconciliation contract, and it is yours. Composed-backtest
  phases 3–4 (surface/biologics) + the per-axis backtest tool remain as the supporting build; CASE-027-D3
  (panel-design) rides along.

**Release conclusion:** criterion 7 is met. No Bucket A/B item blocks the cut; the single Bucket C
residual is a reconciliation-contract decision, not a gate change, and the conservative verdict ships
regardless. The one precondition already discharged is Step 2's conservative fall-through (PR #1461,
squash `91300d5e`) — the framework now *holds rather than nominates when blind*, and (per the reframe)
its own catch-instrument `nominated_while_blind` is a reported-not-scored dimension: the model this
triage now follows.

---

## Closed cases

_(none yet — first turn lands under CASE-001)_
