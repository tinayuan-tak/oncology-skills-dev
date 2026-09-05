---
name: literature-context
description: |
  Verdict-INERT descriptive skill: "What does the literature SAY about target X in indication Y —
  co-occurrence volume/recency, the top cited statements, and typed relation direction — with
  citations?" Composes ONE card, cited-literature-evidence, from two pinned, catalogued literature
  products (no LLM, reproducible):
    - opentargets-europepmc-evidence-per-target-v1 : Open Targets europePMC CO-OCCURRENCE literature
      volume + recency + the top cited statements (pmid/pmc/year/section/sentence).
    - pubtator3-gene-disease-relations-per-gene-v1  : PubTator3 BioREx typed relation DIRECTION
      (associate / cause / positive_correlate / negative_correlate / stimulate / inhibit) + PMIDs.

  DESCRIPTIVE (emits no verdict — like target-intrinsic / translational-readiness): cited literature is
  CONTEXT/CONFIDENCE that informs the synthesis, NEVER a nomination gate (RISK_ASSESSMENT_INTEGRATION.md
  §4). Gateless (verdict_fn=None) → verdict=None, absent from the nomination spine.

  History: PROMOTES the former cited_literature_evidence.json side-channel (the target-profile
  tp_grounding.auto_cited_evidence bolt-on) to a first-class fan-out member composing a governed card,
  so the card + skill validators and the emission guard see it. Distinct from literature-risk-assessment
  (that skill is context-tier by decision record and holds NO cards; it retrieves live PubMed for a
  6-dimension RISK read). This skill is the reproducible pinned-product CITATION facet.

  Question this skill answers:
  For {target} in {indication}, what does the literature say — how much / how recent, the top cited
  statements, and in what direction — with citations?

metadata:
  version: 1.1.0
  owner: ryan.abo@takeda.com
  requires_preflight: true
  environment:
    - AWS_PROFILE=cbg

composition:
  data_mode: derived_read
  phase: [C, D, F, G, J]        # cross-cutting literature context (the pillars its evidence touches);
                                # mirrors literature-risk-assessment's phase span, but reproducible + card-backed
  cards_used:
    - cited-literature-evidence   # OT europepmc co-occurrence + PubTator3 relation direction; gene×indication;
                                  # VERDICT-INERT descriptive literature context (composes both readers)
  measurement_types_pulled:
    - cited_literature_evidence   # cited-literature-evidence (target_indication-grain; OT europepmc + PubTator3)
  rules_scope:
    - none                        # DESCRIPTIVE skill (verdict_fn=None) — no resolver rung, fires no nomination rule
  synthesis:
    - none
  output_shape:
    - data_package
  steps_covered: [1, 2]
  status: wired
---

# literature-context — wired

## Status: wired (2026-09-02)

A verdict-INERT descriptive fan-out member. It composes ONE card — `cited-literature-evidence` — and
emits `decision.json` with:

- `status: "wired"`
- a DESCRIPTIVE headline (no verdict — `verdict_fn=None`):
  - `cited_evidence_status`: `ok` (≥1 literature lane present) / `insufficient` (target didn't resolve) /
    `no_evidence` (target resolved, no literature rows — an honest coverage gap)
  - `literature_scope`: OT co-occurrence disease scoping — `indication` / `target_level` /
    `target_level_fallback`
  - `paper_disease_mentions`: co-occurrence VOLUME (summed paper×disease mentions, NOT distinct papers —
    a paper co-occurring with N subtypes counts N times; `n_diseases` surfaces the inflation)
  - `recent_mentions`: mentions in the recent window (RECENCY)
  - `n_diseases`: indication-scoped disease subtypes summed into the counts
  - `earliest_year` / `latest_year`: literature age + currency
  - `top_cited`: the top cited statements (pmid/pmc/year/section/sentence), English surfaced first
  - `relation_types`: PubTator BioREx typed-relation labels present, ordered by publication support
    (DIRECTION)
  - `total_relation_publications`: total PubTator publications supporting the typed relations
- a DESCRIPTIVE narrator lens (`--synthesize`, v1.1.0) — `LITERATURE_CONTEXT` (mode `descriptive`) — that
  LEADS with the top CITED STATEMENTS and separates a canonical validated relationship from a
  volume-inflation / automated-relation / pleiotropy over-call (see below).
- a VERDICT-INERT cited-evidence CONFIDENCE surface (v1.1.0):
  - `cited_evidence_confidence_caveat` — 3 tiers over the co-occurrence VOLUME + typed RELATION:
    `volume_without_validated_relation` (SHARP — high VOLUME but thin/absent/ambiguous relation; incl. the
    high-`n_diseases` PLEIOTROPY inflation) / `relation_direction_automated_or_conflicting` (SHARP — the
    typed relation rests on conflicting or single-/few-paper BioREx extraction) /
    `validated_established_relationship` (MILDER false-demote guard — a canonical, VALIDATED,
    direction-correct pair: KRAS/COADREAD, ERBB2/BRCA, EGFR/LUAD, VHL/KIRC — is NOT an over-call).
  - `stale_literature_note` — an optional RECENCY flag (old `latest_year` or measured VOLUME with zero
    recent mentions).
  - `cited_evidence_provenance` — a QUORUM summary (volume/recency/disease-breadth, year span, typed-relation
    breadth + publication support + direction-conflict flag, the card's OWN top-cited pmids, pleiotropy +
    stale flags, the validated-relationship flag, and the "co-occurrence ≠ causation + BioREx is automated
    single-sentence extraction" note).
  These gate ONLY on the VOLUME/RECENCY/RELATION fields the headline already pulls (NO new card-field read),
  are VERDICT-INERT (gateless), and the primary caveat is surfaced deterministically in `key_signals.caveat`.

## What this skill wires

- **cited-literature-evidence** (target-contracts): the gene×indication cited-literature card composing
  two pinned literature products via analysis-methods
  `cited_literature_evidence.read_cited_literature_evidence`:
  - **opentargets-europepmc-evidence-per-target-v1** — Open Targets 26.06 europePMC co-occurrence
    evidence (VOLUME + RECENCY + top cited statements).
  - **pubtator3-gene-disease-relations-per-gene-v1** — PubTator3 BioREx typed relation DIRECTION + PMIDs.
  Both lanes best-effort: an absent product/creds degrades that half to null (recorded in `notes`),
  never raising. VERDICT-INERT — reaches the LLM / matrix / headline, drives NO resolver rung.

## What this skill does NOT do

- Does NOT produce a verdict, rule, sub-verdict, or nomination-gate input. Cited literature is
  CONTEXT/CONFIDENCE; the deterministic gate stays literature-blind (RISK_ASSESSMENT_INTEGRATION.md §4).
- Does NOT retrieve live PubMed for the deterministic read — it reads pinned, catalogued products
  (reproducible). The live-PubMed 6-dimension RISK read is the sibling `literature-risk-assessment` skill.
- Does NOT wire the LLM `--literature` lane (a DELIBERATE no-op decision, v1.1.0). Every other skill in the
  literature-and-claims arc bakes a `make_literature_fn` lane that asks an LLM what the published literature
  says, GROUNDED by a fresh Europe PMC retrieval (`default_retrieve` = Europe PMC → PubTator3 fallback). For
  literature-context that lane is REDUNDANT and CIRCULAR: this skill's ONE card, `cited-literature-evidence`,
  IS the Europe PMC + PubTator3 literature (it composes `opentargets-europepmc-evidence-per-target-v1` +
  `pubtator3-gene-disease-relations-per-gene-v1`). A `--literature` lane would re-derive the SAME two sources
  the card already composes deterministically — it cannot be an INDEPENDENT corroboration of itself, and it
  would double-count the card's own PMIDs. The "literature grounding" the arc wants is ALREADY the
  deterministic card, surfaced by the `LITERATURE_CONTEXT` narrator lens + the confidence caveats. So
  `run.py` supplies `synthesize_fn` but NO `literature_fn`; under `--literature` the dispatcher honest-skips.
  (`literature_retrieval._LENS_QUERY_TERMS` / `_LENS_MAX_TERMS` are intentionally NOT touched.)

## How Claude invokes this skill

1. Extract `target` (HGNC symbol, uppercase) + `indication` (OncoTree code).
2. Pick a durable `out` directory (avoid `/tmp`).
3. Run:
   ```
   export AWS_PROFILE=cbg && \
   python3 /home/sagemaker-user/rnd-computational-biology-oncology-claude-oncology-skills/skills/literature-context/scripts/run.py \
     --target <TARGET> --indication <INDICATION> --out <OUT_DIR>
   ```
4. Read `<OUT_DIR>/decision.json`; present `cited_evidence_status` + the co-occurrence volume/recency and
   `relation_types`, and cite `top_cited` (retrieved PMIDs) inline.
