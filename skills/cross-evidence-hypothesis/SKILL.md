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
  version: 0.6.0
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
    - synthesis.skill_reports                        # #1310 — per-axis ROLE view (gating/descriptive/inert)
    - synthesis.skill_report_rollup                  # #1310 — spine rollup, read for the same role split
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
  same underlying measurement re-displayed and count ONCE toward certainty. The
  count is over TAGGED substrates only — an UNTAGGED card is missing provenance,
  not proven independence, and counting it as its own unit made the control inert
  (real packages reported 121–125 "independent" units, so the cap could never
  fire). The cap is graded: 1 unit → `low`, 2 → `moderate`, ≥3 → uncapped.
  When substrate tagging covers a MINORITY of cards the substrate view ABSTAINS
  from the unit cap (`independence_view_authoritative: false`) and only a declared-
  blindness `moderate` cap applies — a pipeline metadata gap must not be charged
  to the target as measured non-independence. The spine's decision-gate-group view
  (`cross_gate_shared_evidence`) is derived from FIRED cards, so it still caps
  where card tagging is absent; the binding view is the LOWER of the two, and
  which one bound is reported (`independence_unit_kind`).
  Two flags, two questions: `independence_view_authoritative` = could the read
  SPEAK; `independence_cap_binding` = did it LOWER anything. A view that spoke and
  found ≥3 units caps nothing, which the single old `independence_cap_applied`
  reported as a cap a reviewer would then go looking for. Every unit count is
  named BY VIEW (`n_independent_substrate_units` vs
  `effective_independent_units`) — the old unqualified `n_independent_units` sat
  beside the binding count under a name claiming to be the authoritative one, and
  on live KRAS-COADREAD they read 2 and 3 with nothing to disambiguate them.

- **Role-aware gaps and certainty** (#1310, UNIFIED_OUTPUT_CONTRACT). Reads
  `synthesis.skill_reports` for each axis's ROLE. An axis with role
  `descriptive`/`inert` and no call is GATELESS BY DESIGN — declared absence of
  scoring, not MISSING data — so it is excluded from `data_gaps`, from the
  supporting-line count, and from the limiting-axis attribution, which is
  restricted to `role=gating` axes. `overall_certainty` remains the conjunctive
  weakest link, but because that scalar is a minimum (and therefore `low` on
  essentially every real package) the DISTRIBUTION behind it is emitted alongside:
  `certainty_by_axis`, `n_axes_by_level` and the gating-only slice, which is what
  a portfolio reviewer can rank on. Per-axis levels sourced from the spine's
  `certainty_by_axis` sidecar are reported separately from proxy-derived ones. A
  package with no `skill_reports` reports roles as UNKNOWN (`axis_roles_present:
  false`, gating slice `null`, not a zeroed histogram) and every consumer falls
  back to its pre-#1310 behaviour.

## Enforced defensibility contract (roadmap §6.3–6.5, invariants)

- **Retrieve-don't-recall**: an asserted PMID must be an EXACT member of the risk
  read's retrieved set — no substring/`any()` escape for PMIDs (a self-invented
  PMID is confabulation, flagged untraceable). A citation ASSERTS a PMID in exactly
  two shapes: an explicit `pmid`/`pubmed` cue, or a bare identifier list
  (`12345678`, `PMIDs 12345678, 34567890`). Space-delimited digits inside PROSE are
  NOT a PMID claim — the framework's own prompt asks the agent to quote `n=123456`,
  `chr7:140453136`, `TPM 1000000`, `p=0.000123456`, and reading each as an
  unretrieved PMID had the teeth biting well-behaved output. This costs no teeth:
  an uncued digit run stays in the residual, which must itself resolve to a
  retrieved spine token, so a confabulated `Smith et al. 34567890` is still
  rejected — as an unresolvable citation rather than as a bad PMID.
- **Clause-traceability WITH TEETH**: every clause cites a spine field / dossier
  field / stratum token / retrieved PMID; an untraceable citation BLOCKS
  promotion (`defensibility.promotable = false`) and caps the verdict at
  `advanceable_flagged`.
- **The PROMOTION cap is not the GATE clamp** and is reported apart from it.
  `verdict.was_clamped` is the spine's ceiling lowering the model's proposal;
  `verdict.promotion_capped` is this hypothesis's own hygiene (untraceable
  citations, absence-discipline, coherence, too few supporting axes) lowering it;
  `verdict.verdict_after_gate` is the value between them, so the drop from
  `proposed_by_agent` to `computed` is attributable. Sharing one flag made the live
  KRAS-COADREAD run emit `was_clamped: true` beside a `gate_ceiling` EQUAL to the
  proposal and `gate_clamp_tension: null` — reading as "the gate overruled the
  model" when the model had matched the gate exactly. It also let ONE defect fire
  TWO of the four claim atoms, double-counting it for any averaging rollup; the
  `gate_agreement` atom is now keyed off the gate clamp alone and merely DISCLOSES
  a promotion cap in its evidence text.
- **Absence-discipline WITH TEETH**: an absent/insufficient line carries no
  weight and can never support a clause; a violation blocks promotion. Matched at
  the same grain as traceability — a citation that EMBEDS a gap axis as a whole
  word ("the dependency sub-verdict") is a gap citation, since traceability would
  credit that same phrasing; word boundaries keep a differently-named card
  (`expression-and-specificity`) from being read as the axis `expression`.
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
  the hypothesis. `immune_context` is IN scope for all three antibody-derived
  channels (adc / antibody / bite_tce) — an immune-excluded or myeloid-suppressed
  microenvironment limits payload delivery and effector engagement, so scoping it
  out for adc/antibody dropped a real efficacy constraint — and OUT of scope for
  small_molecule / degrader / molecular_glue / rna_therapeutic. Scope is by axis
  OWNERSHIP, not by name shape: a multi-lens card counts as in-scope when ANY
  dimension that owns it is in scope, so a shared card (e.g.
  `modality-therapeutic-window`) is not excluded by a token match against an
  out-of-scope axis name.

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

## UNIFIED_OUTPUT_CONTRACT `skill_report` (v0.6.0)

The integrator emits a **top-level** `skill_report` (`_skills_common.skill_report.build_skill_report`,
`docs/UNIFIED_OUTPUT_CONTRACT.md`), so the framework's TERMINAL synthesis is readable by the same
report/rollup/dashboard layer as every emitting skill — it was previously the one artifact those readers
could not consume, because they all key off `skill_report`.

- **`role: descriptive`**, `polarity: not_scored`. `gating` would mean this report can move a nomination;
  this integrator sits ABOVE the nomination and must never feed back into the spine's gate math. Its
  `provenance.cards_used` / `fired_rule_ids` are empty BY CONSTRUCTION (`data_mode: catalog_read`).
- **Top-level, not under `headline`** — `data_product_contract.is_full_decision` keys off
  `headline.skill_report`, and this is not a single-gate decision; top-level keeps that classification
  intact while still exposing the contract.
- **`call`** is the FINAL clamped verdict (built after the promotion cap), so a non-promotable hypothesis
  cannot present a permissive call on the unified spine.
- **Four claim atoms** — `gate_agreement`, `clause_traceability`, `intra_package_coherence`,
  `evidence_independence` — plus non-atom scalars carried losslessly for a rollup reading a coordinate
  off the report (`certainty`, `n_axes_by_level`, `n_gating_axes_by_level`, `n_data_gaps`,
  `n_not_scored_axes`, `limiting_gating_axis`, `promotable`, `modality`). The atoms are the integrator's
  readings of its OWN hypothesis, NOT biology-card signals; a `_disclaimer` says so in the artifact.

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
tension, clause-traceability, computed certainty + caps + the per-axis histogram, data gaps + not-scored
axes, substrate-discount + tagging coverage, intra-package coherence, and the prose-free parts of the
`skill_report`) and the two PINS; it FAILS when any of them drift (a prompt/schema edit flips
`prompt_template_hash`). The LLM PROSE is deliberately NOT frozen. Fixtures are TRIMMED evidence
packages (integrator-relevant fields only) + a canned two-call `llm_replay.json` fed via
`--no-llm --llm-replay` (`run.replay_synthesize`), so CI never calls Bedrock. Documented tolerance:
the offline spine is exactly reproducible run-to-run, so fields compare for exact equality (the one
float within `DRIFT_FLOAT_TOL`); the model/prompt-change channel is handled by REGENERATION + review:

    BEDROCK_AWS_PROFILE=cmp-dev python3 scripts/freeze_drift_golden.py --all       # re-capture LLM + refreeze
    python3 scripts/freeze_drift_golden.py --all --replay-only                     # refreeze spine only (no Bedrock)

KNOWN COVERAGE GAP: both frozen cases predate #1310, so they carry no `synthesis.skill_reports` and no
`cards[].evidence_substrate`. The golden therefore pins the FALLBACK path (`axis_roles_present: false`,
gating slice `null`, `independence_view_authoritative: false`) — correct for those packages, but it does not
drift-guard the role-aware / independence-capped path that production packages now take. Unit tests
(`tests/test_skill_report_and_teeth.py`) cover that path; a THIRD golden case frozen from a fresh
post-#1310 package is the outstanding hardening item.

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
