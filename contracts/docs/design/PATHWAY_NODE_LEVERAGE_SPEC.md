# Design Spec — Pathway-Node-Leverage Axis (WS3)

**Status:** Consolidated 2026-08-16 from the `framework-runs/pathway-node-leverage/`
prototype (validated on live DepMap/Pharos/CORUM/MSigDB data). This is the build
blueprint for productionizing the axis; it supersedes the naive proof-of-concept.
Companion to `CROSS_EVIDENCE_INTEGRATION_ROADMAP.md` (WS3).

Portable GFM per the `README.md` format rules (no Mermaid/HTML).

---

## 1. The question

Every current card asks a **target-intrinsic** question ("is X dependent /
altered / tractable / safe?"). The portfolio decision is **comparative**: given
the biology, *is X the best node to hit, or is it dominated by a more-dependent /
more-tractable member of its neighbourhood?* MARK2/3 is the motivating case — a
correct decline whose true reason (a dominated pathway node) the framework could
not evidence, only flag as a gap.

## 2. What the prototype established (and corrected)

The naive PoC ranked raw pan-cancer Chronos and called the target "dominated" if
any pathway member was more dependent. A 5-lens adversarial review found that
unsound; the prototype validated each correction on live data:

1. **Common-essential exclusion is mandatory.** Without it, housekeeping genes
   (VCP −2.6, AARS1 −2.2) crown themselves as the "dominant" node of any pathway.
   Source: DepMap `CRISPRInferredCommonEssentials` (retain the target itself even
   if common-essential — that is its own safety signal).
2. **Tractability-yield.** A druggable "dominated" node can be a better program
   than an undruggable rate-limiting one. The verdict splits accordingly
   (Pharos TDL: Tclin > Tchem > Tbio > Tdark). Validated: KRAS/PIK3CA/CDK4 (all
   Tclin) read `dominated_but_tractability_edge` — correctly drug-worthy despite
   not being the single-most-dependent gene in their pathway.
3. **Noise-separation gate.** A minimum median-Chronos separation (~0.15) so
   `dominant/competitive/dominated` is not called on screen noise.

## 3. Node-set is a LENS SET (not one source)

The comparison neighbourhood is defined by a lens on a precision/recall gradient.
All source data is **already ingested**:

| Lens | Source (ingested) | Semantics | Precision/recall |
|---|---|---|---|
| complex | CORUM 5.3 (`corum-5-3`) | same physical complex — "wrong subunit?" | tightest, most mechanistic |
| curated-pathway | Reactome / KEGG / WikiPathways in MSigDB **C2.CP** (`msigdb-human-v2026-1-hs`) | same signaling cassette | high precision; misses peripheral nodes |
| functional-pathway | MSigDB **C5 GO:BP** | same biological process (incl. regulators) | high recall; noisy |
| ppi (TODO) | STRING / BioGRID (`biogrid-physical-interactions-per-gene-v1`) | interaction neighbourhood | broadest; hairball |

**Node-set selection:** rank candidate sets by specificity and prefer the tightest
curated set (complex → C2.CP → GO:BP) that contains the target; report each
available lens with its precision caveat. A peripheral regulator (MARK2) that no
tight set contains is itself a signal — only the noisy GO:BP lens applies.

## 4. Verdict taxonomy

Per (target, lens[, node_set]):
- `dominant_node` — target is the most-dependent node (no member stronger by ≥ sep).
- `dominated_but_tractability_edge` — a more-dependent node exists, but none is
  ≥ as tractable as the target (the target is the tractable entry point).
- `dominated_node` — a more-dependent AND ≥-as-tractable node exists.
- `weak_and_uncontested` — target does not clear the dependency floor and nothing dominates it.
- `no_complex_in_corum` / `target_not_screenable` — lens does not apply / no DepMap coverage.

This is a **soft mechanistic-context annotation**: it contributes **no veto** to
the integrator's hard-gate ceiling and **never raises certainty** (it is
Chronos-derived, correlated with the dependency cards). It feeds the
`differentiation` axis and can seed a cross-evidence evidence-path.

## 5. Validation summary (prototype, pan-cancer)

- **CDK4** (complex lens): `dominant_node` in all 10 cyclin-CDK complexes (Tclin,
  −0.53) — the clean positive control (a validated drug target IS the best node).
- **KRAS / PIK3CA** (pathway): `dominated_but_tractability_edge` — Tclin tractability
  edge correctly flags them drug-worthy.
- **MARK2**: `dominated_node` (Hippo GO:BP) + only a chaperone complex (HSP90/CDC37)
  — peripheral from both lenses; no tractability edge (Tchem).
- **SMARCA4**: dominated by core BAF subunits; its SL paralog SMARCA2 is a complex
  member but does NOT surface (context-specific SL, invisible pan-cancer).

## 6. Known limitation → top remaining correction: LINEAGE-SCOPING

Pan-cancer Chronos makes context-specific drivers look dominated (BRAF, CTNNB1)
and hides context-specific SL (SMARCA4→SMARCA2). Surfaced three times in
validation. The production method MUST compute dependency **within the indication
lineage cohort** (DepMap `Model.csv` OncotreeLineage; reuse the
`depmap_chronos` INDICATION→lineage map) with a pan-lineage fallback when the
cohort is thin. **SHIPPED** (2026-08-17): lineage-scoping (#372) and the
paralog/combinatorial correction (#375/#392 — a buffered target's single-KO
leverage is flagged `single_ko_leverage_understated`, reusing the dual-KO
buffering product; the paralog-mediated-effector case, e.g. MARK2 via MARK3,
surfaces as that buffering caveat rather than a node-set edge).

**Directed SIGNOR/OmniPath acts-through check — CLOSED as not-applicable
(2026-08-17).** The original concern was that undirected membership cannot ground
a directional "X acts through Y" claim. But this method makes **no** directional
claim: `node_leverage_class` is a relative fitness-rank comparison ("is the target
the best node in its neighbourhood, or dominated?"), never an "acts-through"
assertion. A directed-edge guard therefore has nothing to guard. This item is
**not a pending TODO** — it becomes in-scope only if a future feature adds a
directional/epistasis claim (e.g. "target acts through effector E"), at which
point a directed SIGNOR/OmniPath check would gate that specific claim. Until then:
intentionally not built.

## 7. Productionization plan (build order)

**STATUS 2026-08-17 — axis LIVE end-to-end.** Step 1 method #371 + refine #372
(lineage-scoped incl PAAD fix; C2.CP-preferred, size-banded node-set selection).
Step 2 card + measurement_type #384 (`derived_from crispr_lof_dependency`,
`evidence_tier: inferred` → machine-enforced soft/no-veto). Step 3 rules #390
(soft `axis_fit` signal; NOT a `differentiation.resolver` rung — orthogonal to
the cooccurrence verdict). Step 4 skill #466 (differentiation-landscape CARDS +
target-profile fanout; hypothesis-agent exposure automatic via `fired_rule_ids`;
nominations byte-stable — nothing consumes `axis_fit`). PPI lens #374 added
**report-only** (excluded from the headline). Lens gradient delivered: complex +
C2.CP + GO:BP (headline) + PPI (report-only). Paralog/combinatorial correction
**SHIPPED** #375/#392 (single_ko_leverage_understated; the leg the dropped
MARK2→YAP/TAZ done-when needed — see the roadmap's revised WS3 done-when).
Step 5 (source-release pins) satisfied by the card's release-pinned
`required_inputs` (see §5). Directed acts-through **CLOSED as not-applicable**
(§6) — no directional claim to ground. **WS3 is complete; no open items remain.**

1. **analysis-methods** `onc_methods/pathway_node_leverage/` — `read_node_leverage(target,
   indication)` returning per-lens verdicts + effect sizes + provenance; reads the
   pinned CORUM / MSigDB / Pharos / DepMap sources; lineage-scoped. `cli.py` for
   batch/derived materialization if needed.
2. **target-contracts** `cards/pathway-node-leverage.card.yaml` — summary_fields
   (per-lens verdict, dominant competitors, effect size, tractability), vocabulary,
   thresholds (DEP_FLOOR, MIN_SEP), caveats (soft/no-veto/no-certainty).
3. **target-contracts** interpretation-rules + wire into the `differentiation`
   resolver as an additive, verdict-inert-or-soft signal (never a veto).
4. **skills** — surface in `differentiation-landscape` and expose to the
   cross-evidence hypothesis agent as a `differentiation`-axis input + evidence-path seed.
5. **data-catalog** — pin the node-set source releases the method depends on
   (MSigDB C5 GO:BP + C2.CP, CORUM) in provenance; membership drift can flip
   verdicts, so releases are pinned like every other source.

## 8. Invariants
- Soft annotation: no hard-gate veto; never raises certainty.
- Common-essential exclusion always applied; target retained.
- Verdicts report effect size + the lens + the pinned source releases.
- Lineage-scoped in production (pan-cancer only as an explicit fallback, flagged).
