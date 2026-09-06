# combinatorial-dependency — finalized data product

The **I/O contract**: data wired IN, package emitted OUT, what is locked. This is an **AUXILIARY (non-fan-out)**
skill — it was RETIRED from the target-profile fan-out 2026-08-20 (its cards compose into
`combination-and-vulnerability`), but it remains runnable standalone and is locked ADDITIVELY as a finalized
data product. Logic + history live in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `combinatorial-dependency` |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | `descriptive` — pinned descriptive-**SCALAR**: it carries a real SELF-CONTAINED verdict but is NOT wired into the target-profile gate ladder (`skill_report.role: descriptive`, `polarity: not_scored`) |
| **Verdict field** | `headline.combinatorial_dependency_verdict` ∈ `{constitutive_combinatorial_dependency, context_combinatorial_dependency, suppressive_combinatorial_interaction, no_combinatorial_dependency, combinatorial_dependency_insufficient}` — and `skill_report.call` MIRRORS it (or null on a build fault) |
| **Output shape** | `data_package` |
| **Emitted schema** | `target-contracts/schemas/skills/combinatorial-dependency.decision.schema.json` (generated, self-contained) |
| **Conformance target** | a FROZEN FULL emit `fixtures/combinatorial_dependency_full_emit.json` (real SMARCA4·LUAD run — the canonical constitutive SMARCA4↔SMARCA2 paralog synthetic lethality; `call=constitutive_combinatorial_dependency`, role=descriptive) — no replay harness |

---

## 1. Inputs — wired data (1 card)

**LIVE.** One card + its dedicated `combinatorial_dependency` rule subset; a SELF-CONTAINED verdict
(`scripts/run.py` `_verdict` maps the fired rule → the verdict directly; NO shared resolver rung).

| card_id | method / manifest | role |
|---|---|---|
| `combinatorial-dependency` | `paralog-genetic-interaction` over `depmap-paralog-genetic-interaction-per-pair-v1` (DepMap ParalogV2 26Q1 dual-KO) | verdict-bearing (`combinatorial_dependency_class` → the 5-member verdict) |

GI = `dual_ko - (single_a + single_b)` on the Chronos scale; NEGATIVE = synthetic-lethal / buffering.
`combinatorial_dependency_class ∈ {strong_synthetic_lethal, context_synthetic_lethal, suppressive_interaction,
no_interaction, no_paralog_screened, data_unavailable}` drives the rule subset
(`interpretation-rules/combinatorial-dependency.rules.yaml`).

---

## 2. Coverage & capability ceilings (contractual)

- **PARALOG library, not arbitrary pairs.** DepMap ParalogV2 screens curated paralog pairs only. Absence of a
  partner → `combinatorial_dependency_insufficient` (a coverage gap, `combo-no-paralog-screened`), NEVER a
  measured negative (measured-vs-null discipline).
- **KO ≠ inhibition / SL reproducibility.** A measured dual-KO GI is a combination HYPOTHESIS: it removes the
  ENTIRE paralog whereas a drug inhibits one activity partially, and SL frequently fails to replicate across
  screens. The VERDICT-INERT `combinatorial_dependency_confidence_caveat` (3 tiers) + `combinatorial_druggability_caveat`
  (scaffold partner → degrader) + `combinatorial_dependency_provenance` quorum surface this; they reuse the shared
  `_skills_common/sl_crosswalks` corpus and NEVER move the verdict.
- **Genotype-conditional SL** (e.g. SMARCA2 conditional on SMARCA4 loss) may read `no_interaction`/`context` on
  the pan-line summary when the panel is thin in the conditioning genotype; the `validated_paralog_synthetic_lethal`
  guard is DATA-BLIND-TOLERANT (fires on a screened canonical pair even when the GI reads `no_interaction`).
- **`--literature` lane is a GENUINE second channel** (published paralog-SL literature vs the measured GI),
  attached AFTER the self-contained verdict — it cannot touch the verdict.

---

## 3. Emitted output

`output_shape: data_package` → the standard `write_package` tree. `decision.json` top-level:
`skill · target · indication · question · generated_at · headline · cards · fired_rules · provenance ·
run_health`. Contractual: `headline.combinatorial_dependency_verdict` (the 5-member enum) + the shared
`skill_report` spine (`role: descriptive`, `polarity: not_scored`, `call == combinatorial_dependency_verdict`),
`headline_block` (verdict + certainty-sidecar confidence + top-tension). Descriptive display fields
(`combinatorial_dependency_class`, `n_paralog_partners_screened`, `n_interacting_partners`, `strongest_partner`,
`strongest_partner_mean_gi`, `top_partners`, the three caveats + provenance quorum) are schema-open.

---

## 4. Contract & versioning (what is locked)

Pinned by the generated, self-contained `combinatorial-dependency.decision.schema.json` (descriptive-scalar
pins: `headline.combinatorial_dependency_verdict` REQUIRED + enum; `skill_report.role: descriptive` const +
`polarity: not_scored` const + `call ∈` the same enum-or-null). CI: full-emit conformance
(`tests/test_data_product_schema.py` against the frozen full golden, CI-fail-not-skip), the descriptive-scalar
spine assertion (`call == verdict`), the cross-skill coverage ratchet, and the target-contracts schema meta-test.

## 5. Known gaps & notes (non-blocking)

- **Auxiliary lock (additive).** Not a fan-out member — retired from the fan-out 2026-08-20 (SKILL.md
  `status: deprecated`); locked because it is a fully-wired standalone verdict skill. It must NOT be re-added
  to `SUB_SKILLS`.
- No stale-metadata / placeholder: the single card composes one LIVE product (DepMap ParalogV2 26Q1).
- No replay harness → conformance rests on the frozen full golden (a SMARCA4·LUAD constitutive-SL emit).
  **Refreeze** (`tests/fixtures/combinatorial_dependency_full_emit.json`) if the emitted shape changes.
- Published CC-BY GI maps (Dede / in4mer / Horlbeck) are a future corroboration leg for genes absent from the
  ParalogV2 library; a per-line join to partner ALTERATION status (for genotype-conditional SL) is a follow-on.
