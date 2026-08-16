# Design Plan — Cross-Evidence Hypothesis Integrator: Systematic Integration Roadmap

**Status:** Drafted 2026-08-16; hardened 2026-08-16 after a 5-lens adversarial
review. **Purpose:** sequence the integration of the cross-evidence hypothesis
layer (prototyped in `framework-runs/cross-dim-agent/`) into the production
framework, methodically, with explicit dependencies and acceptance criteria.
This is a *plan of record*, not a decision on any single component — each
workstream still lands via its own PR + review.

Portable GFM per the `README.md` format rules (no Mermaid/HTML).

---

## 1. Organizing principle

The framework has one mature layer today: a **deterministic spine** —
methods → cards → resolvers/rules → per-subskill sub-verdicts → the
`target-profile` composed gate. It is reproducible and auditable, and it is the
source of every hard gate (safety veto, modality exclusion, functional-requirement
Gate-C, surface `neither_viable`).

Everything prototyped in the 2026-08 cross-evidence work is a **second layer**:
a **cross-evidence integrator** that reasons over multiple grounded evidence
sources and emits a **defensible, cited, gate-clamped drug-target hypothesis**.

The load-bearing invariant, and the reason this is safe to add:

> The integrator ENRICHES; it never OVERRIDES. The **clamp is deterministic and
> safety-monotonic**; where the LLM-proposed verdict exceeds the spine's
> hard-gate ceiling, the ceiling wins and the disagreement is surfaced.

Two honest qualifications this plan must carry (the review surfaced both):

- **The emitted verdict is only partly deterministic.** The *clamp* is
  deterministic; the *pre-clamp hypothesis verdict is an LLM sample* and is
  NOT reproducible. Two runs of a safety-clean target can emit different
  decision-facing verdicts *below* the ceiling. We therefore never call the
  output a "deterministically-clamped verdict" — only the ceiling and the clamp
  operation are deterministic.
- **The integrator can move the verdict DOWNWARD non-reproducibly.** A
  non-reproducible literature/agent read can make the hypothesis *more*
  conservative than the spine. §1's monotone-safety guarantee bounds only the
  permissive direction; the conservative direction is a real, acknowledged
  channel that WS9 (drift-guard) must monitor.

This is consistent with `RISK_ASSESSMENT_INTEGRATION.md` (2026-07-17): literature
risk stays in the **synthesis-context layer** and never becomes a gate/verdict
input. The integrator *is* that synthesis layer — it consumes risk as cited
context, never as an upward gate.

## 2. Target end-state and its inputs

A hypothesis skill sitting ABOVE `target-profile` that consumes grounded inputs
and emits a six-part hypothesis (causal_rationale, therapeutic_hypothesis,
population, therapeutic_window, evidence_grade, go_forth) with typed cross-line
**edges** and **evidence paths**, a clamped verdict, computed weakest-link
certainty + explicit data-gaps, and per-clause traceability.

**Inputs — and their independence status (critical for certainty):**
1. **Indication-conditioned card panel** (evidence package / sub-verdicts).
2. **Indication-independent target-biology dossier** (`target-intrinsic`).
3. **6-dimension literature risk read** (retrieval-grounded).
4. **Pathway-node-leverage** — a *soft mechanistic-context annotation*, NOT an
   independent 4th evidence source (see below).

Sources 1, 2, and 4 share underlying products and are therefore **not mutually
independent**: on-target-safety genetics (gnomAD / OpenTargets) and mechanism
(SIGNOR / OmniPath) appear in both the dossier and the panel; node-leverage is
DepMap-Chronos-derived like the dependency cards. WS7 + §6.8 require picking a
single authoritative surface per shared axis and marking the rest as
non-independent re-display, so the integrator never counts the same evidence
twice toward certainty.

**Pathway-node-leverage — corrected specification (the review found the naive
version unsound):**
- It is a **relative fitness-rank annotation**, not a causal "acts-through"
  claim, UNLESS a **directed** path to the named effector exists in
  SIGNOR/OmniPath (undirected GO:BP membership cannot ground direction).
- Chronos comparison must be **lineage-selective within the indication cohort**,
  must **exclude common-essential genes** from `dominant_node` eligibility, and
  must be **paralog/combinatorial-corrected** before ranking (e.g. MARK2 is
  buffered by MARK3).
- It requires an **absolute dependency floor + a minimum Chronos separation vs
  screen noise**, and reports **effect size**, so `dominant/competitive/dominated`
  is well-posed.
- It **contributes NO veto** to the ceiling, **must never raise certainty** (it is
  Chronos-correlated with the dependency cards), and **yields to tractability**:
  a druggable "dominated" node can be a better program than an undruggable
  rate-limiting effector. (The MARK2→YAP/TAZ case is exactly this trap — YAP/TAZ
  are the less-tractable nodes.)

## 3. Component inventory (as of 2026-08-16)

**Prototyped (scratch, `framework-runs/`; NOT production):**
- Cross-evidence hypothesis agent (`hypothesis_agent.py`): two-call pipeline
  (edges + evidence_paths → clamped hypothesis), `gate_ceiling`/`clamp`,
  clause-traceability, two-clamp uncertainty, absence-discipline. Demonstrated on
  KRAS/COADREAD + MARK2/PAAD. **Known prototype defects to fix in WS4:** ceiling
  fails OPEN + models only 2 gates (§6.6); traceability substring escape-hatch +
  self-reported PMIDs + advisory-only violations (§6.3–6.5); `objective.startswith`
  modality matching (should be a controlled enum). Clause-traceability measures
  pointer-COMPLETENESS only, not clause SOUNDNESS — do not headline "1.0 on n=2".
- 6-dim risk agent (`risk_agent.py`) / draft skill #455.
- Pathway-node-leverage: proof-of-concept only; the naive raw-Chronos ranking is
  superseded by the §2 corrected spec.

**Exists but not wired:** `target-intrinsic` dossier skill.

**Landed / in flight:** Stage 3a (#380) CI-green, ready. Draft PRs #455, #377,
#456; CI-infra-blocked #451/#454.

**Deferred:** genomic Stage 3b; adversarial-survival; curated truth-set;
correlated-evidence discount.

## 4. Workstreams (dependency-ordered)

### Phase 0 — Close what is in flight
- **0.1** Land genomic **Stage 3a (#380)** (CI green). Establishes the edge
  **0.1 → WS8** (Stage 3b is gated on 3a, not free-standing).
- **0.2** **Triage-only** of the standing draft PRs (rebase / close / defer — NO
  merges here; #455's merge lives in WS2). Before declaring any PR
  "CI-infra-blocked", confirm trunk is green and merge trunk into the branch
  first (stale-branch / already-fixed-on-trunk lesson).
- *Done when:* #380 merged; every other open PR has an explicit owner + disposition.
  Phase 1 may begin as soon as trunk is green **excluding** the CI-infra-blocked
  #451/#454, which are carried as a non-blocking Phase-0 tail.

### Phase 1 — Inputs first-class + early parallel tracks
- **WS1 · Target-intrinsic dossier as a wired input** (bundle-reuse / clean contract).
- **WS2 · Promote the 6-dim risk agent** (merge #455; freeze
  `dimensions{risk_level, justification, cited_pmids}`; keep retrieval-grounding +
  containment; add a prompt-injection-resistance acceptance test — sanitize/delimit
  retrieved abstracts).
- **WS3 · Pathway-node-leverage axis**, per the §2 corrected spec. Upstream
  prerequisite: **ingest/scaffold the MSigDB C5 GO:BP node-set as a
  release-PINNED data-catalog source manifest** (stable ID, sort key, lineage);
  the card references that manifest ID (membership drift can flip
  dominated↔competitive). *Done when:* MARK2/3 reads `dominated_node (YAP/TAZ)`
  **with the tractability-yield caveat present**, and an acceptance test confirms
  a tractable upstream kinase "dominated" by an undruggable TF is NOT down-ranked.
- **WS7 (pulled forward) · Correlated-evidence / independence discount.**
  Co-scheduled with WS4's certainty emission (NOT deferred to Phase 3). If it must
  trail, WS4 ships certainty with a hard `correlated_evidence_discounted:false`
  caveat and WS6 depends on WS7 (extrinsic metrics measured on corrected certainty).
- **CUR (early parallel) · Truth-set curation + deterministic baselines.** Start
  now: curate the panel (ryan.abo) and build the two non-LLM readers (best-single-dim,
  deterministic-panel). Only the reasoned-hypothesis reader depends on WS4.

### Phase 2 — Productionize the integrator (depends on WS1/WS2/WS3)
- **WS4 · Promote the hypothesis agent to a composed skill** (owning repo:
  `claude-oncology-skills`; declare its `cards_used` so renames are coordination-gated).
  Must include: the fail-closed, gate-complete ceiling (§6.6) with regression
  fixtures for every veto class; the degraded-mode / minimum-inputs contract
  (§6.7); the hardened traceability + absence enforcement (§6.3–6.5); a runtime
  schema-validate-and-repair loop over every edge/path/clause; the immutable,
  content-addressed provenance manifest (§6.9); modality scope via a controlled
  enum, not string matching. **Contract-freeze milestone gates Phase 1 → Phase 2.**

### Phase 3 — Trust & measurement (depends on WS4)
- **WS5 · Intrinsic metrics:** clause-traceability (pointer-completeness) +
  **adversarial-survival** (skeptic refutes each clause).
- **WS6 · Curated truth-set + extrinsic metrics.** State the minimum panel size /
  expected effect size (20–30 is likely underpowered for recovery); hold the
  truth-set sources **DISJOINT from WS9's rule-anchoring facts** (OncoKB/COSMIC/CGC)
  to avoid circular agreement; **pre-register** the three-reader comparison so the
  delta is a test, not a fit.
- **WS7 · (see Phase 1)** — lands with WS4 certainty; gates WS6.

### Phase 4 — Spine hardening (parallel, independent)
- **WS8 · Finish the genomic redesign** (Stage 3b) — gated on Phase 0.1 — + the
  rule-audit backlog.
- **WS9 · Shadow-audit rigor** (assessment Pivot 1): anchor rule-discovery to
  curated FACTS; freeze a tripwire regression set the rule loop can never edit.

## 5. Suggested sequence and critical path

Critical path: **{WS1, WS2, WS3} → WS4 → WS5/WS6**, with **WS3 the expected long
pole** and WS1/WS2 blocking-but-light (re-designate the pole if WS1 overruns).
Truth-set curation (CUR) runs in PARALLEL from Phase 0/1 — it is the true
pace-setter for the *measured* win, so it must not sit downstream of WS4.
Phase 4 runs alongside throughout as spine maintenance.

## 6. Invariants that must hold across all workstreams

1. **Deterministic-spine reproducibility** — the spine's stats/verdicts stay
   reproducible; the integrator adds no non-determinism to them.
2. **Monotonic safety containment** — the integrator's verdict is clamped to the
   hard-gate ceiling; safety-critical conditioning lives in code-clamped gates.
3. **Retrieve-don't-recall, enforced** — a PMID-shaped citation token must be an
   EXACT member of an actually-retrieved set; `allowed_pmids` comes from the risk
   agent's verified retrieval LOG (query + returned PMIDs), NOT the model's
   self-reported `cited_pmids`. No substring/`any()` fallback for PMID tokens.
4. **Clause traceability with teeth** — every citation is tokenized into atomic
   identifiers and each is validated independently; an untraceable citation
   BLOCKS emission/promotion (not merely recorded). Traceability measures pointer
   completeness, not soundness.
5. **Absence discipline with teeth** — an absent/insufficient line carries no
   weight and can never support a clause; a violation blocks promotion.
6. **Fail-closed, gate-complete ceiling** — if `recommendation_gate` or any
   veto-capable sub-verdict cannot be resolved, is renamed, or carries an
   unrecognized token, the ceiling is the LEAST-permissive value, never
   `advanceable`; the package is schema-validated against a pinned version first,
   aborting loudly on mismatch. The ceiling must honor the COMPLETE hard-gate set
   (safety veto, modality exclusion, functional-requirement Gate-C, surface
   `neither_viable`): either every hard gate routes through one choke point
   (`recommendation_gate.fired`) with a CI test failing if a veto-capable rule
   exists outside it, OR `gate_ceiling` iterates all veto/kill sub-verdicts
   declared in `nomination_verdict_gate.yaml`.
7. **Integrator-verdict determinism / drift control** — pin temperature + seed
   (or treat the captured sample as the archival pin); a golden-set drift-CI
   fails when clamped verdicts or edge structure drift beyond tolerance on
   model/prompt change.
8. **Independence before certainty** — de-duplicate shared products across inputs
   (§2); node-leverage and any Chronos-correlated axis never raise certainty; the
   correlated-evidence discount (WS7) is applied before certainty is reported.
9. **Provenance segregation & immutability** — the archival manifest carries a
   mandatory non-reproducible/as-of-DATE header (model_id, timestamp, temperature);
   LLM-narrated fields sit in schema slots distinct from deterministic
   sub-verdict/gate slots; immutability is enforced by content-addressed /
   write-once storage (hash in the path), not just a filename.

**Non-goals:** `evidence_grade` stays an ordinal weakest-link grade and is NEVER
collapsed into a multiplicative/calibrated global P(success); WS6 metrics are
evaluation diagnostics, not a headline probability. (A Phase-3 tension-audit
metric counts cases where the pre-clamp verdict materially exceeds the ceiling,
so gate over-conservatism is visible too.)

## 7. Operational envelope (Phase 2 workstream)
Per-nomination LLM call budget and portfolio-scale (N-target) runtime target,
given this stacks a 2-call pipeline + retrieval-grounded risk agent on top of
target-profile's ~10-skill fan-out. Cache the compute-once dossier and the risk
read across indications for the same target. Bedrock throttle/retry handling is
an acceptance criterion; record cost-per-hypothesis in the provenance manifest.

## 8. Human-in-the-loop review & feedback (Phase 3 workstream)
A scientist review/annotation surface capturing accepted/revised/rejected +
rationale in a **human-verdict slot distinct from the LLM and deterministic
slots**, feeding WS6 curation. `human sign-off recorded` is an acceptance
criterion for any `go_forth = advance`.

## 9. Integrator drift-guard & versioning (workstream)
Mirror the org's offline-replay drift-CI: pin `prompt_hash` + `model_id` in the
provenance manifest; freeze a golden set of hypotheses (KRAS/COADREAD,
MARK2/PAAD); fail CI when clamped verdicts or edge structure drift beyond
tolerance on model/prompt change; define a Bedrock model-migration procedure and
a backfill-vs-freeze policy for already-archived nominations.

## 10. Integrator ↔ card-panel contract (workstream)
Pin the set of card IDs / verdict tokens / field names the integrator reads, with
a CI contract test **in target-contracts** (where renames are already
coordination-gated) that fails when a consumed field/token changes without a
matching integrator update. Version the evidence-package schema the integrator
ingests. A named **contract-freeze milestone gates Phase 1 → Phase 2**.

## 11. Rendering / surfacing spec (workstream)
Define where the six-part hypothesis, the clamp, and the gate-vs-evidence tension
land in `nomination.json` / `target_profile.md` / the compose-dashboard render
path — including how a clamped/tensioned verdict is displayed so the deterministic
gate and the LLM narrative are never visually conflated.

## 12. Degraded-mode / minimum-inputs contract (WS4 acceptance)
Per-input availability contracts (required vs optional) + a minimum-inputs gate:
explicitly degrade certainty when the dossier or risk read is missing/stale/errors,
and emit an `insufficient_inputs` refusal path below the minimum. A missing input
must NEVER silently raise the ceiling or inflate certainty.

## 13. Multi-indication / subtype grain (workstream)
Emission is per `target × indication (× subtype)`; define how divergent verdicts
across indications for the same target are reconciled/surfaced (the dossier is
shared/compute-once; the panel + risk + node-leverage are indication-scoped).
