# Real-data scorecard panel roster (A7, issue #1994, epic #1985)

This is the **roster decision** for the demo-week component-iterator scorecard — domain judgment,
independent of harness code. Config WIRING into the A0a (#1987) scorecard schema is deferred until
that schema lands; this file is intentionally self-contained (plain `target`/`indication` pairs +
rationale) so A0a can consume it without this issue depending on A0a's shape.

Per the plan (`~/.claude/plans/modular-swinging-dahl.md`, "The panel"), the goal is a small,
archetype-diverse set that is big enough to catch single-target overfit and small enough to eyeball
every field — picked to **maximize red coverage**, not convenience.

## Roster (5 targets)

| target | indication | archetype | stresses |
|---|---|---|---|
| **EPCAM** | COADREAD | flagship — surface antigen | ADC/TCE surface-modality-fit path (focally/broadly expressed epithelial antigen) |
| **KRAS** | COADREAD | flagship — intrinsic driver | dependency + tractability story (oncogene addiction, not a surface play) |
| **ERBB2 (HER2)** | BRCA | amplified surface antigen | cis-dosage / amplification-driven surface story (orthogonal from EPCAM's non-amplified broad-expression story) |
| **PLK1** | COADREAD | pan-essential control | #1794 broad-tox arm — a genuine `AchillesCommonEssentialControls`-anchored killer, must NOT get nominated |
| **HTR1D** | COADREAD | thin-coverage / abstention control | #1792 fail-open confidence floor — a target whose surface derived products are data-blocked, so the honest read is `insufficient`, not a confidently-wrong reassurance |

All five pairs are drawn from `target-contracts/vocabularies/known_target_calibration_set.yaml`
(the framework's existing calibration truth-set) — not novel picks — so each has a **live-verified**
provenance trail already in the repo (see rationale below), satisfying "do not roster a target the
stack cannot run."

## Per-target rationale

### EPCAM / COADREAD — flagship, surface antigen
`known_target_calibration_set.yaml` line ~444 (`reference_profiles.EPCAM`, modality: adc). EPCAM is a
canonical epithelial-cell-adhesion-molecule ADC/TCE antigen (catumaxomab / EPCAM-targeting programs),
broadly and focally expressed across CRC — the flagship surface case fixed by the plan. Confirmed
present in the calibration corpus.

### KRAS / COADREAD — flagship, intrinsic driver
`known_target_calibration_set.yaml` reference_profiles.KRAS + the paralog-buffering fixture
(line ~810, `strongest_paralog_symbol: NRAS`). KRAS is the flagship intrinsic-driver case fixed by
the plan: dependency + tractability (G12C-class), not a surface story — the deliberate contrast
against EPCAM. Confirmed present, including live-verified functional-requirement fixtures.

### ERBB2 (HER2) / BRCA — amplified surface antigen (issue's own default; kept)
`known_target_calibration_set.yaml` reference_profiles.ERBB2 (indication: BRCA, modality: adc,
outcome: approved_class — trastuzumab/T-DXd) + a tumor-selectivity fixture
(`erbb2_brca.tumor-selectivity.json`, line ~735). ERBB2 is amplification-driven (copy-number → 
expression → surface density), which is a distinct axis from EPCAM's non-amplified broad expression
— together the two surface picks exercise both the "just highly expressed" and the "amplified"
surface-antigen sub-archetypes, per the plan's explicit suggestion. Confirmed present with two
independent calibration fixtures (reference_profiles + tumor-selectivity case).

### PLK1 / COADREAD — pan-essential control
`known_target_calibration_set.yaml` line ~591: `PLK1: {indication: multi, ..., deciding_axis:
window_pan_essential, deciding_axis_coverage: captured, agreement: agree, severity: validated_lane,
note: "Correctly-declined negative (VERIFIED live 2026-09-02, PLK1/COADREAD SM → forced_recommendation
=veto). ... Framework CAPTURES the liability: dependency=pan_essential_killer (PLK1 is genuinely
pan-essential — the mitotic kinase) ..."}`. PLK1 is a real, DepMap-curated core-essential gene
(`AchillesCommonEssentialControls` = Hart2015 ∩ Blomen2014 anchor set consumed by
`onc_methods/depmap_chronos_distribution/cli.py::_load_curated_common_essentials`) — chosen over other
pan-essential anchors in the same file (WEE1, CHEK1, KIF11) because it has the most explicit,
already-live-verified `pan_essential_killer` capture note, giving the highest confidence the panel
run will actually exercise the #1794 broad-tox arm rather than silently landing on a NULL/NOT_BUILT
cell. Indication pinned to COADREAD to match the EPCAM/KRAS/HTR1D indication and keep the panel
indication-consistent (panel-consistency criterion (d) in A0a's schema).

### HTR1D / COADREAD — thin-coverage target
`known_target_calibration_set.yaml` `abstention_cases.HTR1D` (line ~820) + the assertion block at
line ~845 (`snapshot: htr1d_coadread.surface-modality-fit.json`, `outcome: honest_insufficient`,
note: "surface derived products not yet on S3"). HTR1D is a GPCR (5-HT1D receptor) with no
oncology-relevant surface/dependency characterization program — its surface-modality-fit read is a
confirmed, already-live-verified `insufficient` abstention (data-blocked E2/F gate), and as a
non-oncology GPCR it is plausible its on-target-safety legs beyond CONSTRAINT (gnomAD, which is
genome-wide and therefore always at least nominally measured) — BURDEN/DOSAGE/CLINVAR/MOUSE_KO/
NORMAL_TISSUE — are thin-to-absent. This is exactly the shape #1792 is about: a target where only
one critical-axis leg is measured, so the honest outcome is a coverage-demoted / `insufficient`
confidence, not a confidently reassuring `clean` verdict. Chosen over rostering an entirely novel
target because HTR1D's thin-coverage behavior is already reproducible and pinned in the corpus
(lower risk the panel run reports ERROR instead of exercising the intended red).

## Panel-consistency note
4 of 5 targets share indication COADREAD; ERBB2 is deliberately BRCA (its approved, amplification-
driven indication — running it in COADREAD would misrepresent the amplified-antigen archetype it is
meant to exercise). This mirrors the plan's own KRAS/LUAD-vs-COADREAD-style indication-per-archetype
pattern rather than forcing one indication where the biology does not fit.

## Per-skill x per-target stress-expectation table (issue #2070, coordinator decision on epic #1985)

The table above assigns each target ONE global archetype label ("thin-coverage control", "pan-
essential control", ...). Issue #2070 found that a global label projected blindly onto every
adapter's `panel_consistency` check is itself a bug: HTR1D's archetype-defining property (surface
derived products are data-blocked) lives in the **surface-modality-fit** vertical, not in
**tumor-selectivity**'s DGE vertical, where HTR1D's tumor-vs-normal read is fully materialized and
reads a confident, concordant `strong_tumor_selective` — the panel's LARGEST fold-change
(max|log2fc|=5.79), coverage-equivalent to flagship ERBB2/PLK1 (live diagnosis, 2026-09-29,
`AWS_PROFILE=cbg`, see issue #2070 comment `issuecomment-5884692550`). **Coverage of an archetype
stress is skill-relative** — a per-skill adapter must assert only the stress its OWN vertical can
actually exercise, per this table. Cells with no live per-skill diagnosis run are marked `not
asserted` rather than guessed; this table is honest to the evidence in hand, not aspirational.

| target | surface-modality-fit | on-target-safety-liability | tumor-selectivity (DGE vertical) | mechanism-and-pharmacology / target-intrinsic / tumor-presence |
|---|---|---|---|---|
| **EPCAM** | primary archetype home — confident ADC/TCE-viable surface call (broad+focal epithelial antigen); `known_target_calibration_set.yaml reference_profiles.EPCAM` | not asserted (no live per-skill diagnosis run for this issue) | measured `field_effect_tumor_selective`, dir=up, comparators discordant (2/1 fam), sig_all=False, max\|log2fc\|=2.10 — flagship, but NOT the panel's most concordant DGE read (live diagnosis 2026-09-29) | not asserted |
| **KRAS** | not applicable — KRAS is the flagship intrinsic-driver/non-surface contrast, deliberately not a surface play | not asserted | measured `discordant_across_comparators`, dir=down, comparators discordant (2/1 fam), sig_all=False, max\|log2fc\|=0.67 — the panel's weakest/most-discordant DGE read (on par with EPCAM's discordance; live diagnosis 2026-09-29) | not asserted |
| **ERBB2** | primary archetype home — amplification-driven surface antigen (cis-dosage story); not yet live-diagnosed by this issue | not asserted | measured `strong_tumor_selective`, dir=up, comparators concordant (2/2 fam), sig_all=True, max\|log2fc\|=5.21 (live diagnosis 2026-09-29) | not asserted |
| **PLK1** | not applicable — pan-essential control, not a surface archetype | primary archetype home — #1794 broad-tox arm (pan-essential killer); not yet live-diagnosed by this issue | measured `strong_tumor_selective`, dir=up, comparators concordant (2/2 fam), sig_all=True, max\|log2fc\|=3.05 — PLK1's essentiality does NOT degrade its own-tissue DGE read either (live diagnosis 2026-09-29) | not asserted |
| **HTR1D** | primary archetype home — confirmed `insufficient` abstention, surface derived products data-blocked (E2/F gate); `known_target_calibration_set.yaml abstention_cases.HTR1D`, `htr1d_coadread.surface-modality-fit.json` | plausible per the roster rationale (non-oncology GPCR; BURDEN/DOSAGE/CLINVAR/MOUSE_KO/NORMAL_TISSUE legs plausibly thin beyond CONSTRAINT/gnomAD) — **UNVERIFIED, no live per-skill diagnosis run yet; do not assume** | **does NOT apply** — measured `strong_tumor_selective`, dir=up, comparators concordant (2/2 fam), sig_all=True, max\|log2fc\|=5.79 (the panel's LARGEST fold-change). The calibration set's own note (`abstention_cases.HTR1D`) confirms: "A/B upstream read strong; the abstention is at the surface (E2/F) gate" — HTR1D's thin-coverage character is surface-specific, not DGE-wide. `tumor-selectivity`'s HTR1D expectation is exactly this strong, concordant read — NOT a degraded one. Comparator-discordance was considered as an alternate DGE-vertical thin-control discriminator and REJECTED (issue #2070 decision pt.4): it fires on the flagship EPCAM/KRAS pair too (both discordant, 2/1), so it does not cleanly separate a control from the flagships. | not asserted (tumor-presence's own per-target roster envelope work is tracked separately on issue #2071) |

Power/coverage grading (the dimension that WOULD let an adapter grade a genuine "thin" read
quantitatively rather than by class label alone) is structurally blocked panel-wide: `n_tumor` reads
`None` for every target in this vintage (flagships included), so zero power variation exists to
grade on. Tracked as **#1663**; re-measure also owed at `#868`'s DGE re-materialization (`n_tumor`
may populate then). Until #1663 lands, `tumor-selectivity`'s `panel_consistency` criterion for the
power/coverage dimension stays `NULL` (never a fabricated pass) rather than `RED` on an inapplicable
clause or a fabricated `GREEN`.

## Non-goals (explicitly deferred, per issue #1994)
- No harness config wiring — that step is blocked on A0a (#1987) landing the scorecard schema +
  sharded persistence. This file is deliberately schema-agnostic (plain markdown table, no YAML tied
  to an unlanded schema) so A0a's author can consume the roster in whatever shape the schema needs.
- No re-derivation / no new cards. This is a roster decision, not an implementation.
