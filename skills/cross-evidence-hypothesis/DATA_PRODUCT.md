# cross-evidence-hypothesis — finalized data product

The **I/O contract**: data reasoned IN, the bespoke package emitted OUT, what is locked. This is an
**auxiliary (non-fan-out) skill**, and a **BESPOKE** one: an LLM cross-skill SYNTHESIS integrator that
sits ABOVE target-profile and emits a gated therapeutic *hypothesis* — **not** the fan-out
`skill_decision` envelope. Logic + history live in SKILL.md / run.py; this file is the data-product spec.

| | |
|---|---|
| **Skill** | `cross-evidence-hypothesis` |
| **Skill code version** | 0.5.0 |
| **Contract version** | 1.0.0 (emitted-output schema; versioned independently — see §4) |
| **Role** | **integrator / gated synthesis** — the LLM PROPOSES a verdict; a DETERMINISTIC, FAIL-CLOSED, GATE-COMPLETE ceiling CLAMPS it (`computed = min(proposed_by_agent, gate_ceiling)` over `VERDICT_RANK`). It ENRICHES; it never OVERRIDES the spine |
| **Verdict field** | `verdict` — an **OBJECT** (`{proposed_by_agent, computed, gate_ceiling, was_clamped, gate_reason, active_vetoes, …}`), each rung ∈ `VERDICT_RANK` |
| **Output shape** | **bespoke `hypothesis.json`** — a single file (NOT the standard `write_package` `decision.json` tree; NO `run_health`, NO `headline.skill_report`) |
| **Emitted schema** | `target-contracts/schemas/skills/cross-evidence-hypothesis.emit.schema.json` — **HAND-AUTHORED** bespoke contract (the `.emit.` suffix, NOT the generated `.decision.` envelope schema; no pin, no cross-file `$ref`) |
| **Conformance target** | the **FRESH deterministic emit** — the real `run.py` over the frozen KRAS-COADREAD evidence package, driven by the canned two-call `llm_replay.json` via `run.replay_synthesize` (`llm_mode="offline_replay"`), exactly as `tests/test_drift_guard.py` does. No Bedrock / no S3; no stale hand-frozen decision fixture |

---

## 1. Inputs — reasoned-over evidence (composed artifacts, not cards)

This is a **META / non-evidence-composing** skill (`data_mode: catalog_read`): it composes NO cards and
fires NO interpretation rules. It reasons over ALREADY-composed, orthogonal grounded evidence — the
emitting skills (target-profile + fan-out) own the cards/rules.

| input (flag) | artifact | required |
|---|---|---|
| `--evidence-package` | a target-profile `evidence_package.json` — the indication-conditioned sub-verdict panel + cards + `synthesis` (recommendation_gate.hard_gates, sub_verdicts, claim_vectors, decision_facets) + `subtype_resolved` | **REQUIRED** |
| `--target-dossier` | a target-intrinsic `decision.json` (indication-INDEPENDENT target biology) | optional |
| `--risk` | a 6-dimension literature-risk `decision.json` (the retrieved-PMID surface for retrieve-don't-recall) | optional |
| `--substrate AXIS=PATH …` | per-subskill GROUNDED SUBSTRATE blocks (`ground_axis` output); enrich the panel + make PMIDs citable + surface engine↔literature discordance — **escalate-only** (never lowers the ceiling) | optional |
| `--modality` | controlled enum (small_molecule / degrader / molecular_glue / rna_therapeutic / adc / bite_tce / antibody / modality_agnostic); else inferred from `--objective`; scopes which sub-verdict axes are in play | optional |

The **spine fields read** are pinned in SKILL.md `composition.reads_spine_fields` (a rename is visible in
review). A missing dossier / risk read degrades certainty (capped `low`) and is FLAGGED — it never
silently inflates certainty or raises the ceiling.

---

## 2. Coverage & capability ceilings (contractual)

- **The integrator ENRICHES; it never OVERRIDES** (roadmap invariant §1). The LLM proposes a verdict but
  a deterministic, fail-closed, gate-complete ceiling (`hypothesis_core.gate_ceiling`, consuming
  `synthesis.recommendation_gate.hard_gates`) CLAMPS it: `computed = min(proposed_by_agent, gate_ceiling)`
  over `VERDICT_RANK`. The emitted verdict is NEVER more permissive than the spine; a clamp is SURFACED
  as `verdict.gate_clamp_tension`. A package with no parseable `synthesis` → `declined`; a `hard_gates`
  block absent (older package) → fail-closed rec-gate + sub-verdict kill scan (never fail-open).
- **The pre-clamp proposed verdict + all clause prose are an LLM sample and are NOT reproducible** (the
  manifest is an as-of-date archival read). Only the DETERMINISTIC SPINE — the ceiling + clamp,
  clause-traceability score, computed certainty + caps, data gaps, substrate-discount, intra-package
  coherence, and the two provenance PINS (`prompt_template_hash` + `model_id`) — is run-to-run stable,
  and it is exactly this spine that `tests/test_drift_guard.py` freezes for KRAS-COADREAD + MARK2-PAAD.
- **Defensibility is an ENFORCED contract WITH TEETH**: retrieve-don't-recall PMIDs (a PMID must be an
  exact member of the risk/substrate retrieved set — no substring escape), clause-traceability
  (untraceable citation → `promotable: false` + verdict capped `advanceable_flagged`), absence-discipline
  (an absent/insufficient line supports nothing), independence-before-certainty (cards sharing an
  `evidence_substrate` count ONCE), and always-on intra-package COHERENCE (a positive-thesis clause may
  not rest on a signal another present signal contradicts unless the tension is surfaced).
- **Modality is a controlled enum**, not `objective.startswith()`; an out-of-scope axis (e.g.
  surface-modality for a small molecule) is surfaced as `modality_excluded`, never a data gap and never a
  degradation.

---

## 3. Emitted output

`hypothesis.json` (a single file under `--out`; bespoke, NOT a `write_package` tree). Top-level keys:
`skill · skill_version · target · indication · objective · modality · hypothesis · edges ·
evidence_paths · verdict · defensibility · uncertainty · evidence_independence · subtype_resolved ·
degraded_mode · grounded_substrate · quality · provenance · panel_conviction`.

Contractual (locked — see §4): the top-level identity (`skill` const, `skill_version`, `target`,
`provenance` with `generated_at`); the gated **`verdict` OBJECT** (`proposed_by_agent` / `computed` /
`gate_ceiling` each ∈ `VERDICT_RANK`); `modality.resolved` ∈ MODALITY_SCOPE; the six-part
`hypothesis` (`hypothesis.evidence_grade.overall` ∈ {strong, moderate, weak, insufficient};
`hypothesis.therapeutic_hypothesis.modality` ∈ MODALITY_SCOPE); and typed `edges[].type` ∈
{conditions, tensions_with, corroborates, contradicts}. All LLM-authored clause prose (statements,
rationales, citations text) is schema-**open** (`additionalProperties: true`) — inherently fluid and
prompt-hash nondeterministic.

---

## 4. Contract & versioning (what is locked)

Pinned by the **hand-authored, self-contained** `cross-evidence-hypothesis.emit.schema.json` (the `.emit.`
suffix flags a bespoke aux-skill emit — NOT the generated fan-out `.decision.` envelope; no pin, no
cross-file/network `$ref`). It `required`s `[skill, skill_version, target, verdict, hypothesis,
provenance]`, locks `skill` = `const` + the `verdict`-object / edge-type / modality / evidence-grade
enum vocabularies + `provenance.generated_at` presence, and is `additionalProperties: true` throughout
so the LLM prose stays open. Append-only within contract major version.

CI: fresh-replay conformance (`tests/test_data_product_schema.py`, CI-fail-not-skip — the real run.py
over the frozen golden llm-replay, no Bedrock) + schema-well-formedness; the offline golden-set drift-CI
(`tests/test_drift_guard.py`, freezing the deterministic spine + the two provenance PINS); the
cross-skill coverage ratchet (`skills/tests/test_data_product_lock_coverage.py`); and the
target-contracts schema meta-test. Change policy: a new verdict token → add to the `VERDICT_RANK` enum
in the hand-authored schema (coordinate with `hypothesis_core.VERDICT_RANK`; minor); a top-level identity
key rename → major; a new open LLM/clause field → no schema change.

## 5. Known gaps & notes (non-blocking)

- **Schema is HAND-AUTHORED, not generated** (unlike the 14 fan-out `.decision.` schemas): it deliberately
  does NOT track every open sub-field of `defensibility` / `uncertainty` / `evidence_independence` /
  `degraded_mode` / `grounded_substrate` / `quality` / `panel_conviction` — those stay
  `additionalProperties`-open by design. It pins identity + the closed enum vocabularies + provenance
  presence; deeper field-fidelity is intentionally deferred (the drift-guard, not the schema, is the
  spine-stability check).
- **`quality.adversarial_survival` is `null`** in the emit unless the OPT-IN Bedrock skeptic post-check
  (`scripts/adversarial_survival.py`) is run; the always-on offline `coherence_violations` guard is its
  deterministic sibling. The conformance target (offline replay) exercises the null-slot path.
- **The pre-clamp proposed verdict + clause prose are non-reproducible** (LLM sample); the drift-CI
  freezes only the deterministic spine + the two provenance PINS, and regenerates the golden on a
  reviewed, deliberate prompt/schema/resolver change (`scripts/freeze_drift_golden.py`).
- **`composition.output_shape: data_package`** in SKILL.md is the framework enum; the concrete emit is
  the single bespoke `hypothesis.json` (no `decision.json` / cards tree).
