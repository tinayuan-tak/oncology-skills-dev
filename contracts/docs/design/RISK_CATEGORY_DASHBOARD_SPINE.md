# Dashboard spine: drug-discovery risk categories — decision memo

**Status:** DECIDED (2026-07-21). Decides the dashboard's TOP-LEVEL section structure. Follows the
gate-model v2 work (GATE_MODEL_V2_MEMO.md) + the axis-band dashboard.

## DECISIONS (locked 2026-07-21)

Anchored to the **AstraZeneca 5R framework** (Cook et al., Nat Rev Drug Discov 2014) — the industry
target/drug-risk taxonomy our 6 categories already map onto. Presenting in 5R terms makes the dashboard
legible to any committee that knows it.

| Our category | 5R pillar |
|---|---|
| Biological | Right Target |
| Biomarker | Right Patient |
| Safety | Right Safety |
| Druggability | (Right Target — tractability arm) |
| Translational | Right Tissue (exposure / PD) |
| Commercial | Right Commercial Potential |
| Clinical | (clinical precedent — practical 6th bucket) |

1. **Biomarker = its own category** (5R "Right Patient" is a PEER of "Right Target", not a child). It is
   also the category with the most room to grow — the reason to give it top-level space now.
2. **Differentiation → under Commercial** as the wired half (don't mint a category for one card; the
   decisive competitive/IP axis is Cortellis/IQVIA-walled). Note the co-mutation cross-link to Biomarker.
3. **Risk-category table REPLACES the gate scorecard** as the lead lens (two summary tables is
   redundant; the axis-banded sections below still carry every gate letter + status).
4. **DATA-DRIVEN SURFACING (key change from the original proposal): surface a category IFF ≥1 of its
   member sub-skills produced evidence this run.** NO "not-wired" placeholder rows. Rationale: the user
   wants the dashboard to reflect what's actually wired + grow automatically as data lands — a category
   appears the moment its first sub-skill fires (wire translational-readiness → "Right Tissue" shows up,
   no dashboard edit). This SUPERSEDES original Decision 2 (honest placeholders): absence of a category
   is itself the honest signal ("we don't evidence this yet"), shown via a compact one-line "categories
   not yet evidenced: Translational, Clinical, Commercial" footnote rather than full rows.
   - For a typical KRAS run today this surfaces: **Biological · Biomarker · Druggability · Safety**
     (all four have wired sub-skills that fire); Translational / Clinical / Commercial stay hidden.

Everything below is the original proposal; §Decision 2 is amended by locked-decision 4 above.

---

## The ask (one sentence)

Organize the target dashboard by the **risk categories a drug-discovery portfolio committee actually
uses** — Biological / Biomarker / Druggability / Safety / Translational / Clinical / Commercial —
so the report reads in the reviewer's language AND the framework's coverage gaps are honestly visible
(unwired categories say "insufficient evidence — not wired", not silently absent).

## The tension to resolve

We have TWO structures in play:
1. **Gate-model v2 (the contract):** two axes — `biology_gates` (A–E) + `modality_fit` (named) —
   with `biomarker_facets` as a relational layer. This is what `gate_coverage.yaml` 2.0.0 encodes and
   what the resolver/scorecard consume.
2. **The 6 discovery risk categories (this memo):** the committee-facing rollup.

These are NOT competing — they are different altitudes. The v2 axes are the *engineering contract*
(what data feeds what verdict). The risk categories are the *presentation spine* (how a reviewer reads
risk). The dashboard can present risk-categories on top WITHOUT changing the contract — the categories
are a VIEW that groups the existing gates.

## Proposed mapping (category ← gates/sub-skills)

| Risk category | Fed by (gates / sub-skills) | Framework coverage today |
|---|---|---|
| **Biological** | A Expressed · B Selective · C Functional dependence · D Mechanism · E Altered | **captured/partial** — the validated lane |
| **Biomarker** | mutation×dependency, expression×dependency, CRISPR×RNAi concordance, predictability, SL partners, subtype | **captured/partial** — patient-selection + confidence facets |
| **Druggability** | Small-molecule (PRISM + pocket) · Surface-biologics (ADC/TCE) | **partial / blind** (surface data-blocked) |
| **Safety** | Safety (gnomAD LoF + normal-tissue) | **partial** — thin (see SAFETY_MECHANISM_AUGMENTATION.md) |
| **Translational** | *(unbuilt — translational-readiness placeholder)* | **blind — not wired** (models/PD/imaging) |
| **Clinical** | *(unbuilt — clinical-precedent placeholder)* | **blind — not wired** (license-walled) |
| **Commercial** | Differentiation (co-mutation/mutual-exclusivity) + *(unbuilt — competitive/IP)* | **partial → license_blocked** (Cortellis/IQVIA) |

## The three decisions this memo makes

### Decision 1 — Biomarker is its OWN category, NOT under Translational.
The user asked: "biomarker goes into translational?" **No.** A biomarker (mutation×dependency,
expression×dependency) answers *"who responds?"* — it is a **patient-selection refinement of the
Biological case** (specifically Functional dependence). Translational is *"can we test it in the
clinic?"* (models, PD assays, imaging tracers) — a different question, currently unwired. Putting
biomarkers under Translational would conflate patient-selection with clinical-readiness.

This reconciles the two recent asks: the **Biomarker band** (third axis band, already scoped) IS the
Biomarker risk-category. It sits between Biological and Druggability — the contract's `biomarker_facets`
list, surfaced as a category. The card-grain facets (mutation-stratified, CRISPR×RNAi, predictability)
render here, pulled out of their home gates — which fixes the "mutation-stratified under Altered is
confusing" complaint: mutation-FREQUENCY stays in Biological/Altered, the biomarker-STRATIFICATION
moves to Biomarker.

### Decision 2 — unwired categories render as honest placeholders, not omissions.
Translational, Clinical, and the unlicensed half of Commercial have no wired sub-skill. They render as
category rows with `risk_level: insufficient_evidence` + a `driver` naming WHY (e.g. "Phase-J
translational-readiness placeholder — data not wired"; "clinical precedent license-walled
(Cortellis/IQVIA)"). This is the same honesty discipline as the placeholder skills + the deciding-axis
router's "gates we're blind on". A committee sees the full risk surface + exactly where the framework
can and cannot speak — never a falsely-clean picture.

### Decision 3 — a category's risk level is a ROLL-UP of its gates' statuses, computed not authored.
`risk_level ∈ {low | moderate | high | insufficient_evidence}` derives from the member gates'
scorecard statuses (the SAME 4-state the scorecard already computes): all-supportive → low; any
opposing → elevated; all coverage-gap / no wired sub-skill → insufficient_evidence. This reuses
`_gate_scorecard` + the nomination-gate policy — NO new classification logic, so the category rollup can
never disagree with the per-gate verdicts. The `driver` column names the load-bearing gate(s).

## Chosen presentation (reconciles both structures)

**Risk-category table as the top-of-dashboard lens + the v2 bands as the section body.**
- **Top:** a compact "Risk by category" table — 7 rows (the 6 categories + Biomarker), columns
  `Category | Risk level | Driver`, each row linking down to its section(s). This is the
  portfolio-committee glance, replacing the current gate-only scorecard as the lead lens.
- **Body:** the axis-organized sections (Biology band, Biomarker band, Modality-fit band) render
  underneath, unchanged from the v2 dashboard. Risk categories map onto these bands (Biological+Biomarker
  live in the biology-ish bands; Druggability+Safety in modality-fit; Translational/Clinical/Commercial
  are placeholder rows that link to a short "not-wired" stub section).

This keeps the engineering contract (v2 axes) intact while giving the reviewer their language on top —
the same HYBRID principle already chosen for the gate scorecard (lens on top, module content below).

## What this changes vs today
- The gate scorecard's ROWS regroup from "8 gate letters" to "7 risk categories" (a presentation change
  in `_gate_scorecard` + its renderer; the per-gate data is unchanged).
- Adds 3 placeholder category rows (Translational/Clinical/Commercial) with wired="no".
- Requires a `risk_category` field on each gate in the contract (additive, like `axis`) so the rollup is
  contract-driven, not hardcoded in the dashboard.

## What it does NOT change
- No resolver / nomination-gate logic (verdict-neutral, like the v2 axes).
- No new science; no gate identities beyond adding the `risk_category` grouping field.
- The v2 two-axis contract structure stays — risk categories are a view over it.

## Open questions for the reviewer
1. **Is "Biomarker" a 7th top-level category, or a sub-row under Biological?** (Memo recommends its own
   category — it's a distinct committee question, patient-selection.)
2. **Does Differentiation (co-mutation) belong under Commercial, or its own "Competitive" category?**
   (Memo folds it under Commercial as the wired half; the unlicensed competitive/IP is the unwired half.)
3. **Should the risk-category table REPLACE the gate scorecard, or sit above it?** (Memo recommends
   replace-as-lead — two scorecards is redundant — but the gate-letter view could stay as a detail toggle.)
