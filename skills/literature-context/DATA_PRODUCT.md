# literature-context — finalized data product

The **I/O contract**: data wired IN, package emitted OUT, what is locked. This is the **15th target-profile
fan-out member** (added #1065). Logic + history live in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `literature-context` |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | `descriptive` — **GATELESS / TOKENLESS** cited-literature read (`verdict_fn=None` → `skill_report.call` null; `polarity: not_scored`) |
| **Verdict field** | none — display fields only (`cited_evidence_status ∈ {ok, insufficient, no_evidence}` is NOT a verdict) |
| **Output shape** | `data_package` |
| **Emitted schema** | `target-contracts/schemas/skills/literature-context.decision.schema.json` (generated, self-contained) |
| **Conformance target** | a FROZEN FULL emit `fixtures/literature_context_full_emit.json` (real KRAS·COADREAD run; `call=null`, role=descriptive) — no replay harness |

---

## 1. Inputs — wired data (1 card)

**LIVE.** One card, composing two products; verdict-inert display (no resolver rung).

| card_id | method / manifest | role |
|---|---|---|
| `cited-literature-evidence` | `cited_literature_evidence` composing `opentargets-europepmc-evidence-per-target-v1` (~1.1 GB) + `pubtator3-gene-disease-relations-per-gene-v1` (~34 MB) | display-only (cited-literature co-occurrence volume/recency + typed relation direction) |

---

## 2. Coverage & capability ceilings (contractual)

- `paper_disease_mentions` is summed paper×disease (inflated; `n_diseases` surfaces the inflation) — the
  3-tier `cited_evidence_confidence_caveat` gates on it (volume ≠ validation).
- Relation types dominated by `associate`; falls back to `target_level` scope when the indication has no EFO/MeSH.
- **Deliberately NO `--literature` LLM lane** — the card *is* the Europe-PMC/PubTator3 literature; a lane would be circular.

---

## 3. Emitted output

`output_shape: data_package` → the standard `write_package` tree. `decision.json` top-level:
`skill · target · indication · question · generated_at · headline · cards · fired_rules · provenance ·
run_health`. Contractual: the `skill_report` spine (`role: descriptive`, `polarity: not_scored`, `call: null`),
`headline_block`, `claim_vector` (VOLUME/RECENCY/RELATION axes), `key_signals`. Display fields
(`cited_evidence_status`, `paper_disease_mentions`, `relation_types`, `cited_statements`, …) are schema-open.

---

## 4. Contract & versioning (what is locked)

Pinned by the generated, self-contained `literature-context.decision.schema.json` (gateless-descriptive pins:
`role: descriptive` + `polarity: not_scored` const + `call: null`; no headline verdict field required). CI:
full-emit conformance (`tests/test_data_product_schema.py` against the frozen full golden, CI-fail-not-skip),
cross-skill coverage ratchet, target-contracts schema meta-test.

## 5. Known gaps & notes (non-blocking)

- Was the one fan-out member missed in the initial 14-skill lock (added to SUB_SKILLS via #1065 after that
  roster was enumerated) — now closed (15/15).
- No stale-metadata / placeholder; both composed products LIVE.
- No replay harness → conformance rests on the frozen full golden (refreeze if the emitted shape changes).
