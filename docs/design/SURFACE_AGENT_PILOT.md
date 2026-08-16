# Pilot — grounded surface agent: recover + ARBITRATE (role #3)

**Status:** DRAFT protocol (2026-08-15, re-scoped on live evidence) · companion to
`PER_DIMENSION_EVIDENCE_REPRESENTATION.md`. Supersedes the initial FOLR1-anchored draft.

## 0. Why this was re-scoped (the live-evidence finding)

The initial premise was "recover surface antigens the framework is BLIND on." A live
evidence-package scan of the cohort **refuted that premise**: the merged surface-density
program (the #5 top-gap axis) has already wired density/topology/fit for most antigens. The
framework is largely **no longer blind** on surface — instead it makes surface calls that are
sometimes **wrong in patterned ways**. FOLR1 (the original anchor) now reads a correct
`adc_preferred_tce_unsafe` deterministically — it needs no agent.

Live scan (2026-08-15, `--emit evidence-package`):

| Target | Surface verdict | topo / density / fit | True status | Failure class |
|---|---|---|---|---|
| FOLR1/OV | adc_preferred_tce_unsafe | no_TM / high / both | approved ADC | **correct** (was mislabeled blind) |
| GRIN2D/COADREAD | tce_unsafe_normal_liability | multi_pass / mod | declined | **correct-reject** |
| TROP2/BRCA | `insufficient` | None / unmeasured | approved ADC | **BLIND** (recover) |
| STEAP1/PRAD | `neither_viable` | multi_pass / low | active (de-risked) | **false-neg** (topology-killer over-fires) |
| MUC13/COADREAD | adc_preferred_tce_unsafe | single / high | declined (shed) | **false-pos** (misses shedding) |
| CD19/DLBC | adc_preferred_tce_unsafe | single / low | approved TCE (blina) | **miscalibrated** (TCE called unsafe) |
| CEACAM5/LUAD | shed_dominant_opposed | single / high | declined Ph3 | **correct-reject** — shed detection fires (proves the shed signal EXISTS) |
| DLL3/SCLC | *(extraction error — blocked)* | — | approved TCE | aberrant-surface trafficking; needs pipeline debug before inclusion |

## 1. The reframed question

Not "can the agent fill a blank" (density already did). The pilot tests whether a grounded
surface agent can **arbitrate the framework's surface calls against clinical precedent and
un-modeled biology**, across four distinct capabilities:

| Capability | Test target | Principle (design doc §5.1) |
|---|---|---|
| **Recover** a still-blind axis | TROP2 (insufficient) | role #3 core |
| **Override** an over-fired heuristic w/ clinical precedent | STEAP1 (topology-killer) | #4 adversarial; clinical precedent subordinates a killer |
| **Flag** a coverage gap in an existing measurement | MUC13 (shed card fires for CEACAM5, misses MUC13 glycan-shed) | #2 un-measured ≠ reasoned-around |
| **Arbitrate** a miscalibrated call vs precedent | CD19 (TCE unsafe, but blina approved) | #3 typed disagreement |
| **Preserve** correct calls (no false rescue) | GRIN2D (correct-reject), FOLR1 (correct-ADC), CEACAM5 (correct shed-reject) | do-no-harm |

## 2. Inputs (grounding — no raw data)

Distilled surface card summaries from the evidence-package
(`surface-topology-and-ptm`, `surfaceome-family-classification`, `structure-features-static`,
`surface-abundance-density`, `adc-tce-modality-fit`: `summary`+`interpretation_call`+
`caveats`+`provenance`) **plus the deterministic surface_modality verdict itself** (the agent
arbitrates it, so it must see it) + PMID-cited literature retrieval.

## 3. Contract (design doc §5)

Cite-or-abstain (every claim → card value or PMID); capped certainty (≤ MEDIUM unless citing a
hard card value); stay-in-lane (surface-modality only; clinical outcome → the clinical risk
lens); adversarial refute-pass on every call; reproducibility envelope (pinned model, temp 0,
input+PMID hash). **Typed disagreement:** the agent may move the framework's surface verdict
toward *conditional/overridden* only with cited precedent or a cited card contradiction —
never on unsourced assertion.

## 4. MUC13 caveat — coverage gap, not missing measurement

MUC13 is `adc_preferred` (density high); it declined for **glycan-shedding**. The scan shows a
shed signal DOES exist — CEACAM5 correctly reads `shed_dominant_opposed` — so this is a
**coverage gap** in an existing card (the shed detection catches CEACAM5's shedding but misses
MUC13's glycan-shed), not a wholly un-measured axis. Per principle #2 the agent must still not
fabricate the shed call from silence; it flags "shed-antigen risk — existing card did not fire
for MUC13; literature suggests glycan-shed [PMID]" at capped certainty. If load-bearing, the
fix is **extending the shed card's coverage** (glycan-shed), not a smarter prompt.

## 5. Metrics & pass criteria (outcome-blinded, reasoning-scored)

1. **Groundedness** = % claims cited → target **100%**.
2. **Recover**: TROP2 → a grounded, defensible ADC-favorable call (or honest abstain if cards
   truly empty).
3. **Override**: STEAP1 → NOT `neither_viable`; cites clinical precedent to subordinate the
   multi-pass topology killer.
4. **Flag**: MUC13 → surfaces shed-antigen risk as a capped caveat (does not confidently
   endorse ADC).
5. **Arbitrate**: CD19 → challenges `tce_unsafe` with the approved-TCE precedent.
6. **Do-no-harm**: GRIN2D stays disfavored; FOLR1 stays ADC-preferred; CEACAM5 stays
   shed-opposed.

**PASS (agent arbitration validated):** 100% groundedness; correct behavior on ≥4/6 scored
targets INCLUDING both do-no-harm controls; zero uncited overrides. **FAIL:** any uncited
call, or a correct framework verdict broken (GRIN2D/FOLR1) → reconsider scope.

## 6. Leakage guard (§5.1 principle 5)

Outcome-blinded prompt (no approval status); reasoning-scored (grounded chain, not landing on
the known answer — the XPO1 trap); do-no-harm + false-neg + false-pos + miscalibration
controls all present so "always favorable"/"always override" both fail.

## 7. Out of scope

Cross-dimensional agent (§8), risk-lens verdict ramp, gate wiring. This pilot answers: does
grounded surface **arbitration** work.
