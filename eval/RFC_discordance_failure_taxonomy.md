# RFC: Discordance failure-class taxonomy + routing — a framework for subskill enhancement

Status: DRAFT (2026-09-09) · Trigger: the subskill-discordance harness (`eval/subskill_discordance.py`)
detects per-subskill omics↔literature discordance, but the discordances have DISTINCT root causes that need
DISTINCT mechanisms. Treating them uniformly (e.g. "fix the resolver") is whack-a-mole. This RFC turns the
harness from a detector into a **triage + routing framework**: every discordance is classified, then routed
to the one layer that can actually fix it.

## 0. TL;DR
- **The detector generalizes; the fix does not.** `subskill_discordance.py` + discarded-signal provenance
  (D1 below) makes EVERY discordance visible and attributable, across all subskills, regardless of cause.
- **But the panel (37 targets) shows discordances span ≥5 distinct classes**, and only ONE (resolver
  precedence) is a resolver problem. The dominant class is **measurement scope/mechanism mismatch** — where
  the resolver is *correct given the data* and the DATA measures the wrong thing. A resolver/gate change
  cannot fix that.
- **Robustness = routing, not a single fix.** Each class has a home engine/layer and a mechanism; the harness
  assigns the class from an observable signature. This prevents "we fixed tractability and the dependency /
  expression / cis discordances didn't budge."

## 1. The two engines + the layers a fix can live in
(Load-bearing context — a fix must target the right layer.)
- **Engine 1 — per-axis resolver** (`_skills_common/resolver.py`, 10 specs): siloed to one gate's fired
  rule-ids, one min-priority winner, no negation/cross-axis. Restriction is deliberate (reachability, golden
  freezing, dangling-rung validation). Fixes here = precedence/provenance only.
- **Engine 2 — cross-axis nomination gate** (`tp_gates.py` + `nomination_verdict_gate.yaml`): reads multiple
  axes + `biology_axis`/`modality`/topology + card fields. Home of reconcilers/downgrades. Fixes here =
  cross-axis conditioning + orthogonality framing.
- **Data/rules layer** (`analysis-methods` products + `interpretation-rules/*.rules.yaml` + cards): what the
  omics actually measures + how a measurement becomes a fired rule. Fixes here = measurement scope/mechanism.
- **Synthesis layer** (Tier-3 LLM prompt / `tp_synthesis_prompt.py`): the narrated recommendation. Fixes
  here = LLM attribution.

## 2. The detector (general, do first)
**D1 — discarded-signal provenance** (`resolver.py`, additive): `match_all_reduce` already computes every
matching rung; emit the losers (`matched_but_discarded: [(priority, verdict, driving)]`) beside the winner.
**D2 — harness triage**: `subskill_discordance.py` already reads per-axis `agreement_vs_omics` + `key_divergence`
+ `citation_ids`. Add class assignment (§4) so each discordance is auto-routed. Together these are the robust,
reusable substrate — they don't fix anything, they make every discordance visible, attributable, and routed.

## 3. The failure-class taxonomy (evidence-grounded, 37-target panel)

### Class A — Signal-integration / precedence  [Engine 1 + Engine 2]
The resolver picks the wrong winner among competing per-axis signals, or discards a more-decisive one.
- **Signature:** the WINNING verdict is contradicted by literature, but a DISCARDED rung (D1) agrees.
- **Example:** `tractability_sm` — STRUCT `predicted_ligandable` (priority 14) outranks `biologic_only`
  (priority 20); 18/37 targets read SM-tractable for antibody/ADC/TCE antigens.
- **Mechanism:** discarded-signal provenance (D1) → resolver precedence-rationale lint (declared
  evidence-strength order: measured-chemical > biologic-annotation > predicted-structural > catalog) →
  for cross-axis conditioning (topology/modality), a gate reconciler in Engine 2 (NOT a resolver reorder —
  the resolver can't see topology). Reuses the contradiction_reconciler machinery.

### Class B — Measurement scope / mechanism mismatch  [Data/rules layer]  ← DOMINANT
The resolver is CORRECT given the data; the omics measured the wrong scope or the wrong mechanism.
- **Signature:** omics call is internally sound (no discarded-rung disagreement), but literature asserts a
  different SCOPE (context-restricted) or a different MECHANISM than the axis measured.
- **Examples:** `dependency` ABL1/CD79B (pooled CRISPR dilutes a fusion/subtype-restricted dependency);
  `expression` CLDN18/CTAG1B (bulk RNA misses isoform 18.2 / a cancer-testis antigen); `cis_coherence`
  EZH2 (measured CN-dosage; the causal event is a Y641 GOF point mutation); `combination_vulnerability`
  KIT/MET (noisy/context-restricted relational partner over-claimed).
- **Mechanism:** NOT a resolver/gate change. Options, in order: (a) **context-stratified reads** (dependency
  by lineage/genotype; expression isoform/subset-aware) — the real fix; (b) a **measurement-applicability
  caveat** — an authored rule that fires "pooled/bulk read likely under-samples this context" when a
  driver/fusion/subtype context is present, so the composed layer knows the negative is low-confidence; (c)
  a data-coverage backlog item. This class is why "fix the resolver" fails — the resolver has nothing wrong.

### Class C — Synthesis mis-attribution  [Synthesis layer]
The deterministic gate is fine (gate.fired False or non-veto) but the Tier-3 LLM vetoes/mis-frames.
- **Signature:** `gate.fired == False` (or gate ≠ veto) yet `llm.overall == veto`, and the LLM cites an axis
  the gate did not decide on.
- **Examples:** CTLA4/PDCD1 checkpoints LLM-vetoed though the deterministic gate clears them; the earlier
  selectivity "veto owns the call" over-attribution.
- **Mechanism:** the synthesis reconciled-block / narrative work (already shipped for selectivity, #1208) —
  generalize it so the LLM is told which axes are reconciled/orthogonal and must not hang the call on them.

### Class D — Coverage / axis-resolution gap  [plumbing]
The omics↔literature comparison can't even run: the axis is `omics_unavailable`/unmeasurable.
- **Signature:** harness `unmeasurable` column (all axes omics_unavailable).
- **Examples:** genomic_alteration/target_intrinsic 37/37 unmeasurable (the `_headline_fn` hook bug, fixed
  #1230); immune_context/translational_readiness sparse.
- **Mechanism:** hook/wiring fixes + retrieval coverage. Cheapest to detect (the harness surfaces it directly),
  per-gap to fix.

### Class E — Framing / orthogonality  [Engine 2]
The omics is CORRECT but is counted as a NEGATIVE when it's orthogonal to the target's engagement mode.
- **Signature:** a measured negative on an axis that is not load-bearing for this `biology_axis`/modality
  (e.g. `dependency: non_dependent` on a surface/fusion/checkpoint target).
- **Examples:** CD33/CD79B `non_dependent` is expected for an ADC/BCR-signaling target; the whole
  surface-antigen + extrinsic/checkpoint class we downgraded this week (TC#693/#694).
- **Mechanism:** Engine-2 `biology_axis`/modality-scoped downgrade/reconciler — already the pattern; make it
  the standing rule ("non_dependent/not_selective is EXPECTED and orthogonal for engagement mode X").

## 4. Routing (the triage rule — makes the harness self-classifying)
Given a discordant subskill on a target, assign the class from observable signals (first match):
1. axis all `omics_unavailable` → **D** (coverage).
2. winner contradicted AND a discarded rung agrees (needs D1 provenance) → **A** (precedence).
3. measured negative on an axis non-load-bearing for the target's `biology_axis`/modality → **E** (framing).
4. `gate.fired==False` (or non-veto) but `llm.overall==veto` → **C** (synthesis).
5. else (omics internally sound, literature asserts different scope/mechanism) → **B** (measurement).
Output: the harness emits, per discordance, `{class, home_layer, suggested_mechanism}` — a routed backlog,
not a flat list. (B vs A disambiguation is exactly what D1 provenance buys.)

## 5. Blast radius + sequencing
| Item | Layer | Blast | Verdict-moving |
|---|---|---|---|
| D1 provenance | resolver.py (additive) + golden row | LOW | no |
| D2 harness triage | eval/ | none | no |
| A precedence lint | validate_fold_migration.py | LOW | no |
| A/E gate reconciler | nomination_verdict_gate.yaml + tp_gates (generic) | MED | yes (bounded) |
| B measurement caveat | interpretation-rules + cards (+ analysis-methods for stratified reads) | MED-HIGH | maybe |
| C synthesis block | tp_synthesis_prompt.py | LOW | no (verdict-inert) |
| D hook/coverage | per-gap | LOW-MED | no |

**Sequence:** (1) D1+D2 — the routed detector, no verdict move. (2) Re-run the panel → a *classified* backlog
(how many A vs B vs C vs D vs E, which targets). (3) Fix by class, highest-count-first — the panel suggests
**B (measurement) is the largest bucket**, so the biggest robustness win is a measurement-applicability caveat
+ context-stratified dependency/expression reads, NOT more resolver work. (4) A/E/C as their buckets warrant.

## 6. Non-goals
- No `unless_fired`/cross-axis/arithmetic in the per-axis resolver grammar (Engine 1 stays dumb + auditable;
  cross-axis lives in Engine 2; negation is an authored `*-absent` rule + `when_all_fired`).
- Don't "fix the resolver" for Class B/C/D/E discordances — the resolver is correct there; the fix is in the
  data/synthesis/gate layer per the routing table.
- The harness proposes classes/mechanisms; a human confirms the fix (esp. Class B, which can be a real
  biological negative, not a framework gap).
