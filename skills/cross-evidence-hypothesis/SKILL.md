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
  version: 0.5.0
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
  status: partial               # WS4 + drift-guard (§9) + intra-package coherence / adversarial-survival gate (WS5)
  # --- integrator ↔ card-panel contract (roadmap §10): the SPINE FIELDS this integrator reads ---
  # (NOT card_ids — this skill reads the composed package, not cards). Pinned here so a rename is
  # visible in review; a target-contracts CI contract test (§10) is a deferred hardening item.
  reads_spine_fields:
    - synthesis.sub_verdicts.*.verdict
    - synthesis.sub_verdicts.safety.safety_verdict_by_modality  # #744 — modality×safety seam (Phase 2)
    - synthesis.recommendation_gate.hard_gates       # #462 — fail-closed gate-complete ceiling
    - synthesis.claim_vectors                        # per-short SIGNAL decomposition + citable atoms
    - synthesis.confidence_tier                      # spine composed tier — integrator cross-checks (Phase 3)
    - synthesis.decision_facets.certainty_by_axis    # #744 — per-axis CERTAINTY_MODEL sidecar (Phase 3)
    - synthesis.decision_facets.composed_modality    # #744 — modality the package was composed under
    - synthesis.decision_facets.cross_gate_shared_evidence  # spine cross-gate correlation (Phase 4)
    - synthesis.decision_facets.fragility            # contested + acquisition_backlog → panel/go_forth (Phase 5)
    - synthesis.decision_facets.competitor_crossref  # competition density → panel differentiation (Phase 5)
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
- **Intra-package COHERENCE WITH TEETH** (`hypothesis_core.coherence_violations`,
  §6.5 — the WS5 adversarial-survival root-cause fix). A positive-thesis clause
  (causal_rationale / therapeutic_hypothesis / population) may NOT assert a
  positive claim on a signal that ANOTHER present package signal contradicts,
  unless the clause SURFACES the tension (in `contradicting_citations` or a
  principal tension). Enforced four ways: (a) a MEASURED-NEGATIVE sub-verdict
  cited as support; (a2) a card whose interpretation_call is measured-negative
  cited as support; (b) the agent's OWN `contradicts`/`tensions_with` edges
  enforced on its own clauses; (c) a small GENERAL intrinsic cross-card registry
  (`INTRINSIC_CONTRADICTIONS`) — e.g. a synthetic-lethal/combination strategy is
  unsupported when `partner-conditional-dependency = no_partner_mapped` is present
  (the exact class the WS5 smoke found dropping MARK2 survival to 0.25, where the
  contradicting line is present but UNCITED). A coherence violation blocks
  promotion and caps the verdict (`advanceable_flagged`), so a clause that is
  internally contradicted cannot ship clean on traceability alone.
- **Degraded mode / minimum-inputs** (§12): a missing dossier or risk read
  degrades certainty (capped `low`) and is flagged — it NEVER silently inflates
  certainty or raises the ceiling. Below the minimum non-gap decision lines the
  run is flagged `minimum_inputs_met: false`.
- **Modality via a controlled enum**, not `objective.startswith()`: `--modality`
  (small_molecule / degrader / molecular_glue / rna_therapeutic / adc / bite_tce
  / antibody / modality_agnostic) scopes which sub-verdict dimensions are in play;
  an out-of-scope axis (e.g. surface-modality for a small molecule) never degrades
  the hypothesis.

## Intra-package coherence guard (WS5)

- **Intra-package coherence WITH TEETH** (always-on, offline; `hypothesis_core.coherence_violations`).
  A positive-thesis clause (causal_rationale / therapeutic_hypothesis / population) may NOT assert a
  positive claim on a signal that ANOTHER present package signal contradicts, unless it SURFACES the
  tension. Four detectors: (a) a measured-NEGATIVE sub-verdict cited as support (e.g.
  dependency=non_dependent_paralog_buffered), (a2) the same at CARD grain, (b) one end of the agent's
  OWN `contradicts`/`tensions_with` edge cited while the other present end is unsurfaced, and (c) the
  INTRINSIC cross-card class (a SL/combination strategy asserted while
  partner-conditional-dependency=no_partner_mapped is present — even if uncited). A violation BLOCKS
  promotion (caps the verdict at `advanceable_flagged`) and is also SURFACED into the structured
  `tensions` slot as a clearly-tagged deterministic entry (`surface_coherence_tensions`,
  `source: integrator_coherence_guard`) — the roadmap's "fold the contradiction into the clause OR
  into `tensions`", done WITHOUT mutating any LLM clause prose (invariant 9). The agent is ALSO
  prompted to fold such tensions into its own `contradicting_citations` / `tensions`, so a coherent
  clause carries the tension explicitly. This is the deterministic, always-on sibling of the
  adversarial-survival skeptic pass. Recorded under `defensibility.coherence_violations` /
  `n_coherence_violations` / `n_coherence_tensions_surfaced`.

- **Adversarial-survival gate** (optional post-check; needs Bedrock;
  `scripts/adversarial_survival.py`). N=3 skeptics try to REFUTE each clause from the SAME package
  only; a refutation whose citations do not resolve to the package is discarded (retrieve-don't-recall
  applied to the skeptic). `score` = fraction of clauses surviving; `adversarial_survival_gate(result,
  threshold=0.75)` FLAGS a below-threshold hypothesis so it is not shipped clean on traceability alone.
  The result attaches to the optional first-class `quality.adversarial_survival` slot (null until run):

        BEDROCK_AWS_PROFILE=cmp-dev python3 scripts/adversarial_survival.py \
            --evidence-package <evidence_package.json> --hypothesis <hypothesis.json> \
            [--risk r.json] [--target-dossier d.json] --threshold 0.75 --out survival.json

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

## WS4 drift-guard (roadmap §9) — DELIVERED (v0.2.0)

The output carries a `provenance` block pinning the two drift PINS — `prompt_template_hash`
(a stable sha256 over both system prompts + both tool schemas) and `model_id` — plus `llm_mode`.
An OFFLINE, DETERMINISTIC golden-set drift-CI (`tests/test_drift_guard.py`) freezes, for
KRAS/COADREAD + MARK2/PAAD, the DETERMINISTIC SPINE outputs (clamped verdict, gate ceiling / clamp
tension, clause-traceability, computed certainty + caps, data gaps, substrate-discount, intra-package
coherence) and the two PINS; it FAILS when any of them drift (a prompt/schema edit flips
`prompt_template_hash`). The LLM PROSE is deliberately NOT frozen. Fixtures are TRIMMED evidence
packages (integrator-relevant fields only) + a canned two-call `llm_replay.json` fed via
`--no-llm --llm-replay` (`run.replay_synthesize`), so CI never calls Bedrock. Documented tolerance:
the offline spine is exactly reproducible run-to-run, so fields compare for exact equality (the one
float within `DRIFT_FLOAT_TOL`); the model/prompt-change channel is handled by REGENERATION + review:

    BEDROCK_AWS_PROFILE=cmp-dev python3 scripts/freeze_drift_golden.py --all       # re-capture LLM + refreeze
    python3 scripts/freeze_drift_golden.py --all --replay-only                     # refreeze spine only (no Bedrock)

## Adversarial-survival post-check / gate (WS5) — DELIVERED (v0.2.0)

The always-on, OFFLINE `hypothesis_core.coherence_violations` guard (above) is the deterministic
sibling of the LLM skeptic pass. `scripts/adversarial_survival.py` (rehomed from
framework-runs, repointed at this skill's `hypothesis_core`) is the OPTIONAL, Bedrock-backed
post-check: N=3 skeptics try to refute each clause FROM THE PACKAGE ONLY (uncontained/confabulated
refutations discarded via `check_traceability`), and `adversarial_survival_gate(result, threshold)`
FLAGS a below-threshold hypothesis so it is not shipped clean on traceability alone. Emit the score
into the optional first-class `quality.adversarial_survival` slot. Run it as a gate:

    BEDROCK_AWS_PROFILE=cmp-dev python3 scripts/adversarial_survival.py \
        --evidence-package <evidence_package.json> --hypothesis <hypothesis.json> --threshold 0.75

## Deferred hardening (TODOs — documented, NOT built in this increment)

- **Immutable, content-addressed provenance manifest** (roadmap §6.9): a hash-in-
  path write-once archival manifest with a mandatory non-reproducible / as-of-DATE
  header (model_id, timestamp, temperature, cost-per-hypothesis, prompt_hash). This
  increment emits `hypothesis.json` in a plain output dir with the `provenance` block.
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
