# on-target-safety-liability — finalized data product

The **I/O contract**: data wired IN, package emitted OUT, what is locked. Human-genetics safety logic +
history live in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `on-target-safety-liability` |
| **Skill code version** | 1.22.0 |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | `gating` (the 4 concern verdicts force `action: hold`; polarity dynamic display-only; **no scalar killer** — safety is a HOLD, not a veto) |
| **Verdict fields** | `headline.safety_verdict` (scalar = the honest raw WT-loss concern; `skill_report.call`) + `safety_verdict_by_modality` (the modality-conditional GoF-downgrade layer) |
| **Output shape** | `data_package` |
| **Emitted schema** | `target-contracts/schemas/skills/on-target-safety-liability.decision.schema.json` (generated, self-contained) |
| **Conformance target** | the FRESH replay emit (`test_safety_replay.py`; BRAF/TP53 `highly_constrained_safety_concern`, EGFR/VHL/ERBB2 `human_genetics_safety_concern`) |

---

## 1. Inputs — wired data (17 cards)

Every card traces card → method → data-catalog manifest → materialized S3 product. **All products LIVE**;
no placeholders, no stale refs, no card-status skew. `run.py` has no `CARD_CONTEXT` map.

**Verdict-driving (8 → `safety.resolver.yaml`):** `gnomad-lof-constraint` (`gnomad-constraint-per-gene-v1`),
`gene-burden-safety`, `clingen-dosage`, `clinvar-pathogenicity-safety`, `mouse-ko-phenotype` (INFERRED
tier — never a measured killer) [all reading the `opentargets-26-06` legs], `pan-cancer-crispr-dependency-distribution`
(`depmap-consortium-26q1`, common-essential broad-tox), `normal-tissue-liability` (`hpa-v25-1`, HPA-IHC),
`normal-tissue-protein-abundance-tphp` (`normal-tissue-protein-abundance-per-gene-v2`, TPHP DIA-MS — the
#1793 HPA-BLIND vital-organ rung: `tphp_hpa_blind_vital_organ_liability_class == vital_organ_abundant` →
`normal_tissue_protein_safety_concern`; the full vital-organ view on the same card stays display context).

**Display-only / verdict-inert (6):** `shet-lof-intolerance` (`shet-selection-per-gene-v1`),
`target-safety-prioritisation`, `normal-tissue-liability-gtex` (`gtex-tpm-recount3-long-v1`, RNA breadth —
additive, fires no safety rung), `drug-warning-safety`, `onsides-adverse-event-safety`,
`sc-normal-celltype-expression` (scRNA normal-tissue leg of the L2b-3 `normal_liability_concordance`
cross-source claim; its veto rule enters the fired list but is not a resolver rung).

**Orphan-rule (3, feed ONLY the per-modality layer + claim_vector, not the scalar):** `alteration-role`
(allele-selective eligibility), `copy-number-distribution` (amplified-oncogene disqualifier),
`functional-gene-state` (rarely-altered disqualifier).

---

## 2. Coverage & capability ceilings (contractual)

- **gnomAD** per-gene, indication-agnostic; `indeterminate` for genes absent from v4.1.1 (bands OR-combined pLI≥0.9 OR LOEUF≤0.45).
- **Open Targets 26.06 legs** (6 cards read the one source): gene-burden p<1e-6; ClinGen Definitive/Strong;
  ClinVar germline-only; mouse-KO INFERRED (developmental-vs-adult guardrail); prioritisation verdict-inert.
- **GTEx breadth** = bulk RNA only (not protein), additive — fires no safety-resolver rung.
- **DepMap pan-essentiality** = Chronos ~1500 lines, co-requires curated core-essential membership; cell-line, not in-vivo.
- **HPA-IHC essential-tissue** = categorical IHC breadth over a closed 16-name tissue vocabulary —
  structurally blind to nerve/blood/adrenal_gland/thyroid/pituitary; an `absent` measured-clear is
  scope-limited to the representable organs.
- **TPHP HPA-blind vital-organ view (#1793)** = DIA-MS protein over exactly that blind set, same
  abundance floor as the full vital-organ view; liability fail-CLOSED (an above-floor hit on a thin arm
  counts; measurability gates ABSENCE claims only). `pituitary` is covered by NO protein panel —
  `hpa_blind_vital_organs_uncovered` + the card's coverage-gap warning carry it explicitly, and
  `data_unavailable` widens the uncovered set to all 5 (a gap, never reassurance).
- **OnSIDES / drug-warning** = confounded on-target joins (~63% fuzzy match), verdict-inert.

---

## 3. Emitted output

`output_shape: data_package` → the standard `write_package` tree. `decision.json` top-level:
`skill · target · indication · question · generated_at · headline · cards · fired_rules · provenance ·
run_health` (+ optional synthesis). Contractual headline fields: `safety_verdict` (pinned 8-value enum —
the raw WT-loss concern; `skill_report.call`), `safety_verdict_by_modality` (10 modality-channel keys ×
`{action ∈ hold/conditional/supportive/not_applicable/no_concern, wt_engagement, driving_rules}` — the
modality-conditional GoF layer where an allele-selective SM may spare WT), the `skill_report` spine
(`role: gating`, dynamic `polarity`, `call` = `safety_verdict`), `headline_block`, `claim_vector`
(constraint/burden/dosage/model/pharmacovigilance), `key_signals`. All else schema-open.

---

## 4. Contract & versioning (what is locked)

Pinned by the generated, self-contained `on-target-safety-liability.decision.schema.json` (gating-scalar
pins: `role: gating` + the 8-value `safety_verdict`/`call` enum = the safety resolver set = `_SAFETY_VERDICT_PHRASE`;
no run.py mints — the mutant-selective downgrade token was retired v2.0.0; no polarity const;
`safety_verdict_by_modality` typed-open). CI: fresh-replay conformance (`test_safety_replay.py`),
schema-well-formedness + static-golden-if-full (CI-fail-not-skip), cross-skill coverage ratchet,
target-contracts schema meta-test. Change policy: new verdict token → pins enum + regenerate (minor);
spine key → SHARED source (coordinate; major on rename); new facet → no schema change.

## 5. Known gaps & notes (non-blocking)

- **Logical aliases resolved at read time:** `opentargets-26-06` (6 cards, distinct partitions),
  `depmap-consortium-26q1` (3 matrices), `onsides-adverse-event-per-gene-v1` (fuzzy join alias).
- **No scalar killer:** the WT-loss "kill" is realized as (a) the per-modality `hold` on `engages_wt`
  channels (degrader/RNA) and (b) borrowed pan-essential killers that veto via the *dependency* axis — the
  safety scalar itself is always a HOLD.
