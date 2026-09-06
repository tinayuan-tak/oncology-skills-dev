# literature-risk-assessment — finalized data product

The **I/O contract**: data retrieved IN, package emitted OUT, what is locked. The retrieval-grounding +
containment logic and history live in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `literature-risk-assessment` |
| **Skill code version** | 0.1.0 |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Kind** | **BESPOKE auxiliary** — NOT a target-profile fan-out member; output is NOT the `skill_decision` envelope (no `run_health`, no `headline.skill_report`) |
| **Role** | `context` — **CONTEXT-TIER ONLY**: top-level `tier` is the literal string `"context"`, never a gate/verdict/card/rule/sub-verdict input (RISK_ASSESSMENT_INTEGRATION.md, decided 2026-07-17) |
| **Verdict field** | none — a per-dimension `risk_level ∈ {LOW, MEDIUM, HIGH, not_assessed}` across the six fixed pillars (no aggregate/rollup verdict) |
| **Output shape** | `data_package` → bespoke `risk_assessment.json` |
| **Emitted schema** | `target-contracts/schemas/skills/literature-risk-assessment.emit.schema.json` (**HAND-AUTHORED** bespoke, self-contained; **NOT generated**, no monolith pin) |
| **Conformance target** | a **FRESH REAL emit** — `run()` assembled through the real emitter (containment guard + confabulation downgrade + provenance) with only its two external I/O boundaries (PubMed retrieval, per-dimension model call) replaced by frozen responses. No live Bedrock / network. CI-fail-not-skip. |
| **Nomination citability** | `provenance.citable_in_nominations: false` (const) — literature is UNPINNABLE / exploratory-grade; it never cites or gates into a nomination |
| **Composition status** | `wired` |

---

## 1. Inputs — retrieved literature (NO cards)

This skill consumes **NO cards and fires NO rules** (`cards_used: []`, `rules_scope: []`). It retrieves
live literature and, optionally, reads a deterministic evidence package for anchoring.

| input | source | role |
|---|---|---|
| PubMed abstracts | `pubmed_search.py` → NCBI E-utilities (6 per-dimension entity-qualified searches) | the ONLY PMIDs the model may cite; date-boundable (`--mindate/--maxdate`) for a pinnable corpus |
| evidence package (optional) | `--evidence-package <pkg.json>` → `synthesis.sub_verdicts` | anchors the three OVERLAP dimensions to the deterministic sub-verdict (never a silent override) |

**Overlap anchoring** (dimension → sub_verdict key): `biological → dependency`, `druggability →
tractability_sm`, `safety → safety`. The other three (`translational`, `clinical`, `commercial`) are
pure-literature / engine-blind — no anchor.

---

## 2. Coverage & capability ceilings (contractual)

- **Retrieval-grounded, not memory-cited:** the model rates only over the retrieved abstracts and may cite
  ONLY their PMIDs. A hard **containment guard** (`_contain`, digit-normalized) splits cited PMIDs into
  surviving (retrieved) vs `confabulated_dropped` (not retrieved). With grounding, `confabulated_dropped`
  MUST be empty.
- **Confabulation-containment downgrade:** a `LOW/MEDIUM/HIGH` grade with ZERO surviving citations is
  ungrounded by this skill's cite-or-abstain contract → downgraded to `not_assessed`, preserving the
  original grade in `risk_level_pre_containment` + a `downgraded_reason`.
- **null ≠ MEDIUM:** a dimension with no retrieved abstracts is `not_assessed` (never a fabricated middle
  score); no model call is made for it.
- **Reproducibility envelope:** the retrieved corpus (per-dimension query + PMIDs + mindate/maxdate) and the
  model pin are stored in `provenance.corpus_pin`. Default window is 2015–2026 (an unbounded window is
  non-reproducible under PubMed relevance sort).
- **Engine-blind dimensions:** `clinical` / `commercial` have no deterministic data source (literature-only).

---

## 3. Emitted output — `risk_assessment.json`

Bespoke top-level (NOT the fan-out envelope): `tier · target · indication · dimensions · provenance`.

- **`tier`** — the literal string `"context"` (const; explicitly NOT a gate/verdict input).
- **`dimensions`** — a **dict-of-objects keyed by exactly the six fixed pillars**
  (`biological, druggability, translational, clinical, safety, commercial`; `additionalProperties:false`).
  Each dimension object carries: `pillar`, `risk_level` (LOW/MEDIUM/HIGH/not_assessed), `justification`,
  `interpretation` (the context read — "what the literature knows", distinct from the risk grade),
  `cited_pmids[]`, `confabulated_dropped[]`, `contradicts_deterministic`, `anchor_verdict`, `n_retrieved`
  (+ `risk_level_pre_containment` / `downgraded_reason` only when a confabulation downgrade fired).
- **`provenance`** — `generated_at`, `corpus_pin` (source + per-dimension retrieved corpus + date window),
  `citable_in_nominations: false` (const), plus `synthesis_model`, `framework_model_version`,
  `generated_by`, `anchored_from_evidence_package`.

No `run_health`, no `headline`, no `skill_report`, no `fired_rules`, no `cards` — intentionally bespoke.

---

## 4. Contract & versioning (what is locked)

Pinned by the HAND-AUTHORED, self-contained `literature-risk-assessment.emit.schema.json`. It locks: the
stable top-level shape (`tier/target/dimensions/provenance` required), the literal `tier: "context"`, the
**fixed six-dimension keyset** (`additionalProperties:false`), the risk-level vocabulary
(`LOW/MEDIUM/HIGH/not_assessed`) on `risk_level` and `risk_level_pre_containment`, the containment-downgrade
fields, `provenance.corpus_pin` presence, and `provenance.citable_in_nominations: false` (const). The LLM
prose (`justification` / `interpretation`) and the per-dimension detail are left **OPEN**
(`additionalProperties: true`) — append-only within the contract major version.

CI: emit conformance (`tests/test_data_product_schema.py` against a fresh real emit, CI-fail-not-skip),
the cross-skill coverage ratchet (`skills/tests/test_data_product_lock_coverage.py` — auxiliary locks are
additive), and the target-contracts schema meta-test. Change policy: promote an open per-dimension field to
contractual → add as a named property + minor bump; a top-level shape change → major bump.

## 5. Known gaps & notes (non-blocking)

- **Bespoke by design:** this is an aux (non-fan-out) skill; there is deliberately NO `build_skill_report`,
  no `run_health`, and no headline envelope. Do NOT retrofit one.
- **A LIVE run needs Bedrock + network** (`BEDROCK_AWS_PROFILE=cmp-dev` + NCBI E-utilities). Conformance
  therefore rests on a fresh emit assembled through the real `run()` with the two external I/O boundaries
  replaced by frozen responses — the sanctioned offline-replay path (no faked JSON; assertions run against
  what `run()` actually produces).
- **The one verdict-affecting ramp is NOT enabled here** (SKILL.md §"The one verdict-affecting ramp"): the
  only defensible future gate-affecting use (a `clinical_validation` NO-GO behind five preconditions) stays
  a separate reviewed decision; this skill stays strictly context-tier.
- **Sibling entrypoints share this dir** (`ground_axis.py`, `risk_rollup.py`, the `cited_evidence.py`
  back-compat shim). This data-product contract governs `run.py`'s `risk_assessment.json` only.
