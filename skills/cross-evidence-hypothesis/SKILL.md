---
name: cross-evidence-hypothesis
description: |
  The cross-evidence hypothesis INTEGRATOR — the framework's decision-facing
  synthesis layer that sits ABOVE target-profile. It consumes ORTHOGONAL
  grounded evidence — a target-profile `evidence_package` (the indication-
  conditioned sub-verdict panel + cards), the indication-INDEPENDENT
  target-intrinsic DOSSIER, and an optional 6-dimension literature-RISK read —
  and reasons ACROSS them into a DEFENSIBLE, CITED, gate-CLAMPED drug-target
  hypothesis: a six-part output (causal_rationale, therapeutic_hypothesis,
  population, therapeutic_window, evidence_grade, go_forth) plus typed cross-line
  EDGES and EVIDENCE PATHS.

  The load-bearing invariant (CROSS_EVIDENCE_INTEGRATION_ROADMAP.md §1): the
  integrator ENRICHES; it never OVERRIDES. The LLM PROPOSES a verdict, but a
  DETERMINISTIC, FAIL-CLOSED, GATE-COMPLETE ceiling — computed from the landed
  spine's `synthesis.recommendation_gate.hard_gates` — CLAMPS it. Where the
  proposed verdict exceeds the hard-gate ceiling, the ceiling wins and the
  tension is SURFACED (never resolved in the hypothesis's favour). Only the
  ceiling + the clamp are deterministic; the pre-clamp hypothesis verdict is an
  LLM sample and is NOT reproducible (the manifest is an as-of-DATE archival read).

  This is a META / non-evidence-composing skill: it composes NO cards live and
  fires NO rules — it reasons over an ALREADY-composed evidence_package (hence
  data_mode: catalog_read, the framework's enum for a skill that answers no
  single biology gate; the emitting skills own the cards/rules). READ-ONLY
  consumer: it does not modify target-profile or any sub-skill.

metadata:
  version: 0.1.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - BEDROCK_AWS_PROFILE=cmp-dev   # the two-call LLM pipeline uses Bedrock (anthropic[bedrock])

composition:
  # META-INTEGRATOR: composes no cards, fires no rules — reasons over an already-composed
  # target-profile evidence_package. catalog_read is the framework's enum for a non-evidence-
  # composing skill (answers no single biology gate; see catalog-query). The evidence_package
  # it ingests is a derived artifact; the emitting skills (target-profile + fan-out) own the
  # cards_used / rules_scope. So those fields are legitimately empty here (schema-exempt for
  # catalog_read) — declaring them would double-count evidence the spine already owns.
  data_mode: catalog_read
  synthesis:
    - structured_llm            # the two-call pipeline (edges → clamped hypothesis)
  output_shape:
    - data_package              # hypothesis.json
  optional_lenses:
    - modality                  # controlled enum (small_molecule / adc / bite_tce / degrader / ...)
    - subgroup                  # subtype-resolved reasoning off the subtype_resolved block
  status: partial               # WS4 first production increment; hardening deferred (see TODOs)
  # --- integrator ↔ card-panel contract (roadmap §10): the SPINE FIELDS this integrator reads ---
  # (NOT card_ids — this skill reads the composed package, not cards). Pinned here so a rename is
  # visible in review; a target-contracts CI contract test (§10) is a deferred hardening item.
  reads_spine_fields:
    - synthesis.sub_verdicts.*.verdict
    - synthesis.recommendation_gate.hard_gates       # #462 — fail-closed gate-complete ceiling
    - subtype_resolved.per_stratum                   # #464 — subtype-resolved reasoning + stratum tokens
    - cards[].evidence_substrate                     # #463 — correlated-evidence certainty discount (WS7 half)
---

# Micro — Cross-Evidence Hypothesis Integrator (WS4)

## What this skill does

Reasons ACROSS orthogonal grounded evidence and emits a defensible, cited,
gate-clamped drug-target hypothesis. It ports the validated scratch prototype
(`framework-runs/cross-dim-agent/hypothesis_agent.py`) into a production skill,
with four upgrades over the prototype.

- **Two-call LLM pipeline** (ported): CALL 1 proposes typed cross-line EDGES
  (`conditions` / `corroborates` / `tensions_with` / `contradicts`) + principal
  tensions + EVIDENCE PATHS (signal chains to a decision-relevant claim); CALL 2
  assembles the six-part hypothesis ON those edges/paths. The LLM call is
  injectable (`synthesize_fn`) so the deterministic spine is unit-testable offline.

- **Fail-closed, gate-complete clamp** (`hypothesis_core.gate_ceiling`, roadmap
  §6.6 — the key upgrade). The prototype's `gate_ceiling()` modelled only two
  gates and FAILED OPEN. This consumes the landed
  `synthesis.recommendation_gate.hard_gates` block (#462 — the COMPLETE declared
  kill set, each `(short, verdict)` with a per-run status). The ceiling is the
  LEAST-permissive value the set implies:
  - a `gated` gate `fired` → `declined` (active blanket veto);
  - a `gated` gate `blind` → `declined`, FAIL-CLOSED (a veto-capable axis could
    not be evaluated, so the veto cannot be ruled out);
  - a `contradiction` `opposing` → caps at `advanceable_with_caveat`;
  - a safety hold-grade sub-verdict → caps at `advanceable_flagged`;
  - a modality-scoped `excluded` gate → surfaced, NOT a blanket veto.
  A package with no parseable `synthesis` → `declined`. If `hard_gates` is absent
  (older package), it falls back to a fail-closed rec-gate + sub-verdict kill
  scan — never the prototype's fail-open behaviour. The clamp is never more
  permissive than the spine; a clamp is surfaced as a `gate_clamp_tension`.

- **Subtype-resolved reasoning** (#464). Parses the first-class
  `subtype_resolved` block; adds per-stratum tokens to the citation surface so
  `population` / `causal_rationale` / `therapeutic_window` can carry
  subtype-resolved, TRACEABLE reasoning ("strong in MSS but absent in MSI-H").
  A stratum axis below its n-floor (`subgroup_n_floor_met: false`) is surfaced
  but flagged so the agent must not credit it (absence-discipline at stratum grain).

- **Independence-before-certainty** (#463, roadmap invariant 8 — the WS7
  certainty-discount half). Groups present cards by their declared
  `evidence_substrate`; cards SHARING a substrate (e.g. the recount3 TCGA/GTEx
  bulk-RNA tumor/normal cluster, or the DepMap-Chronos dependency cluster) are the
  same underlying measurement re-displayed and count ONCE toward certainty. When
  corroboration collapses to a single substrate, certainty is capped `low`.

## Enforced defensibility contract (roadmap §6.3–6.5, invariants)

- **Retrieve-don't-recall**: a PMID-shaped citation token must be an EXACT member
  of the risk read's retrieved set — no substring/`any()` escape for PMIDs (a
  self-invented PMID is confabulation, flagged untraceable).
- **Clause-traceability WITH TEETH**: every clause cites a spine field / dossier
  field / stratum token / retrieved PMID; an untraceable citation BLOCKS
  promotion (`defensibility.promotable = false`) and caps the verdict at
  `advanceable_flagged`.
- **Absence-discipline WITH TEETH**: an absent/insufficient line carries no
  weight and can never support a clause; a violation blocks promotion.
- **Degraded mode / minimum-inputs** (§12): a missing dossier or risk read
  degrades certainty (capped `low`) and is flagged — it NEVER silently inflates
  certainty or raises the ceiling. Below the minimum non-gap decision lines the
  run is flagged `minimum_inputs_met: false`.
- **Modality via a controlled enum**, not `objective.startswith()`: `--modality`
  (small_molecule / degrader / molecular_glue / rna_therapeutic / adc / bite_tce
  / antibody / modality_agnostic) scopes which sub-verdict dimensions are in play;
  an out-of-scope axis (e.g. surface-modality for a small molecule) never degrades
  the hypothesis.

## What this skill does NOT do

- Does NOT modify target-profile, differentiation-landscape, or any method — it
  is a READ-ONLY consumer of the evidence_package (+ optional dossier + risk).
- Does NOT compose cards live or fire interpretation rules — the deterministic
  spine (owned by the emitting skills) does that; this layer reasons over it.
- Does NOT override the spine: the LLM proposal is clamped to the hard-gate
  ceiling; the emitted verdict is never more permissive than the spine.

## Inputs

- `--evidence-package` (REQUIRED): a target-profile `evidence_package.json`.
- `--target-dossier` (optional): a target-intrinsic `decision.json`.
- `--risk` (optional): a 6-dimension literature-risk `decision.json`.
- `--modality` (optional): controlled enum; else inferred from `--objective`.
- Pathway-node-leverage arrives via the evidence package once WS3 lands its
  differentiation wiring; read if present, tolerated if absent.

## Invocation

    BEDROCK_AWS_PROFILE=cmp-dev python skills/cross-evidence-hypothesis/scripts/run.py \
        --evidence-package <evidence_package.json> \
        --target-dossier   <target-intrinsic decision.json> \
        --risk             <6-dim risk decision.json> \
        --modality small_molecule \
        --out <dir>

## Deferred hardening (TODOs — documented, NOT built in this increment)

- **Immutable, content-addressed provenance manifest** (roadmap §6.9): a hash-in-
  path write-once archival manifest with a mandatory non-reproducible / as-of-DATE
  header (model_id, timestamp, temperature, cost-per-hypothesis, prompt_hash). This
  increment emits `hypothesis.json` in a plain output dir.
- **Drift-guard / golden-set CI** (roadmap §9, WS9): pin `prompt_hash` + `model_id`
  and freeze a golden set (KRAS/COADREAD, MARK2/PAAD); fail CI when clamped verdicts
  or edge structure drift on model/prompt change. (Also monitors the conservative,
  non-reproducible DOWNWARD channel called out in §1.)
- **Adversarial-survival metric** (WS5): a skeptic pass that tries to refute each
  clause from the same evidence; clause-traceability here measures pointer
  COMPLETENESS only, not clause SOUNDNESS.
- **Curated truth-set + extrinsic metrics** (WS6): the three-reader comparison,
  pre-registered, on a truth-set disjoint from WS9's rule-anchoring facts.
- **Retrieval-LOG-grounded allowed_pmids** (roadmap §6.3): today `allowed_pmids`
  comes from the risk read's `cited_pmids`; the stronger contract sources them from
  the risk agent's verified retrieval LOG (query + returned PMIDs).
- **Runtime schema-validate-and-repair loop** over every edge/path/clause; a
  target-contracts CI contract test pinning the consumed spine fields (roadmap §10);
  the rendering spec into nomination.json / target_profile.md (roadmap §11).
- **Bedrock throttle/retry + N-target operational envelope** (roadmap §7); the
  human-in-the-loop review slot (roadmap §8).
