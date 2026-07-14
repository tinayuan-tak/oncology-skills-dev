# Skills Scope & Boundary Review — 2026-07-14

**Owner:** Ryan Abo · **Status:** actioned (this branch) + governance items flagged

Companion to the correctness-focused `docs/SUBSKILL_DEFECT_REGISTER_2026-07-14.md`
(PR #60). That register covered per-skill **bugs** (RC1–4: error-dicts counted
as available, bool-vs-string rule matching, rule coverage holes, false-green
test). This doc covers **scope & boundaries** — how the skills are carved up —
and records what was changed and why.

## What changed on this branch (`feat/skills-scope-restructure`)

### 1. Split `tractability-and-modality` → two skills
The skill had grown to 9 cards, but its `_snapshot()` verdict keyed **entirely**
off the 3 chemical-genetic rules — the 6 surface cards were inert (headline
display only, could not change the verdict). Clearest grab-bag in the framework.

- **`tractability-small-molecule`** (v3.0.0) — the 3 chemical-genetic cards +
  the `_snapshot` verdict, verbatim. Verified: KRAS/COADREAD → `well_covered`
  (`e7-triangulated-target-engaged-supportive`), identical to pre-split.
- **`surface-modality-fit`** (v1.0.0, `status: partial`) — the 5 surface/
  structure cards. Resolves a `surface_modality_verdict` from the composed
  `adc-tce-modality-fit` `fit_class` rules; honest `insufficient` when surface
  data is unavailable (most surface derived products not yet on S3). This makes
  the biologics-modality call the old skill only *displayed*.

### 2. Reframe `mutation-profile` → `genomic-alteration-profile`
The same gene is often a driver via different alteration classes across
indications (ERBB2 amp vs mutation; MET exon14 + amplification). A mutation-only
skill implied "not a driver" for amplification-driven targets.

- Added `copy-number-distribution` (the card + its 11 `cn-*` rules already
  existed but were never composed into a skill) + a `fusion-rearrangement-
  landscape` **placeholder** card (data not yet landed → resolves `_missing`).
- Multi-class verdict: SNV/indel primary (rank-order unchanged) + CN modifier.
  Both drive → `multi_class_driver`; CN-only → `recurrent_amplification_driver`
  / `recurrent_deletion_driver`; neither → mixed/passenger/insufficient.
- Verified: KRAS → `biomarker_stratified_dependency` (unchanged), now also
  surfaces `copy_number_class: broadly_neutral`. Regression-safe.

### 3. Deleted `patient-population-and-access`
It was a thin re-projection of the `mutation-hotspot-frequency` card that
`genomic-alteration-profile` already consumes — one card, no rules, no verdict.
Its **prevalence** fields (`n_samples_in_indication`, `n_samples_mutated`,
top-hotspot, `n_recurrent_hotspots`) were folded into `genomic-alteration-
profile`'s headline. Co-occurrence neighborhoods were NOT folded — those remain
`differentiation-landscape`'s job (avoids re-creating that overlap).

### 4. Dropped `surfaceome-cohort-ranking` from the composer fan-out
It is a **per-indication scan** (indication-primary, `batch_compute`), not a
per-target question-skill, and its `cohort_rank_class` is now covered inside
`surface-modality-fit`. The scan skill still exists as a utility; only its
composer fan-out slot was removed. (Its data-loader fix is PR #61's; a full
re-home as a scan utility is deferred until #61 merges.)

### Composer (`target-profile`)
`SUB_SKILLS` went 10 → **9** distinct-question skills. Also fixed a latent bug
the split exposed: `_run_sub_skills` hardcoded `axis="intracellular_intrinsic"`,
so a surface-only sub-skill would fire no rules — now fires **both** axes and
merges (card-id-scoped, so no cross-contamination).

## Governance items — FLAGGED, not actioned (require others' sign-off)

### `query-target-evidence` + `workflow-target-evaluation-onc`
Both are in **Ming-Ju Tsai's plugin manifest** (`.claude-plugin/marketplace.json`
`skills[]`), NOT the symlink-registered v2 set. They are a *different lineage*
(v1 PubMed/ScholarEval + core-artifacts retrieval; `crc`/`nsclc` codes) that
overlaps `target-profile`'s Go/No-Go purpose with a disjoint implementation.

- **Do NOT archive unilaterally** — editing the plugin manifest touches Ming-Ju's
  packaged product. Retiring them is a **governance conversation** (ties to the
  AgenticBoost 6-component vs skills 6-category overlap in Ryan's notes), not a
  code change.
- Recommended: raise at the next sync with Ming-Ju — decide whether the v1
  workflow is legacy-to-retire or a maintained parallel product, and whether the
  two 6-component risk frameworks should converge.

## Deferred / follow-on

- **Surfaceome re-home** as an explicit scan utility (peer to compose-dashboard)
  — after PR #61's loader fix merges.
- **Copy-number rules for the `mixed` bucket + fusion method** when SV data lands.
- **`resolve_verdict` shared helper** (design rec from the verdict-layer review:
  replace the hand-rolled per-skill `if`-chains + add a test that every
  referenced rule-ID exists). Deferred — it touches `_skills_common/` (PR #60).
- **Nomination-bar gating** — port compose-dashboard's `killer_conditions` +
  ≥3-insufficient floor into `target-profile` as a one-directional pre-LLM gate
  (can force veto/insufficient, never nominate). The framework's two synthesis
  engines currently diverge on gating; unifying them is the top interpretation-
  layer refactor. Separate branch (touches the composer + synthesis).

## Handoff to PR #60 (owns `skills/tests/`)

`test_graduated_skills_run_wired.py` `_ALWAYS_WIRED` (~line 51) must, after both
merge: DROP `tractability-and-modality` + `mutation-profile` +
`patient-population-and-access`; ADD `tractability-small-molecule` +
`surface-modality-fit` + `genomic-alteration-profile`. (Not edited here —
PR #60 owns that file. The test currently tolerates the missing dirs.)
