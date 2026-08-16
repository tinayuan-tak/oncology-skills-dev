# Per-axis strength + certainty model (Step-3 design note)

**Status:** DRAFT for sign-off (2026-08-15) · companion to `PER_DIMENSION_EVIDENCE_REPRESENTATION.md`
**Decision this note gates:** what `(strength, certainty)` *means* per axis, before we wire it into
the sub-skills/resolvers (the invasive Layer-1 change). Getting these definitions wrong bakes a bad
certainty model into the production spine, so this is a deliberate, reviewed step — NOT a mechanical port.

---

## 1. The model (axis-agnostic frame)

Every axis emits, alongside its categorical verdict, a triple (§2 of the parent doc):

- **strength** — *signed graded* magnitude of the signal. Sign from the rule-suffix / effect
  direction (`-supportive` = +, `-killer`/`-warning` = −, `-neutral` = 0); magnitude from the axis's
  own numeric provenance (already present in each card's `summary`). Range: a bounded score
  (e.g. −1..+1) or an ordinal (strong/moderate/weak/none) — **recommend ordinal**, to avoid false
  precision, mapped to a sign.
- **certainty** — *how much of the evidence we have, and whether independent lines agree.* Two
  sub-components, combined **weakest-link (min)**:
  - **coverage** — did we measure it, and with what power? (n, data present vs `insufficient`/blind)
  - **corroboration** — do independent comparators/assays agree? (concordance, multi-cohort)
  Emit as ordinal `low | medium | high` **plus an explicit `unknown_mass`** (Dempster–Shafer flavour)
  so a data-thin axis reads as *wide uncertainty*, not *low score*.
- (**relevance** is NOT here — it lives in the objective spec, §2 of the parent doc.)

**Key rule:** certainty needs **no outcome labels** — it is a property of the evidence, computed from
provenance the methods already emit. It is validated *by construction* (a thin-n axis MUST get low
certainty), not against clinical outcomes.

---

## 2. Proposed per-axis definitions (for review)

Drawn from the numeric provenance each card already emits. **These are proposals — each is a
per-axis expert call (like the MARK2/3 and re-grade judgments).**

| Axis | strength from | certainty: coverage | certainty: corroboration |
|---|---|---|---|
| **dependency** | fraction_strongly_dependent, median_chronos effect, dependency_class | n_cell_lines_evaluated (power) | CRISPR↔RNAi concordance; distribution_shape |
| **genomic_alteration** | recurrence/frequency, alteration_role | cohort n; GENIE panel-intersect coverage | agreement across cohorts (MC3 + GENIE) |
| **selectivity** | max_abs_log2fc (A/C cells) | cells_ran (# comparators) | cells_supporting / cells_ran; purity-confound |
| **tumor-presence / expression** | median TPM percentile, fraction_expressed | n samples | RNA↔protein concordance |
| **safety** | LoF-constraint magnitude (LOEUF), # human-genetics legs | gnomAD data present vs indeterminate | # of independent legs firing (burden/ClinGen/ClinVar/mouse) |
| **tractability_sm** | pocket ligandability, PRISM activity | PDB/AlphaFold structure coverage | PRISM↔CRISPR concordance |
| **surface_modality** | density level, topology favorability | density_evidence_level (A–E) | topology × family agreement; internalization measured? |
| **mechanism** | MoA-class specificity | SIGNOR edge count | source breadth |
| **differentiation** | co-mutation / ME effect (q-value) | cohort n | `pooled_eligible` (panel-intersect) |

**Worked example — dependency (the reference axis for the pilot wiring):**
- strength: `strongly_dependent` (frac_strong ≥ ~0.5) → strong+; `lineage_selective` → moderate+;
  `non_dependent` → strong−; scaled by median Chronos.
- coverage: n_cell_lines ≥ 20 → high; 5–20 → medium; < 5 → low (mirrors the existing power floor).
- corroboration: CRISPR↔RNAi `concordant` → high; single-assay → medium; `discordant` → low.
- certainty = min(coverage, corroboration); unknown_mass rises as either drops.

---

## 3. Where it's computed + emitted

The **resolver already sees the numeric provenance** (the `_`-prefixed fields feeding each verdict), so
`(strength, certainty)` is emitted there alongside the categorical verdict — one place per axis, no new
data reads. The grounded context/risk agent (§5.1) *anchors to* the verdict and *reads* certainty; it
does not compute it.

---

## 4. Open questions for sign-off

1. **Ordinal vs continuous** strength/certainty? (Recommend ordinal + `unknown_mass`; matches the
   existing categorical confidence and avoids false precision.)
2. **Per-axis thresholds** — the n / effect-size / concordance cutoffs per axis (the table's
   right-hand columns) need per-axis calibration; who owns each?
3. **`unknown_mass` exposure** — surface it in the panel as an interval/band, or only as the ordinal?
4. **Rollout order** — recommend wiring **dependency first** (richest provenance, clearest thresholds)
   as the reference pattern, validate by construction, then fan out to the other axes.

---

## 5. Reference-implementation plan (Step 3)

1. Wire `dependency` (this note's worked example) in its resolver/sub-skill → emit
   `{strength, certainty{level, coverage, corroboration, unknown_mass}, provenance}` beside the verdict.
2. Validate *by construction*: a low-n / discordant dependency MUST read low certainty; a
   well-powered concordant one high. (No outcome labels involved.)
3. Fan out axis-by-axis using the table, each as its own reviewed change.
