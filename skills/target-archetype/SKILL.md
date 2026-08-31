---
name: target-archetype
description: |
  META / reduction-stage COMPANION — the verdict-INERT cross-skill target-signature LANDSCAPE layer.
  Consumes the OTHER sub-skills' composed claim_vectors (a full target-profile run), distils them into a
  point in a FROZEN low-dimensional embedding of the target-signature space (atlas/atlas.json), and
  positions the (target, indication) pair as a soft PHENOTYPE MIXTURE — a convex membership to curated
  canonical ANCHORS (KRAS=GoF-driver, VHL=TSG, ERBB2=amp, EPCAM=surface, AURKA=dependency, GAPDH=control):
  "60% surface + 25% GoF-driver + ..." (a distribution, NEVER a hard label). Also emits nearest reference
  ANALOGS ("most like CDH17, TROP2"), a MISSINGNESS map (the per-target acquisition backlog), a
  rule-fingerprint PRECEDENT overlay (auditable rule spine), and NOVELTY (hull-residual = a signature
  inconsistent with any canonical phenotype, plus a local-density flag).

  CARDLESS: it derives no evidence of its own and reads no data-catalog cards — it reads the claim_vectors
  the wired sub-skills already produce. DESCRIPTIVE and strictly VERDICT-INERT (synthesis: none,
  verdict=None): it never mints a nomination, never enters the resolver / fired / _SHORT_TO_GATE /
  sub_verdicts spine, and is NOT a SUB_SKILLS fan-out peer. In the composed target-profile it attaches as a
  reduction-stage facet (alongside fragility / heterogeneity). It describes the collected evidence; it is
  NOT a classifier and NOT a gate. Reference panel labels are provisional + partly circular.

  Use for "what drug-target phenotype is target X, what is it most like, and what's the highest-value
  missing evidence?" — the phenotype-landscape companion, not a call.

metadata:
  version: 0.4.0            # MUST equal SKILL_VERSION in scripts/run.py
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

# target-archetype — cross-skill target-signature landscape companion

## What it answers
Given a target's full composed profile, **what drug-target phenotype is it (as a soft mixture), what
reference targets is it most like, and what is the highest-value missing evidence?** It is a *signature
map* — descriptive, immune to any classifier-accuracy ceiling and to label-circularity, because it makes
no classification claim.

## How it works
1. Each sub-skill emits a `synthesis_facet.claim_vector` during the target-profile fan-out (the same
   payload `tp_manifest` serialises into `subskills/<short>/package.json`).
2. `_skills_common/archetype_core.claim_features` ordinal-encodes those claim tiers (signal +
   corroboration; corroboration uses its own low/moderate/high map — the prior "only-moderate" bug is
   fixed) into a per-target vector — **one canonical vectoriser** shared by the offline atlas build and the
   runtime query.
3. The vector is z-scored (vs the frozen corpus mu/sd), mean-imputed (missing → 0), and projected through a
   **frozen linear embedding** (PCA loadings shipped as data in `atlas/atlas.json`) — the *exact* transform
   the offline build applied, so offline == runtime, pure-stdlib + deterministic (no torch, no pickle).
4. Against the frozen atlas (n=213 reference targets; embedding + curated anchors), `Atlas.companion`
   computes:
   - **phenotype_mixture** — a convex membership to the canonical anchors (`min ||e − w·Z||` on the
     simplex); a *distribution* over phenotypes, never a hard label. Aliased as `soft_membership` (keyed by
     the archetype vocabulary) so the D1 scorecard consumes it unchanged.
   - **nearest_analogs** — the k closest reference targets (embedding distance) + labels;
   - **rule_precedent** — reference targets with the most-overlapping fired-rule signature (Jaccard);
   - **missingness** — axes entirely unmeasured for this target (the acquisition backlog);
   - **novelty** — **hull_residual** (distance from the anchor convex hull = a signature INCONSISTENT with
     any canonical phenotype) + a local-density flag. This fixes the old global-NN metric that flagged
     merely-EXTREME targets (e.g. EGFR) as "novel".
5. It also emits a **D1 nomination-readiness SCORECARD** (`nomination_scorecard`): an interpretable,
   glass-box, PHENOTYPE-CONDITIONED score. Each of the 13 axes' z-scored position (vs the frozen corpus
   `axis_ref`) is signed (+favorable / −liability, e.g. safety) and weighted by a phenotype-mixture blend of
   per-archetype weight profiles (ILLUSTRATIVE + SHOWN, not learned), so a surface antigen is scored on its
   OWN route rather than penalised for "not being a driver". Emits per-axis contributions + driving axes +
   a **route-conditioned counterfactual gap** ("closest to nominatable except axis X").

RETIRED: the former outcome-trained approval-propensity score (D2/D3, `nomination_predictive_score`) was
removed. An ablation showed its signal was carried by advancement / study-depth features, not disease
biology (the pure-biology residual did not beat a genetics baseline, and the approval label is
maturity-confounded), so the honest product is the descriptive phenotype landscape above.

## Governance (non-negotiable)
DESCRIPTIVE, `verdict=None`, **out of `_SHORT_TO_GATE`**, never wired into a resolver `when.card_id` or the
nomination spine. It attaches like the other verdict-inert reduction-stage facets and is byte-stable on the
recommendation. No hard single-phenotype label — only a soft mixture. Phenotype anchors are curated
canonical exemplars; reference panel labels are provisional and partly circular (clinical antigens; cards
designed from the same biology). The signature is a continuum, not discrete islands — the mixture is the
honest product, not a bin.

## Entry points
- **Composed** (primary): target-profile's `run.py` computes the companion as a reduction-stage facet over
  `sub_results` and emits it in `nomination.json` (`archetype_companion` + `nomination_scorecard`).
- **Standalone** (`scripts/run.py`): point `--package-dir` at an existing `--full-package` run tree; it
  emits `companion.json`. Used by the example gallery + for spot-checks.

## Re-freezing the atlas
`scripts/build_atlas.py --runs <corpus dirs...> --panel <labels.tsv> --out atlas/atlas.json [--emb-dim 16]`.
Freezes feature_order · mu/sd · the PCA embedding (components + corpus coords) · the anchor coords ·
axis_ref. Re-run ONLY after a validated substrate change. The atlas records its corpus, n, embedding dim,
anchors, build date, and git sha in `meta`.
