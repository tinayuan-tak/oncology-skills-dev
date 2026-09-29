# Framework Reframes from Known-Target Validation

**Status:** Decided (organizing principles) 2026-07-19. Three framework-level reframes
that emerged from validating the 8-gate scaffold against **known targets** — ~16
clinically-approved oncology drugs + ~55 real Takeda ONC program targets (advanced vs
declined). These are *organizing principles* that shape how the gates are presented,
scored, and extended — not new gates and not (yet) code. They sequence the near-term
build backlog (calibration harness, then context-conditional dependency). Companion to
`GATE_SCAFFOLD_MODALITY_CONDITIONAL.md` (the gate scaffold + the Tier-1/Tier-2 ceiling),
`CARD_ARCHITECTURE_DECISION.md` (the two-layer card model + gate table).

Portable GFM (no Mermaid/HTML) per README format rules.

---

## What prompted this

A three-pass review ran the framework against known targets: cluster-by-cluster
adjudication, then an execute+refute+complete verification pass (live DepMap 26q1 reads +
adversarial refutation), then framework-level commentary. The measured findings — several
of which *corrected* the first pass — are recorded in `GATE_SCAFFOLD_MODALITY_CONDITIONAL.md`
(backtest tables) and expose three structural patterns the current design does not name.
These reframes name them.

Key measured/verified facts these reframes rest on:

- **Necessity, not sufficiency.** Every known winner clears the gates as *necessary*
  conditions, but none *advanced because* of them — they advanced on therapeutic window,
  modality-fit, differentiation, or durability. The gates are currently a flat conjunction
  (`CARD_ARCHITECTURE_DECISION.md`: "Nomination = a conjunction of separable necessary
  conditions") with no is-it-real vs will-it-become-a-drug distinction.
- **Abstention is the framework's best property.** Measured (live 26q1): the composed
  framework returns honest `insufficient` on HTR1D/CDH17 (surface cards data-blocked) — it
  does *not* over-promote. A separate RNA-convergence discovery engine ranked those two top;
  both were declined. The framework's discipline of *not* scoring the axis it can't see is
  exactly what would have avoided that.
- **The worldview is narrower than the portfolio.** The data spine (DepMap CRISPR +
  TCGA/recount3 + gnomAD) encodes cell-autonomous, single-perturbation, single-gene biology.
  The portfolio's advanced mass is context-conditional (arm-loss/CIN, partner-conditional SL)
  and modality-defined (glue/degrader, γδ-engager). Modality is deliberately a post-hoc lens
  (`claude-oncology-skills/README.md`), yet the portfolio is *selected on modality*.

---

## Reframe 1 — Necessity gates (A/B/C/D) vs Sufficiency gates (E/F/G/H)

**Current state.** The 8 gates are a flat conjunction of separable necessary conditions,
partially ordered only by a presupposition DAG (`CARD_ARCHITECTURE_DECISION.md` gate table).
There is no partition into "is it real biology" vs "will it become a drug." The nearest
existing concept is the Tier-1/Tier-2 *ceiling* (`GATE_SCAFFOLD_MODALITY_CONDITIONAL.md`) —
a statement about what the static-omics substrate can/can't see — but that is a
confidence-discount, not a gate partition.

**Proposed.** Present the gates in two bands:

| Band | Gates | Question | Framework's standing |
|---|---|---|---|
| **Necessity** | A Present, B Selective, C Required, D Mechanism | "Is this real, actionable biology?" | The framework's validated lane. Mostly wired. High confidence. |
| **Sufficiency** | E Druggable, F Safe, G Differentiated, H Translational | "Will it become a drug in this modality?" | Partially data-blocked / Tier-2. The axes known targets actually advance/decline on. |

The reframe is a **presentation + confidence contract**, NOT new gates and NOT a hard
score. It says: the framework is *authoritative on necessity* and *advisory-to-abstaining
on sufficiency*. A nomination read should visibly separate "the biology is real" (what we
can stand behind) from "the drug case" (where we defer or flag data-blocks).

**What changes.** No gate is added or removed. The composed output and the render gain a
necessity/sufficiency split so a reader sees which half of the verdict is load-bearing. The
Tier-1/Tier-2 ceiling maps onto it (necessity ≈ Tier-1; much of sufficiency ≈ Tier-2). This
is the honest framing of what the known-target validation showed: the framework decides
necessity well and cannot, today, decide sufficiency for most modalities.

**Why it matters (known-target evidence).** The advanced winners (KRAS-G12C on a covalent
pocket, NOX1 on a restricted-normal window, SMARCA2 on partner-conditional lethality)
cleared necessity and were decided on sufficiency. Presenting them as one flat conjunction
implies the framework scored the decision; it did not. The split makes the framework's
actual authority legible.

---

## Reframe 2 — Modality: post-hoc lens vs first-class question axis (DECISION, not build)

**Current state (two senses of "modality" — do not conflate).**
- *Therapeutic* modality (SM / degrader / ADC / TCE / antibody) is deliberately **NOT a
  gate/dimension**. `claude-oncology-skills/README.md`: "Therapeutic modality ... is NOT a
  dimension ... Artifacts themselves remain modality-agnostic. Re-evaluating a target as a
  different modality = same artifacts, new lens." It is an orthogonal conditioning axis /
  post-hoc `--modality` flag.
- *Measurement* modality (bulk-RNA / single-cell / IHC) IS first-class (a Layer-1 atom
  attribute, `MODALITY_TAXONOMY.md`). This reframe is about *therapeutic* modality only.

**The tension the portfolio exposes.** Takeda's portfolio is *selected on therapeutic
modality* — a KRAS-on glue, a CD3 TCE, and a CELMoD degrader against the same antigen are
three different programs with three different evidence needs. Yet the framework produces one
modality-blind read and applies modality as an afterthought. Worse: the shipped nomination
gate (Engine B) currently *flattens* modality into a modality-blind veto —
`GATE_SCAFFOLD_MODALITY_CONDITIONAL.md` calls this "the core defect," and v1.2.0 has only
partially corrected it (biomarker/power/modality suppressors for own-mutation cases).

**Proposed — a decision to make, not a build to start.** Record the fork and pick a
direction that gates the biologics roadmap:
- **(a) Stay-lens (minimal):** keep modality as a post-hoc lens; finish executing the
  documented Engine-B modality-scoping so the *implementation* matches the *design intent*.
  Lowest cost; keeps the modality-agnostic artifact contract intact.
- **(b) First-class axis (larger):** promote therapeutic modality to a first-class input
  that selects *which gates are required* and *which evidence is load-bearing* per modality
  (a TCE requires A2/B2/E2/F-surface; an SM requires C/D/E1). This matches how the portfolio
  is actually selected but is a contract change (modality enters the question, not just the
  interpretation).

**Recommendation:** adopt **(a) now** (execute the shipped design intent — cheap, closes
the known Engine-B defect), and treat **(b)** as an explicit later decision contingent on
the biologics-surface data landing (E2/F are data-blocked today, so first-class biologics
gating has nothing to gate on yet). This reframe's deliverable is the *decision record*, not
the implementation.

**What changes now.** Nothing in code from this doc. It fixes the vocabulary (two senses of
modality), names the Engine-B flat-veto as the standing defect to finish, and sets (a)-now /
(b)-later as the sequencing so the biologics roadmap has a decided posture.

---

## Reframe 3 — Abstention as a feature: the deciding-axis router

**Current state.** When the framework can't evidence a gate (data-blocked surface cards,
Tier-2 axes), it returns `insufficient`. This is correct and — per the measured HTR1D/CDH17
result — its single most valuable behavior. But `insufficient` is presented as a *gap* (a
coverage hole to apologize for) rather than a *signal* (a routing instruction).

**Proposed.** Make abstention an explicit, structured output: for each target, name **which
gate will decide it** and **whether the framework can see that gate**. Instead of a bare
`insufficient`, emit "the decision here lives in gate X (e.g. normal-tissue-surface window /
resistance durability / surface druggability), which the framework does not evidence — route
to [that analysis]." This is a **deciding-axis router**: a per-target statement of the
load-bearing gate and the framework's standing on it.

**What changes.** The composed synthesis gains a `deciding_axis` + `framework_can_evidence`
field (design only in this doc; implementation is later). The value proposition shifts from
"a nomination score" to "a trustworthy triage: here's what's real, here's what will decide
it, here's whether I can see that." For a committee this is more useful than a fabricated
score — and it is what the known-target validation showed the framework already does
implicitly (abstaining on HTR1D/CDH17) but does not surface.

**Why it matters (known-target evidence).** The RNA-convergence discovery engine, which does
*not* abstain, put HTR1D (a GPCR with no TCE-viable epitope) and CDH17 (bulk-clean but
normal-gut-surface-unsafe for a CD3 TCE) at the top; both were declined. The framework's
abstention is the guardrail that engine lacked. Surfacing *why* it abstains (deciding axis =
E2 surface-druggability / F normal-surface window) converts a silent gap into an actionable
hand-off.

---

## How these sequence the roadmap

- **Reframe 1 (necessity/sufficiency)** sets the confidence contract every downstream read
  presents against — it is the frame for the calibration harness's assertions (positive
  controls must clear necessity; sufficiency abstention is not a failure).
- **Reframe 2 (modality decision)** picks (a)-now/(b)-later, which gates whether biologics
  surface work is a near-term or data-blocked-later track.
- **Reframe 3 (abstention router)** defines the output shape the harness measures and the
  eventual synthesis emits.

Next phases (separate PRs, see the session roadmap): **Phase 1** — a runnable known-target
calibration harness (codifying the ad-hoc backtests as a regression suite); **Phase 2** —
gate-C context-conditional dependency via the shipped synleth master table (the highest-
coverage buildable fix, unblocking the SMARCA2/MARK2-3/PELO/CIN false-negatives).

## Cross-references
- `GATE_SCAFFOLD_MODALITY_CONDITIONAL.md` — gate scaffold, the ~16/~32-target backtests, the Tier-1/Tier-2 ceiling.
- `CARD_ARCHITECTURE_DECISION.md` — the 8-gate table + two-layer card model (the flat-conjunction current state).
- `MODALITY_TAXONOMY.md` — *measurement* modality (the other, already-first-class sense).
- `claude-oncology-skills/README.md` — the "modality is NOT a dimension / post-hoc lens" design statement.
