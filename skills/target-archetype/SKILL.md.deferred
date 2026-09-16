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
  version: 0.6.0            # MUST equal SKILL_VERSION in scripts/run.py
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
    - data_package            # the emitted companion.json — which now CARRIES the canonical
                              # `skill_report` spine (role=descriptive, call=None) inside it, exactly as
                              # the fan-out sub-skills carry theirs on synthesis_facet.skill_report.
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
and (given a live run) that no live claim key is silently absent from the frozen `feature_order`.

ANCHOR ACTIVATION IS GATED BY A SEPARATION TEST: `scripts/anchor_separation_test.py`, three legs that must
ALL pass — **centroid isolation** (the candidate centroid sits further from every incumbent anchor than the
corpus's own p90 nearest-neighbour distance), **exemplar recovery** (its own members resolve to it as
dominant), **no bleed** (no non-member target FLIPS its dominant phenotype to it). Two anchors are currently
refused by it, by two different mechanisms:

- **`fusion_driver`** has an exemplar set, so it is withheld by `build_atlas.DEFERRED_ANCHORS`, which carries
  the measured legs (`measured_on`, `measured_by`, `separation_test`) rather than a prose reason. Re-measured
  2026-09-14 at n=504: legs 1 and 2 PASS, leg 3 FAILS with **42 non-member targets flipping to
  `fusion_driver`, 40 of them carrying no FUS evidence at all**, and precision against the FUS column is 7%.
  The cause is the FEATURE SPACE, not the exemplar set: strong FUS is 6/504 rows across **2 of 176 columns**
  holding 0.861% of embedding influence (BELOW their uniform 1.136% share), so a 16-dim PCA cannot preserve
  it and the corner's position is set by the dense RTK/amp features that co-occur with its exemplars.
  Measured across three membership variants, **the three legs move in OPPOSITE directions as membership
  improves** (leg-1 margin 7.574 → 6.685, leg-3 bleed 42 → 49 flips, leg 2 breaks at 3/6), so they cannot be
  satisfied together — activate only after a curated FUS-window feature makes rearrangement separable.
  ⚠️ Three of its five exemplars can never resolve (`ALK/LUAD`, `ROS1/LUAD` — the corpus files both genes
  only under `NSCLC`; `FGFR2/CHOL` — no `CHOL` rows exist), which is declared in `unresolvable_exemplars` and
  enforced by `build_atlas._assert_anchor_exemplars_resolve`. Do NOT repair it by substituting whatever
  indication the corpus carries: gastric `FGFR2` is amplification-driven, not fusion-driven.
- **`synthetic_lethal`** is deferred by the WEAKER mechanism of having no exemplar set at all, so it is
  DECLARED in `build_atlas.UNDECLARED_ANCHORS` (with its own separation-test numbers) and the build REFUSES
  to run if an exemplar set reappears.

Both refusals are at the PRODUCER boundary (`build()` raises), not only in tests, because a re-freeze is run
by hand. See `tests/test_deferred_anchors.py`. ⚠️ **The p90 NN bar MOVES with corpus size and must be
recomputed, never carried over**: 5.929 at n=297 vs 4.968 at n=504 — a denser corpus makes the bar STRICTER.

A CORPUS REGEN **PRECEDES** A RE-FREEZE, it does not ride along in the same commit. The builder imports NONE
of the claim modules — it reads composed PACKAGES off disk — so a claims-ladder change reaches the atlas over
TWO hops, and freezing an unregenerated corpus silently encodes the OLD ladder while every provenance field
looks current. Measured for #1371 (the `single_arm` split): 17530 of 32500 claim cells flip (**53.9%**), 504
of 504 packages, and the `tier_rarity` distinct-count gate moves the WRONG way (31 → 25 reachable `::corrob`
columns) — so "additive to the VOCABULARY" did not mean additive to the DISTRIBUTION. Run
`regenerate_corpus.sh <dir> --panel <the panel THIS corpus was built from> --jobs 3` — **budget ~5.9 h**: median 123 s/pair over the 504 durations the n=504 build LOGGED, so ~17.8 h serial (parallelism is not an optimisation here, it is the difference between a quarter-day and most of a day). Do not size this off package mtimes: a wall-clock-per-package figure from a parallel run understates the pair by 3.5x. ★ **3 IS THE DEFAULT AND 4 THE CEILING, re-measured off the 913-sample monitor log**: 4-wide bought only **+13%** throughput (104.8 vs 92.6 pkg/h) while peak worker RSS went 56 G → **95 G** on a 124 G box with `swap=0` — 0.6 h of wall clock to buy a 35 G margin instead of a 20 G near-miss, and that 95 G was four ORDINARY pairs coinciding (p83–p90 by duration), all four of which succeeded. Two aggregate `MemAvailable` floors now guard it: the soft floor DRAINS (stops launching, lets in-flight pairs finish — costs wall clock, never a pair) and the hard floor SACRIFICES the largest worker (costs exactly one pair). Both land on the recovery loop the driver already had — exit 3 naming the gaps → re-run with `--resume`. It
REFUSES a would-be no-op instead of printing `0 runs written, 0 failed` and exiting 0, and its completion
line is a count RECONCILED against the panel. See `tests/test_regenerate_corpus_guards.py` — no CI job lints
shell, so those tests are the driver's only gate.

FREEZE STABILITY: `scripts/atlas_stability.py` pins a per-field + per-`meta`-key sha256 of the frozen artifact
in `atlas/atlas_freeze.json`, so a value that moves without a re-freeze is a red test that NAMES the field.
This is a different property from the staleness guard above, which checks internal consistency and so cannot
see a self-consistent edit. **Re-freeze checklist**: ★**REGEN THE CORPUS FIRST** (above) → rebuild →
`atlas_stability.py --verify-rebuild <new.json>`
(0 substantive differences expected; only `meta.build_date`/`build_git_sha`/`feature_corr_provenance` are
waived) → **if the corpus changed size, RE-RUN `anchor_separation_test.py` for every deferred anchor and
update its `measured_on`** (the p90 bar moves with n, so a stored verdict is a verdict about a corpus that no
longer exists) → install the new atlas → `atlas_stability.py --write` in the SAME commit → `atlas_health.py` →
**re-pin the producer test** (see next paragraph). `--verify-rebuild` needs the run corpus, so it runs by
hand, not in CI; scikit-learn is declared in `pixi.toml` as of 2026-09-13, so it does run in this env.

⚠️ **The PCA solver is PINNED (`build_atlas.PCA_SVD_SOLVER = "full"`), not sklearn's default `auto`.** `auto`
selects the exact `full` solver only while `max(n_samples, n_features) <= 500` and the stochastic
`randomized` approximation above it. The corpus is n=297, so the pin is a byte-level no-op today — but the
authorised panel expansion (+207 targets) lands n at 504, crossing that boundary. Refitting the shipped `X`
with `randomized` moves the loadings by 1.23e-02 (vs a 2.24e-05 rounding floor), so an unpinned re-freeze
that crossed 500 would show a moved embedding + every moved coord and a reviewer would read that as the new
targets rather than a solver swap. `tests/test_atlas_embedding.py` reproduces the frozen loadings from `X`
under the pinned solver and asserts an unpinned solver measurably would not. The build stamps
`meta.embedding_pca_svd_solver`; the shipped atlas predates the stamp, so
`test_the_shipped_atlas_predates_the_solver_stamp` pins its ABSENCE by name — on the next re-freeze flip that
to assert it equals `PCA_SVD_SOLVER`, and expect `--verify-rebuild` to report `meta.embedding_pca_svd_solver`
as one EXPECTED new key.

⚠️ **A native re-freeze changes `feature_corr`'s producer, and two tests read that.** `build_atlas` computes
`feature_corr` itself and stamps `meta.feature_corr_provenance` via `native_feature_corr_provenance()` with
`derived_post_freeze: False`; `amend_atlas_feature_corr.py` — the backfill path for artifacts frozen before
`feature_corr` existed — stamps `True`. The currently-shipped atlas is the AMENDED one, pinned by
`test_the_shipped_artifact_is_specifically_the_post_freeze_producer`. After a native re-freeze that pin flips
to `False`; update it in the same commit. Do **not** reach for `amend_atlas_feature_corr.py` to make the old
assertion pass — re-running the amend script over a natively-built artifact stamps a post-freeze derivation
that did not happen, which is a false provenance claim in exchange for a green test.

RETIRED: the former outcome-trained approval-propensity score (D2/D3, `nomination_predictive_score`) was
removed. An ablation showed its signal was carried by advancement / study-depth features, not disease
biology (the pure-biology residual did not beat a genetics baseline, and the approval label is
maturity-confounded), so the honest product is the descriptive phenotype landscape above.

## Narrator lens + literature lane + confidence surface (v0.6.0)
This is the FIRST non-fan-out skill wired for the literature-and-claims arc. Because it uses a **bespoke
`main()`** (not `run_wired_skill`), the two LLM lanes are wired surgically in `scripts/run.py`:

- **`--synthesize`** — a DESCRIPTIVE, verdict-INERT narration through the new
  `_skills_common/narrator_lenses.TARGET_ARCHETYPE` LensConfig (`mode=descriptive`; axis_labels
  `PHENOTYPE / ANALOG / PRECEDENT / NOVELTY / READINESS`). `run.py` builds a **decision-shaped dict** from the
  companion + `nomination_scorecard` (a `claim_vector` over those five axes; the phenotype-landscape numbers
  ride in the evidence strings since this layer is cardless) and runs the generic `narrator_engine`. The
  narration LEADS with mixture stability + missingness + label-circularity + the illustrative-weight caveat —
  never an over-confident point label.
- **`--literature`** — a verdict-INERT literature lane (`make_literature_fn(TARGET_ARCHETYPE, default_retrieve,
  verify_citations)`) that grounds the **dominant phenotype component + the top nearest_analogs analogy**
  ("does the literature support that target X is phenotype-P and most like reference-Y?") against Europe PMC,
  PMID-verified. Attached as `decision['literature_synthesis']` BEFORE the narrator (which may cite it). Often
  indication-independent → `None` indication → `_indication_phrase → "cancer"` (like target-intrinsic).

**Confidence surface (VERDICT-INERT).** The TRAP: the `phenotype_mixture` / `nearest_analogs` / `rule_precedent`
/ `nomination_scorecard` OVER-CALLS a real, literature-supported phenotype / analogy / readiness. Gated ONLY on
the already-computed companion + scorecard fields (`mixture_uncertainty.stability`, `missingness`,
`soft_membership`, `nearest_analogs.label_is_derived`, `novelty`) — **cardless + verdict-INERT → no atlas
re-freeze, no resolver, no verdict to move**. Three fields (in `archetype_core.py`, carried by BOTH the
standalone doc and the composed `companion_from_sub_results` facet):
- **`archetype_confidence_caveat`** (3-tier): `validated_canonical_anchor` (MILDER false-demote guard — a
  HIGH-stability, LOW-missingness, decisively canonical-anchor-dominated mixture is NOT an over-call) >
  `phenotype_mixture_low_stability_or_missingness_distorted` (SHARP — jackknife stability below floor OR too
  little of the atlas signature measured; the EGFR amp-because-SNV-silently-0 mode) >
  `analog_or_label_circular` (SHARP — the nearest analog rests on a DATA-DERIVED, same-embedding label →
  label-circularity risk).
- **`scorecard_confidence_caveat`** — the D1 weights are ILLUSTRATIVE + SHOWN, not learned; the score ORIENTS,
  it is NEVER a nomination verdict (cites the RETIRED, maturity-confounded outcome-trained D2/D3 score).
- **`archetype_provenance`** — the QUORUM: measured/unmeasured axis counts, mixture stability, dominant anchor
  + mass, novelty flags, anchor-set provenance + the fusion_driver-DEFERRED note.

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
