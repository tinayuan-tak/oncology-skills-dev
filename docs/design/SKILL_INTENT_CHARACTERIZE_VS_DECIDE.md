# Skill Intent — Characterization Foundation, Decision Primacy (the seam)

**Status:** Decided (strategy) 2026-07-19. Rules on the target-evaluation skill's core
intent: is its output a *target-relevance characterization* (a portrait/score) or a
*go/no-go decision* (a gated call naming the deciding axis)? A 3-agent review
(characterization-primary advocate, decision-primary advocate, adversary on the seam),
grounded in the shipped code + the known-target fidelity data (`known_target_calibration_set.yaml`
`reference_profiles`), ruled. Companion to `KNOWN_TARGET_FRAMEWORK_REFRAMES.md` (extends
Reframes 1–3), `GATE_SCAFFOLD_MODALITY_CONDITIONAL.md`, `RISK_ASSESSMENT_INTEGRATION.md`.

Portable GFM (no Mermaid/HTML) per README format rules.

## Ruling (one line)
**BOTH, LAYERED — conditionally.** Characterization is the *foundation* (reusable,
modality-agnostic, continuous-evidence storage); decision is the *primary intent* (it
governs what characterization gets built and with what veto power — "build-to-decide, not
characterize-then-hope"). The layering is only honest if two seam-invariants are enforced,
each with a build-failing validator. The primary human-facing output leads with a **decision
record + deciding-axis coverage**, not a relevance score.

## Why not either pure frame
- **Not pure characterization.** The known-target data shows a scalar "relevance" blurs the
  two things a decision must separate: "not relevant" vs "relevant but undruggable-by-this-
  modality." Empirically that blur is fatal — STEAP1 (winner) and MUC13 (loser) get the
  IDENTICAL framework output (`deciding_axis_coverage: blind`, `honest_blind`) because both
  hinge on surface-E2 axes the framework can't see. A portrait cannot express "biologically
  maximally relevant AND a hard no-go" (PSMB5, vetoed as pan-essential) or "right-verdict,
  wrong-reason" (HER2, passes gate C on dependency but its deciding E2/F axes are blind).
- **Not pure decision.** A decision on an incomplete characterization is confidently wrong —
  the 4 `dangerous_false_positive` cases (ADAR1, RBM39, CLDN18.2×LRRC15, EGFR×cMET×VEGF) are
  exactly that. Characterization must remain the reusable substrate (Layer-1 atoms serve
  non-decision consumers: the knowledge graph, exploratory biology, other modalities).
- **Not collapse to one object.** Even the adversary rejected collapsing: a single "decision
  that cites its evidence" lets the confident verdict absorb the caveats (worse blindness); a
  "portrait with no decision" abandons the genuinely valuable kill-only one-directional gate.

## The corrected roles (this is the real content, not "we'll do both")
- **Characterization = FOUNDATION.** Storage of continuous, power-tagged evidence atoms;
  modality-agnostic; compute-once/read-many (`evidence.json`). Keep this — it is right.
- **Decision = PRIMARY INTENT.** Determines *which* axes to characterize, *at what
  resolution*, and *what gets veto power*. The known-target backtest proves characterize-first
  builds the wrong things: budget went to deepening the one wired dependency mode (pooled
  CRISPR) while the axes that actually seed NO-GO decisions (normal-tissue-surface window,
  immune/TME, avidity) have zero representation. Build-to-decide reverses that.
- **Output object leads with the decision, not a score:**
  `{call, deciding_axis, framework_can_evidence ∈ {captured|partial|blind|license_blocked|
  out_of_scope}, modality, supporting_convergence[], killing_axis, route_to}`.
  The `framework_can_evidence` field IS the abstention router (Reframe 3) — "I cannot decide
  this; the deciding axis is blind — route to X." More useful to a committee than a fabricated
  score (the framework's own stated best property; the HTR1D/CDH17 abstention proved it —
  the rival RNA-convergence *characterization* engine ranked those losers #1).

## The TWO non-negotiable seam-invariants (each needs a build-failing validator)
The review's core finding: the seam is real where it's cheap (the `overall_recommendation`
enum) and absent where it's expensive (everything a committee actually reads). Two leaks
must be closed or "both, layered" is an evasion:

1. **Card layer — continuous-in / threshold-out.** A characterization atom emits rich,
   un-thresholded, power-tagged evidence; ALL thresholding happens in the decision consumer.
   Today VIOLATED at the highest-stakes gate: gate C thresholds a pooled scalar
   (`fraction_strongly_dependent`) into `common_essential`/`non_dependent` INSIDE the card and
   vetoes on it — the exact early-thresholding the architecture forbids. Fix = the typed
   dependency record `{mode, context, magnitude, confidence}` (`GATE_SCAFFOLD` §typed-record).
   Validator: a card may not emit a pre-thresholded categorical as its only signal for a
   verdict-gating field.

2. **Human layer — nothing ungated above the verdict.** No un-gated field may render with
   more prominence, or earlier in reading order, than the gated verdict + its deciding-axis
   coverage. Every prominent element (executive summary, arguments-for/against, risk grid,
   the "at a glance" figure) must EITHER be a deterministic function of the gated sub-verdicts
   OR be quarantined below the verdict in a labeled "non-reproducible narrative context"
   block. This is the F2 attention-mediated leak `RISK_ASSESSMENT_INTEGRATION.md` ALREADY
   named and mandated-for-literature — extended to ALL LLM prose. Today VIOLATED: the LLM
   executive summary + risk grid render above the sub-verdict table, and the LLM can argue
   FOR a target while the gated verdict says veto (two un-reconciled decisions on the page).
   Validator: fail the build if an ungated field renders above the gated verdict.

Until both validators exist, the seam is a disclaimer ("committees should cite the extract"),
not an architecture.

## Two structural corrections the ruling forces
- **Modality is FIRST-CLASS, not a post-hoc lens.** Resolves the open (a)/(b) fork in Reframe
  2 toward (b). The reference data shows *modality changes which axis decides*: CD19/TROP2/DLL3
  are non-dependency-required — dependency is irrelevant to whether a TCE works, yet the
  modality-blind gate C would veto all three. The same antigen is a GO as an ADC and a NO-GO
  as an SM. Modality must select *which gates are load-bearing and which may veto* before the
  decision, not reweight a modality-agnostic portrait after.
- **GO/NO-GO asymmetry is explicit.** NO-GO is disjunctive (one decisive negative kills — no
  convergence needed); GO is conjunctive (nomination requires convergent positives: ≥2
  independent dimensions, ≥1 dominant — already in the positive-tier config). A relevance
  scalar is symmetric and cannot hold this.

## Honest caveats (recorded so the ruling isn't over-sold)
1. **Decision-first buys triage honesty, not predictive lift.** On the deciding axis the
   framework is blind either way (approved-biologics nominable-on-merit 0/10; approved-SM
   gate-C false-negatives 5/9). The win is a well-labeled "I can't tell you + route to the
   analysis that can," not a better prediction.
2. **The NO-GO arm is a false-negative machine if its veto vocabulary rests on blind axes.**
   The same asymmetry that is a feature (one negative kills) produced the 12
   `silent_false_negative`s (PARP/BCL2/XPO1/PSMB5…). So extending veto power to no-go-seeding
   axes (gate F window, immune context) is safe ONLY after those axes are actually evidenced —
   which is exactly why build-to-decide orders those builds first.
3. **`deciding_axis` is hindsight-assigned.** The reference profiles named the deciding axis
   knowing the outcome. Prospectively the framework must GUESS which axis will decide a novel
   target; a mis-route fails more confidently than a portrait. The router's value is bounded
   by ex-ante deciding-axis predictability, which the reference set does not establish.
4. **The no-go attribution is not yet audited.** The "NO-GO seeded by modality-fit + window +
   immune" finding rests on reasoned deciding-axis attribution, not real committee kill-reasons.
   Validate against the actual ProgramRepository records before over-weighting it.

## No-go attribution — VALIDATED 2026-07-19 (proxy, corrected the roadmap)
Caveat 4's prerequisite was run: an independent biology-vs-portfolio classification of all 20
declined programs (PROXY — inferred from target biology + market, NOT committee kill-reasons;
the snapshots carry decline labels, not rationales). Result:
- **~45% (9/20) biology-driven** — and ALL of them are **surface-modality-fit**: topology
  (GRIN2D, HTR1D), shed/secreted (POSTN, CTHRC1, CA19-9, MUC13), co-expression
  (CLDN18.2-LRRC15), + one pan-essential-window (RBM39).
- **0/20 immune/TME-context-driven** — the immune-context axis explains ZERO declines.
- **~55% (11/20) portfolio / competitive-precedent / format** — HIF2a→belzutifan,
  menin→revumenib, KIF18A (competitors ahead), trispecific/γδ formats. Several the framework's
  biology would GREEN-light and the committee killed anyway → NOT a biology-evidence gap.
- **Fragility:** 8/20 are biology↔portfolio ambiguous; the 45/55 split swings 35–65% under
  small reclassifications. The DIRECTION is robust (biology declines = surface-fit; none
  immune) even at the pessimistic end; the MAGNITUDE needs real kill-reasons to pin.

## What this does to the roadmap (build-to-decide, VALIDATED ordering)
1. **Close seam-invariant #1** (typed dependency record — continuous-in/threshold-out) — the
   precondition for the layering to be real; also the gate-C fix the whole assessment points at.
2. **Gate-F SURFACE-WINDOW axis** — the VALIDATED #1 no-go build (would have correctly no-go'd
   8-9 programs on evidenceable grounds). Four sub-signals, all surface-modality-fit: surface
   topology (GPCR/ion-channel epitope-viability), shed/secreted localization, normal-tissue-
   surface window (fix the dead gnomAD import + wire HPA `normal-tissue-liability`), bispecific
   co-expression/avidity. Skills already exist (`surface-modality-fit`, `on-target-safety-
   liability`, `tumor-selectivity`) — wire, don't invent.
3. **Seam-invariant #2** (render-order validator — quarantine ungated prose below the verdict).
4. **GO-side** (SynLethDB partner-conditional SL reader — improves the GO arm, not the
   decision-protecting NO-GO arm).
5. **Modality as first-class input** (Engine-B consult the modality router — two-engine debt).
- **DROPPED (validation-corrected):** a bespoke immune/TME-context axis — 0/20 declines turn on
  it; unsupported by the sample. Do not build near-term.
- **PARK (not engineering):** competitive-intelligence / clinical-precedent — the LARGEST
  decline tranche (~55%) lives here, but it's license-blocked (Cortellis/patent). A
  competitive-intel gap, not a biology-evidence gap; the framework should not chase it, and its
  biology would sometimes correctly disagree with a portfolio/competitive decline.

## Cross-references
- `KNOWN_TARGET_FRAMEWORK_REFRAMES.md` — Reframes 1 (necessity/sufficiency) / 2 (modality) /
  3 (abstention router) this doc extends and resolves.
- `known_target_calibration_set.yaml` `reference_profiles` — the fidelity data behind every claim.
- `RISK_ASSESSMENT_INTEGRATION.md` — the F2 attention-mediated leak this doc generalizes into
  seam-invariant #2.
- `GATE_SCAFFOLD_MODALITY_CONDITIONAL.md` — the typed-dependency-record fix (seam-invariant #1)
  and the gate-C single-scalar defect.
