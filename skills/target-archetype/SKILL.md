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
  version: 0.5.0            # MUST equal SKILL_VERSION in scripts/run.py
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
   - **nearest_analogs** — the k closest reference targets (embedding distance) + labels, DEDUPED BY TARGET
     (a target present in several indications no longer floods the list — the old "KRAS, KRAS, KRAS");
   - **rule_precedent** — reference targets with the most-overlapping fired-rule signature, **IDF-weighted**
     (rare rungs dominate the match; a shared ubiquitous rung no longer inflates overlap) + `top_shared_rules`;
   - **missingness** — axes entirely unmeasured for this target (the acquisition backlog);
   - **mixture_uncertainty** — an axis-JACKKNIFE stability band on the mixture (re-solve dropping each
     measured axis; per-anchor [min,max] envelope + a scalar `stability` in [0,1]). Turns an over-confident
     point mixture (the pre-fix EGFR failure: amp-dominant only because the SNV axis was silently 0) into an
     honestly-caveated one. Skippable on hot paths (`with_uncertainty=False`).
   - **novelty** — the `inconsistent_flag` now keys off a **SCALE-INVARIANT relative** hull-residual
     (`hull_residual / ‖e‖`) vs the corpus p90, so an EXTREME-but-canonical blend (EGFR = amp+SNV RTK) is no
     longer flagged "novel" merely for being far from the origin — only a signature whose *shape* fits no
     anchor mix trips it. Plus `multimodal` / `mixture_entropy` (a genuine multi-phenotype blend vs truly
     weird) and the local-density flag. (`hull_residual` + `hull_residual_absolute_flag` retained.)
5. It also emits a **D1 nomination-readiness SCORECARD** (`nomination_scorecard`): an interpretable,
   glass-box, PHENOTYPE-CONDITIONED score. Each of the 13 axes' z-scored position (vs the frozen corpus
   `axis_ref`) is signed (+favorable / −liability, e.g. safety) and weighted by a phenotype-mixture blend of
   per-archetype weight profiles (ILLUSTRATIVE + SHOWN, not learned), so a surface antigen is scored on its
   OWN route rather than penalised for "not being a driver". Emits per-axis contributions + driving axes +
   a **route-conditioned counterfactual gap** ("closest to nominatable except axis X") + a ranked
   **value_of_information** backlog (for every UNMEASURED axis, the projected score gain if it came back
   favourable — the general form of the counterfactual gap).

STALENESS GUARD: `scripts/atlas_health.py` (+ `archetype_core.vocabulary_drift`) — a CI-wireable check that
the frozen embedding still re-projects every corpus row onto its stored coord, that provenance is complete,
and (given a live run) that no live claim key is silently absent from the frozen `feature_order`. The
`fusion_driver` anchor is registered ASPIRATIONALLY (build_atlas skips-not-crashes on absent exemplars). Its
5 exemplar runs were generated + FUS-verified, but a trial re-freeze that activated it REGRESSED the panel:
the exemplars land correctly (ALK 97%, NTRK1 88%, RET 83%, ROS1 67%) but — because FUS is one sparse feature
of 108 and every recurrent-fusion driver is an RTK — the anchor encodes RTK-ness, bleeding spurious fusion
mass into non-fusion RTK/surface targets (MET flipped fusion-dominant; ERBB2 35%; CLDN18, not a kinase, 31%).
It stays deferred until the fusion signal is made SEPARABLE in the embedding (e.g. FUS-feature up-weighting),
not merely supplied with exemplars.

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
