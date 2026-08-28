---
name: target-archetype
description: |
  META / reduction-stage COMPANION — the verdict-INERT cross-skill nearest-reference layer.
  Consumes the OTHER sub-skills' composed claim_vectors (a full target-profile run) and positions
  a (target, indication) pair against a FROZEN reference atlas (atlas/atlas.json): nearest reference
  ANALOGS ("most like CDH17, TROP2"), a SOFT archetype membership (distance-weighted kNN — never a
  hard label), a rule-fingerprint PRECEDENT overlay (same fired-rule signature; on the auditable rule
  spine), and a MISSINGNESS map (which axes are unmeasured — the per-target acquisition backlog).

  CARDLESS: it derives no evidence of its own and reads no data-catalog cards directly — it reads the
  claim_vectors the 13 wired sub-skills already produced. DESCRIPTIVE and strictly VERDICT-INERT
  (synthesis: none, verdict=None): it never mints a nomination, never enters the resolver / fired /
  _SHORT_TO_GATE / sub_verdicts spine, and is NOT a SUB_SKILLS fan-out peer. In the composed
  target-profile it attaches as a reduction-stage facet (alongside fragility / heterogeneity). There is
  NO atlas-freeze-FOR-CLASSIFICATION and NO hard archetype label: the held-out blind-label gate (P3) is
  pending, so this ships descriptive-only. Reference labels are provisional + partly circular.

  Use for "what is target X most like, and what's the highest-value missing evidence?" — the
  nearest-analog nomination companion, not a call.

metadata:
  version: 0.1.0            # MUST equal SKILL_VERSION in scripts/run.py
  owner: ryan.abo@takeda.com
  requires_preflight: false

composition:
  data_mode: derived_read   # reads the frozen atlas + the composed claim_vectors; NOT catalog_read
  phase: [K]                # cross-cutting reduction stage (runs AFTER the fan-out, over all axes)
  cards_used: []            # cardless — consumes other sub-skills' claim_vectors, no cards of its own
  rules_scope: []           # no resolver rung — descriptive
  synthesis:
    - none                  # verdict=None (governance: companion, never a gate)
  output_shape:
    - data_package
  steps_covered: [1, 2, 6]
  status: wired
---

# target-archetype — cross-skill nearest-reference companion

## What it answers
Given a target's full composed profile, **what reference targets is it most like, which archetype
region(s) does it fall in, and what is the highest-value missing evidence?** It is a *similarity +
coverage* product — immune to the archetype-classifier accuracy ceiling and to the label-circularity
caveat, because it makes no classification claim.

## How it works
1. Each sub-skill emits a `synthesis_facet.claim_vector` during the target-profile fan-out (the same
   payload `tp_manifest` serialises into `subskills/<short>/package.json`).
2. `_skills_common/archetype_core.claim_features` ordinal-encodes those claim tiers into a per-target
   vector — **one canonical vectoriser** shared by the offline atlas build and the runtime query.
3. Against the frozen `atlas/atlas.json` (n=107 labelled reference targets, 7 archetype regions),
   `Atlas.companion` computes, with a **NaN-aware distance** (absent=0 is real; unmeasured=None is
   ignored per-pair and rescaled — no imputation):
   - **nearest_analogs** — the k closest reference targets + their labels + distance;
   - **soft_membership** — an inverse-distance kNN vote over the neighbours (a *distribution*, not a label);
   - **rule_precedent** — reference targets with the most-overlapping fired-rule signature (Jaccard);
   - **missingness** — axes entirely unmeasured for this target (the acquisition backlog);
   - **novelty** — a crude global nearest-neighbour distance (flags EXTREME, not INCONSISTENT — A3 backlog).

## Governance (non-negotiable)
DESCRIPTIVE, `verdict=None`, **out of `_SHORT_TO_GATE`**, never wired into a resolver `when.card_id` or
the nomination spine. It attaches like the other verdict-inert reduction-stage facets and is byte-stable
on the recommendation. No hard single-archetype label; no atlas-freeze-for-classification. The honest
validated state: archetype structure is real (~0.80 leave-one-TARGET-out, RF on the full claim-vector),
but the shipped companion is a descriptive kNN and the **blind/external-label held-out gate (P3) is the
prerequisite** before any classification claim. Reference labels are provisional and partly circular
(clinical antigens; cards designed from the same biology); `housekeeping` is not a distinct archetype
and `amp_driver` is small-n/fuzzy.

## Entry points
- **Composed** (primary): target-profile's `run.py` computes the companion as a reduction-stage facet
  over `sub_results` and emits it in `nomination.json` (`archetype_companion`).
- **Standalone** (`scripts/run.py`): point `--package-dir` at an existing `--full-package` run tree; it
  emits `companion.json`. Used by the example gallery + for spot-checks.

## Re-freezing the atlas
`scripts/build_atlas.py --runs <corpus> --panel <labels.tsv> --out atlas/atlas.json`. Re-run ONLY after a
validated substrate change (re-confirm leave-one-TARGET-out η²/accuracy first). The atlas records its
corpus, n, build date, and git sha in `meta`.
