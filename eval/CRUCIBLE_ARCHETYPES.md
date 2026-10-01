# RFC — the Crucible across all subskills (archetype adapters)

**Status:** proposal / plan of record. **Epic:** SK#2303 (subskill iteration loop) follow-on.
**Audience:** engineers extending the loop to subskills beyond the current L2a→L2b→L3 vertical.

## 1. What the Crucible is today

The **Crucible** is the subskill self-audit loop in `eval/loop/`. For one focused subskill it runs a
coverage-aware batch of `target × indication` pairs fresh (`--emit-envelope`), then:

```
emit → substrate.assemble → triangulation judge → containment (deterministic, fail-closed)
     → adversarial critic (LLM) → tier router (T2 propose / T3 adjudicate)
     → hash-chained ledger → convergence (held-out) → compile_findings → GitHub issues
```

It runs on the **6 skills that emit the L2a `source_properties` vertical AND the L2b
`integrated_properties` island**: `functional-requirement`, `genomic-alteration-profile`,
`on-target-safety-liability`, `surface-modality-fit`, `tumor-presence`, `tumor-selectivity`.

## 2. The load-bearing observation

**The Crucible core is archetype-independent.** The judge harness (injectable LLM), the containment
*grounding* check (does each `datum_ref` resolve against the raw substrate), the adversarial critic, the
tier router, the hash-chained ledger, the convergence stopping rule, and the cross-run `compile_findings`
+ idempotent issue emitter make **no assumption about a skill's biology** — only that there is *a bounded
structured view, and every claim cites a datum you can re-verify.*

So extending the Crucible to the other subskills is **not** 24 bespoke loops. Only two things vary per
skill, and they are small:

1. **The substrate adapter** — how to assemble the bounded view the judge sees from that skill's emitted
   package (today: `substrate.assemble_from_objects`).
2. **The audit predicates** — the judge's `finding_kinds`, the containment *contract-semantics* checks
   (today: `_corroboration`, `_class_semantics`, the consumption gate), and the applicable probes.

Everything else is shared, untouched.

## 3. The adapter interface (what each archetype must provide)

```
assemble(evidence_package, decision) -> substrate_bundle
    # {layers..., field_contracts, raw islands/objects}; null_everything on a dead package (fail-closed)
judge_view(substrate_bundle, decision) -> prompt_payload
finding_kinds -> enum                      # what a "finding" is for this archetype
containment_predicates -> [fn]             # contract-semantics checks over this archetype's tokens
applicable_probes(skill) -> (probe, ...)   # deterministic structural regressions
```

The shared core consumes these through the same `process_package` seam that exists today
(`judge → contain → adversary → tiers`). An adapter is selected per skill (a registry keyed by skill name
→ archetype). **Invariant preserved everywhere: index on the property layers, NEVER on
`synthesis.verdict` / `go_forth` (SK#2091).**

## 4. Archetype taxonomy

| archetype | output shape | skills | adapter work |
|---|---|---|---|
| **A. L2a→L2b→L3 vertical** | per-source anchors → islands → claims | the 6 loop-ready | **exists** |
| **B. L2b-only focused** | island + provenance, no L2a anchors | `mechanism-and-pharmacology`, `target-intrinsic` | land L2a (→ A), or a thin provenance-native adapter |
| **C. Composed integrator** | consumes an already-composed package; emits typed cross-line edges, evidence paths, a gate-clamped hypothesis | `target-profile`, `cross-evidence-hypothesis` | **new** — integration-consistency audit |
| **D. Relational / ranked-table** | ranked partner table, co-mutation panel | `combination-and-vulnerability`, `differentiation-landscape` | **new** — per-row class-vs-datum + ranking monotonicity |
| **E. Descriptive / verdict-inert** | context classes (lit-volume, immune-hot, readiness tier) | `literature-context`, `immune-context`, `translational-readiness`, `tractability-small-molecule` | **light** — reuse A's class-vs-datum, gateless |

Not in scope (meta / pure read): `render-evidence-package`, `example-gallery`, `query-target-evidence`,
`catalog-query`, `literature-risk-assessment` (context-tier, holds no cards). `cis-feature-coherence`
*deliberately* emits no L2a (`run.py`: "source_properties and local_composites are OMITTED") — not a loop
target.

## 5. Per-archetype design

### E — descriptive / verdict-inert (do first; cheapest)
The descriptive classes are abstractions over a datum exactly like an L2a class token: `immune_hot` rests
on a CD8 fraction, a literature-volume class on co-occurrence counts. **Reuse archetype A's
`class_not_supported_by_datum` check** against the descriptive class + its anchors. Gateless: no
convergence-on-verdict (there is no verdict), so convergence degrades to finding-emptiness only. Adapter is
a thin wrapper that maps the skill's annotation block to the `l2a`-shaped `{property, anchors,
reliability}` the existing judge/containment already read.

### D — relational / ranked-table
The "property layer" is the set of **rows** (partner × interaction-type × evidence × direction; or
gene-pair × co-mutation class). Findings: `row_class_not_supported_by_datum` (a row's class vs its
evidence), `ranking_not_monotone_in_evidence` (a higher-ranked row with weaker evidence than a lower one),
`panel_incomplete` (a measured source absent from the panel). Containment grounds each row's `datum_refs`
against the table; the adversary critiques overstated partner claims. No L2a vertical needed.

### C — composed integrator (hardest; highest value; do last)
target-profile / cross-evidence-hypothesis are **decision-facing** — their output is verdict-adjacent,
which collides head-on with *index-on-property-layers-never-the-verdict*. The adapter must expose the
integrator's **intermediate** structure, NOT its headline verdict:
- the sub-verdict panel it consumed (per-axis, from the composed `evidence_package`),
- the typed **cross-line edges** and **evidence paths** it asserts,
- the **hard-gate ceiling** inputs and the **clamp** arithmetic.

Findings are *integration-consistency* defects, e.g.:
- `edge_unsupported_by_subverdict` — an asserted DEP↔SURVIVAL edge no consumed sub-verdict carries;
- `clamp_not_applied` — a proposed `go_forth` that exceeds the deterministic hard-gate ceiling where the
  clamp should have fired (the loop re-derives the ceiling from the spine; it never proposes a verdict);
- `evidence_path_broken` — a cited path whose datum does not resolve.

Explicitly **out of bounds**: "the verdict is wrong." The audit is on the *plumbing*, not the call.

### B — L2b-only focused
`mechanism-and-pharmacology` / `target-intrinsic` emit the L2b island + `provenance.sources` but no L2a
anchors. Two options, in order of preference: **(1)** land their L2a `source_properties` (this is the
Evidence-Property arc's mandate, SK#1507 — once landed they are archetype A with *zero* new Crucible
code); **(2)** a thin provenance-native adapter that audits the integrated token against its own
`provenance.sources` arms (weaker — no per-source anchors to audit the class against).

## 6. Relationship to the Evidence-Property arc (do not duplicate)

Several "not-loop-ready" skills just need L2a landed — that is **SK#1507's** job, not the Crucible's. The
honest division of labour: the Evidence-Property arc lands the shared property layers; the Crucible rides
on top and audits them. So archetype **B** is mostly arc work; the Crucible-specific new build is
archetypes **C** and **D** (and the light **E** wrapper).

## 7. Phased rollout → child issues

1. **E (descriptive)** — thin class-vs-datum wrapper + skill→archetype registry. Pilot on
   `literature-context` or `immune-context`.
2. **D (relational)** — ranked-table adapter + row-grounding/monotonicity probes.
   (`combination-and-vulnerability`, `differentiation-landscape`.)
3. **C (composed)** — integration-consistency adapter for `target-profile` /
   `cross-evidence-hypothesis`; the crown jewel, done with care around the verdict boundary.
4. **B** — fold into A by landing L2a (coordinate with SK#1507), not a bespoke variant.

Cross-cutting: an **archetype registry** (`skill → adapter`) + an adapter base so `process_package`
dispatches on it; and a LOOP.md §1 refresh (the "3 loop-ready" table is stale — it is 6).

## 8. Non-goals / open questions

- **Non-goal:** auto-applying any finding. STOP-A holds for every archetype — propose-only, issues for
  human adjudication.
- **Open:** convergence for gateless archetypes (E) is finding-emptiness only — is a held-out split even
  meaningful without a verdict to re-derive? (Likely: keep the split for finding-stability, drop the
  verdict-pin.)
- **Open:** archetype C's edge/clamp view needs a stable handle from the composed `evidence_package` — a
  small contract addition on the integrator's side may be required.
