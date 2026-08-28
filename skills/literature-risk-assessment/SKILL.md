---
name: literature-risk-assessment
description: |
  Retrieval-grounded 6-dimension literature RISK assessment for a (target, indication):
  Biological / Druggability / Translational / Clinical / Safety / Commercial, each rated
  LOW / MEDIUM / HIGH / not_assessed with a cited justification.

  Emits, per dimension, BOTH an INTERPRETATION (the context read — "what the literature
  knows about this axis's state") AND a RISK grade ("what could kill it"). This is the
  general grounded context+risk primitive: the context/risk role runs on ANY axis (anchored
  to the deterministic verdict, never overriding it); the verdict role is reserved for blind
  axes (surface/SL/cell-state) in the sibling agents.

  CONTEXT-TIER ONLY — never a card, rule, sub-verdict, or nomination-gate input
  (RISK_ASSESSMENT_INTEGRATION.md, decided 2026-07-17). as-of-DATE literature context a
  human reads, NOT a verdict.

  REVIVES the deprecated workflow-target-evaluation-onc 6-dim assessment, RE-HOMED into
  the grounded-agent layer with the fixes that decision record required:
  - RETRIEVAL-GROUNDED, not memory-cited: real PubMed E-utilities search (Stage 0) feeds
    the model; the model cites ONLY retrieved PMIDs, enforced by a hard containment guard
    (a cited PMID outside the retrieved set is dropped as confabulated). This is the fix for
    the surface-pilot finding that LLMs confabulate PMIDs from memory (~6/9 wrong).
  - ANCHORED overlap dimensions: biological/druggability/safety consume the deterministic
    sub-verdicts (via an optional evidence-package) and must stay consistent — literature
    that contradicts is FLAGGED (contradicts_deterministic), never a silent override.
    clinical/commercial/translational are pure literature (no primary-data source).
  - null != MEDIUM: a dimension with no relevant retrieved abstracts is `not_assessed`,
    never a fabricated middle score.
  - REPRODUCIBILITY ENVELOPE: the retrieved corpus (PMIDs + query + mindate/maxdate) and the
    model pin + prompt_hash are stored as the pinned artifact (temp-0 is impossible on the
    framework model, so the sampled output IS the pin).

  Question this skill answers:
  For {target} in {indication}, what are the six drug-discovery risk dimensions, each graded
  with cited (retrieved, real) literature — and where does that literature agree with or
  contradict the framework's computed verdicts?

metadata:
  version: 0.1.0
  owner: ryan.abo@takeda.com
  requires_preflight: true       # needs Bedrock (BEDROCK_AWS_PROFILE) + network (NCBI E-utilities)
  tier: context                  # NOT a verdict/gate producer — synthesis-context only
  environment:
    - BEDROCK_AWS_PROFILE=cmp-dev
  model_pins:
    synthesis_model: us.anthropic.claude-opus-4-8

composition:
  data_mode: live_read            # live PubMed E-utilities retrieval. Literature is UNPINNABLE-grade
                                  # (citable_in_nominations: false, enforced in the skill output, not via data_mode)
  phase: [C, D, F, G, J]          # cross-cutting literature context spanning the pillars its 6 risk
                                  # dimensions touch: biological(C), mechanism(D), druggability(F),
                                  # safety(G), translational(J). clinical/commercial have no biology phase.
  cards_used: []                  # consumes NO cards; retrieves literature. Optionally READS an
                                  # evidence_package (sub_verdicts) to anchor overlap dimensions.
  rules_scope: []                 # fires NO rules — context-tier, descriptive risk read (no verdict spine)
  synthesis: [structured_llm]     # 6-dim risk read via Bedrock forced tool-use over retrieved abstracts
  output_shape: [data_package]    # risk_assessment.json
  steps_covered: [1, 2, 6]        # retrieve → assess → report (descriptive context, mirrors target-intrinsic)
  produces:
    - risk_assessment.json        # 6-dim {risk_level, justification, cited_pmids, anchor, corpus pin}
  status: wired
---

# literature-risk-assessment

## What this skill does

Runs a 3-stage retrieval-grounded pipeline per (target, indication):

1. **Retrieve (Stage 0):** six per-dimension PubMed E-utilities searches (`pubmed_search.py`,
   no LLM) → real abstracts (PMID + title + abstract). Date-boundable (`--mindate/--maxdate`)
   for a pinnable corpus.
2. **Assess (Stage 1):** for each dimension, the framework-pinned model rates
   LOW/MEDIUM/HIGH/not_assessed over ONLY the retrieved abstracts, citing ONLY their PMIDs.
   Overlap dimensions also receive the deterministic sub-verdict to anchor to.
3. **Guard:** cited PMIDs are validated ⊆ the retrieved set; any outside are dropped and
   recorded in `confabulated_dropped` (must be empty with retrieval-grounding).

## What this skill does NOT do

- Does NOT produce a card, rule, sub-verdict, or nomination-gate input. Its output is
  synthesis-context; the deterministic gate stays literature-blind
  (RISK_ASSESSMENT_INTEGRATION.md §4).
- Does NOT let the model emit PMIDs from memory (the confabulation failure mode).
- Does NOT score absence of evidence as MEDIUM (null → `not_assessed`).

## Invocation

```
BEDROCK_AWS_PROFILE=cmp-dev python3 skills/literature-risk-assessment/scripts/run.py \
  --target FOLR1 --indication "ovarian cancer" \
  --evidence-package <optional evidence_package.json for anchoring> \
  --mindate 2015 --maxdate 2026 \
  --out <dir>
```

## The one verdict-affecting ramp (NOT enabled here)

Per RISK_ASSESSMENT_INTEGRATION.md §5, the ONLY defensible future gate-affecting use is a
`clinical_validation` NO-GO (a well-powered mechanistic de-validation in the exact indication),
behind five preconditions (corpus pin, determinism, null≠MEDIUM, drop commercial/translational,
staleness TTL). This skill implements the corpus-pin + null≠MEDIUM preconditions but stays
context-tier; enabling the ramp is a separate, reviewed decision.

## ground_axis — per-subskill grounded-substrate reader (scripts/ground_axis.py)

A sibling entrypoint that augments ONE subskill/axis's deterministic cards with literature as
ESCALATE-ONLY LIABILITY FINDINGS (specific, PMID-traceable), NOT a LOW/MED/HIGH score. Emitting
findings rather than a re-scored bin is escalate-only by construction: it can RAISE a concern, never
lower a deterministic one — which structurally avoids the anchor-propagation failure (a grounded read
anchored to a narrow "tolerant" verdict otherwise re-concludes LOW and buries the real liability; e.g.
FOLR1 safety, where the narrow on-target read misses the ADC ocular / on-target normal-tissue tox that
`ground_axis` surfaces from the literature). It is the `grounded` block of the substrate record that
the risk roll-up and the cross-evidence hypothesis both consume (grounded-substrate two-projection
design). Reuses this skill's pubmed_search + the containment guard.

AXIS-PARAMETERIZED (AXIS_CONFIG): the block STRUCTURE is one contract across axes (escalate-only
`findings` + corroborations + contradicts flag + confab-containment); only the finding NOUN + KINDS
differ. Validated axes: safety/dependency/selectivity/surface_modality (live) + tractability_sm (config). `safety` (findings = liabilities — ocular/normal-tissue tox, off-target,
immunogenicity; caught FOLR1 mirvetuximab ocular tox the narrow read missed) and `dependency` (findings
= dependency-WEAKENING — resistance, context-dependence, paralog buffering, feedback; on KRAS/LUAD
surfaced sotorasib acquired resistance + STK11/KEAP1 co-mutation context-dependence). Add an axis by
extending AXIS_CONFIG.

    BEDROCK_AWS_PROFILE=cmp-dev python3 scripts/ground_axis.py \
        --target KRAS --indication "lung adenocarcinoma" \
        --evidence-package <pkg.json> --axis dependency --out <rec.json>

## risk_rollup — projection [3A]: 6-dim risk roll-up from the substrate (scripts/risk_rollup.py)

The sibling projection to the cross-evidence hypothesis (grounded-substrate two-projection design). Each
risk dim = a DETERMINISTIC bin (pure function of the evidence-package sub_verdicts — a modality-conditioned
worst-case CONJUNCTION; reproducible + cross-target comparable; the LLM never sets it) + GROUNDED
escalate-only findings from ground_axis substrate blocks (PMID-traceable; can only RAISE a flag, never
change the bin) + a per-dim engine↔literature discordance flag + declared blind-spots. The safety
conjunction (on-target-safety ∧ surface-normal-antigen ∧ tumor-selectivity-normal-breadth) catches the
FOLR1 ADC safety false-LOW that a 1:1 on-target-only mapping misses (validated). Thresholds are v0/
illustrative; the CONTRACT (conjunction + escalate-only fusion + declared blind-spots + reproducible bin)
is the contribution. clinical/commercial are engine-blind (literature-only).

    python3 scripts/risk_rollup.py --evidence-package <pkg.json> --modality adc \
        --substrate safety=<ground_axis_safety.json> dependency=<ground_axis_dep.json> --out <matrix.json>


### Pseudo-cards: clinical + commercial (engine-blind, literature-only)

clinical and commercial are ENGINE-BLIND — no deterministic card measures them — so they are PSEUDO-CARDS in AXIS_CONFIG (verdict_key=None, cards=[], pseudo_card=True): ground_axis runs literature-only with no anchor and emits escalate-only findings (failed/discontinued trials, class tox, crowded landscape, IP/FTO). risk_rollup derives a COARSE literature-only bin for these dims (escalator kind -> HIGH; any finding -> MED; none -> LOW), tagged bin_basis='literature-only (uncalibrated)'. Both the hypothesis and the risk matrix consume them. UPGRADE PATH: when a clinical-trials / commercial data source is ingested, add real `cards` to the config -> the dim gains a deterministic bin like any engine axis (zero rework).

## cited_evidence — verdict-INERT gene×indication cited-literature card (scripts/cited_evidence.py)

A sibling entrypoint (context-tier, like ground_axis/risk_rollup — NO verdict, no card, no gate input)
that composes TWO pinned, catalogued literature products into a "what does the literature say about
{target} in {indication}, with citations" card:

  - opentargets-europepmc-evidence-per-target-v1 (via analysis-methods opentargets_europepmc_evidence):
    OT co-occurrence literature VOLUME + RECENCY + the top cited statements (pmid/pmc/year/section/sentence).
  - pubtator3-gene-disease-relations-per-gene-v1 (via analysis-methods pubtator3_gene_disease_relations):
    PubTator BioREx typed relation DIRECTION (associate / cause / positive_correlate / negative_correlate
    / stimulate / inhibit) + per-type publication counts + PMIDs. Indication-scoped via the
    indication_crosswalk `mesh_ids` lane.

Reproducible (pinned products, no LLM). Both lanes best-effort — an absent method/product/creds degrades
that half to null and is recorded in `notes`, never raising. It composes into target-profile as the
best-effort, verdict-inert `cited_literature_evidence.json` (auto_cited_evidence, gated with the rest of
the substrate chain so the offline/fast/machine modes stay byte-identical).

    python3 scripts/cited_evidence.py --target KRAS --indication COADREAD [--top-cited 8]
